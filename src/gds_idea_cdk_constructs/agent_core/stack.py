import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
from aws_cdk import (
    CfnOutput,
    Stack,
    aws_iam as iam,
)
from constructs import Construct

from .props import AgentCoreProperties


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

        # The Artifact
        code_artifact = agentcore.AgentRuntimeArtifact.from_asset(
            directory=props.agent_code_directory,
            platform=props.platform,
        )

        # --- The Short Term Memory ---
        memory = agentcore.Memory(
            self,
            "AgentMemory",
            memory_name=props.memory_name,
            description=props.memory_description,
        )

        # The Runtime
        runtime = agentcore.Runtime(
            self,
            "AgentCoreRuntime",
            runtime_name=props.runtime_name,
            agent_runtime_artifact=code_artifact,
            description=props.description,
            environment_variables={
                "MEMORY_ID": memory.memory_id,
                "REGION": self.region,
                "MODEL_ID": props.model_id,
                "LOG_LEVEL": props.log_level,
                **(
                    {"SYSTEM_PROMPT": props.system_prompt}
                    if props.system_prompt
                    else {}
                ),
                **props.environment_variables,
            },
        )

        # --- Permissions ---
        # Cross-region model IDs (us., eu., ap.) are inference profiles;
        # plain IDs (anthropic.claude-...) are foundation models.
        if props.model_id.split(".")[0] in ("us", "eu", "ap"):
            model_arn = (
                f"arn:aws:bedrock:{self.region}:{self.account}"
                f":inference-profile/{props.model_id}"
            )
        else:
            model_arn = (
                f"arn:aws:bedrock:{self.region}::foundation-model/{props.model_id}"
            )
        runtime.role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[model_arn],
            )
        )

        # Memory Access
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
                    # The main agent logs
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/*",
                    # The OpenTelemetry Trace logs
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans:*",
                    # The OpenTelemetry Application Signals logs
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

        # AgentCore Identity Access - ensure memory responses
        # are attributed to the correct session and user
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

        # Show outputs
        CfnOutput(self, "RuntimeArn", value=runtime.agent_runtime_arn)
