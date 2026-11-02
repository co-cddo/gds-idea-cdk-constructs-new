"""Shared settings for IAM permission helpers.

`AthenaSettings` fetches the Athena query results bucket and KMS key from
AWS Systems Manager Parameter Store, using the same pattern as
`DeploymentConfig`. It is kept separate because these are permissions
settings, and might not always need a webapp.
Other values are static.
"""

from __future__ import annotations

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
    """Account-specific Athena settings, fetched from Parameter Store.

    Fetches a single SSM parameter (``/gds-idea-athena``) containing a JSON
    object with ``results_bucket_name`` and ``kms_key_arn``. Each account
    holds its own values, same as `DeploymentConfig` parameters.

    For testing, local development without Parameter Store access,
    or to point at a different KMS key/bucket, use the `from_dict`
    classmethod instead.

    Attributes:
        account: The AWS account ID these settings apply to.
        region: The AWS region these settings apply to.
        results_bucket_name: Name of the Athena query results bucket.
        kms_key_arn: ARN of the KMS key encrypting the results bucket.
    """

    PARAM_NAME = "/gds-idea-athena"
    REQUIRED_KEYS = frozenset({"results_bucket_name", "kms_key_arn"})

    def __init__(self, cdk_env: CdkEnvironment):
        """Create AthenaSettings by fetching from Parameter Store.

        Args:
            cdk_env: The CDK Environment (must have account and region set).

        Raises:
            ValueError: If the account is unknown, the environment is
                TESTING, or the parameter is missing required keys.
        """
        environment = DeploymentEnvironment.from_cdk_env(cdk_env)
        if environment == DeploymentEnvironment.TESTING:
            raise ValueError(
                "TESTING environment cannot fetch from Parameter Store. "
                "Use AthenaSettings.from_dict() instead."
            )
        region = cdk_env.region or DEFAULT_REGION
        config = self._fetch_from_parameter_store(region)
        self._apply_config(cdk_env, config)

    @classmethod
    def from_dict(
        cls, cdk_env: CdkEnvironment, config: dict[str, str]
    ) -> AthenaSettings:
        """Create AthenaSettings from an explicit config dict.

        Useful for testing or local development without Parameter Store
        access.

        Args:
            cdk_env: The CDK Environment (must have account set). The
                region defaults to `DEFAULT_REGION` if unset.
            config: Dict containing `results_bucket_name` and `kms_key_arn`.

        Returns:
            A configured AthenaSettings instance.

        Raises:
            ValueError: If config is missing required keys.
        """
        instance = object.__new__(cls)
        instance._apply_config(cdk_env, config)
        return instance

    def _apply_config(self, cdk_env: CdkEnvironment, config: dict[str, str]) -> None:
        """Validate the config and set attributes.

        Args:
            cdk_env: The CDK Environment these settings apply to.
            config: Dict containing the required keys.

        Raises:
            ValueError: If required keys are missing.
        """
        missing = self.REQUIRED_KEYS - config.keys()
        if missing:
            raise ValueError(
                f"Athena config missing required keys: {', '.join(sorted(missing))}"
            )

        self.account = cdk_env.account
        self.region = cdk_env.region or DEFAULT_REGION
        self.results_bucket_name = config["results_bucket_name"]
        self.kms_key_arn = config["kms_key_arn"]

    def _fetch_from_parameter_store(self, region: str) -> dict[str, str]:
        """Fetch and parse the Athena settings parameter.

        Args:
            region: AWS region to create the SSM client in.

        Returns:
            Parsed JSON dict with the Athena settings.

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
