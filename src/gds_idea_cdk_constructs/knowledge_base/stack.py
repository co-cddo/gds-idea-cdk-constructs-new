"""CDK Stack for Bedrock Knowledge Bases.

Creates a fully configured Bedrock Knowledge Base with:
    - S3 bucket for source documents
    - Vector storage backend (selected via :class:`~.props.StorageType`)
    - IAM service role for Bedrock
    - Bedrock Knowledge Base with configurable embedding model
    - Bedrock Data Source with configurable chunking strategy
    - SSM Parameter storing the KB ID for runtime lookup
    - Optional SQS-debounced auto-sync Lambda triggered by S3 events

Resources are named ``{app_name}-kb-*-{environment}`` for easy identification.
"""

import logging
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_events,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct

from ..config import AppConfig, DeploymentConfig
from ._storage_strategies import STORAGE_STRATEGY_MAP, IStorageStrategy
from .props import (
    ChunkingStrategy,
    FixedSizeChunkingConfig,
    HierarchicalChunkingConfig,
    KnowledgeBaseProps,
    SemanticChunkingConfig,
)

logger = logging.getLogger(__name__)


class KnowledgeBase(Stack):
    """A configurable Bedrock Knowledge Base stack.

    Orchestrates all infrastructure needed for a Bedrock Knowledge Base:
    storage backend, embedding model, data source with chunking, and
    optional auto-sync via SQS-debounced S3 event notifications.

    The stack exposes attributes for cross-stack integration:

    Attributes:
        kb_id: The Knowledge Base ID (CloudFormation token).
        kb_arn: The Knowledge Base ARN (CloudFormation token).
        data_bucket: The S3 bucket holding source documents.
        ssm_parameter: The SSM parameter storing the KB ID.
        data_source_id: The Data Source ID (CloudFormation token).

    Example:
        Standalone knowledge base::

            from gds_idea_cdk_constructs import DeploymentConfig
            from gds_idea_cdk_constructs.knowledge_base import (
                ChunkingConfig,
                KnowledgeBase,
                KnowledgeBaseProps,
            )

            config = DeploymentConfig(cdk_env)
            kb = KnowledgeBase(
                app,
                deployment_config=config,
                app_config="my-app",
                kb_props=KnowledgeBaseProps(
                    chunking=ChunkingConfig.fixed_size(max_tokens=500),
                    inclusion_prefixes=["documents/"],
                ),
            )

        With a WebApp (cross-stack)::

            webapp = WebApp(
                app,
                deployment_config=config,
                app_config=app_config,
                container_props=WebAppContainerProperties(
                    environment_variables=kb.environment_variables,
                ),
            )

            # Grant the ECS task role permission to query the KB
            kb.grant_retrieve(webapp.task_role)

        With an AgentCore runtime (cross-stack)::

            from gds_idea_cdk_constructs.agent_core import (
                DEFAULT_AGENT_CODE_DIR,
                AgentCore,
                AgentCoreProperties,
                CustomAgent,
            )

            agent = AgentCore(
                app,
                "MyAgentStack",
                props=AgentCoreProperties(
                    runtime_name="my-agent",
                    agent=CustomAgent(
                        agent_code_directory=DEFAULT_AGENT_CODE_DIR,
                        environment_variables=kb.environment_variables,
                    ),
                ),
            )

            # Grant the runtime permission to query the KB
            kb.grant_retrieve(agent.runtime_role)
    """

    def __init__(
        self,
        scope: Construct,
        deployment_config: DeploymentConfig,
        app_config: AppConfig | str,
        kb_props: KnowledgeBaseProps | None = None,
    ) -> None:
        """Initialize a KnowledgeBase stack.

        Args:
            scope: The CDK app or stage to create this stack within.
            deployment_config: Environment-specific configuration.
            app_config: Application configuration (for naming).  Accepts an
                :class:`~gds_idea_cdk_constructs.AppConfig` instance or a
                plain ``str`` app name for consumers that don't need a
                full web-app config.
            kb_props: Knowledge base configuration.  If ``None``, uses
                defaults from :class:`KnowledgeBaseProps`.
        """
        # Resolve app name from AppConfig or raw string
        self.app_name = (
            app_config.app_name if isinstance(app_config, AppConfig) else app_config
        )

        stack_id = f"{self.app_name}-kb-stack"
        super().__init__(scope, stack_id, env=deployment_config.cdk_env)

        self.deployment_config = deployment_config
        self.kb_props = kb_props or KnowledgeBaseProps()

        env_name = deployment_config.environment.friendly_name
        app_prefix = self.app_name

        logger.info(
            "Creating knowledge base: %s (env=%s, storage=%s, embedding=%s)",
            self.app_name,
            env_name,
            self.kb_props.storage_type,
            self.kb_props.embedding_model,
        )

        # Select storage strategy
        strategy_class = STORAGE_STRATEGY_MAP.get(self.kb_props.storage_type)
        if not strategy_class:
            raise ValueError(f"Unsupported storage type: {self.kb_props.storage_type}")
        self._storage_strategy: IStorageStrategy = strategy_class(self, self.kb_props)

        # Build the stack
        self._create_data_bucket(app_prefix, env_name)
        self._create_storage_resources(app_prefix, env_name)
        self._create_kb_role(app_prefix, env_name)
        self._create_knowledge_base(app_prefix, env_name)
        self._create_data_source(app_prefix, env_name)
        self._create_ssm_parameter(app_prefix)

        if self.kb_props.enable_auto_sync:
            self._setup_auto_sync(app_prefix, env_name)

        self._create_outputs()

    # ------------------------------------------------------------------
    # Cross-Stack integration
    # ------------------------------------------------------------------

    def grant_retrieve(self, grantee: iam.IGrantable) -> None:
        """Grant permissions to retrieve from this knowledge base.

        Grants the grantee:

        - ``bedrock:Retrieve`` on the Knowledge Base ARN
        - Read access to the SSM parameter storing the KB ID

        For ``RetrieveAndGenerate`` or ``InvokeModel`` permissions, the
        user should add those separately since they depend on which
        LLM models the application uses.

        Args:
            grantee: The IAM principal to grant permissions to (e.g. a
                task role from a :class:`~gds_idea_cdk_constructs.web_app.WebApp`
                stack).

        Example:
            ::

                kb = KnowledgeBase(app, deployment_config=config, app_config="my-app")
                webapp = WebApp(app, deployment_config=config, app_config=app_config)
                kb.grant_retrieve(webapp.task_role)
        """
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                sid="BedrockRetrieve",
                actions=["bedrock:Retrieve"],
                resources=[self.kb_arn],
            )
        )
        self.ssm_parameter.grant_read(grantee)

    @property
    def environment_variables(self) -> dict[str, str]:
        """Environment variables for container using the knowledge base.
        Returns a dict suitable for passing into
        WebAppContainerProperties environment_variables:
        - ``KB_ID``: The Knowledge Base ID (CloudFormation token).
        - ``KB_SSM_PARAMETER``: The SSM parameter name storing the KB ID.
        Example:
            ::
                container_props = WebAppContainerProperties(
                    environment_variables={
                        **kb.environment_variables,
                        "MY_OTHER_VAR": "value",
                    },
                )
        """
        return {
            "KB_ID": self.kb_id,
            "KB_SSM_PARAMETER": self.ssm_parameter.parameter_name,
        }

    # ------------------------------------------------------------------
    # Private construction methods
    # ------------------------------------------------------------------

    def _create_data_bucket(self, app_prefix: str, env_name: str) -> None:
        """Create the S3 bucket for source documents."""
        removal_policy = (
            RemovalPolicy.RETAIN
            if self.kb_props.retain_on_delete
            else RemovalPolicy.DESTROY
        )

        self.data_bucket = s3.Bucket(
            self,
            "DataBucket",
            bucket_name=f"{app_prefix}-kb-data-{env_name}",
            removal_policy=removal_policy,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
        )

    def _create_storage_resources(self, app_prefix: str, env_name: str) -> None:
        """Delegate vector storage creation to the selected strategy."""
        self._storage_strategy.create_storage_resources(
            app_prefix, env_name, retain=self.kb_props.retain_on_delete
        )

    def _create_kb_role(self, app_prefix: str, env_name: str) -> None:
        """Create the IAM service role for Bedrock Knowledge Base."""
        self._kb_role = iam.Role(
            self,
            "KnowledgeBaseRole",
            role_name=f"{app_prefix}-kb-role-{env_name}",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                },
            ),
            description=(
                "Service role for Bedrock Knowledge Base "
                "to access S3 and vector storage"
            ),
        )

        # Read source documents from S3
        self.data_bucket.grant_read(self._kb_role)

        # Invoke the embedding model
        embedding_model_arn = self.format_arn(
            service="bedrock",
            resource="foundation-model",
            resource_name=self.kb_props.embedding_model.value,
            arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
            account="",  # Foundation model ARNs have no account ID
        )
        self._kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeEmbeddingModel",
                actions=["bedrock:InvokeModel"],
                resources=[embedding_model_arn],
            )
        )

        # Storage-backend-specific permissions
        for statement in self._storage_strategy.get_iam_policy_statements():
            self._kb_role.add_to_policy(statement)

    def _create_knowledge_base(self, app_prefix: str, env_name: str) -> None:
        """Create the Bedrock Knowledge Base resource."""
        embedding_model_arn = self.format_arn(
            service="bedrock",
            resource="foundation-model",
            resource_name=self.kb_props.embedding_model.value,
            arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
            account="",
        )

        self._knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name=f"{app_prefix}-kb-{env_name}",
            description=self.kb_props.description
            or f"Knowledge base for {self.app_name}",
            role_arn=self._kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embedding_model_arn,
                ),
            ),
            storage_configuration=self._storage_strategy.get_storage_configuration(),
        )

        # Depend on storage resources and IAM role
        for dep in self._storage_strategy.get_resource_dependencies():
            self._knowledge_base.add_dependency(dep)
        self._knowledge_base.node.add_dependency(self._kb_role)

        # Expose cross-stack attributes
        self.kb_id: str = self._knowledge_base.attr_knowledge_base_id
        self.kb_arn: str = self._knowledge_base.attr_knowledge_base_arn

    def _create_data_source(self, app_prefix: str, env_name: str) -> None:
        """Create the Bedrock Data Source with chunking configuration."""
        # Build S3 data source configuration
        s3_config = bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
            bucket_arn=self.data_bucket.bucket_arn,
            **(
                {"inclusion_prefixes": self.kb_props.inclusion_prefixes}
                if self.kb_props.inclusion_prefixes
                else {}
            ),
        )

        self._data_source = bedrock.CfnDataSource(
            self,
            "DataSource",
            name=f"{app_prefix}-datasource-{env_name}",
            description=f"S3 data source for {self.app_name}",
            knowledge_base_id=self._knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=s3_config,
            ),
            vector_ingestion_configuration=self._build_chunking_configuration(),
            data_deletion_policy=self.kb_props.data_deletion_policy,
        )
        self._data_source.add_dependency(self._knowledge_base)

        # Expose for cross-stack references
        self.data_source_id: str = self._data_source.attr_data_source_id

    def _build_chunking_configuration(
        self,
    ) -> bedrock.CfnDataSource.VectorIngestionConfigurationProperty:
        """Build the chunking configuration from KnowledgeBaseProps.

        Returns:
            A ``VectorIngestionConfigurationProperty`` with the appropriate
            chunking settings.
        """
        chunking = self.kb_props.chunking
        strategy = chunking.strategy

        if strategy == ChunkingStrategy.NONE:
            chunking_config = bedrock.CfnDataSource.ChunkingConfigurationProperty(
                chunking_strategy="NONE",
            )
        elif strategy == ChunkingStrategy.FIXED_SIZE and isinstance(
            chunking, FixedSizeChunkingConfig
        ):
            chunking_config = bedrock.CfnDataSource.ChunkingConfigurationProperty(
                chunking_strategy="FIXED_SIZE",
                fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                    max_tokens=chunking.max_tokens,
                    overlap_percentage=chunking.overlap_percentage,
                ),
            )
        elif strategy == ChunkingStrategy.HIERARCHICAL and isinstance(
            chunking, HierarchicalChunkingConfig
        ):
            chunking_config = bedrock.CfnDataSource.ChunkingConfigurationProperty(
                chunking_strategy="HIERARCHICAL",
                hierarchical_chunking_configuration=bedrock.CfnDataSource.HierarchicalChunkingConfigurationProperty(
                    level_configurations=[
                        bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                            max_tokens=chunking.max_tokens * 5,
                        ),
                        bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                            max_tokens=chunking.max_tokens,
                        ),
                    ],
                    overlap_tokens=int(
                        chunking.max_tokens * chunking.overlap_percentage / 100
                    ),
                ),
            )
        elif strategy == ChunkingStrategy.SEMANTIC and isinstance(
            chunking, SemanticChunkingConfig
        ):
            chunking_config = bedrock.CfnDataSource.ChunkingConfigurationProperty(
                chunking_strategy="SEMANTIC",
                semantic_chunking_configuration=bedrock.CfnDataSource.SemanticChunkingConfigurationProperty(
                    max_tokens=chunking.max_tokens,
                    buffer_size=chunking.buffer_size,
                    breakpoint_percentile_threshold=chunking.breakpoint_percentile_threshold,
                ),
            )
        else:
            raise ValueError(f"Unsupported chunking strategy: {strategy}")

        return bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
            chunking_configuration=chunking_config,
        )

    def _create_ssm_parameter(self, app_prefix: str) -> None:
        """Store the Knowledge Base ID in SSM Parameter Store."""
        self.ssm_parameter = ssm.StringParameter(
            self,
            "KnowledgeBaseIdParam",
            parameter_name=f"/{app_prefix}/kb-id",
            string_value=self._knowledge_base.attr_knowledge_base_id,
            description=f"Bedrock Knowledge Base ID for {self.app_name}",
        )

    def _setup_auto_sync(self, app_prefix: str, env_name: str) -> None:
        """Set up SQS-debounced auto-sync from S3 to Bedrock.

        Architecture::

            S3 Bucket (ObjectCreated / ObjectRemoved events)
              -> SQS Queue (batch_window = N minutes)
                -> Lambda (kb_sync.py)
                  -> bedrock-agent:StartIngestionJob
        """
        # Dead-letter queue for failed sync invocations
        dlq = sqs.Queue(
            self,
            "SyncDLQ",
            queue_name=f"{app_prefix}-kb-sync-dlq-{env_name}",
            retention_period=Duration.days(14),
        )

        # Main queue — receives S3 event notifications
        sync_queue = sqs.Queue(
            self,
            "SyncQueue",
            queue_name=f"{app_prefix}-kb-sync-{env_name}",
            visibility_timeout=Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dlq,
            ),
        )

        # S3 -> SQS event notifications
        self.data_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(sync_queue),
        )
        self.data_bucket.add_event_notification(
            s3.EventType.OBJECT_REMOVED,
            s3n.SqsDestination(sync_queue),
        )

        # Lambda function
        lambda_location = Path(__file__).parent / "lambda_handlers"
        sync_fn = _lambda.Function(
            self,
            "KbSyncFunction",
            function_name=f"{app_prefix}-kb-sync-{env_name}",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="kb_sync.handler",
            timeout=Duration.minutes(1),
            code=_lambda.Code.from_asset(str(lambda_location)),
            environment={
                "KNOWLEDGE_BASE_ID": self._knowledge_base.attr_knowledge_base_id,
                "DATA_SOURCE_ID": self._data_source.attr_data_source_id,
            },
        )

        # Grant the Lambda permission to start ingestion jobs
        sync_fn.add_to_role_policy(
            iam.PolicyStatement(
                sid="StartIngestionJob",
                actions=["bedrock:StartIngestionJob"],
                resources=[self._knowledge_base.attr_knowledge_base_arn],
            )
        )

        # SQS -> Lambda event source with batching window
        sync_fn.add_event_source(
            lambda_events.SqsEventSource(
                sync_queue,
                batch_size=10,
                max_batching_window=Duration.seconds(
                    self.kb_props.sync_batch_window_seconds
                ),
            )
        )

        logger.info(
            "Auto-sync enabled: S3 -> SQS (batch_window=%ds) -> Lambda -> "
            "StartIngestionJob",
            self.kb_props.sync_batch_window_seconds,
        )

    def _create_outputs(self) -> None:
        """Create CloudFormation outputs for the stack."""
        CfnOutput(
            self,
            "KnowledgeBaseId",
            value=self._knowledge_base.attr_knowledge_base_id,
            description="Bedrock Knowledge Base ID",
        )
        CfnOutput(
            self,
            "KnowledgeBaseArn",
            value=self._knowledge_base.attr_knowledge_base_arn,
            description="Bedrock Knowledge Base ARN",
        )
        CfnOutput(
            self,
            "DataBucketName",
            value=self.data_bucket.bucket_name,
            description="S3 bucket for source documents",
        )
        CfnOutput(
            self,
            "DataBucketArn",
            value=self.data_bucket.bucket_arn,
            description="S3 bucket ARN for source documents",
        )
        CfnOutput(
            self,
            "DataSourceId",
            value=self._data_source.attr_data_source_id,
            description="Bedrock Data Source ID",
        )
        CfnOutput(
            self,
            "SsmParameterName",
            value=self.ssm_parameter.parameter_name,
            description="SSM parameter storing the KB ID",
        )
