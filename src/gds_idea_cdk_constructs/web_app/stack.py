import logging
from collections.abc import Sequence
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_certificatemanager as acm,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_route53 as route53,
    aws_s3 as s3,
    aws_wafv2 as wafv2,
    custom_resources as cr,
)
from aws_cdk.aws_ecr_assets import Platform
from aws_cdk.aws_route53_targets import LoadBalancerTarget
from constructs import Construct

from ..config import AppConfig, DeploymentConfig, DeploymentEnvironment
from ._auth_strategies import AUTH_STRATEGY_MAP, AuthType, IAuthStrategy
from ._dashboard import AppUsageDashboard
from .props import WebAppContainerProperties

logger = logging.getLogger(__name__)


class WebApp(Stack):
    """
    A configurable web application stack with a simplified API for authentication.
    """

    def __init__(
        self,
        scope: Construct,
        deployment_config: DeploymentConfig,
        app_config: AppConfig,
        authentication: AuthType = AuthType.COGNITO,
        docker_context_path: str = ".",
        dockerfile_path: str = "app_src/Dockerfile",
        container_props: WebAppContainerProperties | None = None,
        task_role: iam.Role | None = None,
        disable_waf: bool = False,
        cross_account_access: bool = False,
        enable_usage_dashboard: bool = True,
        dashboard_show_user_emails: bool = False,
        dashboard_extra_widgets: Sequence[cloudwatch.IWidget] | None = None,
    ) -> None:
        """Initialize a WebApp stack with containerized application infrastructure.

        Creates a complete web application deployment including ECS Fargate service,
        Application Load Balancer with HTTPS, Route53 DNS records, ACM certificate,
        and optional Cognito authentication.

        Args:
            scope: The CDK app or stack to create this stack within.
            deployment_config: Environment-specific configuration including VPC,
                domain name, and AWS resource identifiers.
            app_config: Application configuration including name, framework, and
                health check settings.
            authentication: Authentication strategy to use. Defaults to
                AuthType.COGNITO. Options: COGNITO, INTERNAL_ACCESS, or NONE.
            docker_context_path: Path to the Docker build context directory.
                Defaults to current directory (".").
            dockerfile_path: Path to the Dockerfile relative to docker_context_path.
                Defaults to "app_src/Dockerfile".
            container_props: Custom container configuration (CPU, memory, count, etc.).
                If None, uses default values from WebAppContainerProperties.
            task_role: Custom IAM role for the ECS task. If None, a minimal
                role will be created with permissions required by the
                authentication strategy. If provided, the strategy will augment
                it with necessary permissions.
            disable_waf: Disable WAF association with the ALB. Defaults to False.
                When True, the Web Application Firewall will NOT be associated with
                the Application Load Balancer. **WARNING: This should ONLY be used
                for short-term debugging when WAF rules are blocking legitimate traffic.
                Never use in production. Disabling WAF removes critical security
                protections against common web exploits.**
            cross_account_access: Enable cross-account access to production resources.
                Defaults to False. When True and deploying to a non-production
                environment, grants the task role sts:AssumeRole permission on
                the cross-account role and injects CROSS_ACCOUNT_ROLE_ARN as a
                container environment variable.
            enable_usage_dashboard: When ``True`` (default), create a standard
                CloudWatch usage dashboard for this app. See
                :class:`AppUsageDashboard` for the widgets included.
            dashboard_show_user_emails: When ``True``, the Active users widget
                on the usage dashboard lists individual user emails and their
                last login time. When ``False`` (default), it shows an
                aggregate distinct-user count. Ignored when
                ``enable_usage_dashboard`` is ``False``.
            dashboard_extra_widgets: Optional additional CloudWatch widgets to
                append to the usage dashboard, after the standard Successful
                sign-ins, Active users and Requests widgets. Ignored when
                ``enable_usage_dashboard`` is ``False``.

        Example:
            Basic usage with Cognito authentication::

                app = App()
                deployment_config = DeploymentConfig(cdk_env)
                app_config = AppConfig.from_pyproject()

                WebApp(
                    app,
                    deployment_config,
                    app_config,
                    authentication=AuthType.COGNITO,
                    docker_context_path=".",
                    dockerfile_path="Dockerfile",
                )

        Note:
            The stack automatically creates all required infrastructure including
            VPC subnets lookup, DNS hosted zone, SSL certificate, load balancer,
            ECS cluster lookup, Fargate task definition and service, and optional
            Cognito user pool client configuration.
        """
        # Generate stack ID from app_name
        stack_id = f"{app_config.app_name}-stack"

        # Initialize the Stack with the CDK environment
        super().__init__(scope, stack_id, env=deployment_config.cdk_env)

        self.deployment_config = deployment_config
        self.app_config = app_config
        self.app_name = app_config.app_name
        self.container_props = (
            container_props or WebAppContainerProperties()
        )  # Load the default values

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

        # Configure task role based on whether a custom role is provided
        if task_role:
            # Custom role provided - augment it with auth-specific permissions
            self.task_role = task_role
            self._auth_strategy.configure_role_permissions(self.task_role)
        else:
            # No custom role - let strategy create a properly configured one
            self.task_role = self._auth_strategy.get_minimal_role()

        # Let users assume the role if we are deploying in dev.
        if self.deployment_config.environment == DeploymentEnvironment.DEVELOPMENT:
            self._add_assume_policy_for_dev()

        # Cross-account access to production resources from non-prod environments
        self._cross_account_env: dict[str, str] = {}
        if cross_account_access:
            self._setup_cross_account_access()

        logger.info(
            f"Creating web app: {self.app_name} with authentication: {authentication}"
        )
        logger.info(f"Domain: {self.alb_domain_name}")

        self._import_existing_resources()
        self._setup_dns_and_certificate()
        self._setup_acm_clean_up()
        self._setup_ecs_resources(docker_context_path, dockerfile_path)
        self._setup_load_balancer()
        self._setup_dns_record()

        if disable_waf:
            logging.warning(
                "WAF is disabled. This should only be used for short-term debugging. "
                "Never use in production."
            )
        else:
            self._associate_waf()
        self.usage_dashboard: AppUsageDashboard | None = None
        if enable_usage_dashboard:
            self._setup_usage_dashboard(
                show_user_emails=dashboard_show_user_emails,
                extra_widgets=dashboard_extra_widgets,
            )

        self._create_outputs()

    def _add_assume_policy_for_dev(self):
        """Add ability for devs to assume the role if its being deployed from the dev
        environment."""
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

    def _setup_cross_account_access(self) -> None:
        """Grant the task role permission to assume the cross-account role
        and inject the role ARN as a container environment variable."""
        role_arn = self.deployment_config.cross_account_role_arn
        if role_arn is None:
            logger.info(
                "Cross-account access enabled but no role configured "
                "for this environment — skipping"
            )
            return

        self.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[role_arn],
            )
        )
        self._cross_account_env = {"CROSS_ACCOUNT_ROLE_ARN": role_arn}
        logger.info(f"Cross-account access enabled: {role_arn}")

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
        clean_up_lambda_location = Path(__file__).parent / "lambda_handlers"
        cleanup_fn = _lambda.Function(
            self,
            "AcmDnsCleanupFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="acm_dns_cleanup.handler",
            timeout=Duration.minutes(2),
            code=_lambda.Code.from_asset(str(clean_up_lambda_location)),
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

    def _setup_ecs_resources(
        self, docker_context_path: str, dockerfile_path: str
    ) -> None:
        cpu = self.container_props.cpu
        memory = self.container_props.memory_limit_mib
        desired_count = self.container_props.desired_count
        container_port = self.container_props.container_port
        environment = self.container_props.environment_variables
        health_check_grace_period = self.container_props.health_check_grace_period
        min_healthy_percent = self.container_props.min_healthy_percent

        # Look up the cluster
        self.cluster = ecs.Cluster.from_cluster_attributes(
            self,
            id="Cluster",
            cluster_name=self.deployment_config.cluster_name,
            vpc=self.vpc,
        )

        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDefinition",
            memory_limit_mib=memory,
            cpu=cpu,
            task_role=self.task_role,
        )

        self.log_group = logs.LogGroup(
            self,
            "ContainerLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
        )

        self.container = self.task_definition.add_container(
            "Container",
            image=ecs.ContainerImage.from_asset(
                docker_context_path, file=dockerfile_path, platform=Platform.LINUX_AMD64
            ),
            port_mappings=[ecs.PortMapping(container_port=container_port)],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix=f"{self.app_name}-app",
                log_group=self.log_group,
            ),
            environment={
                **self._auth_strategy.get_environment_variables(),
                **self._cross_account_env,
                **environment,
            },
        )

        self.fargate_service = ecs.FargateService(
            self,
            "FargateService",
            cluster=self.cluster,
            task_definition=self.task_definition,
            desired_count=desired_count,
            vpc_subnets=ec2.SubnetSelection(subnets=self.vpc.private_subnets),
            assign_public_ip=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            health_check_grace_period=Duration.seconds(health_check_grace_period),
            min_healthy_percent=min_healthy_percent,
        )

    def _setup_load_balancer(self) -> None:
        """Create ALB, delegating the listener action to the auth strategy."""

        health_check_path = (
            self.container_props.health_check_path or self.app_config.health_check_path
        )

        self.target_group = elbv2.ApplicationTargetGroup(
            self,
            "TargetGroup",
            vpc=self.vpc,
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[self.fargate_service],
            health_check={"path": health_check_path},
        )

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

        # DELEGATION: Ask the strategy to create the correct listener action
        default_https_action = self._auth_strategy.create_listener_action(
            self.target_group
        )

        self.https_listener = self.load_balancer.add_listener(
            "HttpsListener",
            port=443,
            certificates=[self.certificate],
            default_action=default_https_action,
        )

        self.load_balancer.node.add_dependency(self.certificate)

    def _setup_dns_record(self) -> None:
        self.a_record = route53.ARecord(
            self,
            "ARecord",
            zone=self.app_hosted_zone,
            target=route53.RecordTarget.from_alias(
                LoadBalancerTarget(self.load_balancer)
            ),
        )

    def _associate_waf(self) -> None:
        self.waf_association = wafv2.CfnWebACLAssociation(
            self,
            "WAF-ALB-Association",
            resource_arn=self.load_balancer.load_balancer_arn,
            web_acl_arn=self.deployment_config.waf_arn,
        )

    def _create_outputs(self) -> None:
        """Create base outputs and delegate to the strategy for specific outputs."""
        CfnOutput(
            self,
            "ApplicationURL",
            value=f"https://{self.alb_domain_name}",
            description=f"Application URL for {self.app_name}",
        )

        CfnOutput(
            self,
            "TaskRoleARN",
            value=f"{self.task_role.role_arn}",
            description="Role assumed by the task container. If DEV can be assumed",
        )

        self._auth_strategy.create_outputs()

    def _setup_usage_dashboard(self, *, show_user_emails, extra_widgets) -> None:
        """Create a CloudWatch usage dashboard for this app, reading its own ALB
        metrics and container authentication logs."""
        self.usage_dashboard = AppUsageDashboard(
            self,
            "UsageDashboard",
            app_name=self.app_name,
            stage=self.deployment_config.environment.name.lower(),
            load_balancer=self.load_balancer,
            log_groups=[self.log_group],
            show_user_emails=show_user_emails,
            extra_widgets=extra_widgets,
        )
