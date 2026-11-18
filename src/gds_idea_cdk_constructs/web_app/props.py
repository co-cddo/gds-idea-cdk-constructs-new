import math
from dataclasses import dataclass, field

from aws_cdk import Duration, TimeZone


@dataclass
class WebAppContainerProperties:
    """A structured class for default WebApp Container settings."""

    # ECS Task settings
    cpu: int = 256
    """The number of CPU units to reserve for the container (256 = 0.25 vCPU)."""

    memory_limit_mib: int = 512
    """The amount of memory (in MiB) to reserve for the container."""

    desired_count: int = 1
    """The desired number of tasks for the service."""

    container_port: int = 8080
    """The port number on the container that is bound to the host port."""

    environment_variables: dict[str, str] = field(default_factory=dict)
    """A dictionary of environment variables to pass to the container."""

    # ALB Health Check settings
    health_check_path: str | None = None
    """The destination for the health check request."""

    health_check_grace_period: int = 60
    """Health check grace period in seconds"""

    min_healthy_percent: int = 50
    """Minimum healthy percentage """

    max_healthy_percent: int = 200
    """Maximum healthy percentage.
    Set to 200 to let ECS start a replacement task before draining the old one"""

    def __post_init__(self) -> None:
        validate_rollout(
            self.desired_count, self.min_healthy_percent, self.max_healthy_percent
        )


def validate_rollout(
    desired_count: int, min_healthy_percent: int, max_healthy_percent: int
) -> None:
    """Ensure a rolling deployment has room to start a replacement task.

    ECS rounds the healthy-task floor up and the ceiling down to whole tasks, so
    a valid-looking percentage pair can still leave no room for a replacement
    (e.g. desired_count=1, min=100, max=150 -> must keep 1 task, may run 1).

    Args:
        desired_count: Desired number of running tasks.
        min_healthy_percent: Minimum healthy percentage during a deployment.
        max_healthy_percent: Maximum percentage of tasks during a deployment.

    Raises:
        ValueError: If the configuration leaves no room for a replacement task.
    """
    min_tasks = math.ceil(desired_count * min_healthy_percent / 100)
    max_tasks = math.floor(desired_count * max_healthy_percent / 100)
    if max_tasks <= min_tasks:
        raise ValueError(
            f"With desired_count={desired_count}, ECS must keep {min_tasks} task(s) "
            f"running but may run at most {max_tasks}; no room for a replacement. "
            "Raise max_healthy_percent."
        )


@dataclass
class CronSchedule:
    """Calendar fields for a cron-based ``RefreshSchedule``.

    ``minute`` and ``hour`` are required so a partial spec can't silently expand
    to an unintended schedule (CDK fills omitted fields with ``*``, so
    ``{"hour": "6"}`` would mean *every minute* from 06:00–06:59).

    AWS cron requires exactly one of day-of-month or day-of-week to be unset, so
    provide at most one of ``day`` / ``week_day``; the other is filled in for you.

    Args:
        minute: Minute(s) to fire, e.g. ``"0"``.
        hour: Hour(s) to fire, 24h, e.g. ``"6"``.
        day: Day-of-month. Mutually exclusive with ``week_day``.
        month: Month. Defaults to every month.
        week_day: Day-of-week, e.g. ``"MON"``. Mutually exclusive with ``day``.
        year: Year. Defaults to every year.
        time_zone: Timezone the fields are read in. Defaults to Europe/London so
            a "06:00" restart stays at 06:00 local across DST.

    Raises:
        ValueError: If both ``day`` and ``week_day`` are set.
    """

    minute: str
    hour: str
    day: str | None = None
    month: str = "*"
    week_day: str | None = None
    year: str = "*"
    time_zone: TimeZone | None = None

    def __post_init__(self) -> None:
        if self.day is not None and self.week_day is not None:
            raise ValueError("CronSchedule accepts at most one of 'day' or 'week_day'.")
        if self.time_zone is None:
            self.time_zone = TimeZone.EUROPE_LONDON

    def to_cron_kwargs(self) -> dict:
        """Kwargs for ``ScheduleExpression.cron``, omitting the unset
        day/week_day field so AWS cron's one-or-the-other rule holds."""
        kwargs: dict = {
            "minute": self.minute,
            "hour": self.hour,
            "month": self.month,
            "year": self.year,
            "time_zone": self.time_zone,
        }
        if self.day is not None:
            kwargs["day"] = self.day
        if self.week_day is not None:
            kwargs["week_day"] = self.week_day
        return kwargs


@dataclass
class RefreshSchedule:
    """Schedule for automatically restarting a WebApp's ECS service.

    Forcing a new deployment restarts the container so it reloads data read at
    startup. Provide exactly one of ``rate`` or ``cron`` — or use the
    :meth:`every` / :meth:`daily_at` constructors.

    Args:
        rate: Fixed interval between restarts. Must be a whole number of minutes
            (>= 1), e.g. ``Duration.hours(6)``.
        cron: A :class:`CronSchedule` for calendar-based restarts.
        retry_attempts: Times EventBridge Scheduler retries a failed restart.
            Defaults to 2.
        max_event_age: Maximum age of a restart event before it is dropped
            instead of retried. Defaults to 60 minutes.

    Raises:
        ValueError: If neither or both of ``rate`` / ``cron`` are set, or if
            ``rate`` is not a whole number of minutes >= 1.
    """

    rate: Duration | None = None
    cron: CronSchedule | None = None
    retry_attempts: int = 2
    max_event_age: Duration = field(default_factory=lambda: Duration.minutes(60))

    def __post_init__(self) -> None:
        if bool(self.rate) == bool(self.cron):
            raise ValueError(
                "RefreshSchedule requires exactly one of 'rate' or 'cron'."
            )
        if self.rate is not None:
            minutes = self.rate.to_minutes(integral=False)
            if minutes < 1 or minutes != int(minutes):
                raise ValueError(
                    "RefreshSchedule 'rate' must be a whole number of minutes "
                    "(at least 1 minute)."
                )

    @classmethod
    def every(cls, interval: Duration) -> "RefreshSchedule":
        """Restart on a fixed interval, e.g. ``RefreshSchedule.every(Duration.hours(6))``."""
        return cls(rate=interval)

    @classmethod
    def daily_at(
        cls, hour: int, minute: int = 0, time_zone: TimeZone | None = None
    ) -> "RefreshSchedule":
        """Restart once a day at ``hour:minute`` (Europe/London unless overridden)."""
        return cls(
            cron=CronSchedule(minute=str(minute), hour=str(hour), time_zone=time_zone)
        )
