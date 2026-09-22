"""IAM grant helpers for Athena/Glue/S3/KMS-backed datasets.

IAM policy statements to a task role for running Athena queries,
reading Glue Data Catalog metadata, reading S3 data buckets,
and decrypting with KMS keys.
`grant_athena` composes everything into a single call for full access
to an Athena-backed table.
"""

from aws_cdk import aws_iam as iam

from .settings import ATHENA_WORKGROUP_NAME, AthenaSettings


def grant_athena_workgroup_access(
    grantee: iam.IGrantable,
    athena_settings: AthenaSettings,
    *,
    workgroup_name: str = ATHENA_WORKGROUP_NAME,
    region: str | None = None,
    sid: str | None = None,
) -> None:
    """Grant permissions to run and manage Athena queries in a workgroup.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        athena_settings: Resolved settings for the current environment
            (see `AthenaSettings`), used to resolve region/account for the
            ARN.
        workgroup_name: Athena workgroup name. Defaults to the shared
            "primary" workgroup used in both dev and prod.
        region: Overrides the region in the workgroup ARN. Defaults to
            `athena_settings.region`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    resolved_region = region or athena_settings.region
    grantee.grant_principal.add_to_principal_policy(
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
                f"arn:aws:athena:{resolved_region}:{athena_settings.account}"
                f":workgroup/{workgroup_name}"
            ],
        )
    )


def grant_glue_catalog_access(
    grantee: iam.IGrantable,
    athena_settings: AthenaSettings,
    database_name: str,
    *,
    table_name_pattern: str = "*",
    region: str | None = None,
    sid: str | None = None,
) -> None:
    """Grant read-only access to a Glue Data Catalog database and its tables.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        athena_settings: Resolved settings for the current environment
            (see `AthenaSettings`), used to resolve region/account for the
            ARNs.
        database_name: The Glue database name.
        table_name_pattern: Table name, or wildcard pattern, to scope
            access to.
        region: Overrides the region in the ARNs. Defaults to
            `athena_settings.region`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    resolved_region = region or athena_settings.region
    grantee.grant_principal.add_to_principal_policy(
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
                f"arn:aws:glue:{resolved_region}:{athena_settings.account}:catalog",
                f"arn:aws:glue:{resolved_region}:{athena_settings.account}"
                f":database/{database_name}",
                f"arn:aws:glue:{resolved_region}:{athena_settings.account}"
                f":table/{database_name}/{table_name_pattern}",
            ],
        )
    )


def grant_s3_bucket_access(
    grantee: iam.IGrantable,
    bucket_name: str,
    *,
    write: bool = False,
    sid: str | None = None,
) -> None:
    """Grant read (or read/write) access to an S3 bucket by name.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        bucket_name: Bucket name (without the `arn:aws:s3:::` prefix).
        write: If True, also grant `PutObject`/`AbortMultipartUpload`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    actions = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
    if write:
        actions += ["s3:PutObject", "s3:AbortMultipartUpload"]
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


def grant_kms_key_access(
    grantee: iam.IGrantable,
    key_arn: str,
    *,
    sid: str | None = None,
) -> None:
    """Grant decrypt/encrypt access to a KMS key by ARN.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        key_arn: The KMS key ARN.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    grantee.grant_principal.add_to_principal_policy(
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
    grantee: iam.IGrantable,
    athena_settings: AthenaSettings,
    *,
    write: bool = True,
    sid_prefix: str | None = None,
) -> None:
    """Grant access to the environment's Athena query results bucket + key.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
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
        grantee,
        athena_settings.results_bucket_name,
        write=write,
        sid=f"{sid_prefix}BucketAccess" if sid_prefix else None,
    )
    grant_kms_key_access(
        grantee,
        athena_settings.kms_key_arn,
        sid=f"{sid_prefix}KmsAccess" if sid_prefix else None,
    )


def grant_athena(
    grantee: iam.IGrantable,
    database_name: str,
    bucket_name: str,
    athena_settings: AthenaSettings,
    *,
    table_name_pattern: str = "*",
    workgroup_name: str = ATHENA_WORKGROUP_NAME,
    write: bool = True,
    region: str | None = None,
    sid_prefix: str | None = None,
) -> None:
    """Grant everything needed to query an Athena-backed table.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        database_name: The Glue database name.
        bucket_name: The S3 bucket backing the table's data.
        athena_settings: Resolved settings for the current environment
            (see `AthenaSettings`), providing the results bucket name and
            KMS key ARN, as well as the account/region used to resolve
            the Athena workgroup and Glue catalog ARNs.
        table_name_pattern: Table name, or wildcard pattern, to scope Glue
            access to.
        workgroup_name: Athena workgroup name. Defaults to the shared
            "primary" workgroup
        write: If True (default), also grant write access to the data
            bucket (e.g. for `INSERT INTO`/CTAS queries). The query
            results bucket is always granted write access since Athena
            always needs to write its own results.
        region: Overrides the region in the ARNs. Defaults to
            `athena_settings.region`.
        sid_prefix: Optional prefix used to build the composed statements'
            Sids (`{sid_prefix}WorkgroupAccess`, `{sid_prefix}GlueAccess`,
            `{sid_prefix}DataBucketAccess`. Only set if you want named statements.
    """
    grant_athena_workgroup_access(
        grantee,
        athena_settings,
        workgroup_name=workgroup_name,
        region=region,
        sid=f"{sid_prefix}WorkgroupAccess" if sid_prefix else None,
    )
    grant_glue_catalog_access(
        grantee,
        athena_settings,
        database_name,
        table_name_pattern=table_name_pattern,
        region=region,
        sid=f"{sid_prefix}GlueAccess" if sid_prefix else None,
    )
    grant_s3_bucket_access(
        grantee,
        bucket_name,
        write=write,
        sid=f"{sid_prefix}DataBucketAccess" if sid_prefix else None,
    )
    grant_athena_results_access(grantee, athena_settings, sid_prefix=sid_prefix)
