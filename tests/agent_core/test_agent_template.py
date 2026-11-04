"""Tests for the gateway support in the built-in agent template.

The template is not an importable package (its modules import each other by
bare name), so the pure-Python modules are loaded by file path.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from gds_idea_cdk_constructs.agent_core import DEFAULT_AGENT_CODE_DIR


def _load_template_module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, Path(DEFAULT_AGENT_CODE_DIR) / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_config = _load_template_module("_config")
_gateway = _load_template_module("_gateway")


@pytest.fixture
def base_env(monkeypatch):
    monkeypatch.setenv("REGION", "eu-west-2")
    monkeypatch.setenv("MODEL_ID", "eu.anthropic.claude-sonnet-4-6")
    for name in (
        "GATEWAY_URLS",
        "GATEWAY_TARGETS",
        "THINKING_ENABLED",
        "THINKING_TYPE",
        "EFFORT",
        "BUDGET_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _tool_is_kept(filters, tool_name: str) -> bool:
    return any(pattern.match(tool_name) for pattern in filters["allowed"])


# -- Config tests --


def test_config_no_gateway_by_default(base_env):
    config = _config.Config.from_env()
    assert config.gateway_urls == ()
    assert config.gateway_targets is None


def test_config_parses_gateway_urls(base_env):
    base_env.setenv("GATEWAY_URLS", json.dumps(["https://a/mcp", "https://b/mcp"]))
    config = _config.Config.from_env()
    assert config.gateway_urls == ("https://a/mcp", "https://b/mcp")


def test_config_unset_gateway_targets_means_no_filter(base_env):
    base_env.setenv("GATEWAY_URLS", '["https://a/mcp"]')
    assert _config.Config.from_env().gateway_targets is None


def test_config_parses_gateway_targets(base_env):
    base_env.setenv("GATEWAY_URLS", '["https://a/mcp"]')
    base_env.setenv("GATEWAY_TARGETS", '["wfc", "dpd"]')
    assert _config.Config.from_env().gateway_targets == ("wfc", "dpd")


def test_config_decodes_the_json_encoded_system_prompt(base_env):
    prompt = "Line one.\n- a bullet\n\tindented"
    base_env.setenv("SYSTEM_PROMPT", json.dumps(prompt))
    assert _config.Config.from_env().system_prompt == prompt


def test_config_uses_the_default_prompt_when_none_is_set(base_env):
    base_env.delenv("SYSTEM_PROMPT", raising=False)
    assert "helpful AI assistant" in _config.Config.from_env().system_prompt


# -- Missing target tests --


def test_missing_targets_empty_when_every_target_has_tools():
    tools = ["wfc___read_sql", "wfc___run_sql", "gats_kb___retrieve"]
    assert _gateway.missing_targets(("wfc", "gats_kb"), tools) == []


def test_missing_targets_lists_targets_without_tools_in_order():
    tools = ["wfc___read_sql"]
    assert _gateway.missing_targets(("wcf", "wfc", "dpd"), tools) == ["wcf", "dpd"]


def test_missing_targets_empty_when_nothing_is_pinned():
    assert _gateway.missing_targets(None, []) == []


def test_missing_targets_reports_every_target_when_no_tools_loaded():
    assert _gateway.missing_targets(("wfc",), []) == ["wfc"]


def test_missing_targets_does_not_match_a_longer_target_name():
    """Target 'wfc' must not be satisfied by a tool of target 'wfc_extra'."""
    assert _gateway.missing_targets(("wfc",), ["wfc_extra___run_sql"]) == ["wfc"]


def test_missing_targets_finds_a_hyphenated_target():
    tools = ["gats-assurance___read_sql", "gats-assurance___run_sql"]
    assert _gateway.missing_targets(("gats-assurance",), tools) == []


def test_missing_targets_ignores_tools_with_no_target_prefix():
    """Local tools and the gateway's search tool have no ``target___`` prefix."""
    assert _gateway.missing_targets(("wfc",), ["retrieve"]) == ["wfc"]


# -- Thinking tests --


def test_config_thinking_defaults_to_a_fixed_budget(base_env):
    config = _config.Config.from_env()
    assert config.thinking_request_fields() == {
        "thinking": {"type": "enabled", "budget_tokens": 4000}
    }


def test_config_thinking_off_sends_no_extra_fields(base_env):
    base_env.setenv("THINKING_ENABLED", "false")
    assert _config.Config.from_env().thinking_request_fields() == {}


def test_config_adaptive_thinking_asks_for_a_summary_and_the_effort(base_env):
    base_env.setenv("THINKING_TYPE", "adaptive")
    base_env.setenv("EFFORT", "high")
    assert _config.Config.from_env().thinking_request_fields() == {
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": "high"},
    }


def test_config_adaptive_thinking_off_sends_no_extra_fields(base_env):
    base_env.setenv("THINKING_TYPE", "adaptive")
    base_env.setenv("THINKING_ENABLED", "false")
    assert _config.Config.from_env().thinking_request_fields() == {}


def test_config_adaptive_ignores_the_token_budget(base_env):
    base_env.setenv("THINKING_TYPE", "adaptive")
    base_env.setenv("BUDGET_TOKENS", "123")
    assert "budget_tokens" not in str(
        _config.Config.from_env().thinking_request_fields()
    )


# -- Tool filter tests --


def test_build_tool_filters_none_when_unfiltered():
    assert _gateway.build_tool_filters(None) is None


def test_build_tool_filters_keeps_tools_of_requested_targets():
    filters = _gateway.build_tool_filters(("wfc", "gats_kb"))
    assert _tool_is_kept(filters, "wfc___read_sql")
    assert _tool_is_kept(filters, "wfc___run_sql")
    assert _tool_is_kept(filters, "gats_kb___retrieve")


def test_build_tool_filters_drops_other_targets():
    filters = _gateway.build_tool_filters(("wfc",))
    assert not _tool_is_kept(filters, "dpd___run_sql")


def test_build_tool_filters_does_not_match_target_prefix_overlap():
    """Test that target 'wfc' does not keep tools from target 'wfc_extra'."""
    filters = _gateway.build_tool_filters(("wfc",))
    assert not _tool_is_kept(filters, "wfc_extra___run_sql")


def test_build_tool_filters_does_not_match_target_suffix_overlap():
    filters = _gateway.build_tool_filters(("kb",))
    assert not _tool_is_kept(filters, "gats_kb___retrieve")


def test_build_tool_filters_keeps_hyphenated_target():
    """Test that a hyphenated target keeps only its own tools."""
    filters = _gateway.build_tool_filters(("gats-assurance",))
    assert _tool_is_kept(filters, "gats-assurance___read_sql")
    assert not _tool_is_kept(filters, "gats___read_sql")
    assert not _tool_is_kept(filters, "gats-assurance-extra___read_sql")


def test_create_gateway_clients_empty_for_no_urls():
    assert _gateway.create_gateway_clients((), "eu-west-2", None) == []


# -- Gateway connection loss detection --


def _tool_use(tool_use_id: str, name: str) -> dict:
    return {
        "role": "assistant",
        "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": {}}}],
    }


def _tool_result(tool_use_id: str, text: str, status: str = "error") -> dict:
    return {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "status": status,
                    "content": [{"text": text}],
                }
            }
        ],
    }


@pytest.mark.parametrize(
    "text",
    [
        "Tool execution failed: Connection to the MCP server was closed",
        "Error: the client session is not running. Ensure the agent is used",
    ],
)
def test_connection_lost_when_a_gateway_tool_could_not_reach_the_gateway(text):
    messages = [_tool_use("t1", "gats___run_sql"), _tool_result("t1", text)]

    assert _gateway.gateway_connection_lost(messages) is True


def test_connection_not_lost_when_a_tool_reports_its_own_error():
    messages = [
        _tool_use("t1", "gats___run_sql"),
        _tool_result("t1", 'syntax error at or near "SELEC"'),
    ]

    assert _gateway.gateway_connection_lost(messages) is False


def test_connection_not_lost_when_the_gateway_tool_succeeded():
    messages = [
        _tool_use("t1", "gats___run_sql"),
        _tool_result("t1", "Tool execution failed: not an error", status="success"),
    ]

    assert _gateway.gateway_connection_lost(messages) is False


def test_connection_not_lost_when_a_local_tool_fails():
    """Test that errors from tools not on the gateway do not trigger a rebuild."""
    messages = [
        _tool_use("t1", "retrieve"),
        _tool_result("t1", "Error: knowledge base not found"),
    ]

    assert _gateway.gateway_connection_lost(messages) is False


def test_connection_lost_if_any_of_several_calls_failed():
    messages = [
        _tool_use("t1", "gats___run_sql"),
        _tool_result("t1", "ok", status="success"),
        _tool_use("t2", "gats___read_sql"),
        _tool_result("t2", "Tool execution failed: closed"),
    ]

    assert _gateway.gateway_connection_lost(messages) is True


def test_connection_not_lost_for_plain_text_messages():
    messages = [
        {"role": "user", "content": "saved text"},
        {"role": "assistant", "content": [{"text": "Error: this is just prose"}]},
    ]

    assert _gateway.gateway_connection_lost(messages) is False
