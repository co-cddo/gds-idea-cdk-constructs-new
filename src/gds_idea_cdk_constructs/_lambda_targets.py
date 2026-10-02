"""Helpers for Lambda functions that sit behind an ALB target group."""

from aws_cdk import Aws, Stack, aws_lambda as _lambda
from constructs import Construct

_ELB_PRINCIPAL = "elasticloadbalancing.amazonaws.com"


def scope_elb_invoke_permission(function: _lambda.Function) -> None:
    """Restrict who may invoke ``function`` to ELB target groups in its own account.

    CDK's ``LambdaTarget`` grants ``elasticloadbalancing.amazonaws.com``
    permission to invoke the function with no ``SourceArn``. That lets ANY
    load balancer in ANY AWS account register the function as a target. The
    functions behind these ALBs trust the identity headers the ALB adds, so
    an unscoped permission is an impersonation path.

    Ideally the ``SourceArn`` would name the exact target group, but
    CloudFormation requires the permission to exist before the target group
    registers the Lambda, so referencing the target group's ARN creates a
    dependency cycle. Scoping to target groups in the function's own account
    and region closes the cross-account hole without one.

    Call this after the ``LambdaTarget`` has been attached to a target group.

    Raises:
        RuntimeError: If no ELB invoke permission is found on the function.
            This fails the synth rather than silently shipping an unscoped
            permission.
    """
    stack = Stack.of(function)
    source_arn = (
        f"arn:{Aws.PARTITION}:elasticloadbalancing:"
        f"{stack.region}:{stack.account}:targetgroup/*"
    )

    scoped = 0
    for child in function.permissions_node.children:
        cfn = child.node.default_child or child
        if isinstance(cfn, _lambda.CfnPermission) and cfn.principal == _ELB_PRINCIPAL:
            cfn.source_arn = source_arn
            scoped += 1

    if not scoped:
        raise RuntimeError(
            f"No ELB invoke permission found on {function.node.path} to scope. "
            "Attach the function to a target group with LambdaTarget first."
        )


def is_in_stack(scope: Construct, stack: Stack) -> bool:
    """Whether ``scope`` belongs to ``stack``."""
    return Stack.of(scope).node.path == stack.node.path
