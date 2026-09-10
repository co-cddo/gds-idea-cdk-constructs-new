"""IAM helper for Secrets Manager access."""

import aws_cdk as cdk
from aws_cdk import Stack, aws_iam as iam


def grant_secret_access(
    grantee: iam.IGrantable,
    stack: Stack,
    secret_name_prefix: str,
    *,
    sid: str | None = None,
) -> None:
    """Grant read access to secrets whose name starts with a given prefix.

    Uses an ARN with wildcard so the statement matches the random
    suffix Secrets Manager appends to secret names.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        stack: The stack used to resolve the secret ARN via `format_arn`.
        secret_name_prefix: The secret name, or name prefix, to match.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            **({"sid": sid} if sid else {}),
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
