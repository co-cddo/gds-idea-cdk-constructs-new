"""Unit tests for DynamoDB IAM grant helpers."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment, Stack, aws_iam as iam
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.permissions.dynamodb import (
    grant_dynamodb_read_data,
    grant_dynamodb_read_write_data,
    grant_dynamodb_write_data,
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


def test_grant_dynamodb_read_data_default(test_stack, grantee):
    """Test the default read-only statement, including index ARN."""
    grant_dynamodb_read_data(grantee, test_stack, "my-table")
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
                                    "dynamodb:GetItem",
                                    "dynamodb:BatchGetItem",
                                    "dynamodb:Query",
                                    "dynamodb:Scan",
                                    "dynamodb:DescribeTable",
                                ],
                                "Resource": [
                                    "arn:aws:dynamodb:eu-west-2:992382722318"
                                    ":table/my-table",
                                    "arn:aws:dynamodb:eu-west-2:992382722318"
                                    ":table/my-table/index/*",
                                ],
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_dynamodb_write_data(test_stack, grantee):
    """Test that grant_dynamodb_write_data grants only the write actions."""
    grant_dynamodb_write_data(grantee, test_stack, "my-table")
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
                                    "dynamodb:PutItem",
                                    "dynamodb:UpdateItem",
                                    "dynamodb:DeleteItem",
                                    "dynamodb:BatchWriteItem",
                                ],
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_dynamodb_read_data_exclude_indexes(test_stack, grantee):
    """Test that include_indexes=False omits the index ARN."""
    grant_dynamodb_read_data(grantee, test_stack, "my-table", include_indexes=False)
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Resource": (
                                    "arn:aws:dynamodb:eu-west-2:992382722318"
                                    ":table/my-table"
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_dynamodb_read_data_with_sid(test_stack, grantee):
    """Test that a provided sid is included on the statement."""
    grant_dynamodb_read_data(grantee, test_stack, "my-table", sid="MyTableSid")
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Sid": "MyTableSid"})]
                )
            }
        },
    )


def test_grant_dynamodb_read_data_omits_sid_by_default(test_stack, grantee):
    """Test that no Sid is set when not provided."""
    grant_dynamodb_read_data(grantee, test_stack, "my-table")
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statement = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ][0]

    assert "Sid" not in statement


def test_grant_dynamodb_read_data_excludes_write_actions(test_stack, grantee):
    """Test that grant_dynamodb_read_data does not grant any write action."""
    grant_dynamodb_read_data(grantee, test_stack, "my-table")
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    [statement] = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]

    assert "dynamodb:PutItem" not in statement["Action"]


def test_grant_dynamodb_read_write_data_combines_actions(test_stack, grantee):
    """Test that grant_dynamodb_read_write_data grants read and write actions."""
    grant_dynamodb_read_write_data(grantee, test_stack, "my-table")
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    [statement] = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]

    assert {"dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"} <= set(
        statement["Action"]
    )
    assert len(statement["Action"]) == 9
