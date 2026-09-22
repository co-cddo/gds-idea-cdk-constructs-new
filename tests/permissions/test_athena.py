"""Unit tests for Athena/Glue/S3/KMS IAM grant helpers."""

import pytest
from aws_cdk import App, Environment as CdkEnvironment, Stack, aws_iam as iam
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.config import DeploymentEnvironment
from gds_idea_cdk_constructs.permissions.athena import (
    grant_athena,
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


def test_grant_athena_workgroup_access_default(test_stack, grantee, athena_settings):
    """Test the default workgroup access statement."""
    grant_athena_workgroup_access(grantee, athena_settings)
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


def test_grant_athena_workgroup_access_custom_workgroup_and_region(
    test_stack, grantee, athena_settings
):
    """Test overriding the workgroup name and region."""
    grant_athena_workgroup_access(
        grantee, athena_settings, workgroup_name="custom", region="us-east-1"
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


def test_grant_athena_workgroup_access_with_sid(test_stack, grantee, athena_settings):
    """Test that a provided sid is included on the statement."""
    grant_athena_workgroup_access(grantee, athena_settings, sid="MyWorkgroupSid")
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


def test_grant_athena_workgroup_access_omits_sid_by_default(
    test_stack, grantee, athena_settings
):
    """Test that no Sid is set when not provided."""
    grant_athena_workgroup_access(grantee, athena_settings)
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statement = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ][0]

    assert "Sid" not in statement


def test_grant_glue_catalog_access_default(test_stack, grantee, athena_settings):
    """Test the default Glue catalog access statement."""
    grant_glue_catalog_access(grantee, athena_settings, "my_database")
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


def test_grant_athena_composes_all_four_statements(
    test_stack, grantee, athena_settings
):
    """Test that grant_athena grants workgroup, glue, data bucket, and results."""
    grant_athena(grantee, "my_database", "my-data-bucket", athena_settings)
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statements = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]

    # Workgroup, Glue, data bucket, results bucket, KMS = 5 statements.
    assert len(statements) == 5

    actions = [s["Action"] for s in statements]
    assert any(
        isinstance(a, list) and "athena:StartQueryExecution" in a for a in actions
    )
    assert any(isinstance(a, list) and "glue:GetTable" in a for a in actions)
    assert any(isinstance(a, list) and "kms:Decrypt" in a for a in actions)


def test_grant_athena_uses_default_workgroup(test_stack, grantee, athena_settings):
    """Test that grant_athena defaults to the shared 'primary' workgroup."""
    grant_athena(grantee, "my_database", "my-data-bucket", athena_settings)
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


def test_grant_athena_grants_glue_catalog_for_database(
    test_stack, grantee, athena_settings
):
    """Test that grant_athena grants Glue access scoped to the database."""
    grant_athena(grantee, "my_database", "my-data-bucket", athena_settings)
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
                                        "arn:aws:glue:eu-west-2:992382722318"
                                        ":database/my_database"
                                    ]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_athena_grants_data_bucket_access(test_stack, grantee, athena_settings):
    """Test that grant_athena grants access to the given data bucket."""
    grant_athena(grantee, "my_database", "my-data-bucket", athena_settings)
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
                                    "arn:aws:s3:::my-data-bucket",
                                    "arn:aws:s3:::my-data-bucket/*",
                                ],
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_athena_write_defaults_to_true(test_stack, grantee, athena_settings):
    """Test that write defaults to True, granting write access to the data bucket."""
    grant_athena(grantee, "my_database", "my-data-bucket", athena_settings)
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
                                    "arn:aws:s3:::my-data-bucket",
                                    "arn:aws:s3:::my-data-bucket/*",
                                ],
                                "Action": Match.array_with(["s3:PutObject"]),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_athena_write_false_omits_data_bucket_write(
    test_stack, grantee, athena_settings
):
    """Test that write=False omits write actions on the data bucket only."""
    grant_athena(
        grantee,
        "my_database",
        "my-data-bucket",
        athena_settings,
        write=False,
    )
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statements = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]
    data_bucket_statement = next(
        s
        for s in statements
        if s.get("Resource")
        == ["arn:aws:s3:::my-data-bucket", "arn:aws:s3:::my-data-bucket/*"]
    )

    assert "s3:PutObject" not in data_bucket_statement["Action"]


def test_grant_athena_results_bucket_always_writable_regardless_of_write_flag(
    test_stack, grantee, athena_settings
):
    """Test that write=False still grants write on the results bucket."""
    grant_athena(
        grantee,
        "my_database",
        "my-data-bucket",
        athena_settings,
        write=False,
    )
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statements = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]
    results_bucket_statement = next(
        s
        for s in statements
        if s.get("Resource")
        == [
            "arn:aws:s3:::gds-idea-athena-query-results-development",
            "arn:aws:s3:::gds-idea-athena-query-results-development/*",
        ]
    )

    assert "s3:PutObject" in results_bucket_statement["Action"]


def test_grant_athena_custom_workgroup_and_region(test_stack, grantee, athena_settings):
    """Test that workgroup_name and region overrides are forwarded."""
    grant_athena(
        grantee,
        "my_database",
        "my-data-bucket",
        athena_settings,
        workgroup_name="custom",
        region="us-east-1",
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


def test_grant_athena_sid_prefix_builds_all_sids(test_stack, grantee, athena_settings):
    """Test that sid_prefix names all composed statements."""
    grant_athena(
        grantee,
        "my_database",
        "my-data-bucket",
        athena_settings,
        sid_prefix="MyTable",
    )
    template = Template.from_stack(test_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like({"Sid": "MyTableWorkgroupAccess"}),
                        Match.object_like({"Sid": "MyTableGlueAccess"}),
                        Match.object_like({"Sid": "MyTableDataBucketAccess"}),
                        Match.object_like({"Sid": "MyTableBucketAccess"}),
                        Match.object_like({"Sid": "MyTableKmsAccess"}),
                    ]
                )
            }
        },
    )


def test_grant_athena_omits_sids_by_default(test_stack, grantee, athena_settings):
    """Test that no Sid is set on any composed statement when not provided."""
    grant_athena(grantee, "my_database", "my-data-bucket", athena_settings)
    template = Template.from_stack(test_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statements = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]

    assert all("Sid" not in s for s in statements)
