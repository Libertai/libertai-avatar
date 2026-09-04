"""Connect to MCP servers and expose their tools to the chat model.

Servers are third-party by nature: a scenario can draw on several at once — a booking
system, a pricing service, a public data server — regardless of who runs them. Three
transports are supported:

- ``stdio``: a local process, for servers shipped with this repo.
- ``http``: streamable HTTP, the transport remote servers normally speak.
- ``sse``: server-sent events, for older remote servers.

Servers live in the registry (``apps/api/mcp_registry.py``) and are referenced by name
from a scenario. A browser can never name a server, a URL, or a command: that would allow
arbitrary processes on the API host and requests to arbitrary internal addresses.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

TOOL_TIMEOUT_SECONDS = float(os.getenv("MCP_TOOL_TIMEOUT", "15"))
DISCOVERY_TTL_SECONDS = float(os.getenv("MCP_DISCOVERY_TTL", "300"))

ENV_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")

# Discovered tools per server, so a conversation does not re-handshake on every message.
_discovery_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def configured_servers() -> dict[str, dict[str, Any]]:
    """The registered servers, with their credentials decrypted for use."""
    from apps.api.mcp_registry import load_servers

    return {name: server.model_dump() for name, server in load_servers(reveal=True).items()}


def _resolve_secrets(value: Any) -> Any:
    """Expand ``${ENV_VAR}`` placeholders so tokens live in the environment, not in git."""
    if isinstance(value, str):
        return ENV_PLACEHOLDER.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, dict):
        return {key: _resolve_secrets(item) for key, item in value.items()}
    return value


@asynccontextmanager
async def _session(server: dict[str, Any]):
    """Open a session against one server, whatever transport it speaks."""
    transport = server.get("transport", "stdio")
    headers = _resolve_secrets(server.get("headers", {}))

    if transport in ("http", "streamable-http"):
        async with streamablehttp_client(_resolve_secrets(server["url"]), headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    if transport == "sse":
        async with sse_client(_resolve_secrets(server["url"]), headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    if transport != "stdio":
        raise ValueError(f"Unknown MCP transport '{transport}'. Use stdio, http, or sse.")

    command = server["command"]
    if command == "python":
        # Run Python servers on the interpreter the API itself uses, so they share its venv.
        command = sys.executable

    params = StdioServerParameters(
        command=command,
        args=server.get("args", []),
        env={**os.environ, **_resolve_secrets(server.get("env", {}))},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def discover_tools(name: str, force: bool = False) -> list[dict[str, Any]]:
    """List a registered server's tools by name, connecting only when needed."""
    server = configured_servers().get(name)
    if server is None:
        raise ValueError(f"Unknown MCP server '{name}'.")
    return await _discover(name, server, force=force)


async def _discover(name: str, server: dict[str, Any], force: bool = False) -> list[dict[str, Any]]:
    """List one server's tools, cached so repeated turns do not re-handshake."""
    cached = _discovery_cache.get(name)
    if not force and cached and time.monotonic() - cached[0] < DISCOVERY_TTL_SECONDS:
        return cached[1]

    async with _session(server) as session:
        listed = await session.list_tools()

    tools = [
        {"name": tool.name, "description": tool.description or "", "schema": tool.inputSchema}
        for tool in listed.tools
    ]
    _discovery_cache[name] = (time.monotonic(), tools)
    return tools


def clear_discovery_cache() -> None:
    _discovery_cache.clear()


async def list_tools(server_names: list[str], allowed: list[str] | None = None) -> list[dict[str, Any]]:
    """Describe the tools of several servers as OpenAI function definitions.

    Args:
        server_names: Names from the configured allowlist; servers are queried in order.
        allowed: Optional per-scenario subset. Tools outside it are never offered.

    Returns:
        Tool definitions ready to send as the chat request's ``tools`` field. When two
        servers expose the same tool name, the first server wins and the duplicate is
        dropped, so a later server cannot shadow an earlier one's tool.
    """
    servers = configured_servers()
    tools: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name in server_names:
        server = servers.get(name)
        if server is None:
            continue

        for tool in await _discover(name, server):
            if allowed is not None and tool["name"] not in allowed:
                continue
            if tool["name"] in seen:
                continue

            seen.add(tool["name"])
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["schema"],
                    },
                }
            )

    return tools


async def call_tool(server_names: list[str], tool_name: str, arguments: dict[str, Any]) -> str:
    """Run a tool on the first configured server that provides it."""
    servers = configured_servers()

    for name in server_names:
        server = servers.get(name)
        if server is None:
            continue

        if tool_name not in {tool["name"] for tool in await _discover(name, server)}:
            continue

        async with _session(server) as session:
            result = await session.call_tool(tool_name, arguments)

        parts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        return "\n".join(parts) if parts else "The tool returned no output."

    return f"Tool '{tool_name}' is not available."
