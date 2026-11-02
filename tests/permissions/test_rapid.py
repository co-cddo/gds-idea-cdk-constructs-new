"""Unit tests for the composite rAPId database access IAM grant helper."""

from unittest.mock import patch

import pytest
from aws_cdk import App, Environment as CdkEnvironment, Stack, aws_iam as iam
from aws_cdk.assertions import Match, Template

from gds_idea_cdk_constructs.config import (
    RAPID_CROSS_ACCOUNT_ROLE_ARN,
    DeploymentConfig,
)
from gds_idea_cdk_constructs.permissions.rapid import grant_rapid_database
from gds_idea_cdk_constructs.permissions.settings import (
    RAPID_DATA_BUCKET_NAME,
    RAPID_GLUE_DATABASE,
    RAPID_REGION,
    AthenaSettings,
)
from tests.conftest import TEST_CONFIG

ATHENA_CONFIG = {
    "results_bucket_name": "gds-idea-athena-query-results-production",
    "kms_key_arn": "arn:aws:kms:eu-west-2:588077357019:key/prod-key-id",
}


@pytest.fixture
def cdk_app():
    """Fixture for CDK App."""
    return App()


@pytest.fixture
def dev_stack(cdk_app):
    """Fixture for a test CDK Stack in the dev account."""
    env = CdkEnvironment(account="992382722318", region="eu-west-2")
    return Stack(cdk_app, "DevStack", env=env)


@pytest.fixture
def prod_stack(cdk_app):
    """Fixture for a test CDK Stack in the prod account, non-default region."""
    env = CdkEnvironment(account="588077357019", region="us-east-1")
    return Stack(cdk_app, "ProdStack", env=env)


def _grantee(stack: Stack) -> iam.IGrantable:
    """Build an IAM Role in the given stack to grant permissions to."""
    return iam.Role(
        stack,
        "TestRole",
        assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    )


@pytest.fixture
def dev_deployment_config(dev_cdk_env):
    """Fixture for a DEVELOPMENT DeploymentConfig."""
    return DeploymentConfig.from_dict(dev_cdk_env, TEST_CONFIG)


@pytest.fixture
def prod_deployment_config(prod_cdk_env):
    """Fixture for a PRODUCTION DeploymentConfig."""
    return DeploymentConfig.from_dict(prod_cdk_env, TEST_CONFIG)


@pytest.fixture
def athena_settings(prod_cdk_env):
    """Fixture for AthenaSettings built from an explicit dict."""
    return AthenaSettings.from_dict(prod_cdk_env, ATHENA_CONFIG)


def test_grant_rapid_database_always_grants_secret(
    dev_stack, dev_deployment_config, athena_settings
):
    """Test that the secret access statement is always present."""
    grantee = _grantee(dev_stack)
    grant_rapid_database(
        grantee, dev_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(dev_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Action": "secretsmanager:GetSecretValue"})]
                )
            }
        },
    )


def test_grant_rapid_database_non_production_assumes_cross_account_role(
    dev_stack, dev_deployment_config, athena_settings
):
    """Test that non-production grants sts:AssumeRole on the cross-account role."""
    grantee = _grantee(dev_stack)
    grant_rapid_database(
        grantee, dev_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(dev_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRole",
                                "Effect": "Allow",
                                "Resource": (
                                    dev_deployment_config.cross_account_role_arn
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_rapid_database_non_production_assume_role_has_no_sid(
    dev_stack, dev_deployment_config, athena_settings
):
    """Test that the sts:AssumeRole statement never sets a Sid."""
    grantee = _grantee(dev_stack)
    grant_rapid_database(
        grantee, dev_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(dev_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statements = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]
    assume_role_statement = next(
        s for s in statements if s.get("Action") == "sts:AssumeRole"
    )

    assert "Sid" not in assume_role_statement


def test_grant_rapid_database_non_production_only_grants_two_statements(
    dev_stack, dev_deployment_config, athena_settings
):
    """Test that non-production grants exactly secret + assume-role, no Athena."""
    grantee = _grantee(dev_stack)
    grant_rapid_database(
        grantee, dev_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(dev_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statements = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]

    assert len(statements) == 2
    actions = {s["Action"] for s in statements}
    assert actions == {"secretsmanager:GetSecretValue", "sts:AssumeRole"}


def test_grant_rapid_database_falls_back_to_rapid_constant_role_arn(
    dev_stack, dev_deployment_config, athena_settings
):
    """Test the RAPID_CROSS_ACCOUNT_ROLE_ARN fallback when unset on the config."""
    dev_deployment_config.cross_account_role_arn = None
    grantee = _grantee(dev_stack)
    grant_rapid_database(
        grantee, dev_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(dev_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRole",
                                "Resource": RAPID_CROSS_ACCOUNT_ROLE_ARN,
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_rapid_database_production_grants_athena_workgroup(
    prod_stack, prod_deployment_config, athena_settings
):
    """Test that production grants direct Athena workgroup access."""
    grantee = _grantee(prod_stack)
    grant_rapid_database(
        grantee, prod_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(prod_stack)

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
                                "Resource": (
                                    f"arn:aws:athena:{RAPID_REGION}:588077357019"
                                    ":workgroup/primary"
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_rapid_database_production_forces_rapid_region_for_glue(
    prod_stack, prod_deployment_config, athena_settings
):
    """Test that production forces RAPID_REGION for Glue, ignoring stack.region."""
    grantee = _grantee(prod_stack)
    grant_rapid_database(
        grantee, prod_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(prod_stack)

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
                                        f"arn:aws:glue:{RAPID_REGION}:588077357019"
                                        f":database/{RAPID_GLUE_DATABASE}"
                                    ]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_rapid_database_production_grants_data_bucket(
    prod_stack, prod_deployment_config, athena_settings
):
    """Test that production grants access to rAPId's shared data bucket."""
    grantee = _grantee(prod_stack)
    grant_rapid_database(
        grantee, prod_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(prod_stack)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Resource": [
                                    f"arn:aws:s3:::{RAPID_DATA_BUCKET_NAME}",
                                    f"arn:aws:s3:::{RAPID_DATA_BUCKET_NAME}/*",
                                ],
                            }
                        )
                    ]
                )
            }
        },
    )


def test_grant_rapid_database_production_grants_results_bucket_and_kms(
    prod_stack, prod_deployment_config, athena_settings
):
    """Test that production grants access to the Athena results bucket + KMS key."""
    grantee = _grantee(prod_stack)
    grant_rapid_database(
        grantee, prod_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(prod_stack)

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
                                    "gds-idea-athena-query-results-production",
                                    "arn:aws:s3:::"
                                    "gds-idea-athena-query-results-production/*",
                                ],
                            }
                        ),
                        Match.object_like(
                            {
                                "Resource": (
                                    "arn:aws:kms:eu-west-2:588077357019:key/prod-key-id"
                                ),
                            }
                        ),
                    ]
                )
            }
        },
    )


def test_grant_rapid_database_production_does_not_assume_role(
    prod_stack, prod_deployment_config, athena_settings
):
    """Test that production never grants sts:AssumeRole."""
    grantee = _grantee(prod_stack)
    grant_rapid_database(
        grantee, prod_deployment_config, "my-app/rapid", athena_settings=athena_settings
    )
    template = Template.from_stack(prod_stack)
    policy = template.find_resources("AWS::IAM::Policy")
    statements = next(iter(policy.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]
    actions = {s["Action"] for s in statements if isinstance(s["Action"], str)}

    assert "sts:AssumeRole" not in actions


def test_grant_rapid_database_non_production_does_not_read_parameter_store(
    dev_stack, dev_deployment_config
):
    """Test that non-production never builds AthenaSettings (no SSM read)."""
    with patch(
        "gds_idea_cdk_constructs.permissions.rapid.AthenaSettings"
    ) as athena_settings_cls:
        grant_rapid_database(_grantee(dev_stack), dev_deployment_config, "my-app/rapid")

    athena_settings_cls.assert_not_called()


def test_grant_rapid_database_production_builds_athena_settings_when_omitted(
    prod_stack, prod_deployment_config, athena_settings
):
    """Test that production fetches AthenaSettings for its cdk_env if omitted."""
    with patch(
        "gds_idea_cdk_constructs.permissions.rapid.AthenaSettings",
        return_value=athena_settings,
    ) as athena_settings_cls:
        grant_rapid_database(
            _grantee(prod_stack), prod_deployment_config, "my-app/rapid"
        )

    athena_settings_cls.assert_called_once_with(prod_deployment_config.cdk_env)
