"""IAM helper for Amazon Bedrock model invocation."""

from aws_cdk import Stack, aws_iam as iam

_INVOKE_MODEL_ACTIONS = [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "bedrock:Converse",
    "bedrock:ConverseStream",
]


def grant_bedrock_invoke_model_access(
    task_role: iam.IRole,
    stack: Stack,
    *,
    model_ids: list[str] | None = None,
    sid: str = "BedrockInvokeModelAccess",
) -> None:
    """Grant permission to invoke Bedrock foundation models.

    Args:
        task_role: The role to attach the policy statement to.
        stack: The stack used to resolve the region for the ARN.
        model_ids: Optional list of foundation model IDs to scope access to,
            e.g. ["anthropic.claude-3-5-sonnet-20241022-v2:0"]. Defaults to
            all foundation models ("*") for early testing before devs can
            start to constrain policies.
        sid: Statement ID. Override if calling multiple times on one role.
    """
    resource_ids = model_ids or ["*"]
    task_role.add_to_policy(
        iam.PolicyStatement(
            sid=sid,
            actions=_INVOKE_MODEL_ACTIONS,
            resources=[
                f"arn:aws:bedrock:{stack.region}::foundation-model/{model_id}"
                for model_id in resource_ids
            ],
        )
    )
