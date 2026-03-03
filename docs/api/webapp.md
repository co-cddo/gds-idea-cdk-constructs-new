# WebApp Stack

The `WebApp` class is the main CDK stack for deploying containerized web applications.

## Overview

`WebApp` is a complete AWS CDK Stack that creates and configures all resources needed to run a containerized web application, including:

- ECS Fargate cluster and service
- Application Load Balancer with HTTPS
- Route53 DNS records and ACM certificates
- Optional Cognito authentication
- WAF integration
- CloudWatch logging

## WebApp

::: gds_idea_cdk_constructs.web_app.stack.WebApp
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - __init__

## Usage Examples

### Minimal Example

```python
from aws_cdk import App
from gds_idea_cdk_constructs.config import DeploymentConfig, AppConfig
from gds_idea_cdk_constructs.web_app import WebApp, AuthType

app = App()

deployment_config = DeploymentConfig(cdk_env)
app_config = AppConfig(app_name="simple-app", framework="streamlit")

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.INTERNAL_ACCESS,
    docker_context_path=".",
    dockerfile_path="Dockerfile",
)

app.synth()
```

### Public Application

```python
WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.NONE,  # No authentication
    docker_context_path="./app",
    dockerfile_path="app/Dockerfile",
)
```

### Advanced Configuration

```python
from gds_idea_cdk_constructs.web_app import WebAppContainerProperties
import aws_cdk.aws_iam as iam

# Custom container configuration
container_props = WebAppContainerProperties(
    cpu=512,
    memory_limit_mib=1024,
    desired_count=2,
    container_port=8501,
    health_check_path="/_stcore/health",
    environment_variables={
        "LOG_LEVEL": "INFO",
        "DATABASE_URL": "postgresql://...",
    },
)
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

# Create stack with advanced options
WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.INTERNAL_ACCESS,
    docker_context_path=".",
    dockerfile_path="Dockerfile",
    container_props=container_props,
    task_role=task_role,
)
```

### Debugging with WAF Disabled

!!! warning "Security Warning"
    **Only for debugging** - Never use `disable_waf=True` in production environments. This removes critical security protections against web exploits.

When troubleshooting WAF rule blocks during development, you can temporarily disable WAF:

```python
# TEMPORARY DEBUGGING ONLY
WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.INTERNAL_ACCESS,
    docker_context_path=".",
    dockerfile_path="Dockerfile",
    disable_waf=True,  # WARNING: Removes security protections!
)
```

**Use cases:**
- Debugging legitimate traffic being blocked by WAF rules
- Isolating whether issues are caused by WAF vs application code
- Short-term testing during WAF rule development

**Best practices:**
- Time-box usage (e.g., "disable for 1 hour while testing")
- Never commit `disable_waf=True` to version control
- Re-enable immediately after debugging
- Consider adjusting WAF rules instead of disabling entirely

## Created Resources

When you create a `WebApp`, the following AWS resources are automatically created:

### Networking

- **VPC** (imported) - Uses existing VPC from deployment config
- **Subnets** - Uses public subnets for Fargate tasks
- **Security Groups** - Automatically configured for ALB and ECS

### Compute

- **ECS Cluster** - Fargate cluster for running containers
- **Task Definition** - Container configuration
- **Fargate Service** - Managed service with desired count

### Load Balancing

- **Application Load Balancer** - Internet-facing ALB
- **Target Group** - Routes traffic to ECS tasks
- **Listeners**:
    - HTTP (port 80) - Redirects to HTTPS
    - HTTPS (port 443) - Forwards to target group

### DNS & TLS

- **Route53 Hosted Zone** - Subdomain for your application
- **NS Record** - Links subdomain to parent hosted zone
- **A Record** - Points domain to load balancer
- **ACM Certificate** - TLS certificate with DNS validation

### Authentication (Cognito only)

- **User Pool Client** - OAuth2 client for ALB authentication
- **Secrets Manager Secret** - Stores client credentials

### Security

- **WAF Association** (optional) - By default, links the environment's WAF Web ACL to the Application Load Balancer, providing protection against common web exploits including:
    - SQL injection attacks
    - Cross-site scripting (XSS)
    - HTTP floods and DDoS attempts
    - Known malicious IP addresses

    The WAF can be temporarily disabled using `disable_waf=True` for debugging purposes. **Never disable WAF in production environments.**

- **IAM Roles**:
    - Task Role - For application permissions (can be custom or auto-generated)
    - Execution Role - For ECS to pull images and write logs

- **TLS/HTTPS Enforcement** - All HTTP traffic is automatically redirected to HTTPS

- **Security Groups** - Automatically configured with least-privilege access

### Monitoring

- **CloudWatch Log Group** - Container logs
- **S3 Access Logs** - ALB access logs

## CloudFormation Outputs

The stack creates the following outputs:

- **ApplicationURL** - HTTPS URL for your application
- **TaskRoleARN** - ARN of the ECS task role (can be assumed in DEV)
- **CognitoClientId** (Cognito only) - OAuth2 client ID

## Development Features

### Dev Environment Assume Role

In the development environment, the task role can be assumed by developers with `*-poweraccess` or `*-admin` roles. This enables:

- Local testing with AWS credentials
- Debugging with production-like IAM permissions
- Development without modifying production policies


This feature is **disabled** in production environments.
