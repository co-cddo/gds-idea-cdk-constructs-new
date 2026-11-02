"""Unit tests for S3 IAM grant helpers."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment, Stack, aws_iam as iam
from aws_cdk.assertions import Template

from gds_idea_cdk_constructs.permissions import (
    grant_s3_read,
    grant_s3_read_write,
    grant_s3_write,
)

READ_ACTIONS = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
WRITE_ACTIONS = ["s3:PutObject", "s3:AbortMultipartUpload"]
BUCKET_RESOURCES = ["arn:aws:s3:::my-bucket", "arn:aws:s3:::my-bucket/*"]


@pytest.fixture
def test_stack():
    """Fixture for a test CDK Stack in the dev account."""
    env = CdkEnvironment(account="992382722318", region="eu-west-2")
    return Stack(App(), "TestStack", env=env)


@pytest.fixture
def grantee(test_stack):
    """Fixture for an IAM Role to grant permissions to."""
    return iam.Role(
        test_stack,
        "TestRole",
        assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    )


def _statements(stack):
    """Return the statements of the single IAM policy in the stack."""
    policies = Template.from_stack(stack).find_resources("AWS::IAM::Policy")
    return next(iter(policies.values()))["Properties"]["PolicyDocument"]["Statement"]


def test_grant_s3_read_grants_only_read_actions(test_stack, grantee):
    """Test that grant_s3_read grants only the read actions."""
    grant_s3_read(grantee, "my-bucket")

    [statement] = _statements(test_stack)
    assert statement["Action"] == READ_ACTIONS
    assert statement["Resource"] == BUCKET_RESOURCES


def test_grant_s3_write_grants_only_write_actions(test_stack, grantee):
    """Test that grant_s3_write grants only the write actions."""
    grant_s3_write(grantee, "my-bucket")

    [statement] = _statements(test_stack)
    assert statement["Action"] == WRITE_ACTIONS
    assert statement["Resource"] == BUCKET_RESOURCES


def test_grant_s3_read_write_grants_both_in_one_statement(test_stack, grantee):
    """Test that grant_s3_read_write combines read and write in one statement."""
    grant_s3_read_write(grantee, "my-bucket")

    [statement] = _statements(test_stack)
    assert statement["Action"] == READ_ACTIONS + WRITE_ACTIONS
    assert statement["Resource"] == BUCKET_RESOURCES


@pytest.mark.parametrize("grant", [grant_s3_read, grant_s3_write, grant_s3_read_write])
def test_grant_s3_sid_is_optional(test_stack, grantee, grant):
    """Test that Sid is omitted by default and applied when given."""
    grant(grantee, "my-bucket")
    grant(grantee, "other-bucket", sid="MySid")

    sids = [s.get("Sid") for s in _statements(test_stack)]
    assert sids == [None, "MySid"]
