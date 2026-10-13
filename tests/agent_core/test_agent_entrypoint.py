"""Tests for the built-in agent template's entrypoint and turn wiring.

The template is not an importable package (its modules import each other by
bare name), so ``agent.py`` is loaded by file path with the Strands, AgentCore
and OpenTelemetry packages stubbed out.
"""

import asyncio
import importlib.util
import json
import logging
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from gds_idea_cdk_constructs.agent_core import DEFAULT_AGENT_CODE_DIR

TEMPLATE_MODULES = ("agent", "_config", "_metrics", "_session", "_streaming")

DEFAULT_STREAM = [
    {"event": {"data": "hi "}},
    {
        "event": {
            "result": {
                "message": {"content": [{"text": "hi there"}]},
                "metrics": {"accumulated_usage": {"inputTokens": 3, "outputTokens": 2}},
            }
        }
    },
]


class FakeMemoryClient:
    def __init__(self, region_name):
        self.events = []
        self.saved = []

    def list_events(self, **kwargs):
        return self.events

    def create_blob_event(self, **kwargs):
        self.saved.append(json.loads(kwargs["blob_data"]))


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def template(monkeypatch):
    """Load ``agent.py`` with its SDK dependencies stubbed.

    Returns a namespace with the loaded ``module`` and the ``FakeAgent`` class
    that the module will build.
    """

    class FakeAgent:
        instances = []
        stream = DEFAULT_STREAM
        fail_with = None

        def __init__(self, model, system_prompt, messages, tools):
            self.system_prompt = system_prompt
            self.messages = messages
            self.queries = []
            self.cleaned_up = False
            type(self).instances.append(self)

        async def stream_async(self, query):
            self.queries.append(query)
            for event in type(self).stream:
                yield event
                if type(self).fail_with:
                    raise type(self).fail_with

        def cleanup(self):
            self.cleaned_up = True

    class FakeHTTPError(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class FakeApp:
        def entrypoint(self, function):
            return function

    class FakeDate:
        """Stands in for ``datetime.date`` so tests control "today"."""

        value = "2026-01-01"

        @classmethod
        def today(cls):
            return SimpleNamespace(isoformat=lambda: cls.value)

    stubs = {
        "_logging": _module(
            "_logging", setup_logging=lambda: logging.getLogger("agent")
        ),
        "bedrock_agentcore": _module("bedrock_agentcore"),
        "bedrock_agentcore.memory": _module(
            "bedrock_agentcore.memory", MemoryClient=FakeMemoryClient
        ),
        "bedrock_agentcore.runtime": _module(
            "bedrock_agentcore.runtime", BedrockAgentCoreApp=FakeApp
        ),
        "strands": _module("strands", Agent=FakeAgent),
        "strands.models": _module(
            "strands.models", BedrockModel=lambda **kwargs: object()
        ),
        "opentelemetry": _module("opentelemetry"),
        "starlette": _module("starlette"),
        "starlette.exceptions": _module(
            "starlette.exceptions", HTTPException=FakeHTTPError
        ),
    }
    stubs["opentelemetry"].trace = _module(
        "opentelemetry.trace",
        get_current_span=lambda: SimpleNamespace(is_recording=lambda: False),
    )
    for name, stub in stubs.items():
        monkeypatch.setitem(sys.modules, name, stub)

    monkeypatch.setenv("REGION", "eu-west-2")
    monkeypatch.setenv("MODEL_ID", "test-model")
    monkeypatch.setenv("MEMORY_ID", "test-memory")
    monkeypatch.setenv("SYSTEM_PROMPT", "Today is {today}.")
    monkeypatch.delenv("KB_ID", raising=False)
    monkeypatch.syspath_prepend(str(DEFAULT_AGENT_CODE_DIR))

    spec = importlib.util.spec_from_file_location(
        "agent", Path(DEFAULT_AGENT_CODE_DIR) / "agent.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent"] = module
    try:
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, "date", FakeDate)
        yield SimpleNamespace(
            module=module,
            FakeAgent=FakeAgent,
            FakeDate=FakeDate,
            HTTPException=FakeHTTPError,
        )
    finally:
        for name in TEMPLATE_MODULES:
            sys.modules.pop(name, None)


async def _collect(generator):
    return [event async for event in generator]


def _run_turns(template, *session_ids, query="hello"):
    """Run one turn per session ID in a single event loop."""

    async def scenario():
        return [
            await _collect(template.module.run_agent_turn(query, session_id))
            for session_id in session_ids
        ]

    return asyncio.run(scenario())


def _invoke(template, payload, session_id):
    context = SimpleNamespace(session_id=session_id)
    return asyncio.run(template.module.invoke(payload, context))


def _blob_event(role, content, timestamp):
    blob = json.dumps({"role": role, "content": content})
    return {"eventTimestamp": timestamp, "payload": [{"blob": blob}]}


# -- Session ID resolution --


def _assert_rejected(template, payload, session_id):
    with pytest.raises(template.HTTPException) as error:
        _invoke(template, payload, session_id)
    assert error.value.status_code == 422
    assert "runtimeSessionId" in error.value.detail
    assert template.FakeAgent.instances == []


def test_invoke_rejects_a_request_with_no_runtime_session_id(template):
    _assert_rejected(template, {"prompt": "hi", "session_id": "s1"}, None)


def test_invoke_rejects_a_payload_without_session_id(template):
    _assert_rejected(template, {"prompt": "hi"}, "s1")


def test_invoke_rejects_a_payload_session_id_that_differs_from_the_header(template):
    _assert_rejected(template, {"prompt": "hi", "session_id": "s2"}, "s1")


def test_invoke_rejects_an_empty_prompt(template):
    result = _invoke(template, {"prompt": "", "session_id": "s1"}, "s1")
    assert result == {"error": "No prompt provided"}


def test_invoke_streams_a_turn_keyed_on_the_runtime_session_id(template):
    generator = _invoke(template, {"prompt": "hi", "session_id": "s1"}, "s1")
    events = asyncio.run(_collect(generator))
    assert events[-1]["type"] == "done"
    assert events[-1]["session_id"] == "s1"


# -- Reuse across turns --


def test_turns_in_one_session_build_the_agent_once(template):
    _run_turns(template, "s1", "s1", "s1")
    assert len(template.FakeAgent.instances) == 1
    assert template.FakeAgent.instances[0].queries == ["hello"] * 3


def test_a_new_session_id_builds_a_new_agent(template):
    _run_turns(template, "s1", "s2")
    first, second = template.FakeAgent.instances
    assert first.cleaned_up is True
    assert second.cleaned_up is False


def test_system_prompt_is_refreshed_on_every_turn(template):
    async def scenario():
        await _collect(template.module.run_agent_turn("hello", "s1"))
        template.FakeDate.value = "2026-01-02"
        await _collect(template.module.run_agent_turn("hello", "s1"))

    asyncio.run(scenario())
    (agent,) = template.FakeAgent.instances
    assert agent.system_prompt == "Today is 2026-01-02."


# -- Saving to Memory --


def test_turn_saves_user_then_assistant_before_yielding_done(template):
    saved_when_done = []

    async def scenario():
        async for event in template.module.run_agent_turn("hello", "s1"):
            if event["type"] == "done":
                saved_when_done.extend(template.module.memory_client.saved)

    asyncio.run(scenario())
    assert saved_when_done == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_closing_the_stream_after_done_keeps_the_agent_and_the_saves(template):
    async def scenario():
        generator = template.module.run_agent_turn("hello", "s1")
        async for event in generator:
            if event["type"] == "done":
                break
        await generator.aclose()
        await _collect(template.module.run_agent_turn("again", "s1"))

    asyncio.run(scenario())
    (agent,) = template.FakeAgent.instances
    assert agent.cleaned_up is False
    assert agent.queries == ["hello", "again"]
    assert len(template.module.memory_client.saved) == 4


def test_failed_stream_reports_an_error_discards_the_agent_and_saves_nothing(
    template,
):
    template.FakeAgent.fail_with = RuntimeError("model down")

    async def scenario():
        events = []
        try:
            async for event in template.module.run_agent_turn("hello", "s1"):
                events.append(event)
        except RuntimeError as error:
            return events, error
        return events, None

    events, error = asyncio.run(scenario())
    assert str(error) == "model down"
    assert events[-1] == {"type": "error", "error": "Internal agent error"}
    assert template.FakeAgent.instances[0].cleaned_up is True
    assert template.module.memory_client.saved == []


def test_turn_after_a_failed_stream_builds_a_fresh_agent(template):
    template.FakeAgent.fail_with = RuntimeError("model down")

    async def scenario():
        with pytest.raises(RuntimeError, match="model down"):
            await _collect(template.module.run_agent_turn("hello", "s1"))
        template.FakeAgent.fail_with = None
        await _collect(template.module.run_agent_turn("hello", "s1"))

    asyncio.run(scenario())
    assert len(template.FakeAgent.instances) == 2


# -- Loading history --


def test_history_is_returned_oldest_first_with_ties_in_saved_order(template):
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=1)
    # The API returns newest first.
    template.module.memory_client.events = [
        _blob_event("assistant", "a2", t2),
        _blob_event("user", "u2", t2),
        _blob_event("assistant", "a1", t1),
        _blob_event("user", "u1", t1),
    ]
    history = template.module.get_session_history("s1")
    assert [m["content"][0]["text"] for m in history] == ["u1", "a1", "u2", "a2"]


def test_history_is_ordered_by_event_timestamp(template):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    template.module.memory_client.events = [
        _blob_event("user", "first", start),
        _blob_event("user", "third", start + timedelta(seconds=2)),
        _blob_event("user", "second", start + timedelta(seconds=1)),
    ]
    history = template.module.get_session_history("s1")
    assert [m["content"][0]["text"] for m in history] == ["first", "second", "third"]


def test_history_asks_memory_for_at_most_max_history_events(template):
    asked = {}
    memory_client = template.module.memory_client
    memory_client.list_events = lambda **kwargs: asked.update(kwargs) or []
    template.module.get_session_history("s1")
    assert asked["max_results"] == template.module.config.max_history
    assert asked["session_id"] == "s1"


def test_history_load_failure_returns_no_messages(template, caplog):
    def fail(**kwargs):
        raise OSError("memory unavailable")

    template.module.memory_client.list_events = fail
    with caplog.at_level(logging.ERROR, logger="agent"):
        assert template.module.get_session_history("s1") == []
    assert "Error loading history" in caplog.text
