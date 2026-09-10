"""Unit tests for Secrets Manager IAM grant helpers."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment, Stack, aws_iam as iam
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.permissions.secrets import grant_secret_access


@pytest.fixture
def cdk_app():
    """Fixture for CDK App."""
    return App()


@pytest.fixture
def test_stack(cdk_app):
    """Fixture for a test CDK Stack."""
    env = CdkEnvironment(account="992382722318", region="eu-west-2")
    return Stack(cdk_app, "TestStack", env=env)


@pytest.fixture
def grantee(test_stack):
    """Fixture for an IAM Role to grant permissions to."""
    return iam.Role(
        test_stack,
        "TestRole",
        assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    )


def test_grant_secret_access_default(test_stack, grantee):
    """Test the default secret access statement uses a wildcard suffix."""
    grant_secret_access(grantee, test_stack, "my-app/access")
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "secretsmanager:GetSecretValue",
                                "Effect": "Allow",
                                "Resource": {
                                    "Fn::Join": Match.any_value(),
                                },
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_secret_access_resource_includes_prefix(test_stack, grantee):
    """Test that the resolved ARN includes the secret name prefix."""
    grant_secret_access(grantee, test_stack, "my-app/access")
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statement = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ][0]
    resource_arn_join = statement["Resource"]["Fn::Join"][1]

    assert any(
        isinstance(part, str) and "secret:my-app/access" in part
        for part in resource_arn_join
    )


def test_grant_secret_access_with_sid(test_stack, grantee):
    """Test that a provided sid is included on the statement."""
    grant_secret_access(grantee, test_stack, "my-app/access", sid="MySecretSid")
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Sid": "MySecretSid"})]
                )
            }
        },
    )


def test_grant_secret_access_omits_sid_by_default(test_stack, grantee):
    """Test that no Sid is set when not provided."""
    grant_secret_access(grantee, test_stack, "my-app/access")
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statement = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ][0]

    assert "Sid" not in statement


def test_grant_secret_access_callable_multiple_times_without_clash(test_stack, grantee):
    """Test that calling twice on the same role does not clash (no fixed Sid)."""
    grant_secret_access(grantee, test_stack, "my-app/access")
    grant_secret_access(grantee, test_stack, "other-app/access")
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like({"Action": "secretsmanager:GetSecretValue"}),
                        Match.object_like({"Action": "secretsmanager:GetSecretValue"}),
                    ]
                )
            }
        },
    )
