"""Tests for the IdeaTags dataclass."""

import dataclasses

import pytest
from aws_cdk import App, Stack, aws_s3 as s3
from aws_cdk.assertions import Template

from gds_idea_cdk_constructs import DeploymentEnvironment, IdeaTags

REPO = "gds-idea-app-example"
DEV = DeploymentEnvironment.DEVELOPMENT


def _make(**overrides) -> IdeaTags:
    """Build an IdeaTags with valid defaults, overriding any field."""
    kwargs = {"environment": DEV, "app_name": "example", "repository": REPO}
    kwargs.update(overrides)
    return IdeaTags(**kwargs)


@pytest.fixture
def app_with_bucket():
    """Fixture returning an App containing one stack with one S3 bucket."""
    app = App()
    stack = Stack(app, "TestStack")
    s3.Bucket(stack, "Bucket")
    return app


def _bucket_tags(app: App) -> dict[str, str]:
    """Synthesise the app and return the tags on the single test bucket."""
    template = Template.from_stack(app.node.find_child("TestStack"))
    buckets = template.find_resources("AWS::S3::Bucket")
    assert len(buckets) == 1
    tags = next(iter(buckets.values())).get("Properties", {}).get("Tags", [])
    return {t["Key"]: t["Value"] for t in tags}


# -- tags property --


def test_idea_tags_resolves_all_tags():
    """Test that the resolved tags contain every standard key."""
    tags = _make(owners=["Alice Example"]).tags

    assert tags == {
        "Environment": "development",
        "ManagedBy": "cdk",
        "Repository": REPO,
        "AppName": "example",
        "Owner": "Alice Example",
    }


def test_idea_tags_uses_lowercase_environment():
    """Test that the environment tag is the lowercase environment name."""
    tags = _make(environment=DeploymentEnvironment.PRODUCTION).tags

    assert tags["Environment"] == "production"


def test_idea_tags_omits_owner_when_no_owners():
    """Test that no Owner tag is produced when owners is empty."""
    assert "Owner" not in _make().tags


def test_idea_tags_joins_multiple_owners_with_plus():
    """Test that a list of owners is joined with a plus sign."""
    tags = _make(owners=["Alice Example", "Bob Example"]).tags

    assert tags["Owner"] == "Alice Example+Bob Example"


def test_idea_tags_includes_extra_tags():
    """Test that extra tags are included alongside the standard tags."""
    tags = _make(extra_tags={"Name": "Example App"}).tags

    assert tags["Name"] == "Example App"
    assert tags["AppName"] == "example"


def test_idea_tags_is_frozen():
    """Test that an IdeaTags instance cannot be mutated."""
    idea_tags = _make()

    with pytest.raises(dataclasses.FrozenInstanceError):
        idea_tags.app_name = "other"  # type: ignore[misc]


def test_idea_tags_can_be_copied_with_replace():
    """Test that dataclasses.replace produces a validated modified copy."""
    other = dataclasses.replace(_make(owners=["A", "B"]), app_name="other")

    assert other.tags["AppName"] == "other"
    assert other.tags["Owner"] == "A+B"


# -- validation --


@pytest.mark.parametrize(
    "repository",
    [
        "TBA",
        "tba",
        "",
        "  ",
        "co-cddo/gds-idea-app-example",
        "https://github.com/co-cddo/gds-idea-app-example",
        "gds-idea-app-example.git",
        "git@github.com:co-cddo/gds-idea-app-example.git",
        "gds idea app",
    ],
)
def test_idea_tags_rejects_bad_repository(repository):
    """Test that placeholder or badly formatted repositories are rejected."""
    with pytest.raises(ValueError, match=r"repository"):
        _make(repository=repository)


@pytest.mark.parametrize(
    "owners",
    [["Alice, Bob"], ["Alice", "Bob, Carol"], ["TBA"], ["Alice", "todo"], [""]],
)
def test_idea_tags_rejects_bad_owners(owners):
    """Test that owners with commas, placeholders or no value are rejected."""
    with pytest.raises(ValueError, match=r"owner"):
        _make(owners=owners)


def test_idea_tags_rejects_empty_app_name():
    """Test that an empty app name is rejected."""
    with pytest.raises(ValueError, match=r"app_name"):
        _make(app_name="")


@pytest.mark.parametrize(
    "key", ["Environment", "ManagedBy", "Repository", "AppName", "Owner"]
)
def test_idea_tags_rejects_extra_tag_overriding_standard(key):
    """Test that extra tags cannot override the standard tag keys."""
    with pytest.raises(ValueError, match=r"cannot override"):
        _make(extra_tags={key: "x"})


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("Name", "a,b", r"commas"),
        ("Name", "", r"must not be empty"),
        ("Name", "TBA", r"placeholder"),
    ],
)
def test_idea_tags_rejects_bad_extra_tag_values(key, value, match):
    """Test that invalid extra tag values are rejected."""
    with pytest.raises(ValueError, match=match):
        _make(extra_tags={key: value})


# -- apply --


def test_idea_tags_apply_tags_resources(app_with_bucket):
    """Test that the tags reach resources under the app."""
    idea_tags = _make(owners=["Alice Example"])

    idea_tags.apply(app_with_bucket)

    assert _bucket_tags(app_with_bucket) == idea_tags.tags


def test_idea_tags_apply_tags_the_stack(app_with_bucket):
    """Test that the CloudFormation stack itself is tagged."""
    _make().apply(app_with_bucket)

    artifact = app_with_bucket.synth().get_stack_by_name("TestStack")
    assert artifact.tags["AppName"] == "example"
    assert artifact.tags["ManagedBy"] == "cdk"


def test_idea_tags_can_be_applied_to_a_single_stack():
    """Test that applying to a stack does not tag other stacks in the app."""
    app = App()
    tagged = Stack(app, "Tagged")
    other = Stack(app, "Other")
    s3.Bucket(tagged, "Bucket")
    s3.Bucket(other, "Bucket")

    _make().apply(tagged)

    assembly = app.synth()
    assert assembly.get_stack_by_name("Tagged").tags["AppName"] == "example"
    assert "AppName" not in assembly.get_stack_by_name("Other").tags


def test_idea_tags_apply_to_app_tags_every_stack():
    """Test that applying to the app tags all stacks and their resources."""
    app = App()
    stacks = [Stack(app, name) for name in ("One", "Two", "Three")]
    for stack in stacks:
        s3.Bucket(stack, "Bucket")
    idea_tags = _make(owners=["Alice Example"])

    idea_tags.apply(app)

    assembly = app.synth()
    for stack in stacks:
        assert assembly.get_stack_by_name(stack.stack_name).tags == idea_tags.tags
        template = Template.from_stack(stack)
        bucket = next(iter(template.find_resources("AWS::S3::Bucket").values()))
        bucket_tags = {t["Key"]: t["Value"] for t in bucket["Properties"]["Tags"]}
        assert bucket_tags == idea_tags.tags
