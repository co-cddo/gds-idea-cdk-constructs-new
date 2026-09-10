"""IAM grant helper for rAPId database access."""

from aws_cdk import Stack, aws_iam as iam

from ..config import DeploymentConfig, DeploymentEnvironment
from .athena import (
    grant_athena_results_access,
    grant_athena_workgroup_access,
    grant_glue_catalog_access,
    grant_s3_bucket_access,
)
from .secrets import grant_secret_access
from .settings import (
    RAPID_CROSS_ACCOUNT_ROLE_ARN,
    RAPID_DATA_BUCKET_NAME,
    RAPID_GLUE_DATABASE,
    RAPID_REGION,
    AthenaSettings,
)


def grant_rapid_database_access(
    grantee: iam.IGrantable,
    stack: Stack,
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
        stack: The stack used to resolve region/account for ARNs.
        deployment_config: The current environment's deployment config.
            Used for `.environment` and `.cross_account_role_arn` (falls
            back to rAPId's default cross-account role ARN if unset).
        athena_settings: Resolved Athena settings for the results bucket
            + KMS key (see `AthenaSettings`). Only used in production.
        secret_name: Name, or name prefix, of the secret holding rAPId
            credentials.
    """
    grant_secret_access(grantee, stack, secret_name)

    if deployment_config.environment == DeploymentEnvironment.PRODUCTION:
        grant_athena_workgroup_access(grantee, stack, region=RAPID_REGION)
        grant_glue_catalog_access(
            grantee, stack, RAPID_GLUE_DATABASE, region=RAPID_REGION
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
