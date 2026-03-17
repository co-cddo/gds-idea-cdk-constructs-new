# Getting Started

This guide will walk you through deploying your first containerized web application using gds-idea-cdk-constructs.

## Prerequisites

Before using this library, ensure you have:

1. **AWS Account** - With credentials configured for your environment
2. **AWS CDK v2** - Installed and bootstrapped in your target account and region
3. **Docker** - Installed and running on your local machine
4. **Python 3.11+** - This library requires Python 3.11 or later

### Existing AWS Infrastructure

This library assumes you have the following infrastructure already deployed:

- **VPC** - Virtual Private Cloud for networking
- **Route 53 Hosted Zone** - Parent domain for your applications
- **S3 Bucket** - For ALB access logs
- **Cognito User Pool** (optional) - For authentication
- **WAF Web ACL** - For security

The `DeploymentConfig` class automatically looks up these resources based on your AWS account.

## Installation

Install from github:

```bash
uv add git+https://github.com/co-cddo/gds-idea-cdk-constructs
```


## Your First Application

### 1. Project Setup

Create a new CDK project:

```bash
mkdir my-web-app
cd my-web-app
cdk init app --language python
```

Install the library:

```bash
uv add git+https://github.com/co-cddo/gds-idea-cdk-constructs
```

### 2. Create Your Application Code

Create a simple Streamlit app:

```python
# app.py
import streamlit as st

st.title("Hello GDS Idea!")
st.write("This is my first deployed application.")
```

Create a Dockerfile:

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install streamlit

COPY app.py .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### 3. Create CDK Stack

Edit your `app.py` (or create a new one):

```python
#!/usr/bin/env python3
import os
import aws_cdk as cdk

from gds_idea_cdk_constructs.config import DeploymentConfig, AppConfig
from gds_idea_cdk_constructs.web_app import WebApp, AuthType

app = cdk.App()

# Configure environment from AWS credentials
cdk_env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "eu-west-2"),
)

# Deployment config automatically looks up infrastructure
deployment_config = DeploymentConfig(cdk_env)

# Configure your application
app_config = AppConfig(
    app_name="my-web-app",
    framework="streamlit",
)

# Create the stack
WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.INTERNAL_ACCESS,  # Requires login
    docker_context_path=".",
    dockerfile_path="Dockerfile",
)

app.synth()
```

### 4. Deploy

Set your AWS profile and deploy:

```bash
export AWS_PROFILE=your-profile
cdk deploy
```

The deployment will:
1. Build your Docker image
2. Push it to ECR
3. Create all AWS resources
4. Output your application URL

## Configuration Options

### Custom Container Properties

If you need to change the default parameters of the container, or pass `envs` initiate
a `WebAppContainerProperties` object. All parameters have sensible defaults.

```python
from gds_idea_cdk_constructs.web_app import WebAppContainerProperties

container_props = WebAppContainerProperties(
    cpu=512,                    # 0.5 vCPU
    memory_limit_mib=1024,      # 1 GB RAM
    desired_count=2,            # Run 2 tasks
    container_port=8501,        # Streamlit default
    health_check_path="/_stcore/health",
    environment_variables={
        "LOG_LEVEL": "INFO",
        "APP_ENV": "production",
    },
)

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    container_props=container_props,
    # ... other parameters
)
```

### Custom IAM Role

You can create a custom IAM role to pass to the container, For example if you have a
backend stack that creates s3/database etc and need the app to access them.

```python
from aws_cdk import Stack
from constructs import Construct
import aws_cdk.aws_iam as iam

class MyBackEnd(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

    # ... creation of backend

    # Create custom role
    self.task_role = iam.Role(
        self,
        "CustomTaskRole",
        assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    )

    # Grant S3 access
    task_role.add_to_policy(
        iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject"],
            resources=["arn:aws:s3:::my-bucket/*"],
        )
    )

backend = MyBackEnd(app, "MyBackEnd")

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    task_role=backend.task_role,  # Use custom role
    # ... other parameters
)
```

Or if you need to simply add additional permissions for example the ability to call
bedrock, add them to the automatically generated role.


```python

web_app = WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    # ... other parameters
)

web_app.task_role.add_to_policy(...)

```

## Environment Configuration

The library automatically configures resources based on your active AWS account.
Environment-specific values (VPC, domain, Cognito user pool, WAF, etc.) are
fetched from AWS Systems Manager Parameter Store at synth time. Three parameters
are fetched and merged:

- `/gds-idea-auth` — domain, Cognito, WAF config
- `/gds-idea-ecs` — ECS cluster config
- `/gds-idea-vpc` — VPC and subnet config

These parameters are managed by Terraform and shared within each AWS account.
You do not need to create them manually.

### Development Environment

Account ID: `992382722318`

- Developers can assume task roles for local testing

### Production Environment

Account ID: `588077357019`

- Stricter security policies
- No developer assume role access

## Framework Support

The library automatically configures health check paths for common frameworks:

- **Streamlit**: `/_stcore/health`
- **Dash**: `/health`
- **FastAPI**: `/health`
- **Other**: `/health` (default)

Override with `AppConfig`:

```python
app_config = AppConfig(
    app_name="my-app",
    framework="custom",
    health_check_path="/api/healthz",
)
```

## Next Steps

- [API Reference](api/webapp.md) - Detailed API documentation
- [Authentication Guide](api/auth.md) - Configure authentication strategies
- [Contributing](contributing.md) - Contribute to the project
