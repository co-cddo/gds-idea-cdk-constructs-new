"""Standard resource tagging for GDS IDEA CDK apps.

Every app deployed from this library should carry the same set of tags so that
resources can be traced back to an environment, application, repository and
(optionally) owners. Build an :class:`IdeaTags` in ``app.py`` and apply it to
the app:

Example:
    ```python
    IdeaTags(
        environment=dep_config.environment,
        app_name=app_config.app_name,
        repository="gds-idea-app-example",
        owners=["Alice Example", "Bob Example"],
    ).apply(app)
    ```
"""

import re
from dataclasses import dataclass, field

from aws_cdk import Tags
from constructs import Construct

from .config import DeploymentEnvironment

__all__ = ["OWNER_SEPARATOR", "IdeaTags"]

OWNER_SEPARATOR = "+"
"""Separator used to join multiple owners into a single ``Owner`` tag value."""

_RESERVED_KEYS = frozenset(
    {"Environment", "ManagedBy", "Repository", "AppName", "Owner"}
)

_PLACEHOLDERS = frozenset({"tba", "tbc", "todo", "changeme", "xxx"})

# Bare repository name, e.g. "gds-idea-app-example" (no org prefix). GitHub is
# case-insensitive so case is not enforced. URLs, "org/repo" and ".git" suffixes
# are rejected.
_REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")

# Characters AWS allows in tag values: Unicode letters, digits, whitespace and
# ``_ . : / = + - @``. Notably this excludes commas.
_TAG_VALUE_PATTERN = re.compile(r"[\w\s.:/=+@-]+")


def _check_value(name: str, value: str) -> None:
    """Raise ``ValueError`` if ``value`` is not a usable tag value.

    Args:
        name: Human readable name of the value, used in error messages.
        value: The candidate tag value.

    Raises:
        ValueError: If the value is empty, a placeholder such as ``TBA``, or
            contains characters AWS does not allow in tag values (e.g. commas).
    """
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
    if value.strip().lower() in _PLACEHOLDERS:
        raise ValueError(f"{name} is still a placeholder: {value!r}")
    if not _TAG_VALUE_PATTERN.fullmatch(value):
        raise ValueError(
            f"{name} contains characters not allowed in AWS tag values "
            f"(commas are not allowed): {value!r}"
        )


@dataclass(frozen=True)
class IdeaTags:
    """The standard set of tags for a GDS IDEA CDK app.

    Validation happens at construction, so an invalid value fails where it is
    defined rather than at synth time. Call :meth:`apply` to add the tags to a
    construct; use :attr:`tags` to inspect the resolved key/value pairs.

    The following tags are produced:

    - ``Environment``: lowercase environment name (e.g. ``development``).
    - ``ManagedBy``: always ``cdk``.
    - ``Repository``: the GitHub repository name, without the org.
    - ``AppName``: the application name.
    - ``Owner``: only when ``owners`` is not empty. Owners are joined with ``+``.
    - Any ``extra_tags``.

    Attributes:
        environment: The deployment environment. Its lowercase name is used as
            the ``Environment`` tag value.
        app_name: The application name.
        repository: The GitHub repository name without the org, e.g.
            ``gds-idea-app-example``.
        owners: Optional list of owners, one entry per owner. Use names, not
            email addresses. Commas are not allowed in AWS tag values, so do
            not put several owners in one string.
        extra_tags: Optional additional tags. Cannot override the standard tag
            keys.

    Raises:
        ValueError: On construction, if ``repository`` is not a bare repo name,
            if any value is empty, a placeholder such as ``TBA`` or contains
            characters AWS does not allow, or if ``extra_tags`` overrides a
            standard key.
    """

    environment: DeploymentEnvironment
    app_name: str
    repository: str
    owners: list[str] = field(default_factory=list)
    extra_tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate all fields."""
        _check_value("app_name", self.app_name)
        _check_value("repository", self.repository)
        if self.repository.endswith(".git") or not _REPOSITORY_PATTERN.fullmatch(
            self.repository
        ):
            raise ValueError(
                "repository must be the bare repository name without the org or "
                f"a .git suffix, e.g. 'gds-idea-app-example', got {self.repository!r}"
            )
        for owner in self.owners:
            _check_value("owner", owner)
        for key, value in self.extra_tags.items():
            if key in _RESERVED_KEYS:
                raise ValueError(
                    f"extra_tags cannot override the standard tag {key!r}; "
                    "pass it as a named argument instead"
                )
            _check_value(f"extra_tags[{key!r}]", value)

    @property
    def tags(self) -> dict[str, str]:
        """The resolved tag key/value pairs."""
        tags = {
            "Environment": self.environment.friendly_name,
            "ManagedBy": "cdk",
            "Repository": self.repository,
            "AppName": self.app_name,
        }
        if self.owners:
            tags["Owner"] = OWNER_SEPARATOR.join(o.strip() for o in self.owners)
        tags.update(self.extra_tags)
        return tags

    def apply(self, scope: Construct) -> None:
        """Add the tags to every taggable resource under ``scope``.

        Tags are applied with ``Tags.of(scope)``, so they cascade to every stack
        and resource in the construct tree. Call it on the ``App`` to tag
        everything.

        Args:
            scope: The construct to tag, normally the CDK ``App``.
        """
        for key, value in self.tags.items():
            Tags.of(scope).add(key, value)
            # Also tag the CloudFormation stack itself explicitly. The first
            # call already reaches stacks on the CDK versions we have tested,
            # so this is belt and braces.
            Tags.of(scope).add(key, value, include_resource_types=["aws:cdk:stack"])
