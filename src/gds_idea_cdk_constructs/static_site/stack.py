"""Static site stack served by Lambda from S3 with optional Cognito auth."""

import logging
import shutil
import subprocess
from pathlib import Path

import jsii
from aws_cdk import (
    BundlingOptions,
    CfnOutput,
    CustomResource,
    DockerImage,
    Duration,
    ILocalBundling,
    RemovalPolicy,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as elbv2_targets,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    custom_resources as cr,
)
from aws_cdk.aws_ecr_assets import DockerImageAsset, Platform
from constructs import Construct

from .._base_stack import BaseWebStack
from ..config import AppConfig, DeploymentConfig, DeploymentEnvironment
from ..web_app._auth_strategies import AuthType
from .props import StaticSiteProperties

logger = logging.getLogger(__name__)


@jsii.implements(ILocalBundling)
class _LocalPipBundling:
    """Local bundling using uv pip with cross-platform support.

    Installs Python packages for Linux x86_64 (Lambda's platform) using
    uv's --python-platform flag, regardless of the host architecture.
    """

    def __init__(self, source_path: str) -> None:
        self._source_path = source_path

    def try_bundle(self, output_dir: str, *, image: DockerImage, **kwargs) -> bool:
        """Bundle the Lambda code locally using uv pip."""
        try:
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--no-installer-metadata",
                    "--no-compile-bytecode",
                    "--python-platform",
                    "x86_64-manylinux2014",
                    "--python",
                    "3.12",
                    "--extra-index-url",
                    "https://co-cddo.github.io/gds-idea-pypi/simple/",
                    "-r",
                    f"{self._source_path}/requirements.txt",
                    "--target",
                    output_dir,
                    "--quiet",
                ],
                check=True,
                capture_output=True,
            )
            shutil.copy(f"{self._source_path}/handler.py", output_dir)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f"Local bundling failed: {e}. Falling back to Docker.")
            return False


class StaticSite(BaseWebStack):
    """A static site stack served by Lambda from S3 with ALB and optional auth.

    Deploys a static website using:
    - S3 bucket for built content
    - Serve Lambda that proxies requests from ALB to S3 (with optional authZ)
    - Build Lambda (container-image) that runs the site build and uploads to S3
    - ALB with HTTPS and optional Cognito authentication
    - EventBridge schedule for periodic rebuilds (optional)
    - Custom Resource to auto-invoke build on deploy
    """

    def __init__(
        self,
        scope: Construct,
        deployment_config: DeploymentConfig,
        app_config: AppConfig,
        authentication: AuthType = AuthType.INTERNAL_ACCESS,
        docker_context_path: str = ".",
        dockerfile_path: str = "site_src/Dockerfile",
        static_site_props: StaticSiteProperties | None = None,
        task_role: iam.Role | None = None,
        disable_waf: bool = False,
    ) -> None:
        """Initialize a StaticSite stack.

        Args:
            scope: The CDK app or stack to create this stack within.
            deployment_config: Environment-specific configuration including VPC,
                domain name, and AWS resource identifiers.
            app_config: Application configuration including name and framework.
            authentication: Authentication strategy to use. Defaults to
                AuthType.INTERNAL_ACCESS.
            docker_context_path: Path to the Docker build context directory
                containing the site source and Dockerfile.
            dockerfile_path: Path to the Dockerfile relative to docker_context_path.
                Defaults to "site_src/Dockerfile".
            static_site_props: Configuration for build and serve behaviour.
                Required — must provide at minimum a build_command.
            task_role: Custom IAM role for the Lambda functions. If None, a
                role will be created with appropriate permissions.
            disable_waf: Disable WAF association with the ALB. Defaults to False.

        Example:
            Basic usage with internal access authentication::

                from aws_cdk import Duration, aws_events as events

                app = App()
                deployment_config = DeploymentConfig(cdk_env)
                app_config = AppConfig(app_name="my-docs", framework="static")

                StaticSite(
                    app,
                    deployment_config,
                    app_config,
                    authentication=AuthType.INTERNAL_ACCESS,
                    docker_context_path="site_src",
                    dockerfile_path="site_src/Dockerfile",
                    static_site_props=StaticSiteProperties(
                        build_command="npx @11ty/eleventy --output=/tmp/_site",
                        build_schedule=events.Schedule.rate(Duration.hours(6)),
                    ),
                )
        """
        if static_site_props is None:
            raise ValueError("static_site_props is required for StaticSite")

        super().__init__(scope, deployment_config, app_config, authentication)

        self.static_site_props = static_site_props

        # Create task role for Lambda functions
        if task_role:
            self.task_role = task_role
            self._auth_strategy.configure_role_permissions(self.task_role)
        else:
            self.task_role = iam.Role(
                self,
                "TaskRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AWSLambdaBasicExecutionRole"
                    ),
                ],
            )
            self._auth_strategy.configure_role_permissions(self.task_role)

        # Let users assume the role if we are deploying in dev.
        if self.deployment_config.environment == DeploymentEnvironment.DEVELOPMENT:
            self._add_assume_policy_for_dev()

        logger.info(
            f"Creating static site: {self.app_name} "
            f"with authentication: {authentication}"
        )
        logger.info(f"Domain: {self.alb_domain_name}")

        # Orchestrate resource creation
        self._import_existing_resources()
        self._setup_dns_and_certificate()
        self._setup_acm_clean_up()
        self._setup_content_bucket()
        self._setup_serve_lambda()
        self._setup_build_lambda(docker_context_path, dockerfile_path)
        self._setup_load_balancer()
        self._setup_dns_record()
        self._setup_build_trigger()
        self._setup_auto_invoke()

        if disable_waf:
            logging.warning(
                "WAF is disabled. This should only be used for short-term debugging. "
                "Never use in production."
            )
        else:
            self._associate_waf()

        self._create_outputs()

    def _setup_content_bucket(self) -> None:
        """Create S3 bucket for built static site content."""
        bucket_name = f"cdk-static-{self.app_name}.{self.deployment_config.domain_name}"
        self.content_bucket = s3.Bucket(
            self,
            "ContentBucket",
            bucket_name=bucket_name,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
        )

    def _setup_serve_lambda(self) -> None:
        """Create Lambda function that serves static files from S3."""
        serve_handler_path = str(self._get_lambda_handlers_path() / "serve")

        environment = {
            "CONTENT_BUCKET": self.content_bucket.bucket_name,
            "INDEX_DOCUMENT": self.static_site_props.index_document,
            **self._auth_strategy.get_environment_variables(),
        }
        if self.static_site_props.error_document:
            environment["ERROR_DOCUMENT"] = self.static_site_props.error_document

        self.serve_lambda = _lambda.Function(
            self,
            "ServeLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                serve_handler_path,
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    local=_LocalPipBundling(serve_handler_path),
                    command=["echo", "Docker fallback not implemented"],
                ),
            ),
            memory_size=self.static_site_props.serve_memory_size,
            timeout=Duration.seconds(30),
            role=self.task_role,
            environment=environment,
        )

        # Grant read access to content bucket
        self.content_bucket.grant_read(self.serve_lambda)

    def _setup_build_lambda(
        self, docker_context_path: str, dockerfile_path: str
    ) -> None:
        """Create container-image Lambda for building the static site.

        The build Lambda uses its own auto-generated execution role (not the
        shared task_role) because it only needs S3 write access — it does not
        need auth strategy permissions or dev assume-role capability.
        """
        # Build the Docker image for the build Lambda
        build_image = DockerImageAsset(
            self,
            "BuildImage",
            directory=docker_context_path,
            file=dockerfile_path,
            platform=Platform.LINUX_AMD64,
            target="build",
        )

        # Store image tag for use in auto-invoke trigger
        self._build_image_tag = build_image.image_tag

        environment = {
            "CONTENT_BUCKET": self.content_bucket.bucket_name,
            "BUILD_COMMAND": self.static_site_props.build_command,
            "BUILD_OUTPUT_DIR": self.static_site_props.build_output_dir,
            "CLEAN_ON_BUILD": (
                "true" if self.static_site_props.clean_on_build else "false"
            ),
            "KEEP_PREFIXES": ",".join(self.static_site_props.keep_prefixes),
            # Lambda filesystem is read-only except /tmp
            "HOME": "/tmp",
            "NPM_CONFIG_CACHE": "/tmp/.npm",
            **self.static_site_props.build_environment_variables,
        }

        self.build_lambda = _lambda.DockerImageFunction(
            self,
            "BuildLambda",
            code=_lambda.DockerImageCode.from_ecr(
                repository=build_image.repository,
                tag_or_digest=build_image.image_tag,
            ),
            memory_size=self.static_site_props.build_memory_size,
            timeout=Duration.seconds(self.static_site_props.build_timeout),
            environment=environment,
        )

        # Grant write access to content bucket
        self.content_bucket.grant_read_write(self.build_lambda)

    def _setup_load_balancer(self) -> None:
        """Create Lambda target group and set up ALB with listeners."""
        # Lambda target for ALB
        self.target_group = elbv2.ApplicationTargetGroup(
            self,
            "TargetGroup",
            vpc=self.vpc,
            target_type=elbv2.TargetType.LAMBDA,
            targets=[elbv2_targets.LambdaTarget(self.serve_lambda)],
            health_check=elbv2.HealthCheck(
                enabled=True,
                path="/health",
                healthy_http_codes="200",
            ),
        )

        self._setup_alb_and_listeners(self.target_group)

    def _setup_build_trigger(self) -> None:
        """Create EventBridge schedule rule if a schedule is configured."""
        if not self.static_site_props.build_schedule:
            return

        self.build_schedule_rule = events.Rule(
            self,
            "BuildScheduleRule",
            schedule=self.static_site_props.build_schedule,
            description=f"Scheduled rebuild for {self.app_name} static site",
        )
        self.build_schedule_rule.add_target(
            events_targets.LambdaFunction(self.build_lambda)
        )

    def _setup_auto_invoke(self) -> None:
        """Create Custom Resource to invoke build Lambda on deploy."""
        invoke_fn = _lambda.Function(
            self,
            "BuildInvokerFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.minutes(10),
            code=_lambda.Code.from_inline(self._get_invoke_handler_code()),
            initial_policy=[
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[self.build_lambda.function_arn],
                )
            ],
        )

        invoke_provider = cr.Provider(
            self, "BuildInvokerProvider", on_event_handler=invoke_fn
        )

        # Include image tag so changes to site content trigger a rebuild
        CustomResource(
            self,
            "BuildInvokerResource",
            service_token=invoke_provider.service_token,
            properties={
                "FunctionName": self.build_lambda.function_name,
                "BuildCommand": self.static_site_props.build_command,
                "ImageTag": self._build_image_tag,
            },
        )

    def _create_outputs(self) -> None:
        """Create CloudFormation outputs."""
        CfnOutput(
            self,
            "ApplicationURL",
            value=f"https://{self.alb_domain_name}",
            description=f"Static site URL for {self.app_name}",
        )

        CfnOutput(
            self,
            "ContentBucketName",
            value=self.content_bucket.bucket_name,
            description="S3 bucket containing built static site content",
        )

        CfnOutput(
            self,
            "BuildLambdaArn",
            value=self.build_lambda.function_arn,
            description="ARN of the build Lambda function",
        )

        CfnOutput(
            self,
            "TaskRoleARN",
            value=self.task_role.role_arn,
            description="Role assumed by the serve Lambda. If DEV can be assumed",
        )

        self._auth_strategy.create_outputs()

    @staticmethod
    def _get_lambda_handlers_path():
        """Get the path to the Lambda handlers directory."""
        return Path(__file__).parent / "lambda_handlers"

    @staticmethod
    def _get_invoke_handler_code() -> str:
        """Return inline Lambda code for the build invoker Custom Resource."""
        return """
import json
import boto3

lambda_client = boto3.client("lambda")


def handler(event, context):
    print(f"Event: {json.dumps(event)}")
    request_type = event.get("RequestType")

    if request_type in ("Create", "Update"):
        function_name = event["ResourceProperties"]["FunctionName"]
        print(f"Invoking build Lambda: {function_name}")

        try:
            response = lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="Event",  # Async invocation
            )
            print(f"Invoke response: {response['StatusCode']}")
        except Exception as e:
            print(f"WARNING: Failed to invoke build Lambda: {e}")
            # Don't fail the Custom Resource - site will be empty until
            # next scheduled build or manual invocation

    return {"PhysicalResourceId": "BuildInvoker"}
"""
