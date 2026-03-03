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

    Fetches environment-specific configuration from AWS Secrets Manager
    using a naming convention of ``/gds-idea/{environment}/config``.

    For testing or local development without Secrets Manager access, use
    the :meth:`from_dict` classmethod instead.
    """

    SECRET_PREFIX = "/gds-idea"
    REQUIRED_KEYS = frozenset(
        {
            "domain_name",
            "vpc_id",
            "cluster_name",
            "user_pool_id",
            "external_idp_name",
            "waf_arn",
        }
    )

    def __init__(self, cdk_env: CdkEnvironment):
        """Create DeploymentConfig by fetching from Secrets Manager.

        Args:
            cdk_env: The CDK Environment (must have account and region set).

        Raises:
            ValueError: If the account is unknown, the environment is TESTING,
                or the secret is missing required keys.
        """
        self._init_common(cdk_env)

        if self.environment == DeploymentEnvironment.TESTING:
            raise ValueError(
                "TESTING environment cannot fetch from Secrets Manager. "
                "Use DeploymentConfig.from_dict() instead."
            )

        config = self._fetch_from_secrets_manager()
        self._apply_config(config)

    @classmethod
    def from_dict(
        cls, cdk_env: CdkEnvironment, config: dict[str, str]
    ) -> "DeploymentConfig":
        """Create DeploymentConfig from an explicit config dict.

        Useful for testing or local development without Secrets Manager access.

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
        self.cluster_name = config["cluster_name"]
        self.user_pool_id = config["user_pool_id"]
        self.external_idp_name = config["external_idp_name"]
        self.waf_arn = config["waf_arn"]

        # Derived from domain_name
        self.log_bucket_name = f"{self.domain_name}-logs"
        self.redirect_unauthorised_url = f"{self.domain_name}/401.html"

    def _fetch_from_secrets_manager(self) -> dict[str, str]:
        """Fetch configuration from AWS Secrets Manager.

        Returns:
            Parsed config dict from the secret.

        Raises:
            botocore.exceptions.ClientError: If the secret cannot be retrieved.
        """
        secret_name = f"{self.SECRET_PREFIX}/{self.environment.friendly_name}/config"
        region = self.cdk_env.region or "eu-west-2"

        logger.info(f"Fetching config from Secrets Manager: {secret_name}")
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])


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
