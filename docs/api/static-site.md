# StaticSite Stack

The `StaticSite` class is a CDK stack for deploying static websites with authentication, scheduled rebuilds, and serverless serving.

## Overview

`StaticSite` deploys a static website using:

- **S3** for storing built content
- **Lambda** (container-image) for building the site on a schedule
- **Lambda** (container-image) for serving files with `cognito-auth` authorization
- **ALB** with HTTPS and Cognito authentication
- **EventBridge** for scheduled rebuilds
- **WAF** integration

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Static Site Stack                              │
│                                                                        │
│  ┌────────┐    ┌─────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │Route53 │───▶│ ALB │───▶│ Cognito Auth │───▶│   Serve Lambda    │  │
│  │A Record│    │     │    │ (if enabled) │    │  (container-image) │  │
│  └────────┘    │ WAF │    └──────────────┘    │                   │  │
│                └─────┘                         │  • cognito-auth   │  │
│                                                │  • /.auth/user    │  │
│                                                │  • authZ check    │  │
│                                                │  • S3 proxy       │  │
│                                                └────────┬──────────┘  │
│                                                         │              │
│                                                         ▼              │
│  ┌───────────────┐    ┌───────────────────┐    ┌───────────────────┐ │
│  │  EventBridge  │───▶│   Build Lambda    │───▶│    S3 Bucket      │ │
│  │  (schedule)   │    │  (container-image) │    │  (static files)   │ │
│  └───────────────┘    └───────────────────┘    └───────────────────┘ │
│                               ▲                                        │
│  ┌───────────────────────────┐│                                       │
│  │ Custom Resource            ││                                       │
│  │ (auto-invoke on deploy)   │┘                                       │
│  └───────────────────────────┘                                        │
│                                                                        │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ Shared Infrastructure (from BaseWebStack)                       │   │
│  │ • Route53 subdomain hosted zone + NS delegation                │   │
│  │ • ACM certificate (DNS validated)                               │   │
│  │ • ACM cleanup Lambda (Custom Resource)                          │   │
│  └────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

On deploy, a Custom Resource auto-invokes the build Lambda so the site is immediately populated.

## StaticSite

::: gds_idea_cdk_constructs.static_site.stack.StaticSite
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - __init__

## StaticSiteProperties

::: gds_idea_cdk_constructs.static_site.props.StaticSiteProperties
    options:
      show_root_heading: true
      heading_level: 3

## Usage Examples

### Basic Example (Eleventy)

```python
from aws_cdk import App, Duration, Environment, aws_events as events
from gds_idea_cdk_constructs import AppConfig, DeploymentConfig
from gds_idea_cdk_constructs.static_site import AuthType, StaticSite, StaticSiteProperties

app = App()
cdk_env = Environment(account="992382722318", region="eu-west-2")

StaticSite(
    app,
    DeploymentConfig(cdk_env),
    AppConfig(app_name="my-docs", framework="static"),
    authentication=AuthType.INTERNAL_ACCESS,
    docker_context_path="site_src",
    dockerfile_path="Dockerfile",
    static_site_props=StaticSiteProperties(
        build_command="npx @11ty/eleventy --output=/tmp/_site",
        build_output_dir="/tmp/_site",
        build_schedule=events.Schedule.rate(Duration.hours(6)),
    ),
)

app.synth()
```

### Public Site (No Authentication)

```python
StaticSite(
    app,
    DeploymentConfig(cdk_env),
    AppConfig(app_name="public-docs", framework="static"),
    authentication=AuthType.NONE,
    docker_context_path="site_src",
    dockerfile_path="Dockerfile",
    static_site_props=StaticSiteProperties(
        build_command="npx @11ty/eleventy --output=/tmp/_site",
        build_output_dir="/tmp/_site",
    ),
)
```

### MkDocs Site (Python)

```python
StaticSite(
    app,
    DeploymentConfig(cdk_env),
    AppConfig(app_name="team-docs", framework="static"),
    authentication=AuthType.INTERNAL_ACCESS,
    docker_context_path="docs_src",
    dockerfile_path="Dockerfile",
    static_site_props=StaticSiteProperties(
        build_command="mkdocs build --site-dir /tmp/_site",
        build_output_dir="/tmp/_site",
        build_schedule=events.Schedule.rate(Duration.hours(6)),
    ),
)
```

## Dockerfile Structure

The static site uses a multi-stage Dockerfile shared between the dev container and the build Lambda:

```dockerfile
# Base stage: install build tools and dependencies
FROM node:20-slim AS base
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# Development: used by devcontainer for local development
FROM base AS development
EXPOSE 8080
CMD ["npx", "@11ty/eleventy", "--serve", "--port=8080"]

# Build Lambda: runs the build and uploads to S3
FROM public.ecr.aws/lambda/python:3.12 AS build
RUN dnf install -y nodejs20 npm
COPY --from=base /app /var/task/site
COPY handler.py /var/task/
WORKDIR /var/task/site
CMD ["handler.handler"]
```

!!! important "Lambda filesystem is read-only"
    Lambda can only write to `/tmp`. Always direct build output to `/tmp/` (e.g., `--output=/tmp/_site`) and set `build_output_dir` to the same path.

## Build Handler

The `handler.py` in your project is a construct-managed file. It:

1. Runs the configured `BUILD_COMMAND` via subprocess
2. Walks the `BUILD_OUTPUT_DIR` directory
3. Uploads all files to S3 with correct Content-Type headers

You don't need to write this file — it's provided by the construct (managed by `idea-app`).

## User Claims Endpoint

When authentication is enabled, the serve Lambda exposes a `/.auth/user` endpoint that returns the authenticated user's claims as JSON.

### Request

```
GET /.auth/user
```

### Response

```json
{
  "sub": "abc123",
  "email": "user@example.gov.uk",
  "name": "Jane Smith",
  "given_name": "Jane",
  "family_name": "Smith",
  "groups": ["gds-idea", "my-app-admins"],
  "is_admin": true,
  "email_domain": "example.gov.uk",
  "email_verified": true
}
```

### Usage in Static Site JavaScript

```html
<script>
  fetch('/.auth/user')
    .then(r => r.ok ? r.json() : null)
    .then(user => {
      if (user) {
        document.getElementById('user-email').textContent = user.email;
        document.getElementById('user-name').textContent = user.name;
      }
    });
</script>
```

This endpoint:

- Returns user claims via `cognito-auth` (includes groups from the Cognito access token)
- Sets `Cache-Control: no-store` (never cached)
- Returns `404` for `AuthType.NONE` (no authentication configured)
- Does not require an additional authentication step (ALB already authenticated the user)

## Clean Builds

By default, the build Lambda removes stale files from S3 after uploading new content. This ensures that deleted or renamed pages don't linger.

### Default behaviour (`clean_on_build=True`)

After uploading the build output, any S3 objects that were **not** part of the current build are deleted. New content is uploaded first, so there is no downtime.

### Protecting external files (`keep_prefixes`)

If external processes (ETL pipelines, data uploads) write to the same bucket, protect those files with `keep_prefixes`:

```python
StaticSiteProperties(
    build_command="npx @11ty/eleventy --output=/tmp/_site",
    build_output_dir="/tmp/_site",
    keep_prefixes=["data/", "uploads/"],
)
```

Files under `data/` and `uploads/` will never be deleted during cleanup.

### Disabling cleanup entirely

If you don't want the build to delete anything:

```python
StaticSiteProperties(
    build_command="npx @11ty/eleventy --output=/tmp/_site",
    build_output_dir="/tmp/_site",
    clean_on_build=False,
)
```

Old files will persist until manually removed.

## Created Resources

| Resource | Purpose |
|----------|---------|
| S3 Bucket | Stores built static site content |
| Serve Lambda | Proxies files from S3, handles authZ and `/.auth/user` |
| Build Lambda (container-image) | Runs the site build and uploads output to S3 |
| Application Load Balancer | HTTPS termination, Cognito auth action |
| Target Group (Lambda) | Routes ALB traffic to the serve Lambda |
| EventBridge Rule | Triggers scheduled rebuilds (if configured) |
| Custom Resource | Auto-invokes build on deploy |
| Route53 Hosted Zone | Subdomain DNS |
| ACM Certificate | TLS certificate with DNS validation |
| WAF Association | Security (enabled by default) |

## CloudFormation Outputs

- **ApplicationURL** — HTTPS URL for the static site
- **ContentBucketName** — S3 bucket name (for manual uploads or debugging)
- **BuildLambdaArn** — ARN of the build Lambda (for manual invocation)
- **TaskRoleARN** — IAM role ARN (can be assumed in DEV)
- **CognitoClientId** (Cognito auth only) — OAuth2 client ID
