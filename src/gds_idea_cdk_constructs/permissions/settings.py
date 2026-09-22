"""Shared settings for IAM permission helpers.

`AthenaSettings` fetches the per-environment Athena query results bucket
and KMS key from AWS Systems Manager Parameter Store (mirroring the fetch
pattern used by `DeploymentConfig` Keeps it separate since these are
IAM/permissions-specific settings rather than webapp deployment settings)
and might not always want a webapp.
Other values are static.
"""

import json
import logging

import boto3
from aws_cdk import Environment as CdkEnvironment

from ..config import DeploymentEnvironment

logger = logging.getLogger(__name__)

DEFAULT_REGION = (
    "eu-west-2"  # London should be used by default for every bit of infra we create
)

ATHENA_WORKGROUP_NAME = "primary"  # same name in both dev and prod accounts currently


class AthenaSettings:
    """Environment-specific Athena settings, fetched from Parameter Store.

    Fetches a single SSM parameter (``/gds-idea-athena``) containing a JSON
    blob keyed by account ID each with ``results_bucket_name`` and
    ``kms_key_arn``.

    For testing, local development without Parameter Store access,
    or to point at a different KMS key/bucket, use the `from_dict`
    classmethod instead.
    """

    PARAM_NAME = "/gds-idea-athena"

    def __init__(self, cdk_env: CdkEnvironment):
        """Create AthenaSettings by fetching from Parameter Store.

        Args:
            cdk_env: The CDK Environment (must have account and region set).

        Raises:
            ValueError: If the account is unknown, the environment is
                TESTING, or the parameter is missing the current account.
        """
        environment = DeploymentEnvironment.from_cdk_env(cdk_env)
        if environment == DeploymentEnvironment.TESTING:
            raise ValueError(
                "TESTING environment cannot fetch from Parameter Store. "
                "Use AthenaSettings.from_dict() instead."
            )
        region = cdk_env.region or DEFAULT_REGION
        config = self._fetch_from_parameter_store(region)
        self._apply_config(environment, config, region)

    @classmethod
    def from_dict(
        cls,
        environment: DeploymentEnvironment,
        config: dict[str, dict[str, str]],
        region: str = DEFAULT_REGION,
    ) -> "AthenaSettings":
        """Create AthenaSettings from an explicit config dict.

        Useful for testing or local development without Parameter Store
        access.

        Args:
            environment: The environment to select settings for.
            config: Dict keyed by account ID, matching the shape stored in
                Parameter Store.
            region: AWS region these settings apply to.

        Returns:
            A configured AthenaSettings instance.
        """
        instance = object.__new__(cls)
        instance._apply_config(environment, config, region)
        return instance

    def _apply_config(
        self,
        environment: DeploymentEnvironment,
        config: dict[str, dict[str, str]],
        region: str,
    ) -> None:
        """Select this environment's settings and set attributes.

        Args:
            environment: The environment to select settings for.
            config: Dict keyed by account ID.
            region: AWS region these settings apply to.

        Raises:
            ValueError: If there is no config for this environment's account.
        """
        try:
            env_config = config[environment.value]
        except KeyError as e:
            raise ValueError(
                f"No Athena settings found for environment {environment} "
                f"(account {environment.value})"
            ) from e

        self.account = environment.value
        self.region = region
        self.results_bucket_name = env_config["results_bucket_name"]
        self.kms_key_arn = env_config["kms_key_arn"]

    def _fetch_from_parameter_store(self, region: str) -> dict[str, dict[str, str]]:
        """Fetch and parse the Athena settings parameter.

        Args:
            region: AWS region to create the SSM client in.

        Returns:
            Parsed JSON dict keyed by account ID.

        Raises:
            botocore.exceptions.ClientError: If the parameter cannot be
                retrieved.
        """
        logger.info("Fetching Athena settings from Parameter Store")
        client = boto3.client("ssm", region_name=region)
        response = client.get_parameter(Name=self.PARAM_NAME)
        return json.loads(response["Parameter"]["Value"])


# Set up the variables for rapid connections with athena
RAPID_REGION = DEFAULT_REGION
RAPID_DATA_BUCKET_NAME = "rapid-cddo"
RAPID_GLUE_DATABASE = "rapid-cddo_catalogue_db"
RAPID_CROSS_ACCOUNT_ROLE_ARN = (
    f"arn:aws:iam::{DeploymentEnvironment.PRODUCTION.value}"
    ":role/assume_role_for_development_account"
)
