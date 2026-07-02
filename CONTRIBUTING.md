# Contributing to gds-idea-cdk-constructs

Thank you for your interest in contributing to this project! This guide will help you get set up and understand our development workflow.

## Prerequisites

- **Python 3.12+** - This project supports Python 3.12, 3.13, and 3.14
- **[uv](https://docs.astral.sh/uv/)** - Fast Python package manager and project manager
- **Docker** - Required for running CDK synth with container assets
- **Git** - Version control

## Getting Started

### 1. Install uv

If you don't have uv installed, install it following the [official instructions](https://docs.astral.sh/uv/getting-started/installation/):


### 2. Clone the Repository

```bash
git clone https://github.com/co-cddo/gds-idea-cdk-constructs-new.git
cd gds-idea-cdk-constructs-new
```

### 3. Install Dependencies

```bash
# Install all dependencies including dev dependencies
uv sync --all-groups
```

This will:
- Create a virtual environment (`.venv/`)
- Install all project dependencies
- Install development dependencies (pytest, ruff, etc.)

### 4. Set Up Pre-commit Hooks

We use pre-commit hooks to ensure code quality. Install them with:

```bash
uv run pre-commit install
```

The pre-commit hooks will automatically run:
- **ruff check** - Linting with auto-fix
- **ruff format** - Code formatting
- **Basic hygiene checks** - End-of-file fixer, trailing whitespace, YAML/JSON/TOML validation
- **Security checks** - Detect accidentally committed AWS credentials
- **Test naming** - Ensure test files follow pytest conventions

## Development Workflow

### Running Tests

We use pytest for testing. Run tests with:

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_config.py

# Run specific test
uv run pytest tests/test_config.py::test_deployment_environment_from_account_id_development
```

### Linting and Formatting

```bash
# Run linter
uv run ruff check .

# Run linter with auto-fix
uv run ruff check --fix .

# Format code
uv run ruff format .

# Check formatting without making changes
uv run ruff format --check .
```

### Building Documentation

```bash
# Build documentation
uv run mkdocs build

# Serve documentation locally with live reload
uv run mkdocs serve

# Documentation will be available at http://127.0.0.1:8000
```

### Building the Package

```bash
# Build distribution packages
uv build

# Output will be in dist/
```

## Making Changes

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Your Changes

- Write clean, well-documented code
- Add tests for any new functionality
- Ensure all tests pass
- Follow the existing code style (enforced by ruff)

### 3. Update Documentation

If you're adding new features or changing APIs:
- Update docstrings in the code
- Add examples to the relevant documentation files
- Update README.md if needed

### 4. Version Bumping

Versioning is handled automatically via git tags. When your PR is merged to `main`, the release workflow determines the bump level from PR labels:

- **`bump:major`** - Incompatible API changes
- **`bump:minor`** - Backwards-compatible new features
- **(default)** - Patch version bump for bug fixes

Add the appropriate label to your PR before merging. If no bump label is set, a patch bump is applied automatically.

### 5. Commit Your Changes

The pre-commit hooks will run automatically on `git commit`. If they make changes, review and stage them, then commit again.

```bash
git add .
git commit -m "feat: add support for custom security groups"
```

We follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Adding or updating tests
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

### 6. Push and Create a Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a pull request on GitHub targeting the `main` branch.

## CI/CD Workflows

### PR Checks Workflow

When you create a pull request, the following checks run automatically:

1. **Lint** - Runs `ruff check` and `ruff format --check`
2. **Test** - Runs pytest across Python 3.11, 3.12, 3.13, and 3.14
3. **Build** - Builds the package with `uv build`

All checks must pass before the PR can be merged.

### Release Workflow

When changes are merged to `main`:

1. **Auto-tag** - Determines bump level from PR labels (`bump:major`, `bump:minor`, or patch by default) and creates a git tag
2. **Publish** - Builds the package and publishes to the [GDS IDEA PyPI index](https://co-cddo.github.io/gds-idea-pypi/)

### Deploy Docs Workflow

When changes are merged to `main`:

- Builds and deploys documentation to GitHub Pages

## Project Structure

```
gds-idea-cdk-constructs/
├── src/
│   └── gds_idea_cdk_constructs/
│       ├── config.py              # Environment configuration
│       └── web_app/
│           ├── stack.py           # Main WebApp stack
│           ├── _auth_strategies.py # Authentication strategies
│           └── props.py           # Container properties
├── tests/
│   ├── test_config.py
│   ├── test_props.py
│   └── web_app/
│       ├── test_stack.py
│       └── test_auth_strategies.py
├── docs/                          # MkDocs documentation
├── .github/workflows/             # CI/CD workflows
├── pyproject.toml                 # Project configuration
└── README.md                      # User-facing documentation
```

## Writing Tests

We use pytest with a function-based style:

```python
import pytest
from aws_cdk import Environment as CdkEnvironment
from gds_idea_cdk_constructs.config import DeploymentConfig

@pytest.fixture
def test_cdk_env():
    """Fixture for TESTING CdkEnvironment."""
    return CdkEnvironment(account="testing", region="eu-west-2")

def test_deployment_config_from_dict(test_cdk_env):
    """Test DeploymentConfig from_dict construction."""
    config = DeploymentConfig.from_dict(test_cdk_env, {
        "domain_name": "test.example.com",
        "vpc_id": "vpc-test123",
        "ecs_arn": "arn:aws:ecs:eu-west-2:123456789012:cluster/test-cluster",
        "cognito_user_pool_id": "eu-west-2_TestPool",
        "waf_arn": "arn:aws:wafv2:eu-west-2:123456789012:regional/webacl/test/id",
        "waf_big_upload_arn": "arn:aws:wafv2:eu-west-2:123456789012:regional/webacl/test-upload/id",
        "logs_bucket_name": "test.example.com-logs",
    })
    assert config.environment.friendly_name == "testing"
```

For CDK stack tests, use CDK Assertions:
- `Template.from_stack()` to get CloudFormation template
- `template.has_resource_properties()` to assert resource properties
- `Match.array_with()`, `Match.object_like()` for partial matching

## Getting Help

- **Issues**: Report bugs or request features via [GitHub Issues](https://github.com/co-cddo/gds-idea-cdk-constructs-new/issues)
- **Documentation**: Check the [project documentation](https://co-cddo.github.io/gds-idea-cdk-constructs-new/)
- **Code Review**: Feel free to ask questions in your pull request

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow

Thank you for contributing!
