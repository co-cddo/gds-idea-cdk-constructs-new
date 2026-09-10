"""Unit tests for Bedrock model invocation IAM grant helpers."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment, Stack, aws_iam as iam
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.permissions.bedrock import (
    grant_bedrock_invoke_model_access,
)


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


def test_grant_bedrock_invoke_model_access_default_wildcard(test_stack, grantee):
    """Test that the default model scope is all foundation models."""
    grant_bedrock_invoke_model_access(grantee, test_stack)
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": [
                                    "bedrock:InvokeModel",
                                    "bedrock:InvokeModelWithResponseStream",
                                    "bedrock:Converse",
                                    "bedrock:ConverseStream",
                                ],
                                "Resource": (
                                    "arn:aws:bedrock:eu-west-2::"
                                    "foundation-model/*"
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_bedrock_invoke_model_access_scoped_model_ids(test_stack, grantee):
    """Test that model_ids scopes the resource ARNs to specific models."""
    grant_bedrock_invoke_model_access(
        grantee,
        test_stack,
        model_ids=[
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "amazon.titan-text-express-v1",
        ],
    )
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Resource": [
                                    "arn:aws:bedrock:eu-west-2::foundation-model/"
                                    "anthropic.claude-3-5-sonnet-20241022-v2:0",
                                    "arn:aws:bedrock:eu-west-2::foundation-model/"
                                    "amazon.titan-text-express-v1",
                                ],
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_bedrock_invoke_model_access_with_sid(test_stack, grantee):
    """Test that a provided sid is included on the statement."""
    grant_bedrock_invoke_model_access(grantee, test_stack, sid="MyBedrockSid")
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Sid": "MyBedrockSid"})]
                )
            }
        },
    )


def test_grant_bedrock_invoke_model_access_omits_sid_by_default(test_stack, grantee):
    """Test that no Sid is set when not provided."""
    grant_bedrock_invoke_model_access(grantee, test_stack)
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statement = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ][0]

    assert "Sid" not in statement
