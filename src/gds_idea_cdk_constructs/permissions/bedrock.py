"""IAM helper for Amazon Bedrock model invocation."""

from aws_cdk import Stack, aws_iam as iam

_INVOKE_MODEL_ACTIONS = [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "bedrock:Converse",
    "bedrock:ConverseStream",
]


def grant_bedrock_invoke_model_access(
    grantee: iam.IGrantable,
    stack: Stack,
    *,
    model_ids: list[str] | None = None,
    sid: str | None = None,
) -> None:
    """Grant permission to invoke Bedrock foundation models.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        stack: The stack used to resolve the region for the ARN.
        model_ids: Optional list of foundation model IDs to scope access to,
            e.g. ["anthropic.claude-3-5-sonnet-20241022-v2:0"]. Defaults to
            all foundation models ("*") for early testing before devs can
            start to constrain policies.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    resource_ids = model_ids or ["*"]
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            **({"sid": sid} if sid else {}),
            actions=_INVOKE_MODEL_ACTIONS,
            resources=[
                f"arn:aws:bedrock:{stack.region}::foundation-model/{model_id}"
                for model_id in resource_ids
            ],
        )
    )
