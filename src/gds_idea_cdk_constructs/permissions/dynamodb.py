"""IAM helper for DynamoDB table access."""

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


def grant_dynamodb_table_access(
    task_role: iam.IRole,
    stack: Stack,
    table_name: str,
    *,
    write: bool = False,
    include_indexes: bool = True,
    region: str | None = None,
    sid: str = "DynamoDbTableAccess",
) -> None:
    """Grant read (or read/write) access to a DynamoDB table by name.

    Args:
        task_role: The role to attach the policy statement to.
        stack: The stack used to resolve region/account for the ARN.
        table_name: The DynamoDB table name.
        write: If True, also grant PutItem/UpdateItem/DeleteItem/
            BatchWriteItem.
        include_indexes: If True (default), also scope access to the
            table's Global/Local Secondary Indexes (`Query`/`Scan` against
            a GSI requires permission on the index ARN, not just the
            table ARN).
        region: Overrides the region in the ARN. Defaults to `stack.region`.
        sid: Statement ID. Override if calling multiple times on one role.
    """
    resolved_region = region or stack.region
    table_arn = f"arn:aws:dynamodb:{resolved_region}:{stack.account}:table/{table_name}"
    resources = [table_arn]
    if include_indexes:
        resources.append(f"{table_arn}/index/*")

    actions = list(_READ_ACTIONS)
    if write:
        actions += _WRITE_ACTIONS

    task_role.add_to_policy(
        iam.PolicyStatement(sid=sid, actions=actions, resources=resources)
    )
