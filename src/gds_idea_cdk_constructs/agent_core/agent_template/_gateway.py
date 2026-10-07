"""Tools from shared AgentCore Gateways, over MCP with SigV4 signing."""

import re
from collections.abc import Callable
from typing import Any

# Gateway tools are exposed as "{target}___{tool}".
TOOL_NAME_DELIMITER = "___"
_GATEWAY_SERVICE = "bedrock-agentcore"


def build_tool_filters(targets: tuple[str, ...] | None) -> dict[str, Any] | None:
    """Build Strands ``tool_filters`` that keep only the given targets.

    This keeps the agent's tool list short. It is not a security boundary:
    access is enforced by the gateway itself.

    Args:
        targets: Target names to keep, or ``None`` to keep every tool.

    Returns:
        A ``tool_filters`` dict, or ``None`` when nothing should be filtered.
    """
    if targets is None:
        return None
    # Pattern.match anchors at the start, and the delimiter stops "wfc"
    # matching a tool from a different target such as "wfc_extra".
    return {
        "allowed": [re.compile(re.escape(t) + TOOL_NAME_DELIMITER) for t in targets]
    }


# Strands does not raise when a gateway connection drops mid-turn. It hands the
# model a tool result whose text starts with one of these, so look for them.
_CALL_FAILED_PREFIXES = (
    "Tool execution failed:",  # the MCP client caught an exception
    "Error:",  # Strands caught an exception, e.g. the MCP session is not running
)


def gateway_connection_lost(messages: list[dict[str, Any]]) -> bool:
    """Tell whether a gateway tool call in ``messages`` failed to reach the gateway.

    Strands turns a dropped connection into an error tool result instead of
    raising, so the turn looks successful while every gateway tool is broken.
    This spots those results so the agent can be rebuilt.

    It is a heuristic: it also matches errors the gateway itself reports as
    protocol failures. The cost of a false match is one reconnect. Errors a tool
    reports about its own work (e.g. bad SQL) are not matched.

    Args:
        messages: Messages in Converse format, e.g. those added by one turn.

    Returns:
        True if a gateway tool (named ``{target}___{tool}``) returned such an error.
    """
    gateway_tool_use_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            tool_use = block.get("toolUse")
            if tool_use and TOOL_NAME_DELIMITER in tool_use.get("name", ""):
                gateway_tool_use_ids.add(tool_use.get("toolUseId"))
            if block.get("toolResult"):
                results.append(block["toolResult"])

    for result in results:
        if result.get("status") != "error":
            continue
        if result.get("toolUseId") not in gateway_tool_use_ids:
            continue
        for part in result.get("content", []):
            text = part.get("text", "") if isinstance(part, dict) else ""
            if text.startswith(_CALL_FAILED_PREFIXES):
                return True
    return False


def _transport_factory(url: str, region: str) -> Callable[[], Any]:
    """Return a factory for a SigV4-signed MCP transport to ``url``."""
    # Imported here so the filter logic above can be tested without the SDKs.
    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

    def factory() -> Any:
        return aws_iam_streamablehttp_client(
            endpoint=url,
            aws_service=_GATEWAY_SERVICE,
            aws_region=region,
        )

    return factory


def create_gateway_clients(
    urls: tuple[str, ...], region: str, targets: tuple[str, ...] | None
) -> list[Any]:
    """Create one MCP client per gateway, ready to pass to ``Agent(tools=...)``.

    The agent connects when it is built and disconnects on ``agent.cleanup()``.

    Args:
        urls: MCP endpoint URLs of the gateways.
        region: AWS region used to sign requests.
        targets: Target names to keep, or ``None`` to keep every tool.

    Returns:
        A list of unstarted ``strands.tools.mcp.MCPClient`` objects.
    """
    if not urls:
        return []

    from strands.tools.mcp import MCPClient

    tool_filters = build_tool_filters(targets)
    return [
        MCPClient(_transport_factory(url, region), tool_filters=tool_filters)
        for url in urls
    ]
