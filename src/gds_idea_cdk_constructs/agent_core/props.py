from dataclasses import dataclass, field
from pathlib import Path

from aws_cdk import RemovalPolicy
from aws_cdk.aws_ecr_assets import Platform

_DEFAULT_AGENT_CODE_DIR = str(Path(__file__).parent / "agent_template")


@dataclass
class AgentCoreProperties:
    """Configuration properties for an AgentCore Runtime construct."""

    runtime_name: str
    """Must be unique per account/region."""

    description: str = "An AgentCore Runtime deployed by the Agent Constructs Template"
    """Runtime description."""

    agent_code_directory: str = _DEFAULT_AGENT_CODE_DIR
    """Path to the directory containing agent code and Dockerfile.

    Defaults to the built-in agent template. Set to a custom directory
    if you need to modify the agent code (e.g. add tools, custom logic).
    """

    platform: Platform = Platform.LINUX_ARM64
    """Docker build target platform."""

    memory_name: str = "chat_session_store"
    """Memory store name."""

    memory_description: str = "Stores short-term conversation history"
    """Memory store description."""

    model_id: str = "eu.anthropic.claude-sonnet-4-6"
    """Bedrock model ID."""

    log_level: str = "INFO"
    """Log level for the runtime."""

    system_prompt: str = ""
    """System prompt for the agent.

    If set, passed as a SYSTEM_PROMPT env var and takes priority over the
    default_system_prompt.md file in the agent code directory.
    """

    removal_policy: RemovalPolicy = RemovalPolicy.DESTROY
    """Removal policy for stateful resources (e.g. Memory store).

    DESTROY deletes the memory on stack deletion. Set to RETAIN to keep data.
    """

    environment_variables: dict[str, str] = field(default_factory=dict)
    """Extra environment variables merged with derived ones."""
