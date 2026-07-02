import json

import aws_cdk as cdk
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
)
from aws_cdk.assertions import Template

from gds_idea_cdk_constructs.web_app._dashboard import AppUsageDashboard


def _synth(**dashboard_kwargs) -> Template:
    """Synthesize a stack containing only AppUsageDashboard, with the ALB and log
    group imported by attribute — no VPC lookup or Docker build required."""
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
        **dashboard_kwargs,
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
