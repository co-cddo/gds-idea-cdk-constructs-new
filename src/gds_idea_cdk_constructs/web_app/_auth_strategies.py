from abc import ABC, abstractmethod
from enum import StrEnum

from aws_cdk import (
    CfnOutput,
    aws_cognito as cognito,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_actions as elbv2_actions,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

from ..config import DeploymentConfig


class AuthType(StrEnum):
    """Defines the supported authentication types for the WebApp construct."""

    NONE = "none"
    COGNITO = "cognito"
    INTERNAL_ACCESS = "internal-access"


class IAuthStrategy(ABC):
    """Interface for an authentication strategy."""

    def __init__(
        self, scope: Construct, deployment_config: DeploymentConfig, app_name: str
    ):
        self.scope = scope
        self.deployment_config = deployment_config
        self.app_name = app_name

    @abstractmethod
    def create_listener_action(
        self, target_group: elbv2.IApplicationTargetGroup
    ) -> elbv2.ListenerAction:
        """Return the ALB listener action for this strategy."""
        pass

    @abstractmethod
    def create_outputs(self) -> None:
        """Create any strategy-specific CloudFormation outputs."""
        pass

    @abstractmethod
    def get_minimal_role(self) -> iam.Role:
        """Creates a minimal IAM role configured with permissions
        required by this strategy."""
        pass

    @abstractmethod
    def configure_role_permissions(self, role: iam.IRole) -> None:
        """Grants an existing role the permissions required by this strategy."""
        pass

    @abstractmethod
    def get_environment_variables(self) -> dict[str, str]:
        """Returns environment variables required by this auth strategy."""
        pass


class BaseCognitoAuthStrategy(IAuthStrategy):
    """Base class for Cognito-based authentication strategies.

    Provides common setup for User Pool, Domain, and Client creation.
    Subclasses override _create_user_pool_client() to customize client configuration.
    """

    def __init__(
        self, scope: Construct, deployment_config: DeploymentConfig, app_name: str
    ):
        super().__init__(scope, deployment_config, app_name)
        self._setup_cognito_resources()

    def _setup_cognito_resources(self) -> None:
        """Looks up and creates all necessary Cognito resources."""
        # Import existing User Pool
        self.user_pool = cognito.UserPool.from_user_pool_id(
            self.scope, "ExistingUserPool", self.deployment_config.user_pool_id
        )

        # Import existing User Pool Domain
        self.user_pool_domain = cognito.UserPoolDomain.from_domain_name(
            self.scope,
            "ExistingCustomCognitoDomain",
            user_pool_domain_name=f"auth.{self.deployment_config.domain_name}",
        )

        # Create User Pool Client (subclass-specific configuration)
        self.cognito_client = self._create_user_pool_client()

        # Allow subclasses to create additional resources (e.g., managed branding)
        self._setup_additional_resources()

    @abstractmethod
    def _create_user_pool_client(self) -> cognito.UserPoolClient:
        """Subclasses implement to customize User Pool Client configuration."""
        pass

    def _setup_additional_resources(self) -> None:
        """Optional hook for subclasses to create additional resources.

        Default implementation does nothing. Override in subclasses if needed
        (e.g., to add managed login branding).
        """
        pass

    def create_listener_action(
        self, target_group: elbv2.IApplicationTargetGroup
    ) -> elbv2.ListenerAction:
        """Returns the Cognito authentication action for the ALB listener."""
        return elbv2_actions.AuthenticateCognitoAction(
            user_pool=self.user_pool,
            user_pool_client=self.cognito_client,
            user_pool_domain=self.user_pool_domain,
            next=elbv2.ListenerAction.forward([target_group]),
        )

    def create_outputs(self) -> None:
        """Creates the Cognito Client ID CloudFormation output."""
        CfnOutput(
            self.scope,
            "CognitoClientId",
            value=self.cognito_client.user_pool_client_id,
            description=f"Cognito Client ID for {self.app_name}",
        )

    def get_minimal_role(self) -> iam.Role:
        """Creates a minimal role with Cognito secret read access."""
        role = iam.Role(
            self.scope,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        self._grant_secret_access(role)
        return role

    def configure_role_permissions(self, role: iam.IRole) -> None:
        """Grants existing role access to Cognito secrets."""
        self._grant_secret_access(role)

    def get_environment_variables(self) -> dict[str, str]:
        """Returns Cognito secret name for the container."""
        return {"COGNITO_AUTH_SECRET_NAME": f"{self.app_name}/access"}

    def _grant_secret_access(self, role: iam.IRole) -> None:
        """Helper to grant secret read access to a role."""
        secret = secretsmanager.Secret.from_secret_name_v2(
            self.scope, "CognitoAuthSecret", secret_name=f"{self.app_name}/access"
        )
        secret.grant_read(role)


class NoAuthStrategy(IAuthStrategy):
    """A strategy for apps with no authentication."""

    def create_listener_action(
        self, target_group: elbv2.IApplicationTargetGroup
    ) -> elbv2.ListenerAction:
        """The action is to simply forward traffic."""
        return elbv2.ListenerAction.forward([target_group])

    def create_outputs(self) -> None:
        """This strategy has no specific outputs, so this method does nothing."""
        pass

    def get_minimal_role(self) -> iam.Role:
        """Creates a minimal role with no additional permissions."""
        return iam.Role(
            self.scope,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

    def configure_role_permissions(self, role: iam.IRole) -> None:
        """No auth doesn't need additional permissions."""
        pass

    def get_environment_variables(self) -> dict[str, str]:
        """No auth doesn't need environment variables."""
        return {}


class CognitoManagedLoginAuthStrategy(BaseCognitoAuthStrategy):
    """A strategy for apps using Cognito authentication with managed login UI."""

    def _create_user_pool_client(self) -> cognito.UserPoolClient:
        """Creates a User Pool Client configured to use Cognito managed login."""
        alb_domain_name = f"{self.app_name}.{self.deployment_config.domain_name}"

        return cognito.UserPoolClient(
            self.scope,
            "Client",
            user_pool=self.user_pool,
            user_pool_client_name=f"{self.app_name}UserPoolClient",
            generate_secret=True,
            enable_token_revocation=True,
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.COGNITO
            ],
            auth_flows=cognito.AuthFlow(user=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[f"https://{alb_domain_name}/oauth2/idpresponse"],
                logout_urls=[f"https://{alb_domain_name}"],
            ),
        )

    def _setup_additional_resources(self) -> None:
        """Enable managed login branding with default Cognito styling."""
        cognito.CfnManagedLoginBranding(
            self.scope,
            "ManagedLoginBranding",
            user_pool_id=self.user_pool.user_pool_id,
            client_id=self.cognito_client.user_pool_client_id,
            use_cognito_provided_values=True,
        )


class CognitoExternalIdpAuthStrategy(BaseCognitoAuthStrategy):
    """A strategy for apps using Cognito with an external identity provider.

    This strategy configures the User Pool Client to use an external IdP
    (e.g., EntraID, Okta) instead of Cognito's managed login UI.
    """

    def _create_user_pool_client(self) -> cognito.UserPoolClient:
        """Creates a User Pool Client configured to use an external IdP."""
        alb_domain_name = f"{self.app_name}.{self.deployment_config.domain_name}"

        return cognito.UserPoolClient(
            self.scope,
            "Client",
            user_pool=self.user_pool,
            user_pool_client_name=f"{self.app_name}UserPoolClient",
            generate_secret=True,
            enable_token_revocation=True,
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.custom(
                    self.deployment_config.external_idp_name
                )
            ],
            auth_flows=cognito.AuthFlow(user=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[f"https://{alb_domain_name}/oauth2/idpresponse"],
                logout_urls=[f"https://{alb_domain_name}"],
            ),
        )


# Map the strategies
AUTH_STRATEGY_MAP = {
    AuthType.COGNITO: CognitoManagedLoginAuthStrategy,
    AuthType.INTERNAL_ACCESS: CognitoExternalIdpAuthStrategy,
    AuthType.NONE: NoAuthStrategy,
}
