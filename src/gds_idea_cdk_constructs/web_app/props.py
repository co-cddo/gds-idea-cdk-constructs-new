from dataclasses import dataclass, field


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
    """Mininum healthy percentage """
