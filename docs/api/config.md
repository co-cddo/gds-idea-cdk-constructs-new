# Configuration

The configuration module provides environment-aware settings for deploying applications across different AWS accounts.

## Overview

The configuration system automatically selects appropriate settings based on your AWS account ID, including:

- VPC and subnet configuration
- Route53 hosted zones
- Cognito user pools
- WAF rules
- S3 buckets for logging

## DeploymentEnvironment

::: gds_idea_cdk_constructs.config.DeploymentEnvironment
    options:
      show_root_heading: true
      heading_level: 3

## DeploymentConfig

::: gds_idea_cdk_constructs.config.DeploymentConfig
    options:
      show_root_heading: true
      heading_level: 3

## AppConfig

::: gds_idea_cdk_constructs.config.AppConfig
    options:
      show_root_heading: true
      heading_level: 3

## Usage Examples

### Basic Configuration

```python
import os
import aws_cdk as cdk
from gds_idea_cdk_constructs.config import DeploymentConfig, AppConfig

# Create CDK environment from AWS credentials
cdk_env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"],
    region=os.environ["CDK_DEFAULT_REGION"],
)

# Deployment config automatically detects environment
deployment_config = DeploymentConfig(cdk_env)

# Application config
app_config = AppConfig(
    app_name="my-app",
    framework="streamlit",
)
```

### Custom Health Check

```python
app_config = AppConfig(
    app_name="my-api",
    framework="fastapi",
    health_check_path="/api/v1/health",
)
```

### Loading from pyproject.toml

```python
# pyproject.toml:
# [tool.webapp]
# app_name = "my-app"
# framework = "streamlit"

app_config = AppConfig.from_pyproject("pyproject.toml")
```

## Environment-Specific Values

Environment-specific configuration is fetched from AWS Systems Manager Parameter
Store at synth time. Three parameters are fetched and merged into a single config:

### Parameter Structure

| Parameter | Key | Attribute |
|-----------|-----|-----------|
| `/gds-idea-auth` | `domain_name` | `domain_name` |
| `/gds-idea-auth` | `cognito_user_pool_id` | `user_pool_id` |
| `/gds-idea-auth` | `waf_arn` | `waf_arn` |
| `/gds-idea-auth` | `waf_big_upload_arn` | `waf_big_upload_arn` |
| `/gds-idea-auth` | `logs_bucket_name` | `log_bucket_name` |
| `/gds-idea-ecs` | `ecs_arn` | `cluster_name` (parsed from ARN) |
| `/gds-idea-vpc` | `vpc_id` | `vpc_id` |

The `external_idp_name` attribute is hard-coded to `"internal-access"` to match
the identity provider configured in the Cognito User Pool.

### Environments

| Environment | Account |
|-------------|---------|
| Development | `992382722318` |
| Production | `588077357019` |

**Region**: `eu-west-2` (preferred for both)

### Alternative Construction

For testing or local development without Parameter Store access:

```python
config = DeploymentConfig.from_dict(cdk_env, {
    "domain_name": "example.com",
    "vpc_id": "vpc-abc123",
    "ecs_arn": "arn:aws:ecs:eu-west-2:123456789012:cluster/my-cluster",
    "cognito_user_pool_id": "eu-west-2_PoolId",
    "waf_arn": "arn:aws:wafv2:...",
    "waf_big_upload_arn": "arn:aws:wafv2:...",
    "logs_bucket_name": "example.com-logs",
})
```
