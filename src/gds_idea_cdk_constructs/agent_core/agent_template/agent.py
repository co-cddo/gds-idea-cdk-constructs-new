"""Bedrock AgentCore runtime — conversational agent with memory and streaming."""

# Logging must be configured before other imports to capture SDK output
from _logging import setup_logging

logger = setup_logging()

import json
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any
import os

from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

from _metrics import extract_and_record_usage
from _streaming import _extract_response_text, _handle_reasoning
from _config import Config

# --- Configuration (injected via CDK environment variables) ---
config = Config.from_env()

# --- Shared clients ---
app = BedrockAgentCoreApp()
memory_client = MemoryClient(region_name=config.region) if config.memory_id else None

logger.info("Agent initialising (Model=%s, Region=%s)", config.model_id, config.region)
# --- Knowledge Base (optional, injected if KB is attached via CDK) ---
KB_ID = os.getenv("KB_ID")
if KB_ID:
    os.environ["KNOWLEDGE_BASE_ID"] = KB_ID  # Strands retrieve tool needs this

# --- Tools ---
tools = []

# Conditional import and set up of knowledge base if available
if KB_ID:
    from strands_tools import retrieve
    tools = [retrieve]
    logger.info("KB retrieval tool enabled (KB_ID=%s)", KB_ID)



# ==========================================================================
# Memory
# ==========================================================================

def get_session_history(session_id: str) -> list:
    """Load conversation history from the Memory Store in Converse format."""
    if not memory_client:
        return []

    try:
        events = memory_client.list_events(
            memory_id=config.memory_id,
            actor_id=config.actor_id,
            session_id=session_id,
            max_results=config.max_history,
            include_payload=True,
        )
        if not events:
            return []

        sorted_events = sorted(
            events, key=lambda e: e.get("eventTime", "")
        )
        messages = []
        for event in sorted_events:
            data = _extract_blob(event)
            if data and data.get("role") and data.get("content"):
                messages.append({
                    "role": data["role"],
                    "content": [{"text": data["content"]}],
                })
        return messages

    except Exception:
        logger.exception("Error loading history")
        return []


def _extract_blob(event: dict) -> dict | None:
    """Parse the JSON blob from a memory event.

    Handles multiple response structures from the Memory service.
    """
    raw = None

    payload = event.get("payload")
    if isinstance(payload, list) and payload:
        raw = payload[0].get("blob") if isinstance(payload[0], dict) else None
    elif isinstance(payload, dict):
        raw = payload.get("blob")

    if raw is None:
        raw = event.get("blob_data") or event.get("blobData")

    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def save_interaction(session_id: str, role: str, content: str) -> None:
    """Persist a single message turn to the Memory Store."""
    if not memory_client:
        return

    try:
        memory_client.create_blob_event(
            memory_id=config.memory_id,
            actor_id=config.actor_id,
            session_id=session_id,
            blob_data=json.dumps({"role": role, "content": content}),
        )
    except Exception:
        logger.exception("Error saving history")


# ==========================================================================
# Agent factory
# ==========================================================================

def create_agent(history: list[dict]) -> Agent:
    """Create a Strands Agent with conversation history and thinking enabled."""
    system_prompt = config.system_prompt.replace(
        "{today}", date.today().isoformat()
    )

    additional_fields = {}
    if config.thinking_enabled:
        additional_fields["thinking"] = {
            "type": "enabled",
            "budget_tokens": config.budget_tokens,
        }

    # If knowledge base is available, need to tell LLM that it's available to use via the retrieve tool
    if KB_ID:
        system_prompt += (
            "\n\nYou have access to a knowledge base via the retrieve tool. "
            "Use it to search for relevant information when answering questions "
            "that may require specific knowledge or documentation."
        )

    return Agent(
        model=BedrockModel(
            model_id=config.model_id,
            region_name=config.region,
            max_tokens=config.max_tokens,
            additional_request_fields=additional_fields,
        ),
        system_prompt=system_prompt,
        messages=history,
        tools=tools,
    )


# ==========================================================================
# Main turn
# ==========================================================================

async def run_agent_turn(
    query: str, session_id: str
) -> AsyncGenerator[dict[str, Any], None]:
    """Execute a single conversational turn, streaming events to the caller.

    Yields event dicts with ``type`` in:
    ``text``, ``thinking``, ``done``, ``error``.
    """
    try:
        history = get_session_history(session_id)
        logger.info("Turn start | Session=%s | History=%d", session_id, len(history))

        agent = create_agent(history)
        response_text = ""
        usage = {}

        async for raw_event in agent.stream_async(query):
            event = (
                raw_event.get("event", raw_event)
                if isinstance(raw_event, dict)
                else raw_event
            )
            if not isinstance(event, dict) or not event:
                continue

            # Text chunk
            if "data" in event:
                yield {"type": "text", "data": event["data"]}

            # Reasoning / thinking
            elif "delta" in event and "reasoningContent" in event["delta"]:
                chunk = _handle_reasoning(event)
                if chunk:
                    yield chunk

            # Final result
            elif "result" in event:
                result_obj = event["result"]
                response_text = _extract_response_text(result_obj)
                usage = extract_and_record_usage(
                    result_obj, session_id, config.model_id
                )

        # Persist the turn
        save_interaction(session_id, "user", query)
        save_interaction(session_id, "assistant", response_text)

        logger.info("Turn complete | Session=%s", session_id)

        yield {
            "type": "done",
            "response": response_text,
            "session_id": session_id,
            "usage": usage,
        }

    except Exception:
        logger.exception("Error during agent turn")
        yield {"type": "error", "error": "Internal agent error"}
        raise


# ==========================================================================
# Entrypoint
# ==========================================================================

@app.entrypoint
async def invoke(payload):
    """API handler. Expects ``{"prompt": "...", "session_id": "..."}``.

    Returns an async generator streamed as Server-Sent Events.
    """
    query = payload.get("prompt")
    session_id = payload.get("session_id", "default-session")

    logger.info(
        "Invoke | Chars=%d | Session=%s",
        len(query) if query else 0,
        session_id,
    )

    if not query:
        return {"error": "No prompt provided"}

    return run_agent_turn(query, session_id)


if __name__ == "__main__":
    logger.info("Starting AgentCore (Model=%s, Region=%s)", config.model_id, config.region)
    app.run()
