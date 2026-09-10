"""IAM grant helpers for Athena/Glue/S3/KMS-backed datasets.

IAM policy statements to a task role for running Athena queries,
reading Glue Data Catalog metadata, reading S3 data buckets,
and decrypting with KMS keys.
`grant_athena_results_access` sets up the S3 + KMS helpers using an `AthenaSettings`
instance so that
"""

from aws_cdk import Stack, aws_iam as iam

from .settings import ATHENA_WORKGROUP_NAME, AthenaSettings


def grant_athena_workgroup_access(
    task_role: iam.IRole,
    stack: Stack,
    *,
    workgroup_name: str = ATHENA_WORKGROUP_NAME,
    region: str | None = None,
    sid: str | None = None,
) -> None:
    """Grant permissions to run and manage Athena queries in a workgroup.

    Args:
        task_role: The role to attach the policy statement to.
        stack: The stack used to resolve region/account for the ARN.
        workgroup_name: Athena workgroup name. Defaults to the shared
            "primary" workgroup used in both dev and prod.
        region: Overrides the region in the workgroup ARN. Defaults to
            `stack.region`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    resolved_region = region or stack.region
    task_role.add_to_policy(
        iam.PolicyStatement(
            **({"sid": sid} if sid else {}),
            actions=[
                "athena:StartQueryExecution",
                "athena:GetQueryExecution",
                "athena:GetQueryResults",
                "athena:GetWorkGroup",
                "athena:StopQueryExecution",
            ],
            resources=[
                f"arn:aws:athena:{resolved_region}:{stack.account}"
                f":workgroup/{workgroup_name}"
            ],
        )
    )


def grant_glue_catalog_access(
    task_role: iam.IRole,
    stack: Stack,
    database_name: str,
    *,
    table_name_pattern: str = "*",
    region: str | None = None,
    sid: str | None = None,
) -> None:
    """Grant read-only access to a Glue Data Catalog database and its tables.

    Args:
        task_role: The role to attach the policy statement to.
        stack: The stack used to resolve region/account for the ARN.
        database_name: The Glue database name.
        table_name_pattern: Table name, or wildcard pattern, to scope
            access to.
        region: Overrides the region in the ARNs. Defaults to
            `stack.region`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    resolved_region = region or stack.region
    task_role.add_to_policy(
        iam.PolicyStatement(
            **({"sid": sid} if sid else {}),
            actions=[
                "glue:GetTable",
                "glue:GetTables",
                "glue:GetDatabase",
                "glue:GetDatabases",
                "glue:GetPartitions",
            ],
            resources=[
                f"arn:aws:glue:{resolved_region}:{stack.account}:catalog",
                f"arn:aws:glue:{resolved_region}:{stack.account}"
                f":database/{database_name}",
                f"arn:aws:glue:{resolved_region}:{stack.account}"
                f":table/{database_name}/{table_name_pattern}",
            ],
        )
    )


def grant_s3_bucket_access(
    task_role: iam.IRole,
    bucket_name: str,
    *,
    write: bool = False,
    sid: str | None = None,
) -> None:
    """Grant read (or read/write) access to an S3 bucket by name.

    Args:
        task_role: The role to attach the policy statement to.
        bucket_name: Bucket name (without the `arn:aws:s3:::` prefix).
        write: If True, also grant `PutObject`/`AbortMultipartUpload`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    actions = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
    if write:
        actions += ["s3:PutObject", "s3:AbortMultipartUpload"]
    task_role.add_to_policy(
        iam.PolicyStatement(
            **({"sid": sid} if sid else {}),
            actions=actions,
            resources=[
                f"arn:aws:s3:::{bucket_name}",
                f"arn:aws:s3:::{bucket_name}/*",
            ],
        )
    )


def grant_kms_key_access(
    task_role: iam.IRole,
    key_arn: str,
    *,
    sid: str | None = None,
) -> None:
    """Grant decrypt/encrypt access to a KMS key by ARN.

    Args:
        task_role: The role to attach the policy statement to.
        key_arn: The KMS key ARN.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    task_role.add_to_policy(
        iam.PolicyStatement(
            **({"sid": sid} if sid else {}),
            actions=[
                "kms:Decrypt",
                "kms:GenerateDataKey",
                "kms:DescribeKey",
                "kms:CreateGrant",
            ],
            resources=[key_arn],
        )
    )


def grant_athena_results_access(
    task_role: iam.IRole,
    athena_settings: AthenaSettings,
    *,
    write: bool = True,
    sid_prefix: str | None = None,
) -> None:
    """Grant access to the environment's Athena query results bucket + key.

    Args:
        task_role: The role to attach policy statements to.
        athena_settings: Resolved settings for the current environment
            (see `AthenaSettings`), providing the results bucket name and
            KMS key ARN.
        write: If True (default), also grant write access to the results
            bucket (queries need to write their own results).
        sid_prefix: Optional prefix used to build the two statement Sids
            (`{sid_prefix}BucketAccess`, `{sid_prefix}KmsAccess`). Omitted
            by default; only set if you want named statements.
    """
    grant_s3_bucket_access(
        task_role,
        athena_settings.results_bucket_name,
        write=write,
        sid=f"{sid_prefix}BucketAccess" if sid_prefix else None,
    )
    grant_kms_key_access(
        task_role,
        athena_settings.kms_key_arn,
        sid=f"{sid_prefix}KmsAccess" if sid_prefix else None,
    )
