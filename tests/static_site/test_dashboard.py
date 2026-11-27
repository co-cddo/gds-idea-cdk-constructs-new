import json

import aws_cdk as cdk
import pytest
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
    aws_elasticloadbalancingv2 as elbv2,
    aws_lambda as _lambda,
)
from aws_cdk.assertions import Template

from gds_idea_cdk_constructs.static_site._dashboard import (
    SiteObservabilityDashboard,
    StaticSiteDashboardProperties,
    waf_web_acl_name,
)

WAF_ARN = (
    "arn:aws:wafv2:eu-west-2:111111111111:"
    "regional/webacl/test-waf/00000000-0000-0000-0000-000000000000"
)


def _synth(
    authenticated: bool = True,
    web_acl_name: str | None = "test-waf",
    **property_overrides,
) -> Template:
    """Synthesize a stack containing only SiteObservabilityDashboard.

    Keyword args other than ``authenticated`` and ``web_acl_name`` are
    forwarded into a ``StaticSiteDashboardProperties``.
    """
    app = cdk.App()
    stack = cdk.Stack(
        app,
        "TestStack",
        env=cdk.Environment(account="111111111111", region="eu-west-2"),
    )
    alb = elbv2.ApplicationLoadBalancer.from_application_load_balancer_attributes(
        stack,
        "Alb",
        load_balancer_arn=(
            "arn:aws:elasticloadbalancing:eu-west-2:111111111111:"
            "loadbalancer/app/example/0123456789abcdef"
        ),
        security_group_id="sg-0123456789abcdef0",
    )
    serve = _lambda.Function.from_function_name(stack, "Serve", "example-serve")
    build = _lambda.Function.from_function_name(stack, "Build", "example-build")

    SiteObservabilityDashboard(
        stack,
        "ObservabilityDashboard",
        app_name="example",
        stage="dev",
        load_balancer=alb,
        serve_lambda=serve,
        build_lambda=build,
        authenticated=authenticated,
        web_acl_name=web_acl_name,
        properties=StaticSiteDashboardProperties(**property_overrides),
    )
    return Template.from_stack(stack)


def _body(template: Template) -> str:
    """The whole template as a JSON string, for substring checks against the
    dashboard body (which CloudFormation stores as a serialized blob)."""
    return json.dumps(template.to_json(), ensure_ascii=False)


def test_creates_single_dashboard():
    """Test that exactly one dashboard is created."""
    _synth().resource_count_is("AWS::CloudWatch::Dashboard", 1)


def test_dashboard_name_uses_app_and_stage():
    """Test that the default name is {app}-{stage}-observability."""
    _synth().has_resource_properties(
        "AWS::CloudWatch::Dashboard",
        {"DashboardName": "example-dev-observability"},
    )


def test_dashboard_name_can_be_overridden():
    """Test that dashboard_name overrides the default name."""
    _synth(dashboard_name="custom").has_resource_properties(
        "AWS::CloudWatch::Dashboard", {"DashboardName": "custom"}
    )


def test_does_not_create_log_retention_resources():
    """Test that referencing the serve log group adds no extra resources."""
    template = _synth()
    template.resource_count_is("Custom::LogRetention", 0)
    template.resource_count_is("AWS::Logs::LogGroup", 0)


def test_alb_widgets_present():
    """Test that the ALB traffic and error widgets are present."""
    body = _body(_synth())
    for expected in (
        "Requests",
        "RequestCount",
        "Target response time",
        "TargetResponseTime",
        "HTTP errors",
        "HTTPCode_Target_5XX_Count",
        "HTTPCode_ELB_4XX_Count",
        "AWS/ApplicationELB",
    ):
        assert expected in body


def test_serve_lambda_widgets_present():
    """Test that serve Lambda metrics are charted for the serve function."""
    body = _body(_synth())
    assert "Serve Lambda invocations and errors" in body
    assert "Serve Lambda duration" in body
    assert "AWS/Lambda" in body
    assert "example-serve" in body
    for metric in ("Invocations", "Errors", "Throttles", "Duration"):
        assert metric in body


def test_build_lambda_widgets_present():
    """Test that build Lambda metrics are charted for the build function."""
    body = _body(_synth())
    assert "Build Lambda invocations and errors" in body
    assert "Build Lambda duration" in body
    assert "example-build" in body


def test_waf_widget_uses_web_acl_name_and_region():
    """Test that the WAF widget targets the ACL's name, region and ALL rules."""
    body = _body(_synth())
    assert "WAF requests" in body
    assert "AWS/WAFV2" in body
    assert "AllowedRequests" in body
    assert "BlockedRequests" in body
    assert "test-waf" in body
    assert "ALL" in body


def test_waf_widget_omitted_without_web_acl():
    """Test that the WAF widget is dropped when WAF is not enabled."""
    body = _body(_synth(web_acl_name=None))
    assert "WAF requests" not in body
    assert "AWS/WAFV2" not in body


def test_signin_and_user_widgets_present_when_authenticated():
    """Test that sign-in and user widgets are shown for authenticated sites."""
    body = _body(_synth())
    assert "Successful sign-ins" in body
    assert "ELBAuthSuccess" in body
    assert "Active users" in body
    assert "Most active users" in body


def test_signin_and_user_widgets_omitted_when_unauthenticated():
    """Test that sign-in and user widgets are dropped for AuthType.NONE sites."""
    body = _body(_synth(authenticated=False))
    assert "Successful sign-ins" not in body
    assert "ELBAuthSuccess" not in body
    assert "Active users" not in body
    assert "Most active users" not in body
    assert "Requests" in body


def test_user_queries_target_serve_lambda_log_group():
    """Test that user queries read the serve Lambda's log group."""
    body = _body(_synth())
    assert "SOURCE '/aws/lambda/" in body
    assert "function:example-serve" in body
    assert "User authenticated" in body


def test_active_users_defaults_to_aggregate_count():
    """Test that the default hides individual emails."""
    body = _body(_synth())
    assert "count_distinct(email)" in body
    assert "last_access by email" not in body
    assert "Hidden by default" in body


def test_active_users_shows_emails_only_when_opted_in():
    """Test that show_user_emails reveals the per-user widgets."""
    body = _body(_synth(show_user_emails=True))
    assert "last_access by email" in body
    assert "count() as requests by email" in body
    assert "Hidden by default" not in body


def test_extra_widgets_are_appended():
    """Test that extra_widgets are added to the dashboard."""
    marker = "CUSTOM_MARKER_WIDGET"
    body = _body(
        _synth(
            extra_widgets=[
                cloudwatch.TextWidget(markdown=marker, width=24, height=1),
            ]
        )
    )
    assert marker in body


def test_widget_ordering():
    """Test that widgets appear in the documented order."""
    body = _body(_synth())
    titles = [
        "Successful sign-ins",
        "Active users",
        "Requests",
        "HTTP errors",
        "WAF requests",
        "Serve Lambda invocations and errors",
        "Build Lambda invocations and errors",
    ]
    positions = [body.index(title) for title in titles]
    assert positions == sorted(positions)


def test_docstring_lists_all_widgets():
    """Test that every widget title is documented on the class."""
    doc = SiteObservabilityDashboard.__doc__
    for title in (
        "Successful sign-ins",
        "Successful sign-ins over time",
        "Active users",
        "Most active users",
        "Requests",
        "Target response time",
        "HTTP errors",
        "WAF requests",
        "Serve Lambda invocations and errors",
        "Serve Lambda duration",
        "Build Lambda invocations and errors",
        "Build Lambda duration",
    ):
        assert title in doc


def test_waf_web_acl_name_parses_arn():
    """Test that the Web ACL name is extracted from a regional ARN."""
    assert waf_web_acl_name(WAF_ARN) == "test-waf"


def test_waf_web_acl_name_rejects_other_arns():
    """Test that a non Web ACL ARN raises ValueError."""
    with pytest.raises(ValueError, match="Not a WAFv2 Web ACL ARN"):
        waf_web_acl_name("arn:aws:s3:::some-bucket")
