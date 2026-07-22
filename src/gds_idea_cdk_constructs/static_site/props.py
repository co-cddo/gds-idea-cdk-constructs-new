from dataclasses import dataclass, field

from aws_cdk import aws_events as events


@dataclass
class StaticSiteProperties:
    """Configuration properties for a StaticSite stack.

    Controls build Lambda behaviour, schedule, and serve Lambda settings.
    """

    # Build configuration
    build_command: str
    """The shell command to run inside the build container (e.g. 'npx eleventy')."""

    build_output_dir: str = "/tmp/_site"
    """Directory containing built output. Must be under /tmp/ since Lambda
    filesystem is read-only. Defaults to '/tmp/_site'."""

    build_schedule: events.Schedule | None = None
    """EventBridge schedule for periodic rebuilds. Use events.Schedule.rate()
    or events.Schedule.cron(). If None, no schedule is created.

    Examples:
        events.Schedule.rate(Duration.hours(6))
        events.Schedule.cron(hour="6", minute="0")
    """

    build_timeout: int = 300
    """Lambda timeout in seconds for the build function (max 900)."""

    build_memory_size: int = 1024
    """Memory in MB allocated to the build Lambda."""

    build_environment_variables: dict[str, str] = field(default_factory=dict)
    """Additional environment variables passed to the build Lambda."""

    # Clean build configuration
    clean_on_build: bool = True
    """Remove stale files from S3 after build. Files uploaded by the current
    build are kept; all others are deleted unless protected by keep_prefixes.
    Set to False if external processes write to the same bucket."""

    keep_prefixes: list[str] = field(default_factory=list)
    """S3 key prefixes to never delete during cleanup. Useful when external
    processes (ETL, data pipelines) write to the same bucket under known
    prefixes. Only relevant when clean_on_build=True.
    Example: ['data/', 'uploads/']"""

    # Serve configuration
    serve_memory_size: int = 256
    """Memory in MB allocated to the serve Lambda."""

    index_document: str = "index.html"
    """Default document served for directory requests
    (e.g. '/' serves '/index.html')."""

    error_document: str | None = "404.html"
    """Document served for 404 responses. Set to None to return a generic error."""
