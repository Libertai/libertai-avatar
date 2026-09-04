"""CRUD for the MCP server registry, plus a connection test.

Registered servers are the only ones a scenario can reference, and the only ones the API
will ever contact. Credentials are encrypted on the way in and masked on the way out, so
the admin UI can edit a server without ever receiving its token back.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from apps.api import secrets_box
from apps.api.admin import require_admin
from apps.api.db import connect, json_column

router = APIRouter(prefix="/mcp-servers", tags=["mcp"])

Transport = Literal["stdio", "http", "sse"]


class McpServer(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str = Field(default="", max_length=500)
    transport: Transport = "stdio"
    url: str | None = Field(default=None, max_length=2000)
    command: str | None = Field(default=None, max_length=500)
    args: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)


class McpServersResponse(BaseModel):
    servers: list[McpServer]


class ToolSummary(BaseModel):
    name: str
    description: str


class ConnectionTest(BaseModel):
    ok: bool
    detail: str
    tools: list[ToolSummary] = Field(default_factory=list)


def _row_to_server(row, *, reveal: bool) -> McpServer:
    headers = json_column(row, "headers", {})
    env = json_column(row, "env", {})
    transform = secrets_box.decrypt if reveal else secrets_box.mask
    return McpServer(
        name=row["name"],
        description=row["description"],
        transport=row["transport"],
        url=row["url"],
        command=row["command"],
        args=json_column(row, "args", []),
        headers={key: transform(value) for key, value in headers.items()},
        env={key: transform(value) for key, value in env.items()},
    )


def load_servers(*, reveal: bool = False) -> dict[str, McpServer]:
    with connect() as connection:
        rows = connection.execute("SELECT * FROM mcp_servers ORDER BY name").fetchall()
    return {row["name"]: _row_to_server(row, reveal=reveal) for row in rows}


def server_config(name: str) -> dict[str, Any] | None:
    """The decrypted config the MCP client needs to open a session."""
    server = load_servers(reveal=True).get(name)
    return server.model_dump() if server else None


def _validate(server: McpServer) -> None:
    if server.transport == "stdio" and not server.command:
        raise HTTPException(status_code=422, detail="A stdio server needs a command.")
    if server.transport in ("http", "sse") and not server.url:
        raise HTTPException(status_code=422, detail=f"A {server.transport} server needs a url.")


def _existing_secrets(name: str) -> tuple[dict[str, str], dict[str, str]]:
    with connect() as connection:
        row = connection.execute("SELECT headers, env FROM mcp_servers WHERE name = ?", (name,)).fetchone()
    if row is None:
        return ({}, {})
    return (json_column(row, "headers", {}), json_column(row, "env", {}))


def save_server(server: McpServer) -> McpServer:
    """Insert or update a server, preserving secrets the UI submitted as masked."""
    _validate(server)
    stored_headers, stored_env = _existing_secrets(server.name)

    headers = {key: secrets_box.unmask(value, stored_headers.get(key, "")) for key, value in server.headers.items()}
    env = {key: secrets_box.unmask(value, stored_env.get(key, "")) for key, value in server.env.items()}

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO mcp_servers (name, description, transport, url, command, args, headers, env)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                transport   = excluded.transport,
                url         = excluded.url,
                command     = excluded.command,
                args        = excluded.args,
                headers     = excluded.headers,
                env         = excluded.env,
                updated_at  = datetime('now')
            """,
            (
                server.name,
                server.description,
                server.transport,
                server.url,
                server.command,
                json.dumps(server.args),
                json.dumps(headers),
                json.dumps(env),
            ),
        )

    from apps.api.mcp_client import clear_discovery_cache

    clear_discovery_cache()
    return load_servers()[server.name]


@router.get("", response_model=McpServersResponse)
def list_servers(_: None = Depends(require_admin)) -> McpServersResponse:
    return McpServersResponse(servers=list(load_servers().values()))


@router.put("/{name}", response_model=McpServer)
def upsert_server(name: str, server: McpServer, _: None = Depends(require_admin)) -> McpServer:
    if name != server.name:
        raise HTTPException(status_code=422, detail="The server name in the path and body must match.")
    return save_server(server)


@router.delete("/{name}", status_code=204, response_class=Response)
def delete_server(name: str, _: None = Depends(require_admin)) -> Response:
    with connect() as connection:
        used_by = connection.execute("SELECT slug, mcp FROM scenarios").fetchall()
        for row in used_by:
            if name in json_column(row, "mcp", []):
                raise HTTPException(
                    status_code=409,
                    detail=f"Scenario '{row['slug']}' still uses '{name}'. Remove it there first.",
                )
        connection.execute("DELETE FROM mcp_servers WHERE name = ?", (name,))

    from apps.api.mcp_client import clear_discovery_cache

    clear_discovery_cache()
    return Response(status_code=204)


@router.post("/{name}/test", response_model=ConnectionTest)
async def test_server(name: str, _: None = Depends(require_admin)) -> ConnectionTest:
    """Open a real session and list tools, so a broken server is caught before a demo."""
    from apps.api.mcp_client import discover_tools

    if name not in load_servers():
        raise HTTPException(status_code=404, detail=f"Unknown MCP server '{name}'.")

    try:
        tools = await discover_tools(name, force=True)
    except Exception as exc:
        return ConnectionTest(ok=False, detail=f"{type(exc).__name__}: {exc}")

    return ConnectionTest(
        ok=True,
        detail=f"Connected. {len(tools)} tool(s) available.",
        tools=[ToolSummary(name=tool["name"], description=tool["description"]) for tool in tools],
    )
