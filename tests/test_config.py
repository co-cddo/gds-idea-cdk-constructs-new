"""Unit tests for configuration modules."""

import json
from unittest.mock import MagicMock, patch

import pytest
from aws_cdk import Environment as CdkEnvironment

from gds_idea_cdk_constructs.config import (
    AppConfig,
    DeploymentConfig,
    DeploymentEnvironment,
)

from .conftest import TEST_CONFIG

# DeploymentEnvironment tests


def test_deployment_environment_from_account_id_development():
    """Test getting DEV environment from account ID."""
    env = DeploymentEnvironment.from_account_id("992382722318")
    assert env == DeploymentEnvironment.DEVELOPMENT


def test_deployment_environment_from_account_id_production():
    """Test getting PROD environment from account ID."""
    env = DeploymentEnvironment.from_account_id("588077357019")
    assert env == DeploymentEnvironment.PRODUCTION


def test_deployment_environment_from_account_id_testing():
    """Test getting TESTING environment from account ID."""
    env = DeploymentEnvironment.from_account_id("testing")
    assert env == DeploymentEnvironment.TESTING


def test_deployment_environment_testing_logs_warning(caplog):
    """Test that TESTING environment logs a warning."""
    DeploymentEnvironment.from_account_id("testing")
    assert "Using TESTING environment" in caplog.text
    assert "must not be used in real deployments" in caplog.text


def test_deployment_environment_from_account_id_unknown_raises_error():
    """Test that unknown account ID raises ValueError."""
    with pytest.raises(ValueError, match="Unknown account ID: 123456789012"):
        DeploymentEnvironment.from_account_id("123456789012")


def test_deployment_environment_from_cdk_env_valid():
    """Test getting environment from valid CdkEnvironment."""
    cdk_env = CdkEnvironment(account="992382722318", region="eu-west-2")
    env = DeploymentEnvironment.from_cdk_env(cdk_env)
    assert env == DeploymentEnvironment.DEVELOPMENT


def test_deployment_environment_from_cdk_env_no_account_raises_error():
    """Test that CdkEnvironment without account raises ValueError."""
    cdk_env = CdkEnvironment(region="eu-west-2")
    with pytest.raises(ValueError, match="CDK Environment must have account specified"):
        DeploymentEnvironment.from_cdk_env(cdk_env)


def test_deployment_environment_friendly_name():
    """Test friendly_name property returns lowercase name."""
    assert DeploymentEnvironment.DEVELOPMENT.friendly_name == "development"
    assert DeploymentEnvironment.PRODUCTION.friendly_name == "production"
    assert DeploymentEnvironment.TESTING.friendly_name == "testing"


# DeploymentConfig.from_dict tests


def test_deployment_config_from_dict_creates_config(test_cdk_env):
    """Test that from_dict creates a valid config with all fields set."""
    config = DeploymentConfig.from_dict(test_cdk_env, TEST_CONFIG)

    assert config.environment == DeploymentEnvironment.TESTING
    assert config.domain_name == TEST_CONFIG["domain_name"]
    assert config.vpc_id == TEST_CONFIG["vpc_id"]
    assert config.cluster_name == "test-cluster"
    assert config.user_pool_id == TEST_CONFIG["cognito_user_pool_id"]
    assert config.external_idp_name == DeploymentConfig.EXTERNAL_IDP_NAME
    assert config.waf_arn == TEST_CONFIG["waf_arn"]
    assert config.waf_big_upload_arn == TEST_CONFIG["waf_big_upload_arn"]


def test_deployment_config_from_dict_derived_fields(test_cdk_env):
    """Test that from_dict computes derived fields correctly."""
    config = DeploymentConfig.from_dict(test_cdk_env, TEST_CONFIG)

    assert config.log_bucket_name == TEST_CONFIG["logs_bucket_name"]
    assert config.redirect_unauthorised_url == f"{config.domain_name}/401.html"


def test_deployment_config_from_dict_missing_key_raises_error(test_cdk_env):
    """Test that from_dict raises ValueError when required keys are missing."""
    incomplete = {"domain_name": "test.example.com"}
    with pytest.raises(ValueError, match="Config missing required keys"):
        DeploymentConfig.from_dict(test_cdk_env, incomplete)


def test_deployment_config_from_dict_with_dev_env(dev_cdk_env):
    """Test that from_dict works with DEVELOPMENT environment."""
    config = DeploymentConfig.from_dict(dev_cdk_env, TEST_CONFIG)
    assert config.environment == DeploymentEnvironment.DEVELOPMENT


def test_deployment_config_from_dict_with_prod_env(prod_cdk_env):
    """Test that from_dict works with PRODUCTION environment."""
    config = DeploymentConfig.from_dict(prod_cdk_env, TEST_CONFIG)
    assert config.environment == DeploymentEnvironment.PRODUCTION


# DeploymentConfig.__init__ (Parameter Store) tests


def test_deployment_config_init_testing_env_raises_error(test_cdk_env):
    """Test that __init__ raises ValueError for TESTING environment."""
    with pytest.raises(ValueError, match="TESTING environment cannot fetch"):
        DeploymentConfig(test_cdk_env)


def test_deployment_config_init_fetches_from_parameter_store(dev_cdk_env):
    """Test that __init__ fetches config from all three SSM parameters."""
    param_values = {
        DeploymentConfig.PARAM_AUTH: json.dumps(
            {
                "domain_name": TEST_CONFIG["domain_name"],
                "cognito_user_pool_id": TEST_CONFIG["cognito_user_pool_id"],
                "waf_arn": TEST_CONFIG["waf_arn"],
                "waf_big_upload_arn": TEST_CONFIG["waf_big_upload_arn"],
                "logs_bucket_name": TEST_CONFIG["logs_bucket_name"],
            }
        ),
        DeploymentConfig.PARAM_ECS: json.dumps(
            {
                "ecs_arn": TEST_CONFIG["ecs_arn"],
            }
        ),
        DeploymentConfig.PARAM_VPC: json.dumps(
            {
                "vpc_id": TEST_CONFIG["vpc_id"],
            }
        ),
    }

    mock_client = MagicMock()
    mock_client.get_parameter.side_effect = lambda **kwargs: {
        "Parameter": {"Value": param_values[kwargs["Name"]]}
    }

    with patch("gds_idea_cdk_constructs.config.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_client
        config = DeploymentConfig(dev_cdk_env)

    mock_boto3.client.assert_called_once_with("ssm", region_name="eu-west-2")
    assert mock_client.get_parameter.call_count == 3
    mock_client.get_parameter.assert_any_call(Name=DeploymentConfig.PARAM_AUTH)
    mock_client.get_parameter.assert_any_call(Name=DeploymentConfig.PARAM_ECS)
    mock_client.get_parameter.assert_any_call(Name=DeploymentConfig.PARAM_VPC)
    assert config.domain_name == TEST_CONFIG["domain_name"]
    assert config.vpc_id == TEST_CONFIG["vpc_id"]


def test_deployment_config_init_invalid_account_raises_error():
    """Test that invalid account ID raises ValueError."""
    cdk_env = CdkEnvironment(account="123456789012", region="eu-west-2")
    with pytest.raises(ValueError, match="CDK Environment not configured"):
        DeploymentConfig(cdk_env)


def test_deployment_config_init_no_account_raises_error():
    """Test that missing account raises ValueError."""
    cdk_env = CdkEnvironment(region="eu-west-2")
    with pytest.raises(ValueError, match="CDK Environment not configured"):
        DeploymentConfig(cdk_env)


def test_deployment_config_warns_on_non_preferred_region(caplog):
    """Test that non-eu-west-2 region logs warning."""
    cdk_env = CdkEnvironment(account="testing", region="us-east-1")
    config = DeploymentConfig.from_dict(cdk_env, TEST_CONFIG)

    assert "Using region 'us-east-1' - eu-west-2 is preferred" in caplog.text
    assert config.environment == DeploymentEnvironment.TESTING


def test_deployment_config_warns_on_production_deployment(prod_cdk_env, caplog):
    """Test that PROD deployment logs a warning."""
    config = DeploymentConfig.from_dict(prod_cdk_env, TEST_CONFIG)

    assert "Deploying to PRODUCTION environment" in caplog.text
    assert config.environment == DeploymentEnvironment.PRODUCTION


# AppConfig tests


def test_app_config_init_with_defaults():
    """Test AppConfig initialization with framework defaults."""
    config = AppConfig(app_name="myapp", framework="streamlit")

    assert config.app_name == "myapp"
    assert config.framework == "streamlit"
    assert config.health_check_path == "/_stcore/health"


def test_app_config_init_with_custom_health_check():
    """Test AppConfig initialization with custom health check path."""
    config = AppConfig(
        app_name="myapp", framework="streamlit", health_check_path="/custom/health"
    )

    assert config.health_check_path == "/custom/health"


def test_app_config_default_health_check_path_streamlit():
    """Test default health check path for Streamlit."""
    assert AppConfig._default_health_check_path("streamlit") == "/_stcore/health"


def test_app_config_default_health_check_path_dash():
    """Test default health check path for Dash."""
    assert AppConfig._default_health_check_path("dash") == "/health"


def test_app_config_default_health_check_path_fastapi():
    """Test default health check path for FastAPI."""
    assert AppConfig._default_health_check_path("fastapi") == "/health"


def test_app_config_default_health_check_path_unknown_framework():
    """Test default health check path for unknown framework."""
    assert AppConfig._default_health_check_path("unknown") == "/health"


def test_app_config_from_pyproject(tmp_path):
    """Test loading config from pyproject.toml file."""
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_content = """
[tool.webapp]
app_name = "test-app"
framework = "dash"
"""
    pyproject_file.write_text(pyproject_content)

    config = AppConfig.from_pyproject(str(pyproject_file))

    assert config.app_name == "test-app"
    assert config.framework == "dash"
    assert config.health_check_path == "/health"


def test_app_config_from_pyproject_with_custom_health_check(tmp_path):
    """Test loading config with custom health check path."""
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_content = """
[tool.webapp]
app_name = "test-app"
framework = "fastapi"
health_check_path = "/api/health"
"""
    pyproject_file.write_text(pyproject_content)

    config = AppConfig.from_pyproject(str(pyproject_file))

    assert config.app_name == "test-app"
    assert config.framework == "fastapi"
    assert config.health_check_path == "/api/health"


def test_app_config_from_pyproject_missing_file():
    """Test that missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        AppConfig.from_pyproject("/nonexistent/pyproject.toml")


def test_app_config_from_pyproject_missing_section(tmp_path):
    """Test that missing [tool.webapp] section raises KeyError."""
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_content = """
[tool.other]
key = "value"
"""
    pyproject_file.write_text(pyproject_content)

    with pytest.raises(KeyError):
        AppConfig.from_pyproject(str(pyproject_file))
