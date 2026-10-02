"""Tests for ALB -> Lambda security: invoke-permission scoping and cognito-auth pins.

Covers:
- the ELB invoke permission on Lambdas behind the ALB is scoped (no SourceArn
  means any ALB in any AWS account could invoke the function),
- the COGNITO_AUTH_* pin env vars reach the serve Lambda / ECS container,
- ``add_lambda_route``, in the same stack and in a different stack.

Dependency cycles matter here: the env vars reference the ALB and Cognito client
while the target group references the Lambda. ``Template.from_stack`` fails on
a same-stack cycle ("Template is undeployable"), and ``App.synth`` fails on a
cross-stack one, so building the templates in these tests is itself the check.
"""

import json

import pytest
from aws_cdk import (
    App,
    Duration,
    Environment as CdkEnvironment,
    Stack,
    aws_events as events,
    aws_lambda as _lambda,
)
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs._lambda_targets import scope_elb_invoke_permission
from gds_idea_cdk_constructs.static_site import (
    AuthType,
    StaticSite,
    StaticSiteProperties,
)
from gds_idea_cdk_constructs.web_app.stack import WebApp
from tests.conftest import TEST_CONFIG
from tests.static_site.test_stack import _build_cdk_context

ELB = "elasticloadbalancing.amazonaws.com"
PIN_VARS = {
    "COGNITO_AUTH_USER_POOL_ID",
    "COGNITO_AUTH_CLIENT_IDS",
    "COGNITO_AUTH_ALB_ARNS",
}


# --- helpers ---------------------------------------------------------------


def _elb_permissions(template: Template) -> dict:
    return template.find_resources(
        "AWS::Lambda::Permission", {"Properties": {"Principal": ELB}}
    )


def _assert_scoped_to_account(permission: dict, account: str = "testing") -> None:
    source_arn = json.dumps(permission["Properties"].get("SourceArn"))
    assert "elasticloadbalancing" in source_arn
    assert "targetgroup/*" in source_arn
    assert "eu-west-2" in source_arn
    assert account in source_arn


def _lambda_env(template: Template, marker: str) -> dict:
    """Environment variables of the (single) Lambda that defines ``marker``."""
    for resource in template.find_resources("AWS::Lambda::Function").values():
        env = resource["Properties"].get("Environment", {}).get("Variables", {})
        if marker in env:
            return env
    pytest.fail(f"No Lambda with env var {marker}")


def _simple_function(scope, name="Fn"):
    return _lambda.Function(
        scope,
        name,
        runtime=_lambda.Runtime.PYTHON_3_12,
        handler="index.handler",
        code=_lambda.Code.from_inline("def handler(event, context): pass"),
    )


@pytest.fixture
def cdk_app():
    return App(
        context=_build_cdk_context(
            "testing", "eu-west-2", TEST_CONFIG["vpc_id"], TEST_CONFIG["domain_name"]
        )
    )


def _static_site(cdk_app, deployment_config, app_config, authentication):
    return StaticSite(
        cdk_app,
        deployment_config,
        app_config,
        authentication=authentication,
        docker_context_path="tests/fixtures/static_site",
        dockerfile_path="Dockerfile",
        static_site_props=StaticSiteProperties(
            build_command="npx @11ty/eleventy",
            build_schedule=events.Schedule.rate(Duration.hours(1)),
        ),
    )


# --- StaticSite: permission scoping ----------------------------------------


@pytest.mark.parametrize(
    "authentication", [AuthType.NONE, AuthType.COGNITO, AuthType.INTERNAL_ACCESS]
)
def test_static_site_elb_invoke_permission_is_scoped(
    cdk_app, deployment_config, app_config, authentication
):
    site = _static_site(cdk_app, deployment_config, app_config, authentication)
    template = Template.from_stack(site)

    permissions = _elb_permissions(template)
    assert len(permissions) == 1
    for permission in permissions.values():
        _assert_scoped_to_account(permission)


# --- StaticSite: pin env vars ----------------------------------------------


@pytest.mark.parametrize("authentication", [AuthType.COGNITO, AuthType.INTERNAL_ACCESS])
def test_static_site_serve_lambda_is_pinned(
    cdk_app, deployment_config, app_config, authentication
):
    site = _static_site(cdk_app, deployment_config, app_config, authentication)
    template = Template.from_stack(site)
    env = _lambda_env(template, "INDEX_DOCUMENT")

    assert env["COGNITO_AUTH_SECRET_NAME"] == "testapp/access"
    assert env["COGNITO_AUTH_USER_POOL_ID"] == "eu-west-2_TestPool"

    client = env["COGNITO_AUTH_CLIENT_IDS"]
    assert client["Ref"].startswith("Client")
    assert template.to_json()["Resources"][client["Ref"]]["Type"] == (
        "AWS::Cognito::UserPoolClient"
    )

    alb = env["COGNITO_AUTH_ALB_ARNS"]
    assert template.to_json()["Resources"][alb["Ref"]]["Type"] == (
        "AWS::ElasticLoadBalancingV2::LoadBalancer"
    )


def test_static_site_without_auth_has_no_pins(cdk_app, deployment_config, app_config):
    site = _static_site(cdk_app, deployment_config, app_config, AuthType.NONE)
    env = _lambda_env(Template.from_stack(site), "INDEX_DOCUMENT")

    assert not PIN_VARS & set(env)
    assert "COGNITO_AUTH_SECRET_NAME" not in env


@pytest.mark.parametrize(
    "authentication", [AuthType.NONE, AuthType.COGNITO, AuthType.INTERNAL_ACCESS]
)
def test_static_site_templates_have_no_dependency_cycles(
    cdk_app, deployment_config, app_config, authentication
):
    site = _static_site(cdk_app, deployment_config, app_config, authentication)
    Template.from_stack(site)  # raises on a dependency cycle


# --- WebApp: pin env vars --------------------------------------------------


@pytest.mark.parametrize("authentication", [AuthType.COGNITO, AuthType.INTERNAL_ACCESS])
def test_web_app_container_is_pinned(
    cdk_app, deployment_config, app_config, authentication
):
    stack = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=authentication,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
    )
    template = Template.from_stack(stack)

    (task_def,) = template.find_resources("AWS::ECS::TaskDefinition").values()
    env = {
        item["Name"]: item["Value"]
        for item in task_def["Properties"]["ContainerDefinitions"][0]["Environment"]
    }

    assert env["COGNITO_AUTH_USER_POOL_ID"] == "eu-west-2_TestPool"
    assert "COGNITO_AUTH_CLIENT_IDS" in env
    assert "COGNITO_AUTH_ALB_ARNS" in env


def test_web_app_without_auth_has_no_pins(cdk_app, deployment_config, app_config):
    stack = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
    )
    template = Template.from_stack(stack)

    (task_def,) = template.find_resources("AWS::ECS::TaskDefinition").values()
    names = {
        item["Name"]
        for item in task_def["Properties"]["ContainerDefinitions"][0].get(
            "Environment", []
        )
    }
    assert not PIN_VARS & names


# --- scope_elb_invoke_permission -------------------------------------------


def test_scope_elb_invoke_permission_fails_loudly_without_a_target_group():
    stack = Stack(App(), "S", env=CdkEnvironment(account="testing", region="eu-west-2"))

    with pytest.raises(RuntimeError, match="No ELB invoke permission"):
        scope_elb_invoke_permission(_simple_function(stack))


# --- add_lambda_route ------------------------------------------------------


def test_add_lambda_route_in_same_stack(cdk_app, deployment_config, app_config):
    site = _static_site(cdk_app, deployment_config, app_config, AuthType.COGNITO)
    function = _simple_function(site, "ApiFn")

    site.add_lambda_route(
        site,
        "Api",
        function=function,
        path_patterns=["/api/*"],
        priority=20,
    )
    template = Template.from_stack(site)

    template.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::ListenerRule",
        {
            "Priority": 20,
            "Conditions": Match.array_with(
                [
                    {
                        "Field": "path-pattern",
                        "PathPatternConfig": {"Values": ["/api/*"]},
                    }
                ]
            ),
            # Protected by the site's own Cognito authentication action.
            "Actions": Match.array_with(
                [Match.object_like({"Type": "authenticate-cognito"})]
            ),
        },
    )
    assert len(_elb_permissions(template)) == 2  # serve lambda + ApiFn
    for permission in _elb_permissions(template).values():
        _assert_scoped_to_account(permission)

    env = _lambda_env(template, "COGNITO_AUTH_ALB_ARNS")
    assert PIN_VARS <= set(env)


def test_add_lambda_route_can_skip_pins(cdk_app, deployment_config, app_config):
    site = _static_site(cdk_app, deployment_config, app_config, AuthType.COGNITO)
    function = _simple_function(site, "ApiFn")
    site.add_lambda_route(
        site,
        "Api",
        function=function,
        path_patterns=["/api/*"],
        priority=20,
        pin_cognito_auth=False,
    )

    functions = Template.from_stack(site).find_resources("AWS::Lambda::Function")
    api = next(
        f
        for f in functions.values()
        if f["Properties"].get("Handler") == "index.handler"
    )
    assert not PIN_VARS & set(
        api["Properties"].get("Environment", {}).get("Variables", {})
    )


def test_add_lambda_route_without_auth_forwards_and_has_no_pins(
    cdk_app, deployment_config, app_config
):
    site = _static_site(cdk_app, deployment_config, app_config, AuthType.NONE)
    function = _simple_function(site, "ApiFn")
    site.add_lambda_route(
        site, "Api", function=function, path_patterns=["/api/*"], priority=20
    )
    template = Template.from_stack(site)

    template.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::ListenerRule",
        {"Priority": 20, "Actions": [Match.object_like({"Type": "forward"})]},
    )
    api_env = (
        next(
            f
            for f in template.find_resources("AWS::Lambda::Function").values()
            if f["Properties"].get("Handler") == "index.handler"
        )["Properties"].get("Environment", {})
    ).get("Variables", {})
    assert not PIN_VARS & set(api_env)


def test_add_lambda_route_in_another_stack_depends_one_way(
    cdk_app, deployment_config, app_config
):
    """The route lives in the caller's stack; frontend never references it.

    If the frontend stack referenced the backend's target group while the
    backend's Lambda referenced the frontend's ALB / client, CDK would report
    a cyclic cross-stack reference at synth.
    """
    site = _static_site(
        cdk_app, deployment_config, app_config, AuthType.INTERNAL_ACCESS
    )
    backend = Stack(
        cdk_app, "backend", env=CdkEnvironment(account="testing", region="eu-west-2")
    )
    function = _simple_function(backend, "ApiFn")

    site.add_lambda_route(
        backend,
        "Api",
        function=function,
        path_patterns=["/api/admin/*"],
        priority=30,
    )

    # Synth raises on cyclic cross-stack references.
    cdk_app.synth()

    assert site in backend.dependencies
    assert backend not in site.dependencies

    backend_template = Template.from_stack(backend)
    site_template = Template.from_stack(site)

    backend_template.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::ListenerRule", {"Priority": 30}
    )
    assert "ApiTargetGroup" not in json.dumps(site_template.to_json())
    site_template.resource_count_is("AWS::ElasticLoadBalancingV2::ListenerRule", 0)

    permissions = _elb_permissions(backend_template)
    assert len(permissions) == 1
    for permission in permissions.values():
        _assert_scoped_to_account(permission)

    env = _lambda_env(backend_template, "COGNITO_AUTH_ALB_ARNS")
    assert PIN_VARS <= set(env)
    assert env["COGNITO_AUTH_USER_POOL_ID"] == "eu-west-2_TestPool"
