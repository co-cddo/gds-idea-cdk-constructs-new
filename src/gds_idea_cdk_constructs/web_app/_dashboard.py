"""Internal: CloudWatch usage dashboard composed by the WebApp construct.

Private to ``web_app``. App authors do not instantiate this directly — ``WebApp``
creates it (passing its own load balancer and log group) when
``enable_usage_dashboard`` is set. It reads the app's own ALB metrics and Cognito
authentication logs in the same account/region, so no cross-account (OAM)
configuration is involved.
"""

from __future__ import annotations

from collections.abc import Sequence

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
)
from constructs import Construct


class AppUsageDashboard(Construct):
    """A CloudWatch dashboard summarising usage for a single WebApp.

    Widgets (in display order):

    * **Successful sign-ins** — ALB ``ELBAuthSuccess`` (Sum), shown as a single
    value that follows the dashboard's selected time range. Reflects the
    number of successful Cognito authentications handled by the load
    balancer.
    * **Successful sign-ins over time** — the same ``ELBAuthSuccess`` metric
    as above, plotted as a line at 1-hour ``Sum`` periods so trends across
    the day or week are visible at a glance.
    * **Active users** — by default a privacy-preserving distinct-user count
    from the authentication logs. When ``show_user_emails`` is ``True`` this
    becomes a per-user table of last login (exposes individual emails —
    opt-in).
    * **Most active users** — when ``show_user_emails`` is ``True``, a bar
    chart of authenticated request counts per user email over the
    dashboard's selected time range, sorted by activity. When ``False``
    (default), the widget is replaced with a placeholder explaining that
    the view is hidden to avoid exposing individual emails and how to
    enable it.
    * **Target response time** — ALB ``TargetResponseTime`` (Average, p95, p99
    over 5-minute periods) on one chart, so both typical latency and the
    slow tail are visible together.
    * **Requests** — ALB ``RequestCount`` (Sum, 5-minute periods); dimensions
    are derived from the load balancer object.
    * **HTTP errors** — ALB error responses split across the two axes
    CloudWatch reports them on: *who generated the response* (ALB itself
    vs. your app) and *what class of error* (4xx vs. 5xx). All four series
    are shown on one chart (Sum, 5-minute periods) so a viewer can
    distinguish at a glance between an app crash (``Target 5xx``), an
    unreachable backend (``ELB 5xx``), a rejected request from the app
    (``Target 4xx``), and a bad or unauthenticated request stopped at the
    ALB (``ELB 4xx``).

    :param app_name: Logical app name, used to build the dashboard name.
    :param load_balancer: The application's load balancer (supplied by WebApp).
    :param log_groups: Log group(s) carrying the auth logs (supplied by WebApp).
    :param stage: Optional environment (``"dev"``/``"prod"``) to disambiguate the
        dashboard name when environments share an account.
    :param dashboard_name: Explicit name; overrides the ``app_name``/``stage`` default.
    :param show_user_emails: When ``True``, the Active users widget lists
        individual user emails and their last login, and the Most active
        users bar chart is rendered. When ``False`` (default), Active users
        shows an aggregate distinct-user count and Most active users is
        replaced with a placeholder message.
    :param auth_filter_pattern: Logs Insights ``filter`` predicate identifying
        authentication events. Override if an app's log format differs.
    :param extra_widgets: Additional widgets appended after the standard
        Successful sign-ins, Successful sign-ins over time, Active users,
        Most active users, Target response time, Requests and HTTP errors
        widgets. Pass via ``WebApp``'s ``dashboard_extra_widgets`` parameter —
        no changes to this construct required.
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
        dashboard_name: str | None = None,
        show_user_emails: bool = False,
        auth_filter_pattern: str = "@message like /User authenticated/",
        extra_widgets: Sequence[cloudwatch.IWidget] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not log_groups:
            raise ValueError("log_groups must contain at least one log group")

        if dashboard_name is None:
            dashboard_name = (
                f"{app_name}-{stage}-observability"
                if stage
                else f"{app_name}-observability"
            )

        dashboard = cloudwatch.Dashboard(
            self, "Dashboard", dashboard_name=dashboard_name
        )

        requests_widget = cloudwatch.GraphWidget(
            title="Requests",
            left=[
                load_balancer.metrics.request_count(
                    period=Duration.minutes(5),
                    statistic="Sum",
                )
            ],
            width=12,
            height=6,
        )

        log_group_names = [lg.log_group_name for lg in log_groups]

        if show_user_emails:
            active_users_widget = cloudwatch.LogQueryWidget(
                title="Active users — last login by email",
                log_group_names=log_group_names,
                view=cloudwatch.LogQueryVisualizationType.TABLE,
                query_lines=[
                    "fields @timestamp, @message",
                    f"filter {auth_filter_pattern}",
                    "parse @message /email=(?<email>[^,]+)/",
                    "stats max(@timestamp) as last_login by email",
                    "sort last_login desc",
                ],
                width=12,
                height=6,
            )
        else:
            active_users_widget = cloudwatch.LogQueryWidget(
                title="Active users (daily)",
                log_group_names=log_group_names,
                view=cloudwatch.LogQueryVisualizationType.LINE,
                query_lines=[
                    "fields @timestamp, @message",
                    f"filter {auth_filter_pattern}",
                    "parse @message /email=(?<email>[^,]+)/",
                    "stats count_distinct(email) as active_users by bin(1d)",
                ],
                width=12,
                height=6,
            )

        if show_user_emails:
            most_active_users_widget = cloudwatch.LogQueryWidget(
                title="Most active users",
                log_group_names=log_group_names,
                view=cloudwatch.LogQueryVisualizationType.BAR,
                query_lines=[
                    "fields @timestamp, @message",
                    f"filter {auth_filter_pattern}",
                    "parse @message /email=(?<email>[^,]+)/",
                    "stats count() as requests by email",
                    "sort requests desc",
                ],
                width=12,
                height=6,
            )
        else:
            most_active_users_widget = cloudwatch.TextWidget(
                markdown=(
                    "### Most active users\n\n"
                    "_Hidden by default to avoid exposing individual user emails._\n\n"
                    "Enable by setting `dashboard_show_user_emails=True` on the "
                    "`WebApp` construct."
                ),
                width=12,
                height=6,
            )

        signin_widget = cloudwatch.SingleValueWidget(
            title="Successful sign-ins",
            metrics=[
                load_balancer.metrics.custom(
                    "ELBAuthSuccess",
                    statistic="Sum",
                    period=Duration.days(7),
                )
            ],
            width=12,
            height=6,
            set_period_to_time_range=True,
        )

        signin_trend_widget = cloudwatch.GraphWidget(
            title="Successful sign-ins over time",
            left=[
                load_balancer.metrics.custom(
                    "ELBAuthSuccess",
                    statistic="Sum",
                    period=Duration.hours(1),
                    label="Sign-ins per hour",
                )
            ],
            width=12,
            height=6,
        )

        response_time_widget = cloudwatch.GraphWidget(
            title="Target response time",
            left=[
                load_balancer.metrics.target_response_time(
                    period=Duration.minutes(5),
                    statistic="Average",
                    label="avg",
                ),
                load_balancer.metrics.target_response_time(
                    period=Duration.minutes(5),
                    statistic="p95",
                    label="p95",
                ),
                load_balancer.metrics.target_response_time(
                    period=Duration.minutes(5),
                    statistic="p99",
                    label="p99",
                ),
            ],
            left_y_axis=cloudwatch.YAxisProps(label="seconds", show_units=False),
            width=12,
            height=6,
        )

        errors_widget = cloudwatch.GraphWidget(
            title="HTTP errors",
            left=[
                load_balancer.metrics.http_code_target(
                    code=elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
                    period=Duration.minutes(5),
                    statistic="Sum",
                    label="Target 5xx (app crashes)",
                ),
                load_balancer.metrics.http_code_elb(
                    code=elbv2.HttpCodeElb.ELB_5XX_COUNT,
                    period=Duration.minutes(5),
                    statistic="Sum",
                    label="ELB 5xx (unreachable)",
                ),
                load_balancer.metrics.http_code_target(
                    code=elbv2.HttpCodeTarget.TARGET_4XX_COUNT,
                    period=Duration.minutes(5),
                    statistic="Sum",
                    label="Target 4xx (app rejected)",
                ),
                load_balancer.metrics.http_code_elb(
                    code=elbv2.HttpCodeElb.ELB_4XX_COUNT,
                    period=Duration.minutes(5),
                    statistic="Sum",
                    label="ELB 4xx (bad request / auth fail)",
                ),
            ],
            width=24,
            height=6,
        )

        dashboard.add_widgets(
            signin_widget,
            signin_trend_widget,
            active_users_widget,
            most_active_users_widget,
            response_time_widget,
            requests_widget,
            errors_widget,
        )
        if extra_widgets:
            dashboard.add_widgets(*extra_widgets)
        self.dashboard = dashboard
