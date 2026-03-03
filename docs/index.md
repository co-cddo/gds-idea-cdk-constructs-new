# gds-idea-cdk-constructs

A Python library providing reusable AWS CDK constructs for deploying containerized web applications within the GDS Idea infrastructure.

## Note

It is not designed to be used directly but it is a dependency in the [app templates repo](https://github.com/co-cddo/gds-idea-app-templates)
For instructions on usage please see the docs for gds-idea-app-templates.

## Overview

The primary construct in this library is `WebApp`, which simplifies the deployment of Docker containers with:

- **Built-in authentication patterns** - Choose between Cognito authentication or no authentication
- **Automated infrastructure** - ECS Fargate, Application Load Balancer, VPC integration, DNS configuration
- **Environment-aware** - Automatically configures resources based on AWS account (DEV/PROD)
- **Secure by default** - WAF integration, HTTPS-only, customizable IAM roles
- **Flexible configuration** - Customize CPU, memory, environment variables, and more

## Quick Start

### Prerequisites

Before using this library, ensure you have:

1. An AWS account configured for the gds-idea dev account.
2. AWS CDK installed, recommend installing via brew
3. `uv`, recommend installing via brew
4. docker cli, you dont need docker desktop. recommend installing colima via brew

### Installation

```bash
uv add git+https://github.com/co-cddo/gds-idea-cdk-constructs
```

### Basic Example

Below we configure app to deploy into our infrastructure.

```python
import os
import aws_cdk as cdk
from gds_idea_cdk_constructs.config import DeploymentConfig, AppConfig
from gds_idea_cdk_constructs.web_app import WebApp, AuthType

# Create CDK app
app = cdk.App()

# Set up environment - if you export your AWS_PROFILE into the environment these will be
# correct. export AWS_PROFILE=you-dev-profile
cdk_env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"],
    region=os.environ["CDK_DEFAULT_REGION"],
)

# Configure deployment (automatically looks up existing core infrastructure)
deployment_config = DeploymentConfig(cdk_env)

# Configure your application, this will load the name and framwork from your
# pyproject.toml file
app_config = AppConfig.from_pyproject()

# Create the stack
WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.INTERNAL_ACCESS,
    # authentication=AuthType.NONE, # Swap this line for public access (no authentication)
    # authentication=AuthType.COGNITO, # Swap this line for Cognito managed login authentication

)

app.synth()
```

## Architecture

The `WebApp` construct creates and configures:

1. **ECS Cluster** - Fargate cluster for running containers
2. **Task Definition** - Container configuration with customizable CPU/memory
3. **Fargate Service** - Managed container service with auto-scaling
4. **Application Load Balancer** - HTTPS load balancer with HTTP→HTTPS redirect
5. **DNS Configuration** - Route53 hosted zone and records
6. **TLS Certificate** - ACM certificate with DNS validation
7. **Authentication** (optional) - Cognito user pool client and ALB authentication
8. **Security** - WAF association, security groups, IAM roles

## Next Steps

- [Getting Started Guide](getting-started.md) - Detailed setup instructions
- [API Reference](api/webapp.md) - Complete API documentation
