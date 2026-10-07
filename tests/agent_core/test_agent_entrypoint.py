"""Tests for ``agent.py`` of the built-in agent template, with fake SDKs.

``agent.py`` builds AWS clients when it is imported, and its SDKs (Strands,
Bedrock AgentCore, MCP) are not dependencies of this library. So it is loaded
with fake SDK modules in ``sys.modules``, which also records how the agent and
its gateway clients are created.
"""

import asyncio
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

import pytest

from gds_idea_cdk_constructs.agent_core import DEFAULT_AGENT_CODE_DIR

_TEMPLATE_DIR = Path(DEFAULT_AGENT_CODE_DIR)
_TEMPLATE_MODULES = ("_config", "_gateway", "_session", "_streaming", "agent")
GATEWAY_URL = "https://gw-one.example/mcp"
SECOND_GATEWAY_URL = "https://gw-two.example/mcp"


class FakeAgent:
    """Stands in for ``strands.Agent``; records how it was created."""

    created: list["FakeAgent"] = []
    stream_error: Exception | None = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = kwargs.get("messages", [])
        self.system_prompt = kwargs.get("system_prompt")
        self.cleaned_up = False
        FakeAgent.created.append(self)

    async def stream_async(self, query):
        if FakeAgent.stream_error is not None:
            raise FakeAgent.stream_error
        yield {"data": "hello"}
        yield {"result": "hello"}

    def cleanup(self):
        self.cleaned_up = True


class FakeMCPClient:
    """Stands in for ``strands.tools.mcp.MCPClient``."""

    def __init__(self, transport_factory, tool_filters=None):
        self.transport_factory = transport_factory
        self.tool_filters = tool_filters


class FakeApp:
    def entrypoint(self, fn):
        return fn


def _fake_module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def signed_transports():
    """Keyword arguments of every SigV4 transport the agent opened."""
    return []


@pytest.fixture
def load_agent(monkeypatch, signed_transports):
    """Return a function that imports ``agent.py`` with fake SDKs."""
    FakeAgent.created = []
    FakeAgent.stream_error = None

    def aws_iam_streamablehttp_client(**kwargs):
        signed_transports.append(kwargs)
        return object()

    fakes = {
        "_logging": _fake_module(
            "_logging", setup_logging=lambda: logging.getLogger("agent")
        ),
        "_metrics": _fake_module("_metrics", extract_and_record_usage=lambda *args: {}),
        "bedrock_agentcore": _fake_module("bedrock_agentcore"),
        "bedrock_agentcore.memory": _fake_module(
            "bedrock_agentcore.memory", MemoryClient=lambda **kwargs: object()
        ),
        "bedrock_agentcore.runtime": _fake_module(
            "bedrock_agentcore.runtime", BedrockAgentCoreApp=FakeApp
        ),
        "strands": _fake_module("strands", Agent=FakeAgent),
        "strands.models": _fake_module(
            "strands.models", BedrockModel=lambda **kwargs: kwargs
        ),
        "strands.tools": _fake_module("strands.tools"),
        "strands.tools.mcp": _fake_module("strands.tools.mcp", MCPClient=FakeMCPClient),
        "mcp_proxy_for_aws": _fake_module("mcp_proxy_for_aws"),
        "mcp_proxy_for_aws.client": _fake_module(
            "mcp_proxy_for_aws.client",
            aws_iam_streamablehttp_client=aws_iam_streamablehttp_client,
        ),
        "strands_tools": _fake_module("strands_tools", retrieve="retrieve-tool"),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.syspath_prepend(str(_TEMPLATE_DIR))
    for name in _TEMPLATE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)

    monkeypatch.setenv("REGION", "eu-west-2")
    monkeypatch.setenv("MODEL_ID", "eu.anthropic.claude-sonnet-4-6")
    for name in ("GATEWAY_URLS", "GATEWAY_TARGETS", "MEMORY_ID", "KB_ID"):
        monkeypatch.delenv(name, raising=False)

    def load(**env: str):
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        spec = importlib.util.spec_from_file_location(
            "agent", _TEMPLATE_DIR / "agent.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["agent"] = module
        spec.loader.exec_module(module)
        return module

    yield load

    # Template modules are imported by bare name; don't leak them to other tests.
    for name in _TEMPLATE_MODULES:
        sys.modules.pop(name, None)


def _gateway_tools(agent: FakeAgent) -> list[FakeMCPClient]:
    return [t for t in agent.kwargs["tools"] if isinstance(t, FakeMCPClient)]


# -- Building the agent --


def test_create_agent_has_no_gateway_tools_by_default(load_agent):
    agent = load_agent().create_agent([])
    assert agent.kwargs["tools"] == []


def test_create_agent_passes_one_client_per_gateway_url(load_agent):
    urls = json.dumps([GATEWAY_URL, SECOND_GATEWAY_URL])
    agent = load_agent(GATEWAY_URLS=urls).create_agent([])

    assert len(_gateway_tools(agent)) == 2


def test_create_agent_signs_gateway_requests_for_agentcore(
    load_agent, signed_transports
):
    agent = load_agent(GATEWAY_URLS=json.dumps([GATEWAY_URL])).create_agent([])

    _gateway_tools(agent)[0].transport_factory()

    assert signed_transports == [
        {
            "endpoint": GATEWAY_URL,
            "aws_service": "bedrock-agentcore",
            "aws_region": "eu-west-2",
        }
    ]


def test_create_agent_keeps_every_tool_when_no_targets_are_pinned(load_agent):
    agent = load_agent(GATEWAY_URLS=json.dumps([GATEWAY_URL])).create_agent([])

    assert _gateway_tools(agent)[0].tool_filters is None


def test_create_agent_filters_gateway_tools_to_pinned_targets(load_agent):
    module = load_agent(
        GATEWAY_URLS=json.dumps([GATEWAY_URL]), GATEWAY_TARGETS='["wfc"]'
    )
    agent = module.create_agent([])

    patterns = _gateway_tools(agent)[0].tool_filters["allowed"]
    assert [p.match("wfc___run_sql") is not None for p in patterns] == [True]
    assert [p.match("dpd___run_sql") is not None for p in patterns] == [False]


def test_create_agent_combines_knowledge_base_and_gateway_tools(load_agent):
    agent = load_agent(
        GATEWAY_URLS=json.dumps([GATEWAY_URL]), KB_ID="kb-123"
    ).create_agent([])

    assert agent.kwargs["tools"][0] == "retrieve-tool"
    assert len(_gateway_tools(agent)) == 1


def test_create_agent_passes_history_to_the_agent(load_agent):
    history = [{"role": "user", "content": [{"text": "hi"}]}]

    assert load_agent().create_agent(history).messages == history


# -- Refresh interval --


def test_gateway_agents_are_refreshed_every_15_minutes(load_agent):
    module = load_agent(GATEWAY_URLS=json.dumps([GATEWAY_URL]))

    assert module.agent_session._max_age_seconds == 15 * 60


def test_agents_without_a_gateway_are_never_refreshed(load_agent):
    assert load_agent().agent_session._max_age_seconds is None


# -- Failing loudly --


def test_unreachable_gateway_fails_the_turn_loudly(load_agent, caplog):
    """Test that an unreachable gateway is an error, not an agent without tools."""
    module = load_agent(GATEWAY_URLS=json.dumps([GATEWAY_URL]))

    def connection_refused(**kwargs):
        raise ConnectionError("gateway unreachable")

    # The real Agent connects to its MCP clients inside its constructor.
    module.Agent = connection_refused
    events = []

    async def scenario():
        async for event in module.run_agent_turn("hi", "session-1"):
            events.append(event)

    with caplog.at_level(logging.ERROR, logger="agent"):
        with pytest.raises(ConnectionError, match="gateway unreachable"):
            asyncio.run(scenario())

    assert events == [{"type": "error", "error": "Internal agent error"}]
    assert "Error during agent turn" in caplog.text
    assert "gateway unreachable" in caplog.text
