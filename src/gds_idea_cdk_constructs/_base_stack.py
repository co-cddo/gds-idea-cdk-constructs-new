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
from aws_cdk.aws_route53_targets import LoadBalancerTarget
from constructs import Construct

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
