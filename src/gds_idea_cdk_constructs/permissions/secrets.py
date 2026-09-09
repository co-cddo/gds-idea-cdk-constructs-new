"""IAM grant helper for Secrets Manager access."""

import aws_cdk as cdk
from aws_cdk import Stack, aws_iam as iam


def grant_secret_access(
    task_role: iam.IRole,
    stack: Stack,
    secret_name_prefix: str,
    *,
    sid: str = "SecretAccess",
) -> None:
    """Grant read access to secrets whose name starts with a given prefix.

    Uses a wildcard-suffixed ARN so the statement matches the random
    suffix Secrets Manager appends to secret names.

    Args:
        task_role: The role to attach the policy statement to.
        stack: The stack used to resolve the secret ARN via `format_arn`.
        secret_name_prefix: The secret name, or name prefix, to match.
        sid: Statement ID. Override if calling multiple times on one role.
    """
    task_role.add_to_policy(
        iam.PolicyStatement(
            sid=sid,
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                stack.format_arn(
                    service="secretsmanager",
                    resource="secret",
                    resource_name=f"{secret_name_prefix}*",
                    arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
                )
            ],
        )
    )
