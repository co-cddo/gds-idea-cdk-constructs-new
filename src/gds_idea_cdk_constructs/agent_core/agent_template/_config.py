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
    actor_id: str = "agent"

    @classmethod
    def from_env(cls) -> "Config":
        prompt_file = Path(__file__).parent / "default_system_prompt.md"
        system_prompt = os.getenv("SYSTEM_PROMPT") or (
            prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
        )
        return cls(
            region=os.environ["REGION"],
            model_id=os.environ["MODEL_ID"],
            memory_id=os.getenv("MEMORY_ID"),
            max_history=int(os.getenv("MAX_HISTORY", "20")),
            max_tokens=int(os.getenv("MAX_TOKENS", "8000")),
            budget_tokens=int(os.getenv("BUDGET_TOKENS", "4000")),
            thinking_enabled=os.getenv("THINKING_ENABLED", "true").lower() == "true",
            system_prompt=system_prompt,
        )
