"""IAM grant helper for rAPId database access."""

from aws_cdk import aws_iam as iam

from ..config import DeploymentConfig, DeploymentEnvironment
from .athena import (
    grant_athena_results_access,
    grant_athena_workgroup_access,
    grant_glue_catalog_access,
    grant_s3_bucket_access,
)
from .settings import (
    DEFAULT_REGION,
    RAPID_CROSS_ACCOUNT_ROLE_ARN,
    RAPID_DATA_BUCKET_NAME,
    RAPID_GLUE_DATABASE,
    RAPID_REGION,
    AthenaSettings,
)


def grant_rapid_database_access(
    grantee: iam.IGrantable,
    deployment_config: DeploymentConfig,
    athena_settings: AthenaSettings,
    secret_name: str,
) -> None:
    """Grant access to query rAPId's shared Athena-backed database.

    In production, grants direct access to rAPId's Athena workgroup, Glue
    catalog, data bucket, and query results bucket/KMS key (rAPId lives in
    the production account). In every other environment, grants
    `sts:AssumeRole` on rAPId's cross-account role instead, since access
    must be brokered through the production account.

    A secret holding rAPId API credentials is always granted, regardless
    of environment.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        deployment_config: The current environment's deployment config.
            Used for `.environment`, `.cdk_env.region` (to derive the
            secret ARN's account/region), and `.cross_account_role_arn`.
        athena_settings: Resolved Athena settings for the results bucket
            + KMS key (see `AthenaSettings`). Only used in production.
        secret_name: Name, or name prefix, of the secret holding rAPId
            credentials.
    """
    account = deployment_config.environment.value
    region = deployment_config.cdk_env.region or DEFAULT_REGION
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                f"arn:aws:secretsmanager:{region}:{account}:secret:{secret_name}*"
            ],
        )
    )

    if deployment_config.environment == DeploymentEnvironment.PRODUCTION:
        grant_athena_workgroup_access(grantee, athena_settings, region=RAPID_REGION)
        grant_glue_catalog_access(
            grantee, athena_settings, RAPID_GLUE_DATABASE, region=RAPID_REGION
        )
        grant_s3_bucket_access(grantee, RAPID_DATA_BUCKET_NAME)
        grant_athena_results_access(grantee, athena_settings)
    else:
        role_arn = (
            deployment_config.cross_account_role_arn or RAPID_CROSS_ACCOUNT_ROLE_ARN
        )
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[role_arn],
            )
        )
