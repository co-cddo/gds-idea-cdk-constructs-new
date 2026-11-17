from dataclasses import dataclass, field

from aws_cdk import Duration


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
        if self.max_healthy_percent <= self.min_healthy_percent:
            raise ValueError(
                "max_healthy_percent must be greater than min_healthy_percent "
                "so ECS can start a replacement task before draining the old one "
                f"(got max_healthy_percent={self.max_healthy_percent}, "
                f"min_healthy_percent={self.min_healthy_percent})."
            )


@dataclass
class RefreshSchedule:
    """Schedule for automatically restarting a WebApp's ECS service.

    Forcing a new deployment restarts the container.
    Provide exactly one of ``rate`` or ``cron``.

    Args:
        rate: Fixed interval between restarts, e.g. ``Duration.hours(1)``.
        cron: Cron fields forwarded to ``ScheduleExpression.cron``, e.g.
            ``{"hour": "6", "minute": "0"}`` for a daily 06:00 UTC restart.

    Raises:
        ValueError: If neither or both of ``rate`` and ``cron`` are set.
    """

    rate: Duration | None = None
    cron: dict[str, str] | None = field(default=None)

    def __post_init__(self) -> None:
        if bool(self.rate) == bool(self.cron):
            raise ValueError(
                "RefreshSchedule requires exactly one of 'rate' or 'cron'."
            )
