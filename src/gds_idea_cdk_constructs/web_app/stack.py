import logging

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_logs as logs,
    aws_scheduler as scheduler,
    aws_scheduler_targets as scheduler_targets,
)
from aws_cdk.aws_ecr_assets import Platform
from constructs import Construct

from .._base_stack import BaseWebStack
from ..config import AppConfig, DeploymentConfig, DeploymentEnvironment
from ._auth_strategies import AuthType
from ._dashboard import AppUsageDashboard, DashboardProperties
from .props import RefreshSchedule, WebAppContainerProperties

logger = logging.getLogger(__name__)


class WebApp(BaseWebStack):
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
        dashboard_properties: DashboardProperties | None = None,
        refresh_schedule: RefreshSchedule | None = None,
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
                :class:`AppUsageDashboard` for the widgets included and
                :class:`DashboardProperties` for user-tunable knobs.
            dashboard_properties: Optional overrides for the usage dashboard —
                name, per-user email disclosure, log filter pattern and extra
                widgets. See :class:`DashboardProperties`. Ignored when
                ``enable_usage_dashboard`` is ``False``.
            refresh_schedule: Optional schedule that periodiclly forces a new deployment
                of the ECS task, restarting the container.
                Defaults to None (no automatic restarts), see :class:`RefreshSchedule`

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
        super().__init__(scope, deployment_config, app_config, authentication)

        self.container_props = (
            container_props or WebAppContainerProperties()
        )  # Load the default values

        # A restart schedule is enabled if a RefreshSchedule is provided
        self._restart_enabled = refresh_schedule is not None

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

        if refresh_schedule is not None:
            self._setup_scheduled_restart(refresh_schedule)
            logger.info(
                f"Automatic restart schedule enabled: {refresh_schedule} for {self.app_name}"  # noqa: E501
            )

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
                properties=dashboard_properties or DashboardProperties(),
            )

        self._create_outputs()

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

    def _setup_scheduled_restart(self, refresh: RefreshSchedule) -> None:
        """Force a new ECS deployment on a schedule.

        Uses an EventBridge Scheduler schedule whose universal target calls
        ``ecs:UpdateService`` with ``forceNewDeployment=True``. No Lambda is
        involved. The schedule's role is scoped to this service only.

        Args:
            refresh: The restart schedule (exactly one of rate or cron).
        """
        expression = (
            scheduler.ScheduleExpression.rate(refresh.rate)
            if refresh.rate
            else scheduler.ScheduleExpression.cron(**refresh.cron)
        )

        scheduler.Schedule(
            self,
            "ScheduledRestart",
            schedule=expression,
            target=scheduler_targets.Universal(
                service="ecs",
                action="updateService",
                input=scheduler.ScheduleTargetInput.from_object(
                    {
                        "Cluster": self.cluster.cluster_arn,
                        "Service": self.fargate_service.service_name,
                        "ForceNewDeployment": True,
                    }
                ),
                policy_statements=[
                    iam.PolicyStatement(
                        actions=["ecs:UpdateService"],
                        resources=[self.fargate_service.service_arn],
                    )
                ],
            ),
        )
        logger.info("Scheduled restart enabled for %s", self.app_name)

    def grant_force_deploy(self, grantee: iam.IGrantable) -> None:
        """Allow ``grantee`` to force a new deployment of this app's ECS service.

        Lets an external entity (typically a data-processing Lambda) restart the
        the app by calling ``ecs:UpdateService`` with ``forceNewDeployment=True``
        (generally done after successful completion of the lambda's job).

        Pair this with `force_deploy_environment` to tell the grantee which cluster
        and service to target.

        Args:
            grantee: The principal (e.g. a Lambda function) to grant permission to.
        """
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ecs:UpdateService"],
                resources=[self.fargate_service.service_arn],
            )
        )

    def force_deploy_environment(self) -> dict[str, str]:
        """Environment variables a grantee needs to force a new deployment.

        Inject these into any principal granted via the function `grant_force_deploy`
        so it can call ``ecs:UpdateService`` against this app's cluster and
        service (e.g. with boto3 ``ecs.update_service(forceNewDeployment=True)``).

        Returns:
            Mapping of environment variable name to value.
        """
        return {
            "ECS_CLUSTER_NAME": self.cluster.cluster_name,
            "ECS_SERVICE_NAME": self.fargate_service.service_name,
        }

    def _setup_ecs_resources(
        self, docker_context_path: str, dockerfile_path: str
    ) -> None:
        """Create ECS Fargate task definition, container, and service."""
        cpu = self.container_props.cpu
        memory = self.container_props.memory_limit_mib
        desired_count = self.container_props.desired_count
        container_port = self.container_props.container_port
        environment = self.container_props.environment_variables
        health_check_grace_period = self.container_props.health_check_grace_period
        min_healthy_percent = self.container_props.min_healthy_percent
        # If restart schedule is enabled, then current task must remain healthy until
        # new task is running, so min_healthy_percent must be at least 100.
        if self._restart_enabled:
            min_healthy_percent = max(min_healthy_percent, 100)
        max_healthy_percent = self.container_props.max_healthy_percent
        if max_healthy_percent <= min_healthy_percent:
            raise ValueError(
                "A scheduled restart raises the effective min_healthy_percent to "
                f"{min_healthy_percent}%, but max_healthy_percent is "
                f"{max_healthy_percent}%. Raise max_healthy_percent above "
                f"{min_healthy_percent} so ECS can roll the service without "
                "downtime, or remove refresh_schedule."
            )

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
            retention=logs.RetentionDays.ONE_YEAR,
            removal_policy=RemovalPolicy.DESTROY,
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
            max_healthy_percent=max_healthy_percent,
        )

    def _setup_load_balancer(self) -> None:
        """Create target group for ECS service and set up ALB with listeners."""
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

        self._setup_alb_and_listeners(self.target_group)

        # The ALB ARN (for cognito-auth's signer pin) isn't known until now.
        for name, value in self._auth_strategy.get_load_balancer_environment_variables(
            self.load_balancer.load_balancer_arn
        ).items():
            self.container.add_environment(name, value)

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

    def _setup_usage_dashboard(
        self,
        *,
        properties: DashboardProperties,
    ) -> None:
        """Create a CloudWatch usage dashboard for this app, reading its own ALB
        metrics and container authentication logs."""
        self.usage_dashboard = AppUsageDashboard(
            self,
            "UsageDashboard",
            app_name=self.app_name,
            stage=self.deployment_config.environment.name.lower(),
            load_balancer=self.load_balancer,
            log_groups=[self.log_group],
            properties=properties,
        )
