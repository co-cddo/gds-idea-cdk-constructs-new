"""IAM helpers for DynamoDB table access."""

from aws_cdk import Stack, aws_iam as iam

_READ_ACTIONS = [
    "dynamodb:GetItem",
    "dynamodb:BatchGetItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "dynamodb:DescribeTable",
]
_WRITE_ACTIONS = [
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem",
]


def _grant_dynamodb(
    grantee: iam.IGrantable,
    stack: Stack,
    table_name: str,
    actions: list[str],
    include_indexes: bool,
    region: str | None,
    sid: str | None,
) -> None:
    """Add a single statement with the given actions on a table (and indexes).

    Args:
        grantee: The IAM principal to grant permissions to.
        stack: The stack used to resolve region/account for the ARN.
        table_name: The DynamoDB table name.
        actions: The DynamoDB actions to allow.
        include_indexes: Whether to also cover the table's indexes.
        region: Overrides the region in the ARN. Defaults to `stack.region`.
        sid: Optional statement ID.
    """
    resolved_region = region or stack.region
    table_arn = f"arn:aws:dynamodb:{resolved_region}:{stack.account}:table/{table_name}"
    resources = [table_arn]
    if include_indexes:
        resources.append(f"{table_arn}/index/*")

    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            **({"sid": sid} if sid else {}), actions=actions, resources=resources
        )
    )


def grant_dynamodb_read_data(
    grantee: iam.IGrantable,
    stack: Stack,
    table_name: str,
    *,
    include_indexes: bool = True,
    region: str | None = None,
    sid: str | None = None,
) -> None:
    """Grant read access to a DynamoDB table by name.

    Grants `GetItem`, `BatchGetItem`, `Query`, `Scan` and `DescribeTable`.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        stack: The stack used to resolve region/account for the ARN.
        table_name: The DynamoDB table name.
        include_indexes: If True (default), also scope access to the
            table's Global/Local Secondary Indexes (`Query`/`Scan` against
            a GSI requires permission on the index ARN, not just the
            table ARN).
        region: Overrides the region in the ARN. Defaults to `stack.region`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    _grant_dynamodb(
        grantee, stack, table_name, _READ_ACTIONS, include_indexes, region, sid
    )


def grant_dynamodb_write_data(
    grantee: iam.IGrantable,
    stack: Stack,
    table_name: str,
    *,
    include_indexes: bool = True,
    region: str | None = None,
    sid: str | None = None,
) -> None:
    """Grant write access to a DynamoDB table by name.

    Grants `PutItem`, `UpdateItem`, `DeleteItem` and `BatchWriteItem`.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        stack: The stack used to resolve region/account for the ARN.
        table_name: The DynamoDB table name.
        include_indexes: If True (default), also scope access to the
            table's Global/Local Secondary Indexes.
        region: Overrides the region in the ARN. Defaults to `stack.region`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    _grant_dynamodb(
        grantee, stack, table_name, _WRITE_ACTIONS, include_indexes, region, sid
    )


def grant_dynamodb_read_write_data(
    grantee: iam.IGrantable,
    stack: Stack,
    table_name: str,
    *,
    include_indexes: bool = True,
    region: str | None = None,
    sid: str | None = None,
) -> None:
    """Grant read and write access to a DynamoDB table by name.

    Combines the actions of `grant_dynamodb_read_data` and
    `grant_dynamodb_write_data` in a single statement.

    Args:
        grantee: The IAM principal to grant permissions to (e.g. a Role,
            Lambda Function, EC2 Instance, ECS Service, etc.).
        stack: The stack used to resolve region/account for the ARN.
        table_name: The DynamoDB table name.
        include_indexes: If True (default), also scope access to the
            table's Global/Local Secondary Indexes.
        region: Overrides the region in the ARN. Defaults to `stack.region`.
        sid: Optional statement ID. Omitted by default; a `Sid` only needs
            to be unique within a policy document if one is set, so this
            is safe to call multiple times on the same role.
    """
    _grant_dynamodb(
        grantee,
        stack,
        table_name,
        _READ_ACTIONS + _WRITE_ACTIONS,
        include_indexes,
        region,
        sid,
    )
