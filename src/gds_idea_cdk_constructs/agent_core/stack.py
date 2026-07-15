import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
from aws_cdk import (
    CfnOutput,
    Stack,
    aws_iam as iam,
)
from constructs import Construct

from .props import (
    _DEFAULT_AGENT_CODE_DIR,
    AgentCoreProperties,
    BuiltInAgent,
)


class AgentCore(Stack):
    """CDK Stack that deploys an Amazon Bedrock AgentCore Runtime.

    Provisions the runtime with memory and permissions.

    Args:
        scope: The parent construct.
        construct_id: The construct ID.
        props: Configuration properties for the AgentCore runtime.
        **kwargs: Additional stack arguments (e.g. env, description).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: AgentCoreProperties,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Resolve agent mode ---
        if isinstance(props.agent, BuiltInAgent):
            code_dir = _DEFAULT_AGENT_CODE_DIR
            env_vars = {
                **props.agent.model.to_envs(),
                "REGION": self.region,
                "LOG_LEVEL": props.agent.log_level,
                **(
                    {"SYSTEM_PROMPT": props.agent.system_prompt}
                    if props.agent.system_prompt
                    else {}
                ),
            }
            model_id = props.agent.model.model_id
        else:  # CustomAgent
            code_dir = props.agent.agent_code_directory
            env_vars = {
                "MODEL_ID": props.agent.model_id,
                "REGION": self.region,
                **props.agent.environment_variables,
            }
            model_id = props.agent.model_id

        # --- Memory (optional) ---
        memory = None
        if props.memory:
            memory = agentcore.Memory(
                self,
                "AgentMemory",
                memory_name=props.memory.name,
                description=props.memory.description,
            )
            cfn_memory = memory.node.default_child
            if cfn_memory:
                cfn_memory.apply_removal_policy(props.removal_policy)
            env_vars["MEMORY_ID"] = memory.memory_id

        # --- Knowledge Base (optional)
        if props.knowledge_base:
            kb_config = props.knowledge_base
            env_vars.update(kb_config.knowledge_base.environment_variables)
            env_vars["MIN_SCORE"] = str(kb_config.min_score)
            env_vars["RETRIEVE_ENABLE_METADATA_DEFAULT"] = str(
                kb_config.enable_metadata
            ).lower()

        # --- Artifact + Runtime ---
        code_artifact = agentcore.AgentRuntimeArtifact.from_asset(
            directory=code_dir,
            platform=props.platform,
        )

        runtime = agentcore.Runtime(
            self,
            "AgentCoreRuntime",
            runtime_name=props.runtime_name,
            agent_runtime_artifact=code_artifact,
            description=props.description,
            environment_variables=env_vars,
        )

        # Expose cross-stack attributes
        self.runtime_role = runtime.role
        self.runtime_arn = runtime.agent_runtime_arn

        # --- Permissions ---
        # Model access (only for BuiltInAgent)
        if model_id:
            # Cross-region inference profiles (us., eu., ap.) route to foundation
            # models in other regions. IAM needs access to both the profile and
            # the underlying foundation model (wildcard region).
            prefix = model_id.split(".")[0]
            if prefix in ("us", "eu", "ap"):
                base_model_id = model_id[len(prefix) + 1 :]
                model_resources = [
                    (
                        f"arn:aws:bedrock:{self.region}:{self.account}"
                        f":inference-profile/{model_id}"
                    ),
                    f"arn:aws:bedrock:*::foundation-model/{base_model_id}",
                ]
            else:
                model_resources = [
                    f"arn:aws:bedrock:{self.region}::foundation-model/{model_id}"
                ]
            runtime.role.add_to_policy(
                iam.PolicyStatement(
                    actions=[
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream",
                    ],
                    resources=model_resources,
                )
            )

        # Memory access (only if memory was created)
        if memory:
            memory.grant_read(runtime)
            memory.grant_write(runtime)

        # Broad permission to look at what log groups exist
        runtime.role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:DescribeLogGroups"],
                resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:*"],
            )
        )

        # Strict permission to write logs
        runtime.role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/*",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans:*",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/application-signals/data:*",
                ],
            )
        )

        # X-Ray Tracing
        runtime.role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )

        # Application Signals & Spans (OpenTelemetry)
        runtime.role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:PutLogEvents"],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans:*",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/application-signals/data:*",
                ],
                conditions={
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:aws:logs:{self.region}:{self.account}:log-group:*"
                        )
                    },
                    "StringEquals": {"aws:SourceAccount": self.account},
                },
            )
        )

        # CloudWatch Metrics
        runtime.role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={
                    "StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}
                },
            )
        )

        # AgentCore Identity Access
        runtime.role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:workload-identity-directory/default/workload-identity/*",
                ],
            )
        )

        # Knowledge Base permissions
        if props.knowledge_base:
            props.knowledge_base.knowledge_base.grant_retrieve(runtime.role)

        # Show outputs
        CfnOutput(self, "RuntimeArn", value=runtime.agent_runtime_arn)
        CfnOutput(self, "RuntimeRoleArn", value=runtime.role.role_arn)

    # ------------------------------------------------------------------
    # Cross-Stack integration
    # ------------------------------------------------------------------

    def grant_invoke(self, grantee: iam.IGrantable) -> None:
        """Grant permissions to invoke this AgentCore runtime.

        Grants the grantee ``bedrock-agentcore:InvokeAgentRuntime`` on the
        runtime ARN.

        Args:
            grantee: The IAM principal to grant permissions to (e.g. a
                task role from a
                :class:`~gds_idea_cdk_constructs.web_app.WebApp` stack).

        Example:
            ::

                agent = AgentCore(app, "AgentStack", props=AgentCoreProperties(...))
                webapp = WebApp(app, ...)
                agent.grant_invoke(webapp.task_role)
        """
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                sid="AgentCoreInvoke",
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[self.runtime_arn],
            )
        )

    @property
    def environment_variables(self) -> dict[str, str]:
        """Environment variables for containers invoking this runtime.

        Returns a dict suitable for passing into
        :class:`~gds_idea_cdk_constructs.web_app.WebAppContainerProperties`
        ``environment_variables``:

        - ``AGENTCORE_RUNTIME_ARN``: The AgentCore runtime ARN.

        Example:
            ::

                container_props = WebAppContainerProperties(
                    environment_variables={
                        **agent.environment_variables,
                        "MY_OTHER_VAR": "value",
                    },
                )
        """
        return {"AGENTCORE_RUNTIME_ARN": self.runtime_arn}
