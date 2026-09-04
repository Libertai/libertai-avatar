"""Run a demo MCP server over stdio or HTTP.

stdio is convenient locally: the API spawns the process itself and there is nothing to
deploy. It does not survive a serverless host, which cannot spawn subprocesses, so the same
server can also listen over HTTP and be registered by URL.

    MCP_TRANSPORT=http MCP_PORT=8081 python apps/api/mcp_servers/clinic.py
"""

from __future__ import annotations

import os


def serve(mcp) -> None:
    """Run the server on the transport the environment asks for."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()

    if transport == "stdio":
        mcp.run()
        return

    if transport not in ("http", "streamable-http", "sse"):
        raise SystemExit(f"Unknown MCP_TRANSPORT '{transport}'. Use stdio, http, or sse.")

    mcp.settings.host = os.getenv("MCP_HOST", "127.0.0.1")
    mcp.settings.port = int(os.getenv("MCP_PORT", "8081"))
    mcp.run(transport="sse" if transport == "sse" else "streamable-http")
