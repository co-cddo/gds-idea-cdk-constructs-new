"""Unit tests for WebApp stack."""

import pytest
from aws_cdk import (
    App,
    Environment as CdkEnvironment,
    Stack,
    aws_iam as iam,
)
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.config import DeploymentConfig, DeploymentEnvironment
from gds_idea_cdk_constructs.web_app._auth_strategies import AuthType
from gds_idea_cdk_constructs.web_app.props import WebAppContainerProperties
from gds_idea_cdk_constructs.web_app.stack import WebApp
from tests.conftest import TEST_CONFIG


def _build_cdk_context(account_id: str, region: str, vpc_id: str, domain_name: str):
    """Helper to build CDK context for mocking AWS resource lookups."""
    return {
        # Mock availability zones
        f"availability-zones:account={account_id}:region={region}": [
            f"{region}a",
            f"{region}b",
            f"{region}c",
        ],
        # Mock VPC lookup
        (
            f"vpc-provider:account={account_id}:filter:vpc-id={vpc_id}:"
            f"region={region}:returnAsymmetricSubnets=true"
        ): {
            "vpcId": vpc_id,
            "vpcCidrBlock": "10.0.0.0/16",
            "availabilityZones": [f"{region}a", f"{region}b"],
            "subnetGroups": [
                {
                    "name": "Public",
                    "type": "Public",
                    "subnets": [
                        {
                            "subnetId": "subnet-test1",
                            "cidr": "10.0.0.0/24",
                            "availabilityZone": f"{region}a",
                            "routeTableId": "rtb-test1",
                        },
                        {
                            "subnetId": "subnet-test2",
                            "cidr": "10.0.1.0/24",
                            "availabilityZone": f"{region}b",
                            "routeTableId": "rtb-test2",
                        },
                    ],
                }
            ],
        },
        # Mock HostedZone lookup
        (
            f"hosted-zone:account={account_id}:domainName={domain_name}:region={region}"
        ): {
            "Id": "/hostedzone/ZTESTHOSTEDZONE",
            "Name": f"{domain_name}.",
        },
    }


@pytest.fixture
def cdk_app():
    """Fixture for CDK App with context for resource lookups."""
    account_id = "testing"
    region = "eu-west-2"
    vpc_id = TEST_CONFIG["vpc_id"]
    domain_name = TEST_CONFIG["domain_name"]

    app = App(context=_build_cdk_context(account_id, region, vpc_id, domain_name))
    return app


@pytest.fixture
def dev_cdk_app():
    """Fixture for CDK App using DEV environment (for assume-policy tests)."""
    account_id = "992382722318"
    region = "eu-west-2"
    vpc_id = TEST_CONFIG["vpc_id"]
    domain_name = TEST_CONFIG["domain_name"]

    app = App(context=_build_cdk_context(account_id, region, vpc_id, domain_name))
    return app


@pytest.fixture
def dev_deployment_config():
    """Fixture for DEV DeploymentConfig using from_dict."""
    dev_env = CdkEnvironment(account="992382722318", region="eu-west-2")
    return DeploymentConfig.from_dict(dev_env, TEST_CONFIG)


@pytest.fixture
def prod_cdk_app():
    """Fixture for CDK App using PROD environment."""
    account_id = "588077357019"
    region = "eu-west-2"
    vpc_id = TEST_CONFIG["vpc_id"]
    domain_name = TEST_CONFIG["domain_name"]

    app = App(context=_build_cdk_context(account_id, region, vpc_id, domain_name))
    return app


@pytest.fixture
def prod_deployment_config():
    """Fixture for PROD DeploymentConfig using from_dict."""
    prod_env = CdkEnvironment(account="588077357019", region="eu-west-2")
    return DeploymentConfig.from_dict(prod_env, TEST_CONFIG)


@pytest.fixture
def webapp_no_auth(cdk_app, deployment_config, app_config):
    """Fixture for WebApp with NoAuth."""
    return WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
    )


@pytest.fixture
def webapp_cognito(cdk_app, deployment_config, app_config):
    """Fixture for WebApp with Cognito auth."""
    return WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.COGNITO,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
    )


@pytest.fixture
def custom_task_role_stack(cdk_app, deployment_config):
    """Fixture that creates a stack with a custom IAM task role."""
    # Create stack for the custom role
    role_stack = Stack(cdk_app, "CustomRoleStack", env=deployment_config.cdk_env)

    # Create custom role with an existing permission
    role = iam.Role(
        role_stack,
        "CustomTaskRole",
        assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        description="Custom task role for testing",
    )
    # Add a custom S3 permission to verify it's preserved
    role.add_to_policy(
        iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["s3:GetObject"],
            resources=["arn:aws:s3:::my-test-bucket/*"],
        )
    )
    return {"stack": role_stack, "role": role}


def test_web_app_stack_creates_core_resources(webapp_no_auth):
    """Test that WebApp stack creates core AWS resources."""
    stack = webapp_no_auth

    template = Template.from_stack(stack)

    # Verify core resources exist
    template.resource_count_is("AWS::ECS::Cluster", 0)
    template.resource_count_is("AWS::ECS::TaskDefinition", 1)
    template.resource_count_is("AWS::ECS::Service", 1)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 1)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::TargetGroup", 1)
    template.resource_count_is("AWS::CertificateManager::Certificate", 1)
    template.resource_count_is("AWS::Route53::HostedZone", 1)


def test_web_app_stack_no_auth_has_no_cognito(webapp_no_auth):
    """Test that NoAuth doesn't create Cognito resources."""
    template = Template.from_stack(webapp_no_auth)

    # NoAuth should not create Cognito resources
    template.resource_count_is("AWS::Cognito::UserPoolClient", 0)


def test_web_app_stack_cognito_auth_creates_user_pool_client(webapp_cognito):
    """Test that Cognito auth creates UserPoolClient."""
    template = Template.from_stack(webapp_cognito)

    # Cognito auth should create UserPoolClient
    template.resource_count_is("AWS::Cognito::UserPoolClient", 1)
    template.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "UserPoolId": TEST_CONFIG["cognito_user_pool_id"],
            "GenerateSecret": True,
        },
    )


def test_web_app_stack_cognito_auth_has_callback_urls(webapp_cognito):
    """Test that Cognito client has correct callback URLs."""
    template = Template.from_stack(webapp_cognito)

    domain = TEST_CONFIG["domain_name"]
    template.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "CallbackURLs": [f"https://testapp.{domain}/oauth2/idpresponse"],
            "LogoutURLs": [f"https://testapp.{domain}"],
        },
    )


def test_web_app_stack_no_auth_has_minimal_task_role(webapp_no_auth):
    """Test that NoAuth creates task role without extra permissions."""
    template = Template.from_stack(webapp_no_auth)

    # Two roles for ECS (task role + execution role)
    # Two roles for custom resource cleanup
    template.resource_count_is("AWS::IAM::Role", 4)


def test_web_app_stack_cognito_auth_has_secret_permissions(webapp_cognito):
    """Test that Cognito auth grants secret access to task role."""
    template = Template.from_stack(webapp_cognito)

    # Check for secrets manager permissions
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(
                                    [
                                        "secretsmanager:GetSecretValue",
                                        "secretsmanager:DescribeSecret",
                                    ]
                                ),
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_web_app_stack_container_env_vars_no_auth(webapp_no_auth):
    """Test that NoAuth doesn't add auth env vars to container."""
    template = Template.from_stack(webapp_no_auth)

    # Verify COGNITO_AUTH_SECRET_NAME is not in container environment
    template_dict = template.to_json()
    for resource in template_dict["Resources"].values():
        if resource["Type"] == "AWS::ECS::TaskDefinition":
            container_defs = resource["Properties"]["ContainerDefinitions"]
            for container in container_defs:
                env_vars = container.get("Environment", [])
                env_var_names = [var["Name"] for var in env_vars]
                assert "COGNITO_AUTH_SECRET_NAME" not in env_var_names


def test_web_app_stack_container_env_vars_cognito(webapp_cognito):
    """Test that Cognito auth adds secret name to container env vars."""
    template = Template.from_stack(webapp_cognito)

    # Container should have COGNITO_AUTH_SECRET_NAME
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                Match.object_like(
                    {
                        "Environment": Match.array_with(
                            [
                                {
                                    "Name": "COGNITO_AUTH_SECRET_NAME",
                                    "Value": "testapp/access",
                                }
                            ]
                        )
                    }
                )
            ]
        },
    )


def test_web_app_stack_dev_environment_has_assume_policy(
    dev_cdk_app, dev_deployment_config, app_config
):
    """Test that dev environment adds assume policy for dev roles."""
    stack = WebApp(
        dev_cdk_app,
        dev_deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
    )
    template = Template.from_stack(stack)

    dev_account_id = DeploymentEnvironment.DEVELOPMENT.value

    # Check task role has assume policy with dev role condition
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": {
                "Statement": Match.array_with(
                    [
                        {
                            "Action": "sts:AssumeRole",
                            "Effect": "Allow",
                            "Principal": {"AWS": Match.any_value()},
                            "Condition": {
                                "StringLike": {
                                    "aws:PrincipalArn": [
                                        f"arn:aws:iam::{dev_account_id}:role/*-poweraccess",
                                        f"arn:aws:iam::{dev_account_id}:role/*-admin",
                                    ]
                                }
                            },
                        }
                    ]
                )
            }
        },
    )


def test_web_app_stack_health_check_path(webapp_no_auth):
    """Test that health check path is correctly configured."""
    template = Template.from_stack(webapp_no_auth)

    # Health check should use Streamlit default
    template.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        {"HealthCheckPath": "/_stcore/health"},
    )


def test_web_app_stack_custom_container_props(cdk_app, deployment_config, app_config):
    """Test that custom container properties are applied."""
    custom_props = WebAppContainerProperties(
        cpu=512,
        memory_limit_mib=1024,
        desired_count=2,
        health_check_path="/custom/health",
    )

    stack = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
        container_props=custom_props,
    )

    template = Template.from_stack(stack)

    # Check task definition has custom CPU/memory
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {"Cpu": "512", "Memory": "1024"},
    )

    # Check service has custom desired count
    template.has_resource_properties(
        "AWS::ECS::Service",
        {"DesiredCount": 2},
    )

    # Check health check uses custom path
    template.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        {"HealthCheckPath": "/custom/health"},
    )


def test_web_app_stack_certificate_domain(webapp_no_auth):
    """Test that certificate is created for correct domain."""
    template = Template.from_stack(webapp_no_auth)

    domain = TEST_CONFIG["domain_name"]
    template.has_resource_properties(
        "AWS::CertificateManager::Certificate",
        {"DomainName": f"testapp.{domain}"},
    )


def test_web_app_stack_with_custom_task_role_no_auth(
    cdk_app, deployment_config, app_config, custom_task_role_stack
):
    """Test that custom task role is used with NoAuth."""
    custom_role = custom_task_role_stack["role"]
    role_stack = custom_task_role_stack["stack"]

    stack = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
        task_role=custom_role,
    )

    # Verify the WebApp stack uses the custom role
    assert stack.task_role == custom_role

    # Verify custom role exists in the role stack with its S3 permission
    role_template = Template.from_stack(role_stack)
    role_template.has_resource_properties(
        "AWS::IAM::Role",
        {"Description": "Custom task role for testing"},
    )
    role_template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "s3:GetObject",
                                "Effect": "Allow",
                                "Resource": "arn:aws:s3:::my-test-bucket/*",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_web_app_stack_with_custom_task_role_cognito(
    cdk_app, deployment_config, app_config, custom_task_role_stack
):
    """Test custom role with Cognito auth gets secret permissions added."""
    custom_role = custom_task_role_stack["role"]
    role_stack = custom_task_role_stack["stack"]

    stack = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.COGNITO,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
        task_role=custom_role,
    )

    # Verify the WebApp stack uses the custom role
    assert stack.task_role == custom_role

    # Check the role stack template for both original and added permissions
    role_template = Template.from_stack(role_stack)

    # Verify the original custom S3 permission is still there
    role_template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "s3:GetObject",
                                "Effect": "Allow",
                                "Resource": "arn:aws:s3:::my-test-bucket/*",
                            }
                        )
                    ]
                )
            }
        },
    )

    # Verify Cognito secret permissions were added by the auth strategy
    role_template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(
                                    [
                                        "secretsmanager:GetSecretValue",
                                        "secretsmanager:DescribeSecret",
                                    ]
                                ),
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_web_app_stack_disable_waf_prevents_association(
    cdk_app, deployment_config, app_config
):
    """Test that disable_waf=True prevents WAF association."""
    stack = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
        disable_waf=True,
    )

    template = Template.from_stack(stack)

    # WAF association should not be created
    template.resource_count_is("AWS::WAFv2::WebACLAssociation", 0)


def test_web_app_stack_disable_waf_logs_warning(
    cdk_app, deployment_config, app_config, caplog
):
    """Test that disable_waf=True logs a warning."""
    WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
        disable_waf=True,
    )

    # Check warning was logged
    assert "WAF is disabled" in caplog.text
    assert "short-term debugging" in caplog.text
    assert "Never use in production" in caplog.text


def test_web_app_stack_associates_waf_by_default(webapp_no_auth):
    """Test that WAF is associated when disable_waf=False (default)."""
    template = Template.from_stack(webapp_no_auth)

    # WAF association should be created
    template.resource_count_is("AWS::WAFv2::WebACLAssociation", 1)
    template.has_resource_properties(
        "AWS::WAFv2::WebACLAssociation",
        {
            "WebACLArn": Match.string_like_regexp(r"arn:aws:wafv2:.*"),
        },
    )


def test_web_app_stack_no_warning_when_waf_enabled(
    cdk_app, deployment_config, app_config, caplog
):
    """Test that no warning is logged when WAF is enabled (default)."""
    WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
        disable_waf=False,  # Explicit False
    )

    # Check no WAF warning was logged
    assert "WAF is disabled" not in caplog.text


def test_web_app_stack_invalid_authentication_raises_error(
    cdk_app, deployment_config, app_config
):
    """Test that invalid authentication type raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported authentication type"):
        WebApp(
            cdk_app,
            deployment_config,
            app_config,
            authentication="invalid_auth",  # type: ignore [arg-type]
            docker_context_path="tests/fixtures",
            dockerfile_path="Dockerfile",
        )


# Cross-account access tests


def test_web_app_stack_cross_account_access_in_dev(
    dev_cdk_app, dev_deployment_config, app_config
):
    """Test that cross_account_access=True adds IAM policy and env var in dev."""
    stack = WebApp(
        dev_cdk_app,
        dev_deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
        cross_account_access=True,
    )
    template = Template.from_stack(stack)

    # Task role should have sts:AssumeRole policy
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRole",
                                "Effect": "Allow",
                                "Resource": Match.string_like_regexp(
                                    r".*assume_role_for_development_account"
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )

    # Container should have CROSS_ACCOUNT_ROLE_ARN env var
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": Match.array_with(
                [
                    Match.object_like(
                        {
                            "Environment": Match.array_with(
                                [
                                    {
                                        "Name": "CROSS_ACCOUNT_ROLE_ARN",
                                        "Value": Match.string_like_regexp(
                                            r".*assume_role_for_development_account"
                                        ),
                                    }
                                ]
                            )
                        }
                    )
                ]
            )
        },
    )


def test_web_app_stack_cross_account_access_disabled_by_default(
    cdk_app, deployment_config, app_config
):
    """Test that cross_account_access defaults to False and adds nothing."""
    stack = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
    )
    template = Template.from_stack(stack)

    # Should have no IAM policy with sts:AssumeRole for cross-account role
    # (the only policies should be for logging, not sts:AssumeRole)
    policies = template.find_resources("AWS::IAM::Policy")
    for _policy_id, policy in policies.items():
        statements = (
            policy.get("Properties", {}).get("PolicyDocument", {}).get("Statement", [])
        )
        for stmt in statements:
            if stmt.get("Action") == "sts:AssumeRole":
                resource = stmt.get("Resource", "")
                assert "assume_role_for_development_account" not in str(resource)


def test_web_app_stack_cross_account_access_true_in_prod(
    prod_cdk_app, prod_deployment_config, app_config
):
    """Test that cross_account_access=True in production adds no AssumeRole policy."""
    stack = WebApp(
        prod_cdk_app,
        prod_deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
        cross_account_access=True,
    )
    template = Template.from_stack(stack)

    # Even with cross_account_access=True, production should have no
    # sts:AssumeRole policy for the cross-account role
    policies = template.find_resources("AWS::IAM::Policy")
    for _policy_id, policy in policies.items():
        statements = (
            policy.get("Properties", {}).get("PolicyDocument", {}).get("Statement", [])
        )
        for stmt in statements:
            if stmt.get("Action") == "sts:AssumeRole":
                resource = stmt.get("Resource", "")
                assert "assume_role_for_development_account" not in str(resource)
