# Contributing

Thank you for your interest in contributing to gds-idea-cdk-constructs.

We welcome contributions of all kinds:

- 🐛 Bug fixes
- ✨ New features
- 📝 Documentation improvements
- 🧪 Additional tests
- 💡 Feature requests and ideas

## Quick Links

- [Full Contributing Guide](https://github.com/co-cddo/gds-idea-cdk-constructs-new/blob/main/CONTRIBUTING.md) - Complete guide for developers
- [GitHub Issues](https://github.com/co-cddo/gds-idea-cdk-constructs-new/issues) - Report bugs or request features
- [GitHub Discussions](https://github.com/co-cddo/gds-idea-cdk-constructs-new/discussions) - Ask questions and discuss ideas

## Quick Start

```bash
# Clone the repository
git clone https://github.com/co-cddo/gds-idea-cdk-constructs-new.git
cd gds-idea-cdk-constructs-new

# Install dependencies
uv sync --all-groups

# Set up pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest

# Build documentation
uv run mkdocs serve
```

## Development Workflow

1. **Fork and clone** the repository
2. **Create a branch** for your changes (`git checkout -b feature/my-feature`)
3. **Make your changes** with tests and documentation
4. **Push and create a PR** targeting the `main` branch
5. **Add a bump label** (`bump:major`, `bump:minor`, or default patch) to the PR

## Code Quality

We use:

- **Ruff** for linting and formatting (configured in `pyproject.toml`)
- **pytest** for testing (aim for 100% coverage)
- **pre-commit hooks** to ensure code quality before commit

All PRs must pass:

- ✅ Linting (`ruff check`)
- ✅ Formatting (`ruff format --check`)
- ✅ Tests (`pytest`)
- ✅ Build (`uv build`)

## Documentation

- Update docstrings for any API changes
- Add examples to relevant documentation pages
- Build docs locally to verify: `uv run mkdocs serve`

## Need Help?

- Check the [full contributing guide](https://github.com/co-cddo/gds-idea-cdk-constructs-new/blob/main/CONTRIBUTING.md)
- Open a [GitHub Discussion](https://github.com/co-cddo/gds-idea-cdk-constructs-new/discussions)
- Ask questions in your PR - we're happy to help!

Thank you for contributing.
