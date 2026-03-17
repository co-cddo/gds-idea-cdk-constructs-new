# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project Overview

Python library of reusable AWS CDK constructs for deploying containerized web apps. Uses `hatchling` as build backend and `uv` as the package manager. Requires Python >=3.11 (targets 3.12+).

## Build and Development Commands

```bash
uv sync                                        # Install dev dependencies
uv sync --all-groups                           # Install dev + docs dependencies (needed for mkdocs)
uv run pytest                                  # Run all tests
uv run pytest --cov --cov-report=term-missing  # Run tests with coverage
uv run pytest tests/test_config.py             # Run a single test file
uv run pytest tests/test_config.py::test_fn    # Run a single test function
uv run pytest -k "test_keyword"                # Run tests matching keyword
uv run ruff check .                            # Lint (check only)
uv run ruff check --fix .                      # Lint (auto-fix)
uv run ruff format --check .                   # Format (check only)
uv run ruff format .                           # Format (apply)
uv build                                       # Build the package
uv run mkdocs build --strict                   # Build docs
uv run pre-commit run --all-files              # Run all pre-commit hooks
```

Always run `uv run ruff check .` and `uv run ruff format --check .` before committing. CI runs both plus tests on Python 3.12, 3.13, and 3.14.

## Project Structure

```
src/gds_idea_cdk_constructs/
├── __init__.py              # Public API: DeploymentConfig, DeploymentEnvironment, AppConfig
├── config.py                # DeploymentConfig, DeploymentEnvironment, AppConfig
└── web_app/
    ├── __init__.py           # Public API: WebApp, WebAppContainerProperties, AuthType
    ├── _auth_strategies.py   # IAuthStrategy ABC + implementations
    ├── props.py              # WebAppContainerProperties dataclass
    ├── stack.py              # WebApp CDK Stack
    └── lambda_handlers/
        └── acm_dns_cleanup.py
tests/
├── conftest.py              # Shared fixtures and TEST_CONFIG dict
├── test_config.py
├── test_props.py
└── web_app/
    ├── test_auth_strategies.py
    └── test_stack.py
```

## Architecture

### WebApp Stack (`stack.py`)

`WebApp` extends `Stack`. It orchestrates: VPC/Route53/S3 resource import via `DeploymentConfig`, subdomain hosted zone + ACM certificate (with `_setup_acm_clean_up()` Lambda/CustomResource to remove CNAME records before hosted zone deletion), Docker image build + Fargate service on private subnets with public IPs, ALB with HTTP-to-HTTPS redirect and access logging, authentication via strategy pattern, and WAF association (disable with `disable_waf=True` for debugging only, never in production). Always emits `ApplicationURL` and `TaskRoleARN` outputs.

### Authentication (`_auth_strategies.py`)

Strategy pattern via `IAuthStrategy` ABC with 5 abstract methods: `create_listener_action`, `create_outputs`, `get_minimal_role`, `configure_role_permissions`, `get_environment_variables`. Strategies: `NoAuthStrategy` (public), `CognitoManagedLoginAuthStrategy` (Cognito managed login UI), `CognitoExternalIdpAuthStrategy` (external IdP e.g. EntraID). Selected by `AuthType` `StrEnum` via `AUTH_STRATEGY_MAP`. Default is `AuthType.COGNITO`. `BaseCognitoAuthStrategy` provides a template method with abstract `_create_user_pool_client()` and optional `_setup_additional_resources()` hook. To add a new auth type: implement `IAuthStrategy`, add an `AuthType` value, register in `AUTH_STRATEGY_MAP`.

### DeploymentConfig (`config.py`)

Uses AWS account ID to resolve `DeploymentEnvironment` (enum values are account ID strings, e.g. `DEVELOPMENT = "992382722318"`). Fetches config from Secrets Manager at `/gds-idea/{environment}/config`. The `TESTING` environment must use `from_dict()` — `__init__` explicitly blocks it. `AppConfig` loads app metadata from `pyproject.toml [tool.webapp]`; provides framework-aware health check defaults (`/_stcore/health` for Streamlit, `/health` otherwise).

### Domain Structure

Apps deploy as `{app_name}.{domain}` subdomains with their own hosted zone + NS delegation. Cognito auth domain: `auth.{domain}`. Fargate tasks run on private subnets with `assign_public_ip=True`.

## Code Style Guidelines

### Formatting and Linting

Ruff is the sole linter/formatter (`target-version = "py312"`, line length 88). Enabled rule sets: `E`, `F`, `I` (isort), `B` (bugbear), `UP` (pyupgrade), `N` (pep8-naming), `A` (builtins), `PT` (pytest-style). Pre-commit runs `ruff-check --fix` and `ruff-format` automatically, plus `detect-aws-credentials` (blocks credential leaks).

### Imports

Follow isort ordering: stdlib → third-party → local. Use `combine-as-imports = true`. Group `aws_cdk` imports with module aliases:

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
- **Interfaces/ABCs**: `I` prefix (`IAuthStrategy`)
- **Functions/methods**: snake_case (`create_listener_action`)
- **Private methods/modules**: single underscore (`_setup_dns`, `_auth_strategies.py`)
- **Constants/maps**: UPPER_SNAKE_CASE (`AUTH_STRATEGY_MAP`)
- **Enums**: PascalCase class, UPPER_SNAKE_CASE members (`AuthType.COGNITO`)
- **Loggers**: `logger = logging.getLogger(__name__)` at module level
- **Test functions**: `test_<descriptive_name>`; files named `test_*.py` (enforced by pre-commit)

### Type Hints

- Always annotate parameters and return types in library code
- Use modern syntax: `str | None` (not `Optional[str]`), `dict[str, str]` (not `Dict`)
- Explicitly declare `-> None` on void methods
- Lambda handlers (running in AWS Lambda) may omit type hints

### Docstrings

Google-style (compatible with mkdocstrings). Test docstrings start with `"""Test that ...` or `"""Test getting ...`.

```python
def create_listener_action(self, scope: Construct) -> elbv2.ListenerAction:
    """Create the ALB listener action for this auth strategy.

    Args:
        scope: The CDK construct scope.

    Returns:
        The configured listener action.
    """
```

### Error Handling

- Raise `ValueError` for invalid inputs; use exception chaining: `raise ValueError(...) from e`
- Raise `NotImplementedError` for unimplemented features
- In tests: `pytest.raises(ExceptionType, match=r"regex")`
- Lambda handlers: catch broadly at top level, never re-raise (avoids blocking CloudFormation), use `print()` for logging

### Data Modeling

- `@dataclass` for data containers (`WebAppContainerProperties` defaults: `cpu=256`, `memory_limit_mib=512`, `desired_count=1`, `container_port=8080`, `health_check_grace_period=60`, `min_healthy_percent=50`)
- `Enum` for fixed sets of values; `StrEnum` when string values are needed (`AuthType`)
- `field(default_factory=dict)` for mutable defaults

### Design Patterns

- **Strategy pattern**: auth strategies implement `IAuthStrategy`; selected via `AUTH_STRATEGY_MAP`
- **Template method**: `BaseCognitoAuthStrategy` with `_create_user_pool_client()` (abstract) and `_setup_additional_resources()` (hook)
- **Construct composition**: `WebApp` extends `Stack` and composes CDK constructs
- Define `__all__` in `__init__.py` to control public API

### Testing

- Function-based tests with pytest fixtures (no test classes); pytest flags `--strict-markers` and `--strict-config` are active — all custom marks must be registered
- CDK Assertions: `Template.from_stack()`, `template.has_resource_properties()`, `Match.array_with()`, `Match.object_like()`, `Match.any_value()`, `Match.string_like_regexp()`
- Mock boto3 calls with `unittest.mock.patch` / `MagicMock`; use `caplog` for log assertions, `tmp_path` for filesystem tests
- Stack tests inject CDK context via `App(context=_build_cdk_context(...))` to satisfy `from_lookup` calls
- Shared fixtures and `TEST_CONFIG` dict live in `tests/conftest.py`; local fixtures go in the test file itself

### Commit Messages

Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`. Bump version in `pyproject.toml` for PRs to `main` (semver: patch for fixes, minor for features, major for breaking changes).
