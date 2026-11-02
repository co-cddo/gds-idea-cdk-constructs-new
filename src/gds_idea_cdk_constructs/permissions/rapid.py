"""IAM grant helper for rAPId database access."""

from aws_cdk import aws_iam as iam

from ..config import (
    RAPID_CROSS_ACCOUNT_ROLE_ARN,
    DeploymentConfig,
    DeploymentEnvironment,
)
from .athena import (
    grant_athena_results,
    grant_athena_workgroup,
    grant_glue_catalog,
)
from .s3 import grant_s3_read
from .settings import (
    DEFAULT_REGION,
    RAPID_DATA_BUCKET_NAME,
    RAPID_GLUE_DATABASE,
    RAPID_REGION,
    AthenaSettings,
)


def grant_rapid_database(
    grantee: iam.IGrantable,
    deployment_config: DeploymentConfig,
    secret_name: str,
    *,
    athena_settings: AthenaSettings | None = None,
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
        secret_name: Name, or name prefix, of the secret holding rAPId
            credentials.
        athena_settings: Optional resolved Athena settings for the results
            bucket + KMS key (see `AthenaSettings`). Only used in
            production, where it defaults to
            `AthenaSettings(deployment_config.cdk_env)` (which reads
            Parameter Store). Never read in other environments.
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
        athena_settings = athena_settings or AthenaSettings(deployment_config.cdk_env)
        grant_athena_workgroup(grantee, athena_settings, region=RAPID_REGION)
        grant_glue_catalog(
            grantee, athena_settings, RAPID_GLUE_DATABASE, region=RAPID_REGION
        )
        grant_s3_read(grantee, RAPID_DATA_BUCKET_NAME)
        grant_athena_results(grantee, athena_settings)
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
