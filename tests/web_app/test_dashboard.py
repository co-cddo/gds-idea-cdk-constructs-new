import json

import aws_cdk as cdk
import pytest
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
)
from aws_cdk.assertions import Template

from gds_idea_cdk_constructs.web_app._dashboard import (
    AppUsageDashboard,
    DashboardProperties,
)


def _synth(**property_overrides) -> Template:
    """Synthesize a stack containing only AppUsageDashboard.

    Any keyword args are forwarded into a ``DashboardProperties``, so tests
    can write ``_synth(show_user_emails=True)`` as before.
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
    log_group = logs.LogGroup.from_log_group_name(stack, "Logs", "/example/app")

    AppUsageDashboard(
        stack,
        "UsageDashboard",
        app_name="example",
        stage="dev",
        load_balancer=alb,
        log_groups=[log_group],
        properties=DashboardProperties(**property_overrides),
    )
    return Template.from_stack(stack)


def _body(template: Template) -> str:
    """The whole template as a JSON string, for substring checks against the
    dashboard body (which CloudFormation stores as a serialized blob)."""
    return json.dumps(template.to_json(), ensure_ascii=False)


def test_creates_single_dashboard():
    _synth().resource_count_is("AWS::CloudWatch::Dashboard", 1)


def test_dashboard_name_uses_app_and_stage():
    _synth().has_resource_properties(
        "AWS::CloudWatch::Dashboard",
        {"DashboardName": "example-dev-observability"},
    )


def test_requests_widget_present():
    body = _body(_synth())
    assert "Requests" in body
    assert "AWS/ApplicationELB" in body
    assert "RequestCount" in body


def test_active_users_defaults_to_aggregate_count():
    # Privacy-preserving default: a distinct-user count, never individual emails.
    body = _body(_synth())
    assert "count_distinct(email)" in body
    assert "active_users" in body
    assert "last_login by email" not in body


def test_active_users_shows_emails_only_when_opted_in():
    body = _body(_synth(show_user_emails=True))
    assert "last_login by email" in body
    assert "max(@timestamp)" in body


def test_extra_widgets_are_appended():
    marker = "CUSTOM_MARKER_WIDGET"
    body = _body(
        _synth(
            extra_widgets=[
                cloudwatch.TextWidget(markdown=marker, width=24, height=1),
            ]
        )
    )
    assert marker in body


def test_signin_widget_present():
    body = _body(_synth())
    assert "Successful sign-ins" in body
    assert "ELBAuthSuccess" in body
    assert "AWS/ApplicationELB" in body


def test_signin_widget_appears_before_active_users_and_requests():
    # Ordering is part of the public contract described in the docstring.
    body = _body(_synth())
    assert body.index("Successful sign-ins") < body.index("Active users")
    assert body.index("Active users") < body.index("Requests")


def test_response_time_widget_present():
    body = _body(_synth())
    assert "Target response time" in body
    assert "TargetResponseTime" in body


def test_http_errors_widget_present():
    body = _body(_synth())

    # Widget title
    assert "HTTP errors" in body

    # All four series show up as metrics on the widget
    assert "HTTPCode_Target_5XX_Count" in body
    assert "HTTPCode_ELB_5XX_Count" in body
    assert "HTTPCode_Target_4XX_Count" in body
    assert "HTTPCode_ELB_4XX_Count" in body

    # Namespace is right (guards against these leaking under, say, AWS/NetworkELB)
    assert "AWS/ApplicationELB" in body


def test_docstring_lists_all_widgets():
    """The class docstring's widget list must stay in sync with what
    the construct actually renders."""
    doc = AppUsageDashboard.__doc__ or ""
    for title in (
        "Successful sign-ins",
        "Successful sign-ins over time",
        "Active users",
        "Most active users",
        "Target response time",
        "Requests",
        "HTTP errors",
    ):
        assert title in doc, f"{title!r} missing from AppUsageDashboard docstring"


def test_signin_trend_widget_present():
    body = _body(_synth())
    assert "Successful sign-ins over time" in body
    assert "ELBAuthSuccess" in body


def test_most_active_users_query_only_when_opted_in():
    body_default = _body(_synth())
    assert "count() as requests by email" not in body_default

    body_optin = _body(_synth(show_user_emails=True))
    assert "count() as requests by email" in body_optin
    assert "Most active users" in body_optin


def test_most_active_users_shows_placeholder_by_default():
    body = _body(_synth())
    assert "Hidden by default to avoid exposing" in body


def test_empty_log_groups_raises():
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
    with pytest.raises(
        ValueError, match=r"log_groups must contain at least one log group"
    ):
        AppUsageDashboard(
            stack,
            "UsageDashboard",
            app_name="example",
            stage="dev",
            load_balancer=alb,
            log_groups=[],
            properties=DashboardProperties(),
        )


def test_auth_filter_pattern_override_flows_through():
    """Custom filter pattern set on DashboardProperties should appear in the
    generated Logs Insights queries."""
    body = _body(_synth(auth_filter_pattern="@message like /LOGIN_OK/"))
    assert "@message like /LOGIN_OK/" in body
    # And the default is gone
    assert "User authenticated" not in body
