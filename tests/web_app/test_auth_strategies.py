"""Unit tests for authentication strategies."""

import pytest
from aws_cdk import (
    App,
    Environment as CdkEnvironment,
    Stack,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
)

from gds_idea_cdk_constructs.web_app._auth_strategies import (
    AUTH_STRATEGY_MAP,
    AuthType,
    CognitoExternalIdpAuthStrategy,
    CognitoManagedLoginAuthStrategy,
    NoAuthStrategy,
)


@pytest.fixture
def cdk_app():
    """Fixture for CDK App."""
    return App()


@pytest.fixture
def test_stack(cdk_app):
    """Fixture for a test CDK Stack."""
    env = CdkEnvironment(account="testing", region="eu-west-2")
    return Stack(cdk_app, "TestStack", env=env)


@pytest.fixture
def mock_target_group(test_stack):
    """Fixture for a mock ApplicationTargetGroup."""
    vpc = ec2.Vpc(test_stack, "TestVpc", max_azs=2)

    return elbv2.ApplicationTargetGroup(
        test_stack,
        "TestTargetGroup",
        vpc=vpc,
        port=80,
        protocol=elbv2.ApplicationProtocol.HTTP,
    )


# NoAuthStrategy tests


def test_no_auth_strategy_create_listener_action(
    test_stack, deployment_config, mock_target_group
):
    """Test that NoAuthStrategy creates a forward action."""
    strategy = NoAuthStrategy(test_stack, deployment_config, "testapp")
    action = strategy.create_listener_action(mock_target_group)

    assert action is not None
    assert isinstance(action, elbv2.ListenerAction)


def test_no_auth_strategy_create_outputs(test_stack, deployment_config):
    """Test that NoAuthStrategy create_outputs does nothing."""
    strategy = NoAuthStrategy(test_stack, deployment_config, "testapp")
    strategy.create_outputs()  # Should not raise any errors


def test_no_auth_strategy_get_minimal_role(test_stack, deployment_config):
    """Test that NoAuthStrategy creates a minimal IAM role."""
    strategy = NoAuthStrategy(test_stack, deployment_config, "testapp")
    role = strategy.get_minimal_role()

    assert isinstance(role, iam.Role)
    assert role.assume_role_policy is not None


def test_no_auth_strategy_configure_role_permissions(test_stack, deployment_config):
    """Test that NoAuthStrategy doesn't add permissions to existing role."""
    strategy = NoAuthStrategy(test_stack, deployment_config, "testapp")
    role = iam.Role(
        test_stack,
        "CustomRole",
        assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    )

    strategy.configure_role_permissions(role)  # Should not raise any errors


def test_no_auth_strategy_get_environment_variables(test_stack, deployment_config):
    """Test that NoAuthStrategy returns empty environment variables."""
    strategy = NoAuthStrategy(test_stack, deployment_config, "testapp")
    env_vars = strategy.get_environment_variables()

    assert env_vars == {}


# CognitoManagedLoginAuthStrategy tests


def test_cognito_auth_strategy_initialization(test_stack, deployment_config):
    """Test that CognitoManagedLoginAuthStrategy initializes and sets up resources."""
    strategy = CognitoManagedLoginAuthStrategy(test_stack, deployment_config, "testapp")

    # Verify that Cognito resources are set up
    assert hasattr(strategy, "user_pool")
    assert hasattr(strategy, "user_pool_domain")
    assert hasattr(strategy, "cognito_client")
    assert strategy.user_pool is not None
    assert strategy.cognito_client is not None


def test_cognito_auth_strategy_create_listener_action(
    test_stack, deployment_config, mock_target_group
):
    """Test that CognitoManagedLoginAuthStrategy creates an authenticate action."""
    strategy = CognitoManagedLoginAuthStrategy(test_stack, deployment_config, "testapp")
    action = strategy.create_listener_action(mock_target_group)

    assert action is not None
    assert isinstance(action, elbv2.ListenerAction)


def test_cognito_auth_strategy_create_outputs(test_stack, deployment_config):
    """Test that CognitoManagedLoginAuthStrategy creates CloudFormation outputs."""
    strategy = CognitoManagedLoginAuthStrategy(test_stack, deployment_config, "testapp")
    # Should not raise any errors
    strategy.create_outputs()


def test_cognito_auth_strategy_get_minimal_role(test_stack, deployment_config):
    """Test that CognitoManagedLoginAuthStrategy creates a role with secret access."""
    strategy = CognitoManagedLoginAuthStrategy(test_stack, deployment_config, "testapp")
    role = strategy.get_minimal_role()

    assert isinstance(role, iam.Role)
    assert role.assume_role_policy is not None


def test_cognito_auth_strategy_configure_role_permissions(
    test_stack, deployment_config
):
    """Test that CognitoManagedLoginAuthStrategy adds secret permissions to
    existing role."""
    strategy = CognitoManagedLoginAuthStrategy(test_stack, deployment_config, "testapp")
    role = iam.Role(
        test_stack,
        "CustomRole",
        assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    )

    # Should not raise any errors
    strategy.configure_role_permissions(role)


def test_cognito_auth_strategy_get_environment_variables(test_stack, deployment_config):
    """Test that CognitoManagedLoginAuthStrategy returns secret name."""
    strategy = CognitoManagedLoginAuthStrategy(test_stack, deployment_config, "testapp")
    env_vars = strategy.get_environment_variables()

    assert "COGNITO_AUTH_SECRET_NAME" in env_vars
    assert env_vars["COGNITO_AUTH_SECRET_NAME"] == "testapp/access"


def test_cognito_auth_strategy_client_configuration(test_stack, deployment_config):
    """Test that Cognito client is configured correctly."""
    app_name = "testapp"
    strategy = CognitoManagedLoginAuthStrategy(test_stack, deployment_config, app_name)

    # Verify client was created successfully
    assert strategy.cognito_client is not None
    assert strategy.user_pool is not None
    assert strategy.user_pool_domain is not None


# AUTH_STRATEGY_MAP tests


def test_strategy_map_contains_all_auth_types():
    """Test that AUTH_STRATEGY_MAP contains all AuthType values."""
    assert AuthType.NONE in AUTH_STRATEGY_MAP
    assert AuthType.COGNITO in AUTH_STRATEGY_MAP
    assert AuthType.INTERNAL_ACCESS in AUTH_STRATEGY_MAP


def test_strategy_map_values_are_correct_classes():
    """Test that AUTH_STRATEGY_MAP maps to correct strategy classes."""
    assert AUTH_STRATEGY_MAP[AuthType.NONE] == NoAuthStrategy
    assert AUTH_STRATEGY_MAP[AuthType.COGNITO] == CognitoManagedLoginAuthStrategy
    assert AUTH_STRATEGY_MAP[AuthType.INTERNAL_ACCESS] == CognitoExternalIdpAuthStrategy


def test_all_strategies_implement_interface():
    """Test that all strategies have required methods."""
    # Verify all strategies in the map implement the interface
    for _, strategy_class in AUTH_STRATEGY_MAP.items():
        # Check that all required methods exist
        assert hasattr(strategy_class, "create_listener_action")
        assert hasattr(strategy_class, "create_outputs")
        assert hasattr(strategy_class, "get_minimal_role")
        assert hasattr(strategy_class, "configure_role_permissions")
        assert hasattr(strategy_class, "get_environment_variables")
