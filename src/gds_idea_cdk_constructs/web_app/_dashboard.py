"""Internal: CloudWatch usage dashboard composed by the WebApp construct.

Private to ``web_app``. App authors do not instantiate this directly — ``WebApp``
creates it (passing its own load balancer and log group) when
``enable_usage_dashboard`` is set. It reads the app's own ALB metrics and Cognito
authentication logs in the same account/region, so no cross-account (OAM)
configuration is involved.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
)
from constructs import Construct

DEFAULT_WIDGET_WIDTH = 12
DEFAULT_WIDGET_HEIGHT = 6
DEFAULT_AUTH_FILTER_PATTERN = "@message like /User authenticated/"

OPERATIONAL_METRIC_PERIOD = Duration.minutes(5)
TREND_METRIC_PERIOD = Duration.hours(1)
SUMMARY_METRIC_PERIOD = Duration.days(7)


@dataclass
class DashboardProperties:
    """User-facing configuration for the WebApp usage dashboard.

    Bundled into a single value so ``WebApp``'s constructor doesn't grow a
    new ``dashboard_*`` kwarg every time this construct gains a knob. Pass
    an instance via ``WebApp(..., dashboard_properties=DashboardProperties(
    ...))`` to override any of the defaults; omit it to get the standard
    dashboard.

    :param dashboard_name: Explicit dashboard name. When ``None`` (default),
        the name is derived from the app name and stage as
        ``{app_name}-{stage}-observability`` (or ``{app_name}-observability``
        when no stage is set).
    :param show_user_emails: Privacy switch for widgets that surface
        individual user identities. When ``True``, the Active users widget
        lists individual emails and their last login time, and the Most
        active users bar chart is rendered. When ``False`` (default), the
        Active users widget shows an aggregate distinct-user count and the
        Most active users slot is replaced with a placeholder explaining
        that the view is hidden and how to enable it.
    :param auth_filter_pattern: Logs Insights ``filter`` predicate
        identifying authentication events in the app's container logs.
        Defaults to ``"@message like /User authenticated/"``, which matches
        the log line emitted by the standard ``gds-idea-app-auth`` package.
        Override if an app's log format differs.
    :param extra_widgets: Additional CloudWatch widgets appended after the
        standard set. Use for app-specific metrics that don't belong in the
        shared construct. Widgets are appended in the order supplied, on new
        rows below the standard ones.
    """

    dashboard_name: str | None = None
    show_user_emails: bool = False
    auth_filter_pattern: str = DEFAULT_AUTH_FILTER_PATTERN
    extra_widgets: Sequence[cloudwatch.IWidget] | None = None


class AppUsageDashboard(Construct):
    """A CloudWatch dashboard summarising usage for a single WebApp.

    Widgets (in display order):

    * **Successful sign-ins** — ALB ``ELBAuthSuccess`` (Sum), shown as a
    single value that follows the dashboard's selected time range.
    * **Successful sign-ins over time** — the same ``ELBAuthSuccess``
    metric plotted as a line at 1-hour Sum periods so trends across the
    day or week are visible at a glance.
    * **Active users** — by default a privacy-preserving distinct-user
    count from the authentication logs. When ``show_user_emails`` is set
    on :class:`DashboardProperties`, this becomes a per-user table of
    last login (exposes individual emails — opt-in).
    * **Most active users** — when ``show_user_emails`` is ``True``, a bar
    chart of authenticated request counts per user email, sorted by
    activity. When ``False`` (default), the slot holds a placeholder
    explaining the view is hidden and how to enable it.
    * **Target response time** — ALB ``TargetResponseTime`` (Average, p95,
    p99 over 5-minute periods) on one chart, so both typical latency and
    the slow tail are visible together.
    * **Requests** — ALB ``RequestCount`` (Sum, 5-minute periods).
    * **HTTP errors** — ALB error responses split across the two axes
    CloudWatch reports them on: *who generated the response* (ALB itself
    vs. your app) and *what class of error* (4xx vs. 5xx). All four
    series are shown on one chart (Sum, 5-minute periods) so a viewer
    can distinguish at a glance between an app crash (``Target 5xx``),
    an unreachable backend (``ELB 5xx``), a rejected request from the
    app (``Target 4xx``), and a bad or unauthenticated request stopped
    at the ALB (``ELB 4xx``).

    User-tunable behaviour (dashboard name, privacy switch, log filter
    pattern, extra widgets) is grouped on :class:`DashboardProperties`;
    pass an instance via the ``properties`` parameter to override defaults.

    :param app_name: Logical app name, used to build the default dashboard
        name.
    :param load_balancer: The application's load balancer (supplied by
        WebApp).
    :param log_groups: Log group(s) carrying the auth logs (supplied by
        WebApp). Must contain at least one entry; an empty sequence raises
        ``ValueError``.
    :param stage: Optional environment (``"dev"``/``"prod"``) to
        disambiguate the default dashboard name when environments share an
        account.
    :param properties: Optional :class:`DashboardProperties` overriding any
        of the user-tunable defaults. When ``None`` (default), the standard
        dashboard is created with privacy-preserving defaults.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        load_balancer: elbv2.IApplicationLoadBalancer,
        log_groups: Sequence[logs.ILogGroup],
        stage: str | None = None,
        properties: DashboardProperties | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not log_groups:
            raise ValueError("log_groups must contain at least one log group")

        properties = properties or DashboardProperties()

        self._load_balancer = load_balancer
        self._log_group_names = [lg.log_group_name for lg in log_groups]
        self._auth_filter_pattern = properties.auth_filter_pattern
        self._show_user_emails = properties.show_user_emails

        dashboard_name = properties.dashboard_name or (
            f"{app_name}-{stage}-observability"
            if stage
            else f"{app_name}-observability"
        )
        dashboard = cloudwatch.Dashboard(
            self, "Dashboard", dashboard_name=dashboard_name
        )

        dashboard.add_widgets(
            self._signin_widget(),
            self._signin_trend_widget(),
            self._active_users_widget(),
            self._most_active_users_widget(),
            self._response_time_widget(),
            self._requests_widget(),
            self._errors_widget(),
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

    def _active_users_widget(self) -> cloudwatch.IWidget:
        # Single `if` covers both this widget and _most_active_users_widget
        # via the flag on self; no duplicate control flow.
        if self._show_user_emails:
            return cloudwatch.LogQueryWidget(
                title="Active users — last login by email",
                log_group_names=self._log_group_names,
                view=cloudwatch.LogQueryVisualizationType.TABLE,
                query_lines=[
                    "fields @timestamp, @message",
                    f"filter {self._auth_filter_pattern}",
                    "parse @message /email=(?<email>[^,]+)/",
                    "stats max(@timestamp) as last_login by email",
                    "sort last_login desc",
                ],
                width=DEFAULT_WIDGET_WIDTH,
                height=DEFAULT_WIDGET_HEIGHT,
            )
        return cloudwatch.LogQueryWidget(
            title="Active users (daily)",
            log_group_names=self._log_group_names,
            view=cloudwatch.LogQueryVisualizationType.LINE,
            query_lines=[
                "fields @timestamp, @message",
                f"filter {self._auth_filter_pattern}",
                "parse @message /email=(?<email>[^,]+)/",
                "stats count_distinct(email) as active_users by bin(1d)",
            ],
            width=DEFAULT_WIDGET_WIDTH,
            height=DEFAULT_WIDGET_HEIGHT,
        )

    def _most_active_users_widget(self) -> cloudwatch.IWidget:
        if self._show_user_emails:
            return cloudwatch.LogQueryWidget(
                title="Most active users",
                log_group_names=self._log_group_names,
                view=cloudwatch.LogQueryVisualizationType.BAR,
                query_lines=[
                    "fields @timestamp, @message",
                    f"filter {self._auth_filter_pattern}",
                    "parse @message /email=(?<email>[^,]+)/",
                    "stats count() as requests by email",
                    "sort requests desc",
                ],
                width=DEFAULT_WIDGET_WIDTH,
                height=DEFAULT_WIDGET_HEIGHT,
            )
        return cloudwatch.TextWidget(
            markdown=(
                "### Most active users\n\n"
                "_Hidden by default to avoid exposing individual user emails._"
                "\n\nEnable by setting ``show_user_emails=True`` on the "
                "``DashboardProperties`` passed to ``WebApp``."
            ),
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

    def _errors_widget(self) -> cloudwatch.IWidget:
        return cloudwatch.GraphWidget(
            title="HTTP errors",
            left=[
                self._load_balancer.metrics.http_code_target(
                    code=elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
                    period=OPERATIONAL_METRIC_PERIOD,
                    statistic="Sum",
                    label="Target 5xx (app crashes)",
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
                    label="Target 4xx (app rejected)",
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
