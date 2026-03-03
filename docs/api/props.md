# Container Properties

Configure CPU, memory, scaling, and other container-specific settings.

## Overview

The `WebAppContainerProperties` dataclass allows you to customize the ECS Fargate container configuration, including:

- CPU and memory allocation
- Number of running tasks
- Container port
- Environment variables
- Health check endpoint

## WebAppContainerProperties

::: gds_idea_cdk_constructs.web_app.props.WebAppContainerProperties
    options:
      show_root_heading: true
      heading_level: 3

## Usage Examples

### Default Configuration

```python
from gds_idea_cdk_constructs.web_app import WebApp, AuthType

# Using defaults
WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.NONE,
    # container_props not specified - uses defaults
)

# Equivalent to:
# cpu=256 (0.25 vCPU)
# memory_limit_mib=512 (512 MB)
# desired_count=1
# container_port=80
# environment_variables={}
# health_check_path=None (uses framework default)
```

### Custom CPU and Memory

```python
from gds_idea_cdk_constructs.web_app import WebAppContainerProperties

# High-performance configuration
props = WebAppContainerProperties(
    cpu=1024,              # 1 vCPU
    memory_limit_mib=2048, # 2 GB RAM
)

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    container_props=props,
    # ... other parameters
)
```

#### Valid CPU and Memory Combinations

Fargate has specific valid combinations:

| CPU (vCPU) | Memory (MB)                    |
|------------|--------------------------------|
| 256        | 512, 1024, 2048                |
| 512        | 1024, 2048, 3072, 4096         |
| 1024       | 2048, 3072, 4096, 5120, 6144, 7168, 8192 |
| 2048       | 4096 to 16384 (1GB increments) |
| 4096       | 8192 to 30720 (1GB increments) |

### Multiple Tasks (High Availability)

```python
props = WebAppContainerProperties(
    desired_count=3,  # Run 3 tasks
    cpu=512,
    memory_limit_mib=1024,
)

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    container_props=props,
    # ... other parameters
)
```

This creates 3 running containers with load balancing across them.

### Custom Port

```python
# For non-standard ports
props = WebAppContainerProperties(
    container_port=8080,  # Application listens on 8080
)

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    container_props=props,
    # ... other parameters
)
```

### Environment Variables

```python
props = WebAppContainerProperties(
    environment_variables={
        "LOG_LEVEL": "INFO",
        "DATABASE_URL": "postgresql://db.example.com/mydb",
        "REDIS_HOST": "redis.example.com",
        "REDIS_PORT": "6379",
        "FEATURE_FLAG_NEW_UI": "true",
    },
)

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    container_props=props,
    # ... other parameters
)
```

**Note:** Sensitive values (like database passwords) should be stored in AWS Secrets Manager or Systems Manager Parameter Store and accessed via IAM role, not passed as environment variables.

### Custom Health Check

```python
props = WebAppContainerProperties(
    health_check_path="/api/health",  # Override framework default
)

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    container_props=props,
    # ... other parameters
)
```

Health checks are used by:
- **ALB Target Group** - To determine if a task is healthy
- **ECS Service** - To restart unhealthy tasks

Your application must respond with HTTP 200 at this endpoint.

### Complete Example

```python
from gds_idea_cdk_constructs.web_app import WebAppContainerProperties

# Production-ready configuration
props = WebAppContainerProperties(
    # Compute resources
    cpu=512,
    memory_limit_mib=1024,

    # High availability
    desired_count=2,

    # Network
    container_port=8501,

    # Health check
    health_check_path="/_stcore/health",

    # Application config
    environment_variables={
        "LOG_LEVEL": "INFO",
        "ENVIRONMENT": "production",
        "APP_VERSION": "1.2.3",
    },
)

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.COGNITO,
    container_props=props,
)
```
