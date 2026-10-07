"""Bedrock AgentCore runtime — conversational agent with memory and streaming."""

# Logging must be configured before other imports to capture SDK output
from _logging import setup_logging

logger = setup_logging()

import json
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime
from typing import Any
import os

from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from starlette.exceptions import HTTPException

from _metrics import extract_and_record_usage
from _streaming import _extract_response_text, _handle_reasoning
from _config import Config
from _gateway import create_gateway_clients, gateway_connection_lost
from _session import AgentSession

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

if config.gateway_urls:
    logger.info(
        "Gateway tools enabled (Gateways=%d, Targets=%s)",
        len(config.gateway_urls),
        list(config.gateway_targets) if config.gateway_targets is not None else "all",
    )



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

        # The API returns newest first. Reversing before the stable sort keeps
        # events with equal timestamps (user, then assistant) in saved order.
        sorted_events = sorted(
            reversed(events),
            key=lambda e: e.get("eventTimestamp") or datetime.min.replace(tzinfo=UTC),
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

def build_system_prompt() -> str:
    """Render the system prompt for today's date."""
    system_prompt = config.system_prompt.replace(
        "{today}", date.today().isoformat()
    )

    # If knowledge base is available, need to tell LLM that it's available to use via the retrieve tool
    if KB_ID:
        system_prompt += (
            "\n\nYou have access to a knowledge base via the retrieve tool. "
            "Use it to search for relevant information when answering questions "
            "that may require specific knowledge or documentation."
        )
    return system_prompt


def create_agent(history: list[dict]) -> Agent:
    """Create a Strands Agent with conversation history and thinking enabled."""
    additional_fields = {}
    if config.thinking_enabled:
        additional_fields["thinking"] = {
            "type": "enabled",
            "budget_tokens": config.budget_tokens,
        }

    return Agent(
        model=BedrockModel(
            model_id=config.model_id,
            region_name=config.region,
            max_tokens=config.max_tokens,
            additional_request_fields=additional_fields,
        ),
        system_prompt=build_system_prompt(),
        messages=history,
        # The agent owns these connections: Strands opens them here and closes
        # them in agent.cleanup(), when AgentSession replaces the agent.
        tools=[
            *tools,
            *create_gateway_clients(
                config.gateway_urls, config.region, config.gateway_targets
            ),
        ],
    )


# ==========================================================================
# Main turn
# ==========================================================================

# One agent per conversation: rebuilt from Memory only when the session changes
# or a turn fails. Callers must send runtimeSessionId for turns to share a VM.
# With gateways, the agent is also rebuilt every 15 minutes (keeping its
# messages) so its gateway connections are renewed, and on the turn after a
# gateway tool call fails to connect.
GATEWAY_REFRESH_SECONDS = 15 * 60
agent_session = AgentSession(
    create_agent,
    get_session_history,
    max_age_seconds=GATEWAY_REFRESH_SECONDS if config.gateway_urls else None,
    connection_lost=gateway_connection_lost if config.gateway_urls else None,
)


async def run_agent_turn(
    query: str, session_id: str
) -> AsyncGenerator[dict[str, Any], None]:
    """Execute a single conversational turn, streaming events to the caller.

    Yields event dicts with ``type`` in:
    ``text``, ``thinking``, ``done``, ``error``.
    """
    try:
        response_text = ""
        usage = {}

        async with agent_session.turn(session_id) as agent:
            agent.system_prompt = build_system_prompt()  # keeps {today} current
            logger.info(
                "Turn start | Session=%s | Messages=%d", session_id, len(agent.messages)
            )

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

        # Persist the turn (after the block, so a disconnect while yielding
        # "done" below cannot discard an agent whose turn already finished).
        # The turn lock is already released here and these saves block the
        # event loop. That is safe only because nothing awaits between the
        # release and the saves, so no other turn can start in between.
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
async def invoke(payload, context):
    """API handler. Expects ``{"prompt": "...", "session_id": "..."}``.

    The payload ``session_id`` must equal the ``runtimeSessionId`` the caller
    invoked the runtime with, so the container that holds the warm agent is the
    one serving the conversation.

    Returns an async generator streamed as Server-Sent Events.
    """
    query = payload.get("prompt")
    session_id = context.session_id

    logger.info(
        "Invoke | Chars=%d | Session=%s",
        len(query) if query else 0,
        session_id,
    )

    if not query:
        return {"error": "No prompt provided"}

    if not session_id or payload.get("session_id") != session_id:
        raise HTTPException(
            status_code=422,
            detail="The payload session_id must equal the runtimeSessionId "
            "used to invoke the agent runtime",
        )

    return run_agent_turn(query, session_id)


if __name__ == "__main__":
    logger.info("Starting AgentCore (Model=%s, Region=%s)", config.model_id, config.region)
    app.run()
