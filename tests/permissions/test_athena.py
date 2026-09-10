"""Unit tests for Athena/Glue/S3/KMS IAM grant helpers."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment, Stack, aws_iam as iam
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.config import DeploymentEnvironment
from gds_idea_cdk_constructs.permissions.athena import (
    grant_athena_results_access,
    grant_athena_workgroup_access,
    grant_glue_catalog_access,
    grant_kms_key_access,
    grant_s3_bucket_access,
)
from gds_idea_cdk_constructs.permissions.settings import AthenaSettings


@pytest.fixture
def cdk_app():
    """Fixture for CDK App."""
    return App()


@pytest.fixture
def test_stack(cdk_app):
    """Fixture for a test CDK Stack in the dev account."""
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


@pytest.fixture
def athena_settings():
    """Fixture for AthenaSettings built from an explicit dict."""
    return AthenaSettings.from_dict(
        DeploymentEnvironment.DEVELOPMENT,
        {
            "992382722318": {
                "results_bucket_name": "gds-idea-athena-query-results-development",
                "kms_key_arn": "arn:aws:kms:eu-west-2:992382722318:key/dev-key-id",
            }
        },
    )


def test_grant_athena_workgroup_access_default(test_stack, grantee):
    """Test the default workgroup access statement."""
    grant_athena_workgroup_access(grantee, test_stack)
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(
                                    ["athena:StartQueryExecution"]
                                ),
                                "Effect": "Allow",
                                "Resource": (
                                    "arn:aws:athena:eu-west-2:992382722318"
                                    ":workgroup/primary"
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_athena_workgroup_access_custom_workgroup_and_region(test_stack, grantee):
    """Test overriding the workgroup name and region."""
    grant_athena_workgroup_access(
        grantee, test_stack, workgroup_name="custom", region="us-east-1"
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
                                "Resource": (
                                    "arn:aws:athena:us-east-1:992382722318"
                                    ":workgroup/custom"
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_athena_workgroup_access_with_sid(test_stack, grantee):
    """Test that a provided sid is included on the statement."""
    grant_athena_workgroup_access(grantee, test_stack, sid="MyWorkgroupSid")
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Sid": "MyWorkgroupSid"})]
                )
            }
        },
    )


def test_grant_athena_workgroup_access_omits_sid_by_default(test_stack, grantee):
    """Test that no Sid is set when not provided."""
    grant_athena_workgroup_access(grantee, test_stack)
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statement = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ][0]

    assert "Sid" not in statement


def test_grant_glue_catalog_access_default(test_stack, grantee):
    """Test the default Glue catalog access statement."""
    grant_glue_catalog_access(grantee, test_stack, "my_database")
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(["glue:GetTable"]),
                                "Resource": Match.array_with(
                                    [
                                        "arn:aws:glue:eu-west-2:992382722318:catalog",
                                        (
                                            "arn:aws:glue:eu-west-2:992382722318"
                                            ":database/my_database"
                                        ),
                                        (
                                            "arn:aws:glue:eu-west-2:992382722318"
                                            ":table/my_database/*"
                                        ),
                                    ]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_s3_bucket_access_read_only(test_stack, grantee):
    """Test that read-only access grants the expected actions."""
    grant_s3_bucket_access(grantee, "my-bucket")
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
                                    "s3:GetObject",
                                    "s3:ListBucket",
                                    "s3:GetBucketLocation",
                                ],
                                "Resource": [
                                    "arn:aws:s3:::my-bucket",
                                    "arn:aws:s3:::my-bucket/*",
                                ],
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_s3_bucket_access_write(test_stack, grantee):
    """Test that write=True adds the write actions."""
    grant_s3_bucket_access(grantee, "my-bucket", write=True)
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(
                                    [
                                        "s3:PutObject",
                                        "s3:AbortMultipartUpload",
                                    ]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_kms_key_access(test_stack, grantee):
    """Test the KMS key access statement."""
    key_arn = "arn:aws:kms:eu-west-2:992382722318:key/some-key-id"
    grant_kms_key_access(grantee, key_arn)
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
                                    "kms:Decrypt",
                                    "kms:GenerateDataKey",
                                    "kms:DescribeKey",
                                    "kms:CreateGrant",
                                ],
                                "Resource": key_arn,
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_athena_results_access_grants_bucket_and_kms(
    test_stack, grantee, athena_settings
):
    """Test that the composite helper grants both bucket and KMS access."""
    grant_athena_results_access(grantee, athena_settings)
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
                                    "arn:aws:s3:::"
                                    "gds-idea-athena-query-results-development",
                                    "arn:aws:s3:::"
                                    "gds-idea-athena-query-results-development/*",
                                ],
                            }
                        ),
                        Match.object_like(
                            {
                                "Resource": (
                                    "arn:aws:kms:eu-west-2:992382722318:key/dev-key-id"
                                ),
                            }
                        ),
                    ]
                )
            }
        },
    )


def test_grant_athena_results_access_default_is_write(
    test_stack, grantee, athena_settings
):
    """Test that write defaults to True (queries write their own results)."""
    grant_athena_results_access(grantee, athena_settings)
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Action": Match.array_with(["s3:PutObject"])})]
                )
            }
        },
    )


def test_grant_athena_results_access_sid_prefix_builds_two_sids(
    test_stack, grantee, athena_settings
):
    """Test that sid_prefix builds the two expected Sids."""
    grant_athena_results_access(grantee, athena_settings, sid_prefix="RapidResults")
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like({"Sid": "RapidResultsBucketAccess"}),
                        Match.object_like({"Sid": "RapidResultsKmsAccess"}),
                    ]
                )
            }
        },
    )
