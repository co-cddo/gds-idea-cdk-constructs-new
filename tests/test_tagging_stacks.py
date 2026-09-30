"""Synth tests checking IdeaTags reach the real stacks this library builds."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment
from aws_cdk.assertions import Template

from gds_idea_cdk_constructs import AppConfig, DeploymentConfig, IdeaTags
from gds_idea_cdk_constructs.agent_core.props import AgentCoreProperties
from gds_idea_cdk_constructs.agent_core.stack import AgentCore
from gds_idea_cdk_constructs.config import DeploymentEnvironment
from gds_idea_cdk_constructs.knowledge_base.stack import KnowledgeBase
from gds_idea_cdk_constructs.static_site import StaticSite, StaticSiteProperties
from gds_idea_cdk_constructs.web_app import AuthType, WebApp
from tests.conftest import TEST_CONFIG
from tests.web_app.test_stack import _build_cdk_context

# Resource types that must carry tags in each stack. Not exhaustive: it is the
# set of taggable resources we expect the stack to contain.
WEB_APP_TAGGED_TYPES = [
    "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "AWS::ElasticLoadBalancingV2::TargetGroup",
    "AWS::ECS::Service",
    "AWS::ECS::TaskDefinition",
    "AWS::IAM::Role",
    "AWS::Lambda::Function",
    "AWS::Route53::HostedZone",
]
STATIC_SITE_TAGGED_TYPES = [
    "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "AWS::S3::Bucket",
    "AWS::IAM::Role",
    "AWS::Lambda::Function",
    "AWS::Route53::HostedZone",
]
KNOWLEDGE_BASE_TAGGED_TYPES = ["AWS::S3::Bucket", "AWS::IAM::Role"]
AGENT_CORE_TAGGED_TYPES = ["AWS::IAM::Role"]


@pytest.fixture
def idea_tags():
    """Fixture for a valid IdeaTags."""
    return IdeaTags(
        environment=DeploymentEnvironment.TESTING,
        app_name="testapp",
        repository="gds-idea-app-example",
        owners=["Alice Example", "Bob Example"],
    )


@pytest.fixture
def deployment_config():
    """Fixture for a TESTING DeploymentConfig."""
    env = CdkEnvironment(account="testing", region="eu-west-2")
    return DeploymentConfig.from_dict(env, TEST_CONFIG)


@pytest.fixture
def app_config():
    """Fixture for AppConfig."""
    return AppConfig(app_name="testapp", framework="streamlit")


@pytest.fixture
def cdk_app(idea_tags):
    """Fixture for a tagged App with context for resource lookups."""
    app = App(
        context=_build_cdk_context(
            "testing",
            "eu-west-2",
            TEST_CONFIG["vpc_id"],
            TEST_CONFIG["domain_name"],
        )
    )
    idea_tags.apply(app)
    return app


def _tag_dict(tags) -> dict[str, str]:
    """Convert CloudFormation tag lists or dicts to a plain dict."""
    if isinstance(tags, dict):
        return tags
    return {t["Key"]: t["Value"] for t in tags}


def _resource_tags(properties: dict) -> dict[str, str] | None:
    """Return a resource's tags, whichever property CloudFormation calls them."""
    for name in ("Tags", "HostedZoneTags"):
        if name in properties:
            return _tag_dict(properties[name])
    return None


def _assert_stack_tagged(app, stack, expected, required_types):
    """Assert the stack, and its taggable resources, carry the expected tags."""
    artifact = app.synth().get_stack_by_name(stack.stack_name)
    assert artifact.tags == expected

    resources = Template.from_stack(stack).to_json()["Resources"]
    seen_types = set()
    for logical_id, resource in resources.items():
        tags = _resource_tags(resource.get("Properties", {}))
        if tags is None:
            continue
        seen_types.add(resource["Type"])
        # Auto-generated resources may add their own tags (e.g. Name); the
        # standard tags must still all be present and unchanged.
        missing = {k: v for k, v in expected.items() if tags.get(k) != v}
        assert not missing, f"{logical_id} ({resource['Type']}) missing {missing}"

    assert set(required_types) <= seen_types, (
        f"expected tagged resources of types {set(required_types) - seen_types}"
    )


def test_web_app_stack_is_tagged(cdk_app, deployment_config, app_config, idea_tags):
    """Test that a WebApp stack and its resources carry the tags."""
    stack = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
    )

    _assert_stack_tagged(cdk_app, stack, idea_tags.tags, WEB_APP_TAGGED_TYPES)


def test_static_site_stack_is_tagged(cdk_app, deployment_config, app_config, idea_tags):
    """Test that a StaticSite stack and its resources carry the tags."""
    stack = StaticSite(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures/static_site",
        dockerfile_path="Dockerfile",
        static_site_props=StaticSiteProperties(build_command="npx @11ty/eleventy"),
    )

    _assert_stack_tagged(cdk_app, stack, idea_tags.tags, STATIC_SITE_TAGGED_TYPES)


def test_knowledge_base_stack_is_tagged(
    cdk_app, deployment_config, app_config, idea_tags
):
    """Test that a KnowledgeBase stack and its resources carry the tags."""
    stack = KnowledgeBase(
        cdk_app, deployment_config=deployment_config, app_config=app_config
    )

    _assert_stack_tagged(cdk_app, stack, idea_tags.tags, KNOWLEDGE_BASE_TAGGED_TYPES)


def test_agent_core_stack_is_tagged(cdk_app, idea_tags):
    """Test that an AgentCore stack and its resources carry the tags."""
    stack = AgentCore(
        cdk_app,
        "TestStack",
        props=AgentCoreProperties(runtime_name="test_agent"),
        env=CdkEnvironment(account="123456789012", region="eu-west-2"),
    )

    _assert_stack_tagged(cdk_app, stack, idea_tags.tags, AGENT_CORE_TAGGED_TYPES)


def test_all_stacks_in_one_app_are_tagged(
    cdk_app, deployment_config, app_config, idea_tags
):
    """Test that several different stacks in one app all carry the tags."""
    web = WebApp(
        cdk_app,
        deployment_config,
        app_config,
        authentication=AuthType.NONE,
        docker_context_path="tests/fixtures",
        dockerfile_path="Dockerfile",
    )
    kb = KnowledgeBase(
        cdk_app, deployment_config=deployment_config, app_config=app_config
    )

    assembly = cdk_app.synth()
    for stack in (web, kb):
        assert assembly.get_stack_by_name(stack.stack_name).tags == idea_tags.tags
