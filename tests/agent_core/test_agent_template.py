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
    for name in ("GATEWAY_URLS", "GATEWAY_TARGETS"):
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


def test_create_gateway_clients_empty_for_no_urls():
    assert _gateway.create_gateway_clients((), "eu-west-2", None) == []
