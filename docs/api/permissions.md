# Permissions

Reusable IAM grant helpers. Each `grant_*` function takes an `iam.IGrantable` (a `Role`, `Function`, `Instance`, `Service`, etc.) as its first argument and attaches a scoped policy statement to it. Use them for resources you do not own as CDK constructs, such as shared buckets, tables, secrets and rAPId.

## Usage

```python
from gds_idea_cdk_constructs.permissions import (
    AthenaSettings,
    grant_athena,
    grant_s3_read,
    grant_secret_read,
)

grant_secret_read(webapp.task_role, stack, "my-app/access")
grant_s3_read(webapp.task_role, "my-data-bucket")

athena_settings = AthenaSettings(cdk_env)
grant_athena(webapp.task_role, athena_settings, "my_database", "my-data-bucket")
```

S3 and DynamoDB helpers come in `read`, `write` and `read_write` variants. Every helper accepts an optional `sid`, which is omitted by default so the helpers are safe to call more than once on the same principal.

## AthenaSettings

`AthenaSettings` reads the `/gds-idea-athena` SSM parameter, a flat JSON object holding the current account's `results_bucket_name` and `kms_key_arn`. Use `AthenaSettings.from_dict(cdk_env, config)` in tests.

::: gds_idea_cdk_constructs.permissions.settings.AthenaSettings
    options:
      show_root_heading: true
      heading_level: 3

## Grant helpers

::: gds_idea_cdk_constructs.permissions.athena.grant_athena
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.athena.grant_athena_workgroup
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.athena.grant_glue_catalog
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.athena.grant_athena_results
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.athena.grant_kms_encrypt_decrypt
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.s3.grant_s3_read
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.s3.grant_s3_write
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.s3.grant_s3_read_write
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.secrets.grant_secret_read
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.bedrock.grant_bedrock_invoke_model
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.dynamodb.grant_dynamodb_read_data
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.dynamodb.grant_dynamodb_write_data
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.dynamodb.grant_dynamodb_read_write_data
    options:
      show_root_heading: true
      heading_level: 3

::: gds_idea_cdk_constructs.permissions.rapid.grant_rapid_database
    options:
      show_root_heading: true
      heading_level: 3
