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
