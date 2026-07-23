"""Unit tests for StaticSite stack."""

import pytest
from aws_cdk import App, Duration, Environment as CdkEnvironment, aws_events as events
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.config import DeploymentConfig
from gds_idea_cdk_constructs.static_site import (
    AuthType,
    StaticSite,
    StaticSiteProperties,
)
from tests.conftest import TEST_CONFIG


def _build_cdk_context(account_id: str, region: str, vpc_id: str, domain_name: str):
    """Helper to build CDK context for mocking AWS resource lookups."""
    return {
        f"availability-zones:account={account_id}:region={region}": [
            f"{region}a",
            f"{region}b",
            f"{region}c",
        ],
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
def static_site_props():
    """Fixture for default StaticSiteProperties."""
    return StaticSiteProperties(
        build_command="npx @11ty/eleventy",
        build_schedule=events.Schedule.rate(Duration.hours(1)),
    )


@pytest.fixture
def static_site_no_auth(cdk_app, deployment_config, app_config, static_site_props):
    """Fixture for StaticSite with NoAuth."""
    return StaticSite(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures/static_site",
        dockerfile_path="Dockerfile",
        static_site_props=static_site_props,
    )


@pytest.fixture
def static_site_cognito(cdk_app, deployment_config, app_config, static_site_props):
    """Fixture for StaticSite with Cognito auth."""
    return StaticSite(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.COGNITO,
        docker_context_path="tests/fixtures/static_site",
        dockerfile_path="Dockerfile",
        static_site_props=static_site_props,
    )


@pytest.fixture
def static_site_no_schedule(cdk_app, deployment_config, app_config):
    """Fixture for StaticSite without a build schedule."""
    props = StaticSiteProperties(
        build_command="npx @11ty/eleventy",
        build_schedule=None,
    )
    return StaticSite(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures/static_site",
        dockerfile_path="Dockerfile",
        static_site_props=props,
    )


# --- Core resource tests ---


def test_static_site_creates_core_resources(static_site_no_auth):
    """Test that StaticSite stack creates core AWS resources."""
    template = Template.from_stack(static_site_no_auth)

    template.resource_count_is("AWS::S3::Bucket", 1)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 1)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::TargetGroup", 1)
    template.resource_count_is("AWS::CertificateManager::Certificate", 1)
    template.resource_count_is("AWS::Route53::HostedZone", 1)
    # No ECS resources
    template.resource_count_is("AWS::ECS::TaskDefinition", 0)
    template.resource_count_is("AWS::ECS::Service", 0)


def test_static_site_creates_content_bucket(static_site_no_auth):
    """Test that content bucket is created with correct properties."""
    template = Template.from_stack(static_site_no_auth)

    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "BucketName": "cdk-static-testapp.test.example.com",
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
        },
    )


def test_static_site_certificate_domain(static_site_no_auth):
    """Test that certificate is created for correct domain."""
    template = Template.from_stack(static_site_no_auth)

    template.has_resource_properties(
        "AWS::CertificateManager::Certificate",
        {"DomainName": "testapp.test.example.com"},
    )


# --- Auth type tests ---


def test_static_site_no_auth_has_no_cognito(static_site_no_auth):
    """Test that NoAuth doesn't create Cognito resources."""
    template = Template.from_stack(static_site_no_auth)

    template.resource_count_is("AWS::Cognito::UserPoolClient", 0)


def test_static_site_cognito_auth_creates_user_pool_client(static_site_cognito):
    """Test that Cognito auth creates UserPoolClient."""
    template = Template.from_stack(static_site_cognito)

    template.resource_count_is("AWS::Cognito::UserPoolClient", 1)
    template.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "UserPoolId": "eu-west-2_TestPool",
            "GenerateSecret": True,
        },
    )


def test_static_site_cognito_auth_has_secret_permissions(static_site_cognito):
    """Test that Cognito auth grants secret access to the Lambda role."""
    template = Template.from_stack(static_site_cognito)

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


# --- Schedule tests ---


def test_static_site_with_schedule_creates_eventbridge_rule(static_site_no_auth):
    """Test that a build schedule creates an EventBridge rule."""
    template = Template.from_stack(static_site_no_auth)

    template.resource_count_is("AWS::Events::Rule", 1)
    template.has_resource_properties(
        "AWS::Events::Rule",
        {"ScheduleExpression": "rate(1 hour)"},
    )


def test_static_site_without_schedule_has_no_eventbridge_rule(
    static_site_no_schedule,
):
    """Test that no schedule means no EventBridge rule."""
    template = Template.from_stack(static_site_no_schedule)

    template.resource_count_is("AWS::Events::Rule", 0)


# --- WAF tests ---


def test_static_site_associates_waf_by_default(static_site_no_auth):
    """Test that WAF is associated when disable_waf=False (default)."""
    template = Template.from_stack(static_site_no_auth)

    template.resource_count_is("AWS::WAFv2::WebACLAssociation", 1)
    template.has_resource_properties(
        "AWS::WAFv2::WebACLAssociation",
        {"WebACLArn": Match.string_like_regexp(r"arn:aws:wafv2:.*")},
    )


def test_static_site_disable_waf_prevents_association(
    cdk_app, deployment_config, app_config, static_site_props
):
    """Test that disable_waf=True prevents WAF association."""
    stack = StaticSite(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures/static_site",
        dockerfile_path="Dockerfile",
        static_site_props=static_site_props,
        disable_waf=True,
    )

    template = Template.from_stack(stack)
    template.resource_count_is("AWS::WAFv2::WebACLAssociation", 0)


# --- Build Lambda tests ---


def test_static_site_build_lambda_has_correct_environment(static_site_no_auth):
    """Test that build Lambda has required environment variables."""
    template = Template.from_stack(static_site_no_auth)

    template_json = template.to_json()
    found_build_env = False
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::Lambda::Function":
            env_vars = (
                resource.get("Properties", {})
                .get("Environment", {})
                .get("Variables", {})
            )
            if "BUILD_COMMAND" in env_vars:
                assert env_vars["BUILD_COMMAND"] == "npx @11ty/eleventy"
                assert env_vars["BUILD_OUTPUT_DIR"] == "/tmp/_site"
                assert env_vars["CLEAN_ON_BUILD"] == "true"
                assert env_vars["KEEP_PREFIXES"] == ""
                assert "CONTENT_BUCKET" in env_vars
                found_build_env = True
                break

    assert found_build_env, "No Lambda found with BUILD_COMMAND environment variable"


def test_static_site_build_lambda_clean_disabled(
    cdk_app, deployment_config, app_config
):
    """Test that clean_on_build=False sets CLEAN_ON_BUILD to 'false'."""
    props = StaticSiteProperties(
        build_command="npx @11ty/eleventy",
        clean_on_build=False,
        keep_prefixes=["data/", "uploads/"],
    )
    stack = StaticSite(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures/static_site",
        dockerfile_path="Dockerfile",
        static_site_props=props,
    )

    template = Template.from_stack(stack)
    template_json = template.to_json()
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::Lambda::Function":
            env_vars = (
                resource.get("Properties", {})
                .get("Environment", {})
                .get("Variables", {})
            )
            if "BUILD_COMMAND" in env_vars:
                assert env_vars["CLEAN_ON_BUILD"] == "false"
                assert env_vars["KEEP_PREFIXES"] == "data/,uploads/"
                return

    pytest.fail("No Lambda found with BUILD_COMMAND environment variable")


# --- Serve Lambda tests ---


def test_static_site_serve_lambda_has_correct_environment_no_auth(
    static_site_no_auth,
):
    """Test that serve Lambda has content bucket but no auth env vars."""
    template = Template.from_stack(static_site_no_auth)

    template_json = template.to_json()
    found_serve = False
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::Lambda::Function":
            env_vars = (
                resource.get("Properties", {})
                .get("Environment", {})
                .get("Variables", {})
            )
            if "INDEX_DOCUMENT" in env_vars:
                assert "CONTENT_BUCKET" in env_vars
                assert env_vars["INDEX_DOCUMENT"] == "index.html"
                assert "COGNITO_AUTH_SECRET_NAME" not in env_vars
                found_serve = True
                break

    assert found_serve, "No Lambda found with INDEX_DOCUMENT environment variable"


def test_static_site_serve_lambda_has_auth_env_vars_cognito(static_site_cognito):
    """Test that serve Lambda has COGNITO_AUTH_SECRET_NAME with Cognito auth."""
    template = Template.from_stack(static_site_cognito)

    template_json = template.to_json()
    found_serve = False
    for resource in template_json["Resources"].values():
        if resource["Type"] == "AWS::Lambda::Function":
            env_vars = (
                resource.get("Properties", {})
                .get("Environment", {})
                .get("Variables", {})
            )
            if "INDEX_DOCUMENT" in env_vars:
                assert env_vars["COGNITO_AUTH_SECRET_NAME"] == "testapp/access"
                found_serve = True
                break

    assert found_serve, "No Lambda found with INDEX_DOCUMENT environment variable"


# --- Auto-invoke tests ---


def test_static_site_creates_auto_invoke_custom_resource(static_site_no_auth):
    """Test that a Custom Resource is created to invoke build on deploy."""
    template = Template.from_stack(static_site_no_auth)

    # Custom resources: ACM cleanup + Build invoker
    template.resource_count_is("AWS::CloudFormation::CustomResource", 2)


# --- Dev environment tests ---


def test_static_site_dev_environment_has_assume_policy(
    dev_cdk_app, dev_deployment_config, app_config, static_site_props
):
    """Test that dev environment adds assume policy for dev roles."""
    stack = StaticSite(
        dev_cdk_app,
        dev_deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures/static_site",
        dockerfile_path="Dockerfile",
        static_site_props=static_site_props,
    )

    template = Template.from_stack(stack)

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
                                        "arn:aws:iam::992382722318:role/*-poweraccess",
                                        "arn:aws:iam::992382722318:role/*-admin",
                                    ]
                                }
                            },
                        }
                    ]
                )
            }
        },
    )


# --- Validation tests ---


def test_static_site_requires_props(cdk_app, deployment_config, app_config):
    """Test that StaticSite raises ValueError without props."""
    with pytest.raises(ValueError, match="static_site_props is required"):
        StaticSite(
            cdk_app,
            deployment_config,
            app_config,
            authentication=AuthType.NONE,
            docker_context_path="tests/fixtures/static_site",
            dockerfile_path="Dockerfile",
            static_site_props=None,
        )


def test_static_site_invalid_authentication_raises_error(
    cdk_app, deployment_config, app_config, static_site_props
):
    """Test that invalid authentication type raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported authentication type"):
        StaticSite(
            cdk_app,
            deployment_config,
            app_config,
            authentication="invalid_auth",  # type: ignore[arg-type]
            docker_context_path="tests/fixtures/static_site",
            dockerfile_path="Dockerfile",
            static_site_props=static_site_props,
        )
