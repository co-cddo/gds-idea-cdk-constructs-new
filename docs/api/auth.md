# Authentication Strategies

The authentication module provides pluggable authentication strategies for the WebApp construct.

## Overview

Authentication is implemented allowing you to choose between different authentication methods without changing your application code.

### Available Strategies

- **`AuthType.NONE`** - No authentication (public access)
- **`AuthType.COGNITO`** - AWS Cognito authentication with OAuth2 (managed login UI)
- **`AuthType.INTERNAL_ACCESS`** - AWS Cognito authentication with external IdP (e.g., EntraID)

## AuthType

::: gds_idea_cdk_constructs.web_app._auth_strategies.AuthType
    options:
      show_root_heading: true
      heading_level: 3

## IAuthStrategy (Interface)

::: gds_idea_cdk_constructs.web_app._auth_strategies.IAuthStrategy
    options:
      show_root_heading: true
      heading_level: 3

## NoAuthStrategy

::: gds_idea_cdk_constructs.web_app._auth_strategies.NoAuthStrategy
    options:
      show_root_heading: true
      heading_level: 3

## BaseCognitoAuthStrategy

::: gds_idea_cdk_constructs.web_app._auth_strategies.BaseCognitoAuthStrategy
    options:
      show_root_heading: true
      heading_level: 3

## CognitoManagedLoginAuthStrategy

::: gds_idea_cdk_constructs.web_app._auth_strategies.CognitoManagedLoginAuthStrategy
    options:
      show_root_heading: true
      heading_level: 3

## CognitoExternalIdpAuthStrategy

::: gds_idea_cdk_constructs.web_app._auth_strategies.CognitoExternalIdpAuthStrategy
    options:
      show_root_heading: true
      heading_level: 3

## Usage Examples

### No Authentication (Public Access)

```python
from gds_idea_cdk_constructs.web_app import WebApp, AuthType

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.NONE,  # Public access
)
```

**Use cases:**
- Public dashboards
- Open APIs
- Status pages
- Documentation sites

**Behavior:**
- No authentication required
- Direct access to application
- Minimal IAM permissions
- No environment variables added to container

### Cognito Authentication

```python
from gds_idea_cdk_constructs.web_app import WebApp, AuthType

WebApp(
    app,
    deployment_config=deployment_config,
    app_config=app_config,
    authentication=AuthType.COGNITO,  # Requires login
)
```

**Use cases:**
- Internal tools and dashboards
- Applications requiring user identity
- Protected data visualization
- Admin panels

**Behavior:**
- Users must authenticate via Cognito
- ALB performs authentication before forwarding requests
- OAuth2 authorization code flow
- Session cookies for authenticated users
- Automatic redirect to Cognito login page

**What gets created:**
- Cognito User Pool Client (OAuth2 client)
- Secrets Manager secret for client credentials
- ALB listener rule with authentication action
- IAM permissions for secret access

**Environment variables added to container:**
```python
{
    "COGNITO_AUTH_SECRET_NAME": "app-name/access"
}
```


### Authentication Flow (Cognito)

```
┌─────────┐         ┌─────────┐         ┌─────────┐         ┌─────────┐
│ Browser │         │   ALB   │         │ Cognito │         │   ECS   │
└────┬────┘         └────┬────┘         └────┬────┘         └────┬────┘
     │                   │                   │                   │
     │  1. GET /         │                   │                   │
     ├──────────────────>│                   │                   │
     │                   │                   │                   │
     │  2. No auth cookie, redirect to Cognito                   │
     │<──────────────────┤                   │                   │
     │                   │                   │                   │
     │  3. Login page    │                   │                   │
     ├───────────────────────────────────────>│                   │
     │                   │                   │                   │
     │  4. User logs in  │                   │                   │
     ├───────────────────────────────────────>│                   │
     │                   │                   │                   │
     │  5. OAuth callback with code          │                   │
     │<───────────────────────────────────────┤                   │
     │                   │                   │                   │
     │  6. Exchange code for tokens          │                   │
     ├──────────────────>├───────────────────>│                   │
     │                   │                   │                   │
     │  7. Set auth cookie & forward request │                   │
     ├──────────────────>├───────────────────────────────────────>│
     │                   │                   │                   │
     │  8. Response      │                   │                   │
     │<──────────────────┴───────────────────────────────────────┤
```

## Accessing User Information (Cognito)

Please see our repo https://github.com/co-cddo/gds-idea-app-auth which automatically
validates and verifies tokens to provide you with a user object containing user details.


## Security Considerations

### NoAuth

- ⚠️ **No access control** - Anyone can access your application
- ✅ Use for truly public content only
- ✅ Consider WAF rules for rate limiting
- ✅ Ensure application doesn't expose sensitive data

### Cognito

- ✅ **OAuth2 standard** - Industry-standard authentication
- ✅ **Session management** - ALB handles session cookies
- ✅ **User pool integration** - Leverages existing user directory
