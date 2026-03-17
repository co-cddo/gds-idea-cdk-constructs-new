import json
import logging
import tomllib
from dataclasses import dataclass
from enum import Enum

import boto3
from aws_cdk import Environment as CdkEnvironment

logger = logging.getLogger(__name__)


class DeploymentEnvironment(Enum):
    DEVELOPMENT = "992382722318"
    PRODUCTION = "588077357019"
    TESTING = "testing"

    @classmethod
    def from_cdk_env(cls, cdk_env: CdkEnvironment) -> "DeploymentEnvironment":
        """Get environment from CDK Environment."""
        if not cdk_env.account:
            raise ValueError("CDK Environment must have account specified")
        return cls.from_account_id(cdk_env.account)

    @classmethod
    def from_account_id(cls, account_id: str) -> "DeploymentEnvironment":
        """Get environment from account ID."""
        for env in cls:
            if env.value == account_id:
                if env == cls.TESTING:
                    logger.warning(
                        "Using TESTING environment - "
                        "this must not be used in real deployments"
                    )
                return env
        raise ValueError(f"Unknown account ID: {account_id}")

    @property
    def friendly_name(self) -> str:
        """Get lowercase environment name for display/logging."""
        return self.name.lower()


@dataclass
class DeploymentConfig:
    """Configuration for GDS Idea web applications.

    Fetches environment-specific configuration from AWS Systems Manager
    Parameter Store, merging three parameters: ``/gds-idea-auth``,
    ``/gds-idea-ecs``, and ``/gds-idea-vpc``.

    For testing or local development without Parameter Store access, use
    the :meth:`from_dict` classmethod instead.
    """

    PARAM_AUTH = "/gds-idea-auth"
    PARAM_ECS = "/gds-idea-ecs"
    PARAM_VPC = "/gds-idea-vpc"
    EXTERNAL_IDP_NAME = "internal-access"
    REQUIRED_KEYS = frozenset(
        {
            "domain_name",
            "vpc_id",
            "ecs_arn",
            "cognito_user_pool_id",
            "waf_arn",
            "waf_big_upload_arn",
            "logs_bucket_name",
        }
    )

    def __init__(self, cdk_env: CdkEnvironment):
        """Create DeploymentConfig by fetching from Parameter Store.

        Args:
            cdk_env: The CDK Environment (must have account and region set).

        Raises:
            ValueError: If the account is unknown, the environment is TESTING,
                or the parameters are missing required keys.
        """
        self._init_common(cdk_env)

        if self.environment == DeploymentEnvironment.TESTING:
            raise ValueError(
                "TESTING environment cannot fetch from Parameter Store. "
                "Use DeploymentConfig.from_dict() instead."
            )

        config = self._fetch_from_parameter_store()
        self._apply_config(config)

    @classmethod
    def from_dict(
        cls, cdk_env: CdkEnvironment, config: dict[str, str]
    ) -> "DeploymentConfig":
        """Create DeploymentConfig from an explicit config dict.

        Useful for testing or local development without Parameter Store access.

        Args:
            cdk_env: The CDK Environment (must have account set).
            config: Dict containing all required configuration keys.

        Returns:
            A configured DeploymentConfig instance.

        Raises:
            ValueError: If config is missing required keys.
        """
        instance = object.__new__(cls)
        instance._init_common(cdk_env)
        instance._apply_config(config)
        return instance

    def _init_common(self, cdk_env: CdkEnvironment) -> None:
        """Shared initialisation: region warning, environment resolution."""
        if cdk_env.region and cdk_env.region != "eu-west-2":
            logger.warning(f"Using region '{cdk_env.region}' - eu-west-2 is preferred")

        try:
            environment = DeploymentEnvironment.from_cdk_env(cdk_env)
        except ValueError as e:
            raise ValueError(f"CDK Environment not configured. {e}") from e

        if environment == DeploymentEnvironment.PRODUCTION:
            logger.warning(
                f"Deploying to {environment.friendly_name.upper()} environment "
                "- please double-check configuration"
            )

        self.cdk_env = cdk_env
        self.environment = environment

    def _apply_config(self, config: dict[str, str]) -> None:
        """Apply config values and compute derived fields.

        Args:
            config: Dict containing configuration values.

        Raises:
            ValueError: If required keys are missing.
        """
        missing = self.REQUIRED_KEYS - config.keys()
        if missing:
            raise ValueError(
                f"Config missing required keys: {', '.join(sorted(missing))}"
            )

        self.domain_name = config["domain_name"]
        self.vpc_id = config["vpc_id"]
        self.cluster_name = config["ecs_arn"].split("/")[-1]
        self.user_pool_id = config["cognito_user_pool_id"]
        self.external_idp_name = self.EXTERNAL_IDP_NAME
        self.waf_arn = config["waf_arn"]
        self.waf_big_upload_arn = config["waf_big_upload_arn"]
        self.log_bucket_name = config["logs_bucket_name"]

        # Derived from domain_name
        self.redirect_unauthorised_url = f"{self.domain_name}/401.html"

    def _fetch_from_parameter_store(self) -> dict[str, str]:
        """Fetch configuration from AWS Systems Manager Parameter Store.

        Fetches and merges three parameters: ``/gds-idea-auth``,
        ``/gds-idea-ecs``, and ``/gds-idea-vpc``.

        Returns:
            Merged config dict from all three parameters.

        Raises:
            botocore.exceptions.ClientError: If a parameter cannot be retrieved.
        """
        region = self.cdk_env.region or "eu-west-2"

        logger.info("Fetching config from Parameter Store")
        client = boto3.client("ssm", region_name=region)
        result = {}
        for name in (self.PARAM_AUTH, self.PARAM_ECS, self.PARAM_VPC):
            response = client.get_parameter(Name=name)
            result.update(json.loads(response["Parameter"]["Value"]))
        return result


class AppConfig:
    """Load web application configuration from pyproject.toml [tool.webapp]"""

    def __init__(
        self, app_name: str, framework: str, health_check_path: str | None = None
    ):
        self.app_name = app_name
        self.framework = framework
        self.health_check_path = health_check_path or self._default_health_check_path(
            framework
        )

    @classmethod
    def from_pyproject(cls, path: str = "pyproject.toml") -> "AppConfig":
        """Load config from pyproject.toml [tool.webapp] section"""
        with open(path, "rb") as f:
            config = tomllib.load(f)

        app_name = config["tool"]["webapp"]["app_name"]
        framework = config["tool"]["webapp"]["framework"]
        health_check_path = config["tool"]["webapp"].get(
            "health_check_path"
        )  # Optional override

        return cls(app_name, framework, health_check_path)

    @staticmethod
    def _default_health_check_path(framework: str) -> str:
        paths = {
            "streamlit": "/_stcore/health",
            "dash": "/health",
            "fastapi": "/health",
        }
        return paths.get(framework, "/health")
