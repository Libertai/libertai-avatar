import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from pathlib import Path

import pytest

from apps.api import mcp_client
from apps.api.mcp_registry import McpServer, save_server


@pytest.fixture(autouse=True)
def clean_cache():
    mcp_client.clear_discovery_cache()
    yield
    mcp_client.clear_discovery_cache()


@pytest.fixture
def servers_file():
    """Register servers by name; contents do not matter because sessions are faked."""

    def register(config: dict) -> None:
        for name in config:
            save_server(McpServer(name=name, transport="stdio", command="python", args=["x.py"]))

    return register


def fake_discovery(monkeypatch: pytest.MonkeyPatch, by_server: dict[str, list[str]], counter: dict | None = None):
    async def _discover(name, server):
        if counter is not None:
            counter[name] = counter.get(name, 0) + 1
        return [{"name": tool, "description": "", "schema": {"type": "object"}} for tool in by_server.get(name, [])]

    monkeypatch.setattr(mcp_client, "_discover", _discover)


@pytest.mark.anyio
async def test_lists_tools_from_several_servers(servers_file, monkeypatch: pytest.MonkeyPatch) -> None:
    servers_file({"agenda": {}, "pricing": {}})
    fake_discovery(monkeypatch, {"agenda": ["list_slots"], "pricing": ["quote"]})

    tools = await mcp_client.list_tools(["agenda", "pricing"])

    assert [tool["function"]["name"] for tool in tools] == ["list_slots", "quote"]


@pytest.mark.anyio
async def test_a_later_server_cannot_shadow_an_earlier_tool(servers_file, monkeypatch: pytest.MonkeyPatch) -> None:
    servers_file({"trusted": {}, "other": {}})
    fake_discovery(monkeypatch, {"trusted": ["lookup"], "other": ["lookup", "extra"]})

    tools = await mcp_client.list_tools(["trusted", "other"])

    assert [tool["function"]["name"] for tool in tools] == ["lookup", "extra"]


@pytest.mark.anyio
async def test_unknown_server_names_are_ignored(servers_file, monkeypatch: pytest.MonkeyPatch) -> None:
    servers_file({"agenda": {}})
    fake_discovery(monkeypatch, {"agenda": ["list_slots"]})

    tools = await mcp_client.list_tools(["agenda", "not-configured"])

    assert [tool["function"]["name"] for tool in tools] == ["list_slots"]


@pytest.mark.anyio
async def test_allowlist_filters_tools(servers_file, monkeypatch: pytest.MonkeyPatch) -> None:
    servers_file({"agenda": {}})
    fake_discovery(monkeypatch, {"agenda": ["list_slots", "delete_calendar"]})

    tools = await mcp_client.list_tools(["agenda"], ["list_slots"])

    assert [tool["function"]["name"] for tool in tools] == ["list_slots"]


@pytest.mark.anyio
async def test_call_tool_reports_a_tool_no_server_provides(servers_file, monkeypatch: pytest.MonkeyPatch) -> None:
    servers_file({"agenda": {}})
    fake_discovery(monkeypatch, {"agenda": ["list_slots"]})

    assert await mcp_client.call_tool(["agenda"], "quote", {}) == "Tool 'quote' is not available."


@pytest.mark.anyio
async def test_discovery_connects_once_and_then_serves_from_cache(
    servers_file, monkeypatch: pytest.MonkeyPatch
) -> None:
    servers_file({"agenda": {}})
    connections = {"count": 0}

    class FakeTool:
        name = "list_slots"
        description = "List slots"
        inputSchema = {"type": "object"}

    class FakeSession:
        async def list_tools(self):
            return SimpleNamespace(tools=[FakeTool()])

    @asynccontextmanager
    async def counting_session(server):
        connections["count"] += 1
        yield FakeSession()

    monkeypatch.setattr(mcp_client, "_session", counting_session)

    first = await mcp_client.list_tools(["agenda"])
    second = await mcp_client.list_tools(["agenda"])

    assert connections["count"] == 1
    assert first == second


@pytest.mark.anyio
async def test_expired_discovery_reconnects(servers_file, monkeypatch: pytest.MonkeyPatch) -> None:
    servers_file({"agenda": {}})
    connections = {"count": 0}

    class FakeSession:
        async def list_tools(self):
            return SimpleNamespace(tools=[])

    @asynccontextmanager
    async def counting_session(server):
        connections["count"] += 1
        yield FakeSession()

    monkeypatch.setattr(mcp_client, "_session", counting_session)
    monkeypatch.setattr(mcp_client, "DISCOVERY_TTL_SECONDS", 0)

    await mcp_client.list_tools(["agenda"])
    await mcp_client.list_tools(["agenda"])

    assert connections["count"] == 2


def test_secrets_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXAMPLE_MCP_TOKEN", "s3cret")

    resolved = mcp_client._resolve_secrets({"Authorization": "Bearer ${EXAMPLE_MCP_TOKEN}"})

    assert resolved == {"Authorization": "Bearer s3cret"}


def test_missing_secrets_resolve_to_empty_rather_than_leaking_the_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ABSENT_TOKEN", raising=False)

    assert mcp_client._resolve_secrets("Bearer ${ABSENT_TOKEN}") == "Bearer "


@pytest.mark.anyio
async def test_unknown_transport_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown MCP transport"):
        async with mcp_client._session({"transport": "carrier-pigeon"}):
            pass


def test_an_empty_registry_means_no_servers() -> None:
    assert mcp_client.configured_servers() == {}
