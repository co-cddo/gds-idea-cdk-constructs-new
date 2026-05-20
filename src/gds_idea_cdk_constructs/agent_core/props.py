from dataclasses import dataclass, field
from pathlib import Path

from aws_cdk import RemovalPolicy
from aws_cdk.aws_ecr_assets import Platform

from ..knowledge_base.stack import KnowledgeBase

_DEFAULT_AGENT_CODE_DIR = str(Path(__file__).parent / "agent_template")


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

    description: str = "An AgentCore Runtime deployed by the Agent Constructs Template"
    """Runtime description."""

    platform: Platform = Platform.LINUX_ARM64
    """Docker build target platform."""

    removal_policy: RemovalPolicy = RemovalPolicy.DESTROY
    """Removal policy for stateful resources (e.g. Memory store)."""
