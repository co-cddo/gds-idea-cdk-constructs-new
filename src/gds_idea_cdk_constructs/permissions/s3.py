"""IAM grant helpers for S3 buckets addressed by name.

Use these for buckets that are not created and owned by the stack (for
example shared or cross-account buckets). For buckets created in your
own stack, use CDK's `grant_read` / `grant_write`.
"""

from aws_cdk import aws_iam as iam

_READ_ACTIONS = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
_WRITE_ACTIONS = ["s3:PutObject", "s3:AbortMultipartUpload"]


def _grant_s3(
    grantee: iam.IGrantable,
    bucket_name: str,
    actions: list[str],
    sid: str | None,
) -> None:
    """Add a single statement with the given actions on a bucket and its objects.

    Args:
        grantee: The IAM principal to grant permissions to.
        bucket_name: Bucket name (without the `arn:aws:s3:::` prefix).
        actions: The S3 actions to allow.
        sid: Optional statement ID.
    """
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            **({"sid": sid} if sid else {}),
            actions=actions,
            resources=[
                f"arn:aws:s3:::{bucket_name}",
                f"arn:aws:s3:::{bucket_name}/*",
            ],
        )
    )


def grant_s3_read(
    grantee: iam.IGrantable,
    bucket_name: str,
    *,
    sid: str | None = None,
) -> None:
    """Grant read access (`GetObject`, `ListBucket`, `GetBucketLocation`).

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        bucket_name: Bucket name (without the `arn:aws:s3:::` prefix).
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    _grant_s3(grantee, bucket_name, _READ_ACTIONS, sid)


def grant_s3_write(
    grantee: iam.IGrantable,
    bucket_name: str,
    *,
    sid: str | None = None,
) -> None:
    """Grant write access (`PutObject`, `AbortMultipartUpload`).

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        bucket_name: Bucket name (without the `arn:aws:s3:::` prefix).
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    _grant_s3(grantee, bucket_name, _WRITE_ACTIONS, sid)


def grant_s3_read_write(
    grantee: iam.IGrantable,
    bucket_name: str,
    *,
    sid: str | None = None,
) -> None:
    """Grant read and write access in a single statement.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        bucket_name: Bucket name (without the `arn:aws:s3:::` prefix).
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    _grant_s3(grantee, bucket_name, _READ_ACTIONS + _WRITE_ACTIONS, sid)
