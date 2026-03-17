"""Shared test fixtures."""

import pytest
from aws_cdk import Environment as CdkEnvironment

from gds_idea_cdk_constructs.config import AppConfig, DeploymentConfig

# Test config values — intentionally fake to prove code doesn't depend on real infra
# Keys mirror the merged SSM parameter store structure (auth + ecs + vpc).
TEST_CONFIG = {
    # /gds-idea-auth
    "domain_name": "test.example.com",
    "cognito_user_pool_id": "eu-west-2_TestPool",
    "waf_arn": (
        "arn:aws:wafv2:eu-west-2:123456789012:"
        "regional/webacl/test-waf/00000000-0000-0000-0000-000000000000"
    ),
    "waf_big_upload_arn": (
        "arn:aws:wafv2:eu-west-2:123456789012:"
        "regional/webacl/test-waf-upload/00000000-0000-0000-0000-000000000000"
    ),
    "logs_bucket_name": "test.example.com-logs",
    # /gds-idea-ecs
    "ecs_arn": "arn:aws:ecs:eu-west-2:123456789012:cluster/test-cluster",
    # /gds-idea-vpc
    "vpc_id": "vpc-test123",
}


@pytest.fixture
def test_cdk_env():
    """Fixture for TESTING CdkEnvironment."""
    return CdkEnvironment(account="testing", region="eu-west-2")


@pytest.fixture
def dev_cdk_env():
    """Fixture for DEV CdkEnvironment."""
    return CdkEnvironment(account="992382722318", region="eu-west-2")


@pytest.fixture
def prod_cdk_env():
    """Fixture for PROD CdkEnvironment."""
    return CdkEnvironment(account="588077357019", region="eu-west-2")


@pytest.fixture
def deployment_config(test_cdk_env):
    """Fixture for test DeploymentConfig using from_dict."""
    return DeploymentConfig.from_dict(test_cdk_env, TEST_CONFIG)


@pytest.fixture
def app_config():
    """Fixture for AppConfig."""
    return AppConfig(app_name="testapp", framework="streamlit")
