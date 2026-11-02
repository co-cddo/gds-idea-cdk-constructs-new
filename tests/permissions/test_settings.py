"""Unit tests for AthenaSettings."""

import json
from unittest.mock import MagicMock, patch

import pytest
from aws_cdk import Environment as CdkEnvironment

from gds_idea_cdk_constructs.permissions.settings import AthenaSettings

ATHENA_CONFIG = {
    "results_bucket_name": "gds-idea-athena-query-results-development",
    "kms_key_arn": "arn:aws:kms:eu-west-2:992382722318:key/dev-key-id",
}


def test_from_dict_sets_attributes_from_cdk_env_and_config(dev_cdk_env):
    """Test that from_dict takes account/region from cdk_env and the flat config."""
    settings = AthenaSettings.from_dict(dev_cdk_env, ATHENA_CONFIG)

    assert settings.account == "992382722318"
    assert settings.region == "eu-west-2"
    assert settings.results_bucket_name == ATHENA_CONFIG["results_bucket_name"]
    assert settings.kms_key_arn == ATHENA_CONFIG["kms_key_arn"]


def test_from_dict_defaults_region_when_unset():
    """Test that the region falls back to the default when cdk_env has none."""
    settings = AthenaSettings.from_dict(
        CdkEnvironment(account="992382722318"), ATHENA_CONFIG
    )

    assert settings.region == "eu-west-2"


@pytest.mark.parametrize("missing", ["results_bucket_name", "kms_key_arn"])
def test_from_dict_raises_when_required_key_missing(dev_cdk_env, missing):
    """Test that from_dict names the missing required key."""
    config = {k: v for k, v in ATHENA_CONFIG.items() if k != missing}

    with pytest.raises(ValueError, match=missing):
        AthenaSettings.from_dict(dev_cdk_env, config)


def test_init_fetches_flat_parameter_from_ssm(dev_cdk_env):
    """Test that the constructor reads /gds-idea-athena as a flat JSON object."""
    client = MagicMock()
    client.get_parameter.return_value = {
        "Parameter": {"Value": json.dumps(ATHENA_CONFIG)}
    }

    with patch("boto3.client", return_value=client):
        settings = AthenaSettings(dev_cdk_env)

    client.get_parameter.assert_called_once_with(Name="/gds-idea-athena")
    assert settings.results_bucket_name == ATHENA_CONFIG["results_bucket_name"]


def test_init_raises_for_testing_environment(test_cdk_env):
    """Test that the TESTING environment cannot fetch from Parameter Store."""
    with pytest.raises(ValueError, match="from_dict"):
        AthenaSettings(test_cdk_env)
