"""Internal: CloudWatch observability dashboard composed by the StaticSite construct.

Private to ``static_site``. App authors do not instantiate this directly —
``StaticSite`` creates it (passing its own load balancer and Lambda functions)
when ``enable_dashboard`` is set. Everything it reads lives in the same
account and region as the stack, so no cross-account (OAM) configuration is
involved.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aws_cdk import (
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_elasticloadbalancingv2 as elbv2,
    aws_lambda as _lambda,
)
from constructs import Construct

from ..web_app._dashboard import (
    DEFAULT_WIDGET_HEIGHT,
    DEFAULT_WIDGET_WIDTH,
    OPERATIONAL_METRIC_PERIOD,
    SUMMARY_METRIC_PERIOD,
    TREND_METRIC_PERIOD,
)

AUTH_LOG_FILTER = "@message like /User authenticated/"
EMAIL_PARSE_PATTERN = "/email=(?<email>[^,\\s]+)/"


def waf_web_acl_name(web_acl_arn: str) -> str:
    """Extract the Web ACL name from a regional WAFv2 Web ACL ARN.

    Args:
        web_acl_arn: ARN of the form
            ``arn:aws:wafv2:<region>:<account>:regional/webacl/<name>/<id>``.

    Returns:
        The Web ACL name, as used in the ``WebACL`` CloudWatch dimension.

    Raises:
        ValueError: If the ARN is not a Web ACL ARN.
    """
    resource = web_acl_arn.split(":", 5)[-1]
    parts = resource.split("/")
    if len(parts) != 4 or parts[1] != "webacl":
        raise ValueError(f"Not a WAFv2 Web ACL ARN: {web_acl_arn}")
    return parts[2]


@dataclass
class StaticSiteDashboardProperties:
    """User-facing configuration for the StaticSite observability dashboard.

    Pass an instance via ``StaticSite(..., dashboard_properties=
    StaticSiteDashboardProperties(...))`` to override any of the defaults; omit
    it to get the standard dashboard.

    Attributes:
        dashboard_name: Explicit dashboard name. When ``None`` (default), the
            name is ``{app_name}-{stage}-observability``.
        show_user_emails: Privacy switch for widgets that surface individual
            user identities. When ``True``, the Active users widget lists
            individual emails and their last access time, and the Most active
            users bar chart is rendered. When ``False`` (default), the Active
            users widget shows an aggregate distinct-user count and the Most
            active users slot is replaced with a placeholder explaining how to
            enable it.
        extra_widgets: Additional CloudWatch widgets appended after the
            standard set, in the order supplied, on new rows below the
            standard ones.
    """

    dashboard_name: str | None = None
    show_user_emails: bool = False
    extra_widgets: Sequence[cloudwatch.IWidget] | None = None


class SiteObservabilityDashboard(Construct):
    """A CloudWatch dashboard covering traffic, health and usage of a StaticSite.

    Widgets (in display order, two per row):

    * **Successful sign-ins** and **Successful sign-ins over time** — ALB
      ``ELBAuthSuccess``. Only when ``authenticated`` is ``True``.
    * **Active users** and **Most active users** — from the serve Lambda's
      ``User authenticated`` log line. Only when ``authenticated`` is ``True``.
      Privacy-preserving by default; see ``show_user_emails`` on
      :class:`StaticSiteDashboardProperties`.
    * **Requests** — ALB ``RequestCount`` (Sum, 5-minute periods).
    * **Target response time** — ALB ``TargetResponseTime`` (Average, p95,
      p99 over 5-minute periods).
    * **HTTP errors** — ALB 4xx and 5xx responses, split by whether the ALB
      or the serve Lambda generated them.
    * **WAF requests** — allowed and blocked requests for the Web ACL. Only
      when ``web_acl_name`` is supplied.
    * **Serve Lambda invocations and errors** — invocations, errors and
      throttles of the Lambda that serves the site.
    * **Serve Lambda duration** — Average, p95 and p99.
    * **Build Lambda invocations and errors** — builds run and failed.
    * **Build Lambda duration** — Average and Maximum.

    Args:
        scope: The construct scope.
        construct_id: The construct ID.
        app_name: Logical app name, used to build the default dashboard name.
        load_balancer: The site's application load balancer.
        serve_lambda: The Lambda function serving the site.
        build_lambda: The Lambda function building the site.
        stage: Optional environment (``"dev"``/``"prod"``) used in the default
            dashboard name.
        authenticated: Whether the site sits behind authentication. When
            ``False`` the sign-in and user widgets are omitted.
        web_acl_name: Name of the Web ACL associated with the ALB. When
            ``None`` the WAF widget is omitted.
        properties: Optional :class:`StaticSiteDashboardProperties`.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        load_balancer: elbv2.IApplicationLoadBalancer,
        serve_lambda: _lambda.IFunction,
        build_lambda: _lambda.IFunction,
        stage: str | None = None,
        authenticated: bool = True,
        web_acl_name: str | None = None,
        properties: StaticSiteDashboardProperties | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        properties = properties or StaticSiteDashboardProperties()

        self._load_balancer = load_balancer
        self._serve_lambda = serve_lambda
        self._build_lambda = build_lambda
        self._web_acl_name = web_acl_name
        self._show_user_emails = properties.show_user_emails
        # Referenced by name rather than via ``serve_lambda.log_group``, which
        # would add a LogRetention custom resource to the stack.
        self._serve_log_group_name = f"/aws/lambda/{serve_lambda.function_name}"

        dashboard_name = properties.dashboard_name or (
            f"{app_name}-{stage}-observability"
            if stage
            else f"{app_name}-observability"
        )
        dashboard = cloudwatch.Dashboard(
            self, "Dashboard", dashboard_name=dashboard_name
        )

        if authenticated:
            dashboard.add_widgets(
                self._signin_widget(),
                self._signin_trend_widget(),
            )
            dashboard.add_widgets(
                self._active_users_widget(),
                self._most_active_users_widget(),
            )
        dashboard.add_widgets(self._requests_widget(), self._response_time_widget())
        if web_acl_name:
            dashboard.add_widgets(self._errors_widget(), self._waf_widget())
        else:
            dashboard.add_widgets(self._errors_widget())
        dashboard.add_widgets(
            self._serve_invocations_widget(), self._serve_duration_widget()
        )
        dashboard.add_widgets(
            self._build_invocations_widget(), self._build_duration_widget()
        )
        if properties.extra_widgets:
            dashboard.add_widgets(*properties.extra_widgets)

        self.dashboard = dashboard

    def _signin_widget(self) -> cloudwatch.IWidget:
        return cloudwatch.SingleValueWidget(
            title="Successful sign-ins",
            metrics=[
                self._load_balancer.metrics.custom(
                    "ELBAuthSuccess",
                    statistic="Sum",
                    period=SUMMARY_METRIC_PERIOD,
                )
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
            set_period_to_time_range=True,
        )

    def _signin_trend_widget(self) -> cloudwatch.IWidget:
        return cloudwatch.GraphWidget(
            title="Successful sign-ins over time",
            left=[
                self._load_balancer.metrics.custom(
                    "ELBAuthSuccess",
                    statistic="Sum",
                    period=TREND_METRIC_PERIOD,
                    label="Sign-ins per hour",
                )
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _user_query(self, *stats_lines: str) -> list[str]:
        return [
            "fields @timestamp, @message",
            f"filter {AUTH_LOG_FILTER}",
            f"parse @message {EMAIL_PARSE_PATTERN}",
            *stats_lines,
        ]

    def _active_users_widget(self) -> cloudwatch.IWidget:
        if self._show_user_emails:
            return cloudwatch.LogQueryWidget(
                title="Active users — last access by email",
                log_group_names=[self._serve_log_group_name],
                view=cloudwatch.LogQueryVisualizationType.TABLE,
                query_lines=self._user_query(
                    "stats max(@timestamp) as last_access by email",
                    "sort last_access desc",
                ),
                width=DEFAULT_WIDGET_WIDTH,
                height=DEFAULT_WIDGET_HEIGHT,
            )
        return cloudwatch.LogQueryWidget(
            title="Active users (daily)",
            log_group_names=[self._serve_log_group_name],
            view=cloudwatch.LogQueryVisualizationType.LINE,
            query_lines=self._user_query(
                "stats count_distinct(email) as active_users by bin(1d)"
            ),
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _most_active_users_widget(self) -> cloudwatch.IWidget:
        if self._show_user_emails:
            return cloudwatch.LogQueryWidget(
                title="Most active users",
                log_group_names=[self._serve_log_group_name],
                view=cloudwatch.LogQueryVisualizationType.BAR,
                query_lines=self._user_query(
                    "stats count() as requests by email",
                    "sort requests desc",
                ),
                width=DEFAULT_WIDGET_WIDTH,
                height=DEFAULT_WIDGET_HEIGHT,
            )
        return cloudwatch.TextWidget(
            markdown=(
                "### Most active users\n\n"
                "_Hidden by default to avoid exposing individual user emails._"
                "\n\nEnable by setting ``show_user_emails=True`` on the "
                "``StaticSiteDashboardProperties`` passed to ``StaticSite``."
            ),
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _requests_widget(self) -> cloudwatch.IWidget:
        return cloudwatch.GraphWidget(
            title="Requests",
            left=[
                self._load_balancer.metrics.request_count(
                    period=OPERATIONAL_METRIC_PERIOD,
                    statistic="Sum",
                )
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _response_time_widget(self) -> cloudwatch.IWidget:
        stats = ("Average", "p95", "p99")
        return cloudwatch.GraphWidget(
            title="Target response time",
            left=[
                self._load_balancer.metrics.target_response_time(
                    period=OPERATIONAL_METRIC_PERIOD,
                    statistic=stat,
                    label=stat.lower() if stat != "Average" else "avg",
                )
                for stat in stats
            ],
            left_y_axis=cloudwatch.YAxisProps(label="seconds", show_units=False),
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _errors_widget(self) -> cloudwatch.IWidget:
        return cloudwatch.GraphWidget(
            title="HTTP errors",
            left=[
                self._load_balancer.metrics.http_code_target(
                    code=elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
                    period=OPERATIONAL_METRIC_PERIOD,
                    statistic="Sum",
                    label="Target 5xx (serve Lambda failed)",
                ),
                self._load_balancer.metrics.http_code_elb(
                    code=elbv2.HttpCodeElb.ELB_5XX_COUNT,
                    period=OPERATIONAL_METRIC_PERIOD,
                    statistic="Sum",
                    label="ELB 5xx (unreachable)",
                ),
                self._load_balancer.metrics.http_code_target(
                    code=elbv2.HttpCodeTarget.TARGET_4XX_COUNT,
                    period=OPERATIONAL_METRIC_PERIOD,
                    statistic="Sum",
                    label="Target 4xx (not found / forbidden)",
                ),
                self._load_balancer.metrics.http_code_elb(
                    code=elbv2.HttpCodeElb.ELB_4XX_COUNT,
                    period=OPERATIONAL_METRIC_PERIOD,
                    statistic="Sum",
                    label="ELB 4xx (bad request / auth fail)",
                ),
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _waf_widget(self) -> cloudwatch.IWidget:
        def waf_metric(name: str, label: str) -> cloudwatch.Metric:
            return cloudwatch.Metric(
                namespace="AWS/WAFV2",
                metric_name=name,
                dimensions_map={
                    "WebACL": self._web_acl_name,
                    "Region": Stack.of(self).region,
                    "Rule": "ALL",
                },
                statistic="Sum",
                period=OPERATIONAL_METRIC_PERIOD,
                label=label,
            )

        return cloudwatch.GraphWidget(
            title="WAF requests",
            left=[
                waf_metric("AllowedRequests", "Allowed"),
                waf_metric("BlockedRequests", "Blocked"),
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _serve_invocations_widget(self) -> cloudwatch.IWidget:
        return cloudwatch.GraphWidget(
            title="Serve Lambda invocations and errors",
            left=[
                self._serve_lambda.metric_invocations(
                    period=OPERATIONAL_METRIC_PERIOD, statistic="Sum"
                ),
                self._serve_lambda.metric_errors(
                    period=OPERATIONAL_METRIC_PERIOD, statistic="Sum"
                ),
                self._serve_lambda.metric_throttles(
                    period=OPERATIONAL_METRIC_PERIOD, statistic="Sum"
                ),
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _serve_duration_widget(self) -> cloudwatch.IWidget:
        stats = ("Average", "p95", "p99")
        return cloudwatch.GraphWidget(
            title="Serve Lambda duration",
            left=[
                self._serve_lambda.metric_duration(
                    period=OPERATIONAL_METRIC_PERIOD,
                    statistic=stat,
                    label=stat.lower() if stat != "Average" else "avg",
                )
                for stat in stats
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _build_invocations_widget(self) -> cloudwatch.IWidget:
        # Builds are infrequent, so use the trend period to keep them visible.
        return cloudwatch.GraphWidget(
            title="Build Lambda invocations and errors",
            left=[
                self._build_lambda.metric_invocations(
                    period=TREND_METRIC_PERIOD, statistic="Sum"
                ),
                self._build_lambda.metric_errors(
                    period=TREND_METRIC_PERIOD, statistic="Sum"
                ),
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _build_duration_widget(self) -> cloudwatch.IWidget:
        return cloudwatch.GraphWidget(
            title="Build Lambda duration",
            left=[
                self._build_lambda.metric_duration(
                    period=TREND_METRIC_PERIOD,
                    statistic=stat,
                    label=stat.lower() if stat != "Average" else "avg",
                )
                for stat in ("Average", "Maximum")
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )
