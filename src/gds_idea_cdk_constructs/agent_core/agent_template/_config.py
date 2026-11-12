import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Runtime configuration loaded from environment variables."""

    region: str
    model_id: str
    memory_id: str | None
    max_history: int
    max_tokens: int
    budget_tokens: int
    thinking_enabled: bool
    system_prompt: str
    gateway_urls: tuple[str, ...] = ()
    gateway_targets: tuple[str, ...] | None = None
    actor_id: str = "agent"
    thinking_type: str = "enabled"
    effort: str = "medium"

    def thinking_request_fields(self) -> dict:
        """Build the model request fields that turn thinking on.

        Returns:
            Fields for ``additional_request_fields``, or ``{}`` when thinking is
            off. ``"enabled"`` sends a fixed token budget. ``"adaptive"`` lets
            the model decide, guided by ``effort``, and asks for the reasoning
            summary, which newer models leave out unless requested.
        """
        if not self.thinking_enabled:
            return {}
        if self.thinking_type == "adaptive":
            return {
                "thinking": {"type": "adaptive", "display": "summarized"},
                "output_config": {"effort": self.effort},
            }
        return {"thinking": {"type": "enabled", "budget_tokens": self.budget_tokens}}

    @classmethod
    def from_env(cls) -> "Config":
        prompt_file = Path(__file__).parent / "default_system_prompt.md"
        # SYSTEM_PROMPT is JSON-encoded by the CDK stack, because AgentCore
        # rejects newlines and other control characters in env var values.
        encoded_prompt = os.getenv("SYSTEM_PROMPT")
        if encoded_prompt:
            system_prompt = json.loads(encoded_prompt)
        elif prompt_file.exists():
            system_prompt = prompt_file.read_text(encoding="utf-8")
        else:
            system_prompt = ""
        # The stack always sets GATEWAY_TARGETS when a gateway is attached. It is
        # optional here only so the template can run without a gateway.
        gateway_targets = os.getenv("GATEWAY_TARGETS")
        return cls(
            region=os.environ["REGION"],
            model_id=os.environ["MODEL_ID"],
            memory_id=os.getenv("MEMORY_ID"),
            max_history=int(os.getenv("MAX_HISTORY", "20")),
            max_tokens=int(os.getenv("MAX_TOKENS", "8000")),
            budget_tokens=int(os.getenv("BUDGET_TOKENS", "4000")),
            thinking_enabled=os.getenv("THINKING_ENABLED", "true").lower() == "true",
            thinking_type=os.getenv("THINKING_TYPE", "enabled"),
            effort=os.getenv("EFFORT", "medium"),
            system_prompt=system_prompt,
            gateway_urls=tuple(json.loads(os.getenv("GATEWAY_URLS", "[]"))),
            gateway_targets=(
                tuple(json.loads(gateway_targets))
                if gateway_targets is not None
                else None
            ),
        )
