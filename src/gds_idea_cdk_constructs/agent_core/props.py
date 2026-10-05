import re
from dataclasses import dataclass, field
from pathlib import Path

from aws_cdk import RemovalPolicy
from aws_cdk.aws_ecr_assets import Platform

from ..knowledge_base.stack import KnowledgeBase

_DEFAULT_AGENT_CODE_DIR = str(Path(__file__).parent / "agent_template")

_GATEWAY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
_TARGET_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")

# Gateway tools are exposed as "{target}___{tool}".
_TOOL_NAME_DELIMITER = "___"


@dataclass
class ModelConfig:
    """Model configuration with synth-time validation."""

    model_id: str = "eu.anthropic.claude-sonnet-4-6"
    max_tokens: int = 8000
    thinking_enabled: bool = True
    budget_tokens: int = 4000
    max_history: int = 20

    def __post_init__(self) -> None:
        if self.budget_tokens >= self.max_tokens:
            raise ValueError("budget_tokens must be less than max_tokens")

    def to_envs(self) -> dict[str, str]:
        return {
            "MODEL_ID": self.model_id,
            "MAX_TOKENS": str(self.max_tokens),
            "BUDGET_TOKENS": str(self.budget_tokens),
            "THINKING_ENABLED": str(self.thinking_enabled).lower(),
            "MAX_HISTORY": str(self.max_history),
        }


@dataclass
class MemoryConfig:
    """Memory store configuration. Set to None on props to skip creation."""

    name: str = "chat_session_store"
    description: str = "Stores short-term conversation history"


@dataclass
class KnowledgeBaseConfig:
    """A KnowledgeBase stack reference with retrieval defaults.
    When attached to AgentCoreProperties, the stack automatically:
    - Injects KB_ID and KB_SSM_PARAMETER environment variables
    - Injects retrieval config env vars (read by strands_tools.retrieve)
    - Grants bedrock:Retrieve permissions to the runtime role
    Attributes:
        knowledge_base: The KnowledgeBase stack to attach.
        min_score: Minimum relevance score threshold (0.0-1.0).
            Results below this score are filtered out by the retrieve tool.
        enable_metadata: Whether to include source metadata in
            retrieval results by default.
    """

    knowledge_base: KnowledgeBase
    min_score: float = 0.4
    enable_metadata: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError("min_score must be between 0.0 and 1.0")


@dataclass
class GatewayConfig:
    """Consume tools from one or more shared AgentCore Gateways.

    Gateways are created and owned by a separate repository. This config only
    names the gateways to use and, optionally, which targets to keep.

    The ``targets`` allowlist keeps an agent's tool list short and relevant. It
    is not a security boundary: access is enforced by the gateway itself.

    Attributes:
        gateways: Names of the gateways to consume. Always a list so a second
            gateway can be added later without an API change.
        targets: Target names to keep (e.g. ``["wfc"]`` keeps every tool named
            ``wfc___*``). ``None`` keeps every tool on the gateway, including
            targets added in future.
    """

    gateways: list[str] = field(default_factory=lambda: ["idea-data"])
    targets: list[str] | None = None

    def __post_init__(self) -> None:
        if not self.gateways:
            raise ValueError("gateways must contain at least one gateway name")
        if len(set(self.gateways)) != len(self.gateways):
            raise ValueError(f"gateways must not contain duplicates: {self.gateways}")
        for name in self.gateways:
            if not _GATEWAY_NAME_PATTERN.match(name):
                raise ValueError(
                    f"Invalid gateway name '{name}': use lowercase letters, "
                    "digits and hyphens, starting with a letter"
                )

        if self.targets is None:
            return
        if not self.targets:
            raise ValueError(
                "targets must not be empty; use None to keep every tool on the gateway"
            )
        if len(set(self.targets)) != len(self.targets):
            raise ValueError(f"targets must not contain duplicates: {self.targets}")
        for target in self.targets:
            if not _TARGET_NAME_PATTERN.match(target):
                raise ValueError(
                    f"Invalid target name '{target}': use lowercase letters, "
                    "digits and single underscores between words, starting with "
                    "a letter"
                )

    def validate_against(self, available_tools: list[str]) -> None:
        """Check every requested target exists on the gateway.

        Does nothing when ``targets`` is ``None``, since there is nothing to
        check. Fails the build on a typo or a renamed target, instead of the
        agent silently ending up with no tools at runtime.

        Args:
            available_tools: Full tool names published by the gateway, in the
                form ``{target}___{tool}``.

        Raises:
            ValueError: If one or more requested targets have no tools on the
                gateway.
        """
        if self.targets is None:
            return

        available_targets = {
            tool.split(_TOOL_NAME_DELIMITER, 1)[0] for tool in available_tools
        }
        missing = [t for t in self.targets if t not in available_targets]
        if missing:
            raise ValueError(
                f"Targets not found on gateway {self.gateways}: {missing}. "
                f"Available targets: {sorted(available_targets)}. "
                "If the target was added to the gateway recently, run "
                "'cdk context --reset <key>' to refresh the cached tool list."
            )


@dataclass
class BuiltInAgent:
    """Use the built-in agent template with typed configuration."""

    model: ModelConfig = field(default_factory=ModelConfig)
    system_prompt: str = ""
    log_level: str = "INFO"


@dataclass
class CustomAgent:
    """Bring your own agent code directory.

    The construct automatically injects REGION, MODEL_ID, and MEMORY_ID
    (if memory is enabled). Use environment_variables for any additional
    vars your agent code needs.
    """

    agent_code_directory: str
    model_id: str = "eu.anthropic.claude-sonnet-4-6"
    environment_variables: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentCoreProperties:
    """Top-level construct configuration."""

    runtime_name: str
    """Must be unique per account/region."""

    agent: BuiltInAgent | CustomAgent = field(default_factory=BuiltInAgent)
    """Agent mode: BuiltInAgent (default) or CustomAgent."""

    memory: MemoryConfig | None = field(default_factory=MemoryConfig)
    """Memory configuration. Set to None to skip memory creation."""

    knowledge_base: KnowledgeBaseConfig | None = None
    """Optional knowledge base attachment. When set, KB env vars and
    bedrock:Retrieve permissions are automatically wired to the runtime."""

    gateway: GatewayConfig | None = None
    """Optional gateway attachment. When set, the agent consumes tools from the
    named shared AgentCore Gateway(s)."""

    description: str = "An AgentCore Runtime deployed by the Agent Constructs Template"
    """Runtime description."""

    platform: Platform = Platform.LINUX_ARM64
    """Docker build target platform."""

    removal_policy: RemovalPolicy = RemovalPolicy.DESTROY
    """Removal policy for stateful resources (e.g. Memory store)."""
