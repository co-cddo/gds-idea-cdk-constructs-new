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

Environment-specific configuration is fetched from AWS Secrets Manager at synth
time. Each account maps to a secret via the naming convention
`/gds-idea/{environment}/config`.

### Required Secret Keys

The secret must be a JSON object with these keys:

- **domain_name** — Parent domain (e.g. `example.com`)
- **vpc_id** — Existing VPC ID
- **cluster_name** — Existing ECS cluster name
- **user_pool_id** — Existing Cognito User Pool ID
- **external_idp_name** — External identity provider name in Cognito
- **waf_arn** — WAF WebACL ARN

### Environments

| Environment | Account | Secret Path |
|-------------|---------|-------------|
| Development | `992382722318` | `/gds-idea/development/config` |
| Production | `588077357019` | `/gds-idea/production/config` |

**Region**: `eu-west-2` (preferred for both)

### Alternative Construction

For testing or local development without Secrets Manager access:

```python
config = DeploymentConfig.from_dict(cdk_env, {
    "domain_name": "example.com",
    "vpc_id": "vpc-abc123",
    "cluster_name": "my-cluster",
    "user_pool_id": "eu-west-2_PoolId",
    "external_idp_name": "my-idp",
    "waf_arn": "arn:aws:wafv2:...",
})
```
