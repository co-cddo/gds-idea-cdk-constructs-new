# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project Overview

Python library of reusable AWS CDK constructs for deploying containerized web apps. Uses `hatchling` as build backend and `uv` as the package manager. Requires Python >=3.11 (targets 3.12+).

## Build and Development Commands

```bash
# Install dependencies (dev group)
uv sync

# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov --cov-report=term-missing

# Run a single test file
uv run pytest tests/test_config.py

# Run a single test function
uv run pytest tests/test_config.py::test_function_name

# Run tests matching a keyword expression
uv run pytest -k "test_keyword"

# Lint (check only)
uv run ruff check .

# Lint (auto-fix)
uv run ruff check --fix .

# Format (check only)
uv run ruff format --check .

# Format (apply)
uv run ruff format .

# Build the package
uv build

# Build docs
uv run mkdocs build --strict

# Run pre-commit hooks manually
uv run pre-commit run --all-files
```

Always run `uv run ruff check .` and `uv run ruff format --check .` before committing. CI runs both plus tests on Python 3.12, 3.13, and 3.14.

## Project Structure

```
src/gds_idea_cdk_constructs/
├── __init__.py              # Public API (__all__ exports)
├── config.py                # DeploymentConfig, DeploymentEnvironment enum
└── web_app/
    ├── __init__.py           # Public API (__all__ exports)
    ├── _auth_strategies.py   # IAuthStrategy ABC + implementations
    ├── props.py              # WebAppContainerProperties dataclass
    ├── stack.py              # WebApp CDK Stack
    └── lambda_handlers/      # Lambda function code
        └── acm_dns_cleanup.py
tests/
├── test_config.py
├── test_props.py
└── web_app/
    ├── test_stack.py
    └── test_auth_strategies.py
```

## Architecture

### WebApp Stack (stack.py)

The primary construct. It orchestrates: VPC/Route53/S3 resource import via `DeploymentConfig`, subdomain hosted zone + ACM certificate, Docker image build + Fargate service, ALB with HTTP-to-HTTPS redirect and access logging, authentication via strategy pattern, and WAF association (disable with `disable_waf=True` for debugging only).

### Authentication (_auth_strategies.py)

Strategy pattern via `IAuthStrategy` ABC. Strategies: `NoAuthStrategy` (public), `CognitoManagedLoginAuthStrategy` (Cognito managed login UI), `CognitoExternalIdpAuthStrategy` (external IdP e.g. EntraID — used by `AuthType.INTERNAL_ACCESS`, the preferred default). Selected by `AuthType` enum via `AUTH_STRATEGY_MAP`. To add a new auth type: create a class implementing `IAuthStrategy`, add an `AuthType` value, register in `AUTH_STRATEGY_MAP`.

### DeploymentConfig (config.py)

Uses AWS account ID to resolve environment (DEV/PROD/TESTING) and fetches environment-specific config (VPC, domain, Cognito, WAF, etc.) from AWS Secrets Manager using the convention `/gds-idea/{environment}/config`. The `from_dict()` classmethod provides an alternative constructor for testing or local development without Secrets Manager access. To add a new environment: add a `DeploymentEnvironment` enum value and create the corresponding secret in Secrets Manager.

### Domain Structure

Apps deploy as `{app_name}.{domain}` subdomains, each with their own hosted zone + NS delegation. Cognito auth domain: `auth.{domain}`.

### Key Implementation Details

- Docker images target `Platform.LINUX_AMD64`
- ECS tasks deploy to PUBLIC subnets with public IPs
- ALB logs go to S3 with prefix `access/{app_name}.{domain}`
- WAF is on by default; never disable in production

## Code Style Guidelines

### Formatting and Linting

Ruff is the sole linter/formatter. Enabled rule sets: `E`, `F`, `I` (isort), `B` (bugbear), `UP` (pyupgrade), `N` (pep8-naming), `A` (builtins), `PT` (pytest-style). Default line length is 88 characters.

### Imports

Follow isort ordering (enforced by ruff): stdlib, third-party, local. Use `combine-as-imports = true`. Group aws_cdk imports with module aliases:

```python
from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_certificatemanager as acm,
    aws_ec2 as ec2,
    aws_ecs as ecs,
)
```

Use relative imports within the package (e.g., `from ..config import DeploymentConfig`).

### Naming Conventions

- **Classes**: PascalCase (`WebApp`, `DeploymentConfig`)
- **Interfaces/ABCs**: Prefix with `I` (`IAuthStrategy`)
- **Functions/methods**: snake_case (`create_listener_action`)
- **Private methods/modules**: Single underscore prefix (`_setup_dns`, `_auth_strategies.py`)
- **Constants/maps**: UPPER_SNAKE_CASE (`AUTH_STRATEGY_MAP`)
- **Enums**: PascalCase class, UPPER_SNAKE_CASE members (`AuthType.COGNITO`)
- **Loggers**: `logger = logging.getLogger(__name__)` at module level
- **Test files**: `test_*.py`; test functions: `test_<descriptive_name>`

### Type Hints

- Always annotate function parameters and return types in library code
- Use modern syntax: `str | None` (not `Optional[str]`), `dict[str, str]` (not `Dict`)
- Explicitly declare `-> None` on void methods
- Lambda handlers (running in AWS Lambda) may omit type hints

### Docstrings

Use Google-style docstrings (compatible with mkdocstrings):

```python
def create_listener_action(self, scope: Construct) -> elbv2.ListenerAction:
    """Create the ALB listener action for this auth strategy.

    Args:
        scope: The CDK construct scope.

    Returns:
        The configured listener action.
    """
```

Test docstrings: start with `"""Test that ...` or `"""Test getting ...`.

### Error Handling

- Raise `ValueError` for invalid inputs (unknown account IDs, bad config)
- Raise `NotImplementedError` for unfinished features
- Use exception chaining: `raise ValueError(...) from e`
- In tests, use `pytest.raises(ExceptionType, match=r"regex")`
- Lambda handlers: catch broadly at top level, never re-raise (to avoid blocking CloudFormation stack operations), use `print()` for logging

### Data Modeling

- Use `@dataclass` for simple data containers (see `WebAppContainerProperties`)
- Use `Enum` for fixed sets of values, `StrEnum` when string values are needed
- Use `field(default_factory=dict)` for mutable defaults

### Design Patterns

- **Strategy pattern**: Auth strategies implement `IAuthStrategy` ABC; selected via `AUTH_STRATEGY_MAP` dict
- **Template method**: `BaseCognitoAuthStrategy` with abstract `_create_user_pool_client()` and optional `_setup_additional_resources()` hook
- **Construct composition**: `WebApp` extends `Stack` and composes CDK constructs
- Define `__all__` in `__init__.py` to control public API

### Testing

- Use function-based tests (not class-based) with pytest fixtures
- Use CDK Assertions for infrastructure tests: `Template.from_stack()`, `template.has_resource_properties()`, `Match.array_with()`, `Match.object_like()`
- Place fixtures in the test files or `conftest.py`; use descriptive names
- Fixture docstrings: `"""Fixture for ..."""`
- Test files mirror source structure under `tests/`

### Commit Messages

Use conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`. Bump the version in `pyproject.toml` for PRs to `main` (semver: patch for fixes, minor for features, major for breaking changes).
