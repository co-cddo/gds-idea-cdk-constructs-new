"""Base stack with shared infrastructure for web-facing applications."""

import logging
from pathlib import Path

from aws_cdk import (
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_certificatemanager as acm,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_route53 as route53,
    aws_s3 as s3,
    aws_wafv2 as wafv2,
    custom_resources as cr,
)
from aws_cdk.aws_elasticloadbalancingv2_targets import LambdaTarget
from aws_cdk.aws_route53_targets import LoadBalancerTarget
from constructs import Construct

from ._lambda_targets import is_in_stack, scope_elb_invoke_permission
from .config import AppConfig, DeploymentConfig, DeploymentEnvironment
from .web_app._auth_strategies import AUTH_STRATEGY_MAP, AuthType, IAuthStrategy

logger = logging.getLogger(__name__)


class BaseWebStack(Stack):
    """Base class for web stacks with shared DNS, ACM, ALB, and WAF infrastructure.

    Provides common infrastructure setup methods shared between WebApp (ECS Fargate)
    and StaticSite (Lambda + S3) stacks. Subclasses create their own compute
    resources and target groups, then use these shared methods for networking,
    DNS, TLS, and security.

    Args:
        scope: The CDK app or stack to create this stack within.
        deployment_config: Environment-specific configuration including VPC,
            domain name, and AWS resource identifiers.
        app_config: Application configuration including name and framework.
        authentication: Authentication strategy to use.
    """

    def __init__(
        self,
        scope: Construct,
        deployment_config: DeploymentConfig,
        app_config: AppConfig,
        authentication: AuthType,
        **kwargs,
    ) -> None:
        # Generate stack ID from app_name
        stack_id = f"{app_config.app_name}-stack"

        # Initialize the Stack with the CDK environment
        super().__init__(scope, stack_id, env=deployment_config.cdk_env, **kwargs)

        self.deployment_config = deployment_config
        self.app_config = app_config
        self.app_name = app_config.app_name

        # Derived configuration
        self.alb_domain_name = f"{self.app_name}.{self.deployment_config.domain_name}"

        # Select the auth strategy
        strategy_class = AUTH_STRATEGY_MAP.get(authentication)

        if not strategy_class:
            raise ValueError(f"Unsupported authentication type: {authentication}")

        self._auth_strategy: IAuthStrategy = strategy_class(
            self,
            deployment_config,
            self.app_name,
        )

    def _import_existing_resources(self) -> None:
        """Import existing VPC and other shared resources."""
        self.vpc = ec2.Vpc.from_lookup(
            self, "ExistingVPC", vpc_id=self.deployment_config.vpc_id
        )

        self.parent_hosted_zone = route53.HostedZone.from_lookup(
            self, "HostedZone", domain_name=self.deployment_config.domain_name
        )

        self.log_bucket = s3.Bucket.from_bucket_name(
            self, "ALBAccessLogsBucket", self.deployment_config.log_bucket_name
        )

    def _setup_dns_and_certificate(self) -> None:
        """Create subdomain hosted zone, NS delegation, and ACM certificate."""
        self.app_hosted_zone = route53.HostedZone(
            self, "AppHostedZone", zone_name=self.alb_domain_name
        )
        route53.NsRecord(
            self,
            "NsRecord",
            zone=self.parent_hosted_zone,
            record_name=self.app_name,
            values=self.app_hosted_zone.hosted_zone_name_servers,
        )
        self.certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=self.alb_domain_name,
            validation=acm.CertificateValidation.from_dns(self.app_hosted_zone),
        )

        self.certificate.apply_removal_policy(RemovalPolicy.DESTROY)
        self.app_hosted_zone.apply_removal_policy(RemovalPolicy.DESTROY)

    def _setup_acm_clean_up(self) -> None:
        """Create Lambda and Custom Resource to clean up ACM DNS records on deletion."""
        lambda_handlers_path = Path(__file__).parent / "_lambda_handlers"
        cleanup_fn = _lambda.Function(
            self,
            "AcmDnsCleanupFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="acm_dns_cleanup.handler",
            timeout=Duration.minutes(2),
            code=_lambda.Code.from_asset(str(lambda_handlers_path)),
            initial_policy=[
                iam.PolicyStatement(
                    actions=[
                        "route53:ListResourceRecordSets",
                        "route53:ChangeResourceRecordSets",
                    ],
                    resources=[
                        f"arn:aws:route53:::hostedzone/{self.app_hosted_zone.hosted_zone_id}"
                    ],
                )
            ],
        )

        cleanup_provider = cr.Provider(
            self, "AcmDnsCleanupProvider", on_event_handler=cleanup_fn
        )

        cleanup_resource = CustomResource(
            self,
            "AcmDnsCleanupResource",
            service_token=cleanup_provider.service_token,
            properties={
                "ZoneId": self.app_hosted_zone.hosted_zone_id,
                "DomainName": self.alb_domain_name,
            },
        )

        # Ensure clean up happens before zone is deleted.
        cleanup_resource.node.add_dependency(self.app_hosted_zone)

    def _setup_alb_and_listeners(
        self, target_group: elbv2.IApplicationTargetGroup
    ) -> None:
        """Create ALB with HTTP-to-HTTPS redirect and authenticated HTTPS listener.

        Args:
            target_group: The target group to forward authenticated traffic to.
        """
        self.load_balancer = elbv2.ApplicationLoadBalancer(
            self,
            "LoadBalancer",
            vpc=self.vpc,
            internet_facing=True,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC, one_per_az=True
            ),
        )
        self.load_balancer.log_access_logs(
            self.log_bucket, prefix=f"access/{self.alb_domain_name}"
        )

        self.load_balancer.add_listener(
            "HttpListener",
            port=80,
            default_action=elbv2.ListenerAction.redirect(
                protocol="HTTPS", port="443", permanent=True
            ),
        )

        # Delegate listener action to the auth strategy
        default_https_action = self._auth_strategy.create_listener_action(target_group)

        self.https_listener = self.load_balancer.add_listener(
            "HttpsListener",
            port=443,
            certificates=[self.certificate],
            default_action=default_https_action,
        )

        self.load_balancer.node.add_dependency(self.certificate)

    # Env vars that tell cognito-auth which user pool / app client / ALB to
    # trust. Everything else the strategy emits (e.g. the authorisation secret
    # name) is specific to this app and is not re-exported.
    _COGNITO_PIN_ENV_VARS = ("COGNITO_AUTH_USER_POOL_ID", "COGNITO_AUTH_CLIENT_IDS")

    def cognito_pin_environment_variables(self) -> dict[str, str]:
        """Env vars that pin ``cognito-auth`` to this app's pool, client and ALB.

        Put these on any Lambda or container that verifies this app's ALB
        tokens, otherwise ``cognito-auth`` accepts tokens from any Cognito
        user pool and any AWS load balancer. ``add_lambda_route`` does this
        for you. Empty for apps with no authentication.

        Only valid once the load balancer exists.
        """
        pins = {
            name: value
            for name, value in self._auth_strategy.get_environment_variables().items()
            if name in self._COGNITO_PIN_ENV_VARS
        }
        pins.update(
            self._auth_strategy.get_load_balancer_environment_variables(
                self.load_balancer.load_balancer_arn
            )
        )
        return pins

    def add_lambda_route(
        self,
        scope: Construct,
        route_id: str,
        *,
        function: _lambda.Function,
        path_patterns: list[str],
        priority: int,
        pin_cognito_auth: bool = True,
    ) -> elbv2.ApplicationTargetGroup:
        """Route ``path_patterns`` on this app's ALB to a Lambda function.

        The route goes through this app's own authentication action, so it
        shares the site's login and session. The function receives the
        verified ``x-amzn-oidc-*`` headers; verify them with ``cognito-auth``.

        The function may live in another stack (pass that stack, or a
        construct in it, as ``scope``). Everything the route needs is then
        created in that stack, on an imported listener, so the dependency
        only ever points from that stack to this one. Referencing resources
        of the other stack from this one would make the dependency circular.

        This also:

        - scopes the function's ELB invoke permission to target groups in its
          own account (see ``scope_elb_invoke_permission``), and
        - sets the ``COGNITO_AUTH_*`` pin env vars on the function, so
          ``cognito-auth`` only trusts this app's user pool, app client and ALB
          (disable with ``pin_cognito_auth=False``).

        Args:
            scope: Construct (typically a stack) to create the route in.
            route_id: Unique id for the route within ``scope``.
            function: The Lambda function to route to.
            path_patterns: ALB path patterns, e.g. ``["/api/admin/*"]``.
            priority: Listener rule priority. Must be unique on the listener.
            pin_cognito_auth: Add the ``COGNITO_AUTH_*`` pin env vars.

        Returns:
            The Lambda target group.
        """
        target_group = elbv2.ApplicationTargetGroup(
            scope,
            f"{route_id}TargetGroup",
            vpc=self.vpc,
            target_type=elbv2.TargetType.LAMBDA,
            targets=[LambdaTarget(function)],
        )
        scope_elb_invoke_permission(function)

        if pin_cognito_auth:
            for name, value in self.cognito_pin_environment_variables().items():
                function.add_environment(name, value)

        conditions = [elbv2.ListenerCondition.path_patterns(path_patterns)]
        action = self._auth_strategy.create_listener_action(target_group)

        if is_in_stack(scope, self):
            self.https_listener.add_action(
                route_id, priority=priority, conditions=conditions, action=action
            )
        else:
            listener = elbv2.ApplicationListener.from_application_listener_attributes(
                scope,
                f"{route_id}Listener",
                listener_arn=self.https_listener.listener_arn,
                security_group=ec2.SecurityGroup.from_security_group_id(
                    scope,
                    f"{route_id}ListenerSecurityGroup",
                    self.load_balancer.connections.security_groups[0].security_group_id,
                ),
            )
            elbv2.ApplicationListenerRule(
                scope,
                route_id,
                listener=listener,
                priority=priority,
                conditions=conditions,
                action=action,
            )

        return target_group

    def _setup_dns_record(self) -> None:
        """Create A record pointing the subdomain to the ALB."""
        self.a_record = route53.ARecord(
            self,
            "ARecord",
            zone=self.app_hosted_zone,
            target=route53.RecordTarget.from_alias(
                LoadBalancerTarget(self.load_balancer)
            ),
        )

    def _associate_waf(self) -> None:
        """Associate WAF WebACL with the ALB."""
        self.waf_association = wafv2.CfnWebACLAssociation(
            self,
            "WAF-ALB-Association",
            resource_arn=self.load_balancer.load_balancer_arn,
            web_acl_arn=self.deployment_config.waf_arn,
        )

    def _add_assume_policy_for_dev(self) -> None:
        """Add ability for devs to assume the task role in DEV environment."""
        dev_account_id = DeploymentEnvironment.DEVELOPMENT.value
        self.task_role.assume_role_policy.add_statements(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.AccountPrincipal(dev_account_id)],
                actions=["sts:AssumeRole"],
                conditions={
                    "StringLike": {
                        "aws:PrincipalArn": [
                            f"arn:aws:iam::{dev_account_id}:role/*-poweraccess",
                            f"arn:aws:iam::{dev_account_id}:role/*-admin",
                        ]
                    }
                },
            )
        )
        logger.info(
            "Dev container access enabled: (*-poweraccess, *-admin) "
            "can assume TaskRole for local development"
        )
