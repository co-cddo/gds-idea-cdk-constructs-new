import json

import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_iam as iam,
    aws_ssm as ssm,
)
from constructs import Construct, IConstruct

from .props import (
    _DEFAULT_AGENT_CODE_DIR,
    AgentCoreProperties,
    BuiltInAgent,
    GatewayConfig,
)

# value_from_lookup returns "dummy-value-for-<path>" until the CDK has fetched it
_LOOKUP_PLACEHOLDER_PREFIX = "dummy-value-for-"


def _gateway_ssm_path(gateway_name: str, attribute: str) -> str:
    """SSM parameter path published by the gateway repository."""
    return f"/gds-idea/gateways/{gateway_name}/{attribute}"


def _ssm_context_key(account: str, region: str, parameter_name: str) -> str:
    """Key the CDK caches an SSM lookup under in ``cdk.context.json``."""
    return f"ssm:account={account}:parameterName={parameter_name}:region={region}"


def _lookup_gateway_tools(scope: IConstruct, gateway_name: str) -> list[str] | None:
    """Read the tool names a gateway publishes, at synth time.

    The value is cached by the CDK in ``cdk.context.json``.

    Args:
        scope: Construct whose stack env is used for the lookup. Must have a
            concrete account and region.
        gateway_name: Name of the gateway.

    Returns:
        The published ``{target}___{tool}`` names, or ``None`` on the first
        synth, when the CDK has not yet fetched the value and returns a
        placeholder.

    Raises:
        ValueError: If the parameter does not hold a JSON list of strings.
    """
    path = _gateway_ssm_path(gateway_name, "tools")
    value = ssm.StringParameter.value_from_lookup(scope, path)
    if value.startswith(_LOOKUP_PLACEHOLDER_PREFIX):
        return None
    try:
        tools = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"SSM parameter {path} does not contain valid JSON") from e
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise ValueError(f"SSM parameter {path} must contain a JSON list of strings")
    return tools


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

        # --- Gateway (optional) ---
        gateway_arns: list[str] = []
        if props.gateway:
            gateway_urls = []
            for gateway_name in props.gateway.gateways:
                gateway_urls.append(
                    ssm.StringParameter.value_for_string_parameter(
                        self, _gateway_ssm_path(gateway_name, "url")
                    )
                )
                gateway_arns.append(
                    ssm.StringParameter.value_for_string_parameter(
                        self, _gateway_ssm_path(gateway_name, "arn")
                    )
                )
            # to_json_string (not json.dumps) so deploy-time SSM tokens resolve
            env_vars["GATEWAY_URLS"] = self.to_json_string(gateway_urls)
            if props.gateway.targets is not None:
                env_vars["GATEWAY_TARGETS"] = json.dumps(props.gateway.targets)
                self._validate_gateway_targets(props.gateway)

        # --- Artifact + Runtime ---
        code_artifact = agentcore.AgentRuntimeArtifact.from_asset(
            directory=code_dir,
            platform=props.platform,
        )

        # A fixed role name lets other stacks (e.g. a gateway's Cedar policy)
        # refer to this role. A generated name changes if the role is replaced.
        # Same settings as the role the runtime would create for itself.
        execution_role = iam.Role(
            self,
            "AgentCoreRuntimeRole",
            role_name=f"{props.runtime_name}-{self.region}",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description="Execution role for Bedrock Agent Core Runtime",
            max_session_duration=Duration.hours(8),
        )

        runtime = agentcore.Runtime(
            self,
            "AgentCoreRuntime",
            runtime_name=props.runtime_name,
            agent_runtime_artifact=code_artifact,
            description=props.description,
            environment_variables=env_vars,
            execution_role=execution_role,
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

        # Gateway permissions: InvokeGateway is per gateway and needs the exact ARN
        if gateway_arns:
            runtime.role.add_to_policy(
                iam.PolicyStatement(
                    sid="GatewayInvoke",
                    actions=["bedrock-agentcore:InvokeGateway"],
                    resources=gateway_arns,
                )
            )

        # Show outputs
        CfnOutput(self, "RuntimeArn", value=runtime.agent_runtime_arn)
        CfnOutput(self, "RuntimeRoleArn", value=runtime.role.role_arn)

    def _validate_gateway_targets(self, gateway: GatewayConfig) -> None:
        """Fail synth if a requested target is not published by the gateway(s).

        Skipped on the first synth, while any gateway's tool list is still a
        placeholder: the CDK fetches the real value and synthesises again.
        """
        published: list[str] = []
        for gateway_name in gateway.gateways:
            tools = _lookup_gateway_tools(self, gateway_name)
            if tools is None:
                return
            published.extend(tools)
        context_keys = [
            _ssm_context_key(
                self.account, self.region, _gateway_ssm_path(name, "tools")
            )
            for name in gateway.gateways
        ]
        gateway.validate_against(published, context_keys)

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
