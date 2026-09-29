# Tagging

`IdeaTags` applies the standard GDS IDEA tags to every stack and resource in a CDK app, so anything deployed can be traced back to its environment, application, repository and owners.

## Usage

Build an `IdeaTags` in `app.py` and apply it to the `App`:

```python
import aws_cdk as cdk
from gds_idea_cdk_constructs import AppConfig, DeploymentConfig, IdeaTags

app = cdk.App()
app_config = AppConfig.from_pyproject()
dep_config = DeploymentConfig(cdk_env)

IdeaTags(
    environment=dep_config.environment,
    app_name=app_config.app_name,
    repository="gds-idea-app-example",
    owners=["Alice Example", "Bob Example"],
).apply(app)
```

Applying to the `App` tags **every stack in the app**, and every taggable resource inside them. Applying to a single stack tags only that stack.

Repos that do not use `DeploymentConfig` only need the environment enum, for example `DeploymentEnvironment.from_cdk_env(cdk_env)`.

## Tags

| Tag | Value |
|-----|-------|
| `Environment` | Lowercase environment name: `development`, `production` or `testing` |
| `ManagedBy` | Always `cdk` |
| `Repository` | The GitHub repository name, without the org |
| `AppName` | The application name |
| `Owner` | Owners joined with `+`. Only set when `owners` is not empty. Use names, not email addresses |

Extra tags can be added with `extra_tags`. They cannot override the standard keys.

```python
IdeaTags(
    environment=dep_config.environment,
    app_name="my-app",
    repository="gds-idea-app-my-app",
    extra_tags={"Name": "My App"},
).apply(app)
```

## Validation

Values are validated when the object is created, so mistakes fail on the line that defines them instead of at deploy time. A `ValueError` is raised for:

- A `repository` that is not the bare repository name, for example `gds-idea-app-example`. `org/repo`, URLs and `.git` suffixes are rejected.
- Empty values, and placeholders such as `TBA` or `TODO`.
- Characters AWS does not allow in tag values. **Commas are not allowed**, so put each owner in its own list entry rather than a comma separated string.
- `extra_tags` keys that override `Environment`, `ManagedBy`, `Repository`, `AppName` or `Owner`.

## Inspecting the tags

The resolved tags are available without a CDK app:

```python
tags = IdeaTags(
    environment=DeploymentEnvironment.DEVELOPMENT,
    app_name="my-app",
    repository="gds-idea-app-my-app",
    owners=["Alice Example", "Bob Example"],
)

tags.tags
# {
#     "Environment": "development",
#     "ManagedBy": "cdk",
#     "Repository": "gds-idea-app-my-app",
#     "AppName": "my-app",
#     "Owner": "Alice Example+Bob Example",
# }
```

`IdeaTags` is a frozen dataclass, so use `dataclasses.replace()` to make a modified copy, for example to give one nested stack a different `AppName`.

## API

::: gds_idea_cdk_constructs.tagging.IdeaTags
    options:
      show_root_heading: true
      heading_level: 3
