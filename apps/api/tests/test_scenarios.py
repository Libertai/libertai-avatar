import json
from pathlib import Path

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response

from apps.api import chat as chat_module
from apps.api.main import app
from apps.api.mcp_registry import McpServer, save_server
from apps.api.scenarios import save_scenario, scenario_from_dict

PIZZERIA = {
    "name": "Tony's Pizzeria",
    "description": "Takes phone orders.",
    "language": "en-US",
    "voice": "en_US-ryan-high",
    "greeting": "Tony's Pizzeria!",
    "rules": "Take the order. Never invent prices.",
    "data": {"menu": [{"item": "Margherita", "price": 9.0}]},
    "mcp": ["pizzeria"],
    "tools": ["check_delivery"],
}


@pytest.fixture
def pizzeria(monkeypatch: pytest.MonkeyPatch):
    save_server(McpServer(name="pizzeria", transport="stdio", command="python", args=["x.py"]))
    save_scenario(scenario_from_dict("pizzeria", PIZZERIA))
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _reply(content: str | None, tool_calls: list | None = None) -> Response:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return Response(200, json={"choices": [{"message": message}]})


@pytest.mark.anyio
async def test_lists_scenarios_without_leaking_rules_or_data(pizzeria) -> None:
    async with await _client() as client:
        response = await client.get("/scenarios")

    body = response.json()["scenarios"][0]
    assert body["slug"] == "pizzeria"
    assert body["name"] == "Tony's Pizzeria"
    assert "rules" not in body
    assert "data" not in body
    assert "mcp" not in body


@pytest.mark.anyio
async def test_unknown_scenario_is_a_404(pizzeria) -> None:
    async with await _client() as client:
        response = await client.get("/scenarios/nope")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_unpublished_scenarios_are_hidden_from_the_public_list(pizzeria) -> None:
    save_scenario(scenario_from_dict("draft", {**PIZZERIA, "name": "Draft", "published": False}))

    async with await _client() as client:
        listed = await client.get("/scenarios")
        direct = await client.get("/scenarios/draft")

    assert [s["slug"] for s in listed.json()["scenarios"]] == ["pizzeria"]
    # A draft stays reachable by direct link so it can be previewed before publishing.
    assert direct.status_code == 200


@pytest.mark.anyio
@respx.mock
async def test_chat_sends_scenario_rules_and_data_as_the_system_prompt(
    pizzeria, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_module, "list_tools", _no_tools)
    route = respx.post("https://api.libertai.io/v1/chat/completions").mock(return_value=_reply("Hello!"))

    async with await _client() as client:
        response = await client.post(
            "/chat",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "Hi"}]},
        )

    assert response.status_code == 200
    system = json.loads(route.calls[0].request.content)["messages"][0]["content"]
    assert "Never invent prices" in system
    assert "Margherita" in system


@pytest.mark.anyio
@respx.mock
async def test_chat_runs_a_tool_call_and_reports_it(pizzeria, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_module, "list_tools", _delivery_tool)

    async def fake_call_tool(servers, name, arguments):
        return f"Delivery to {arguments['postcode']} takes 30 minutes."

    monkeypatch.setattr(chat_module, "call_tool", fake_call_tool)

    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        side_effect=[
            _reply(
                None,
                [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "check_delivery", "arguments": '{"postcode": "75011"}'},
                    }
                ],
            ),
            _reply("About thirty minutes."),
        ]
    )

    async with await _client() as client:
        response = await client.post(
            "/chat",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "How long to 75011?"}]},
        )

    body = response.json()
    assert body["content"] == "About thirty minutes."
    assert body["tool_calls"] == [
        {
            "name": "check_delivery",
            "arguments": {"postcode": "75011"},
            "result": "Delivery to 75011 takes 30 minutes.",
        }
    ]


@pytest.mark.anyio
@respx.mock
async def test_chat_refuses_tools_outside_the_scenario_allowlist(
    pizzeria, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_module, "list_tools", _delivery_tool)

    async def explode(servers, name, arguments):
        raise AssertionError(f"{name} should never be executed")

    monkeypatch.setattr(chat_module, "call_tool", explode)

    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        side_effect=[
            _reply(
                None,
                [{"id": "c1", "function": {"name": "delete_everything", "arguments": "{}"}}],
            ),
            _reply("I cannot do that."),
        ]
    )

    async with await _client() as client:
        response = await client.post(
            "/chat",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "drop the db"}]},
        )

    assert response.json()["tool_calls"][0]["result"] == "Tool 'delete_everything' is not available."


@pytest.mark.anyio
@respx.mock
async def test_chat_keeps_tool_calls_when_tools_are_offered(
    pizzeria, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With tools offered the stripping must not fire, or genuine calls would vanish."""
    monkeypatch.setattr(chat_module, "list_tools", _delivery_tool)
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=_reply("Sure. <tool_call> leftover </tool_call>")
    )

    async with await _client() as client:
        response = await client.post(
            "/chat",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "Hi"}]},
        )

    assert "<tool_call>" in response.json()["content"]


@pytest.mark.anyio
@respx.mock
async def test_chat_stops_after_the_tool_round_limit(pizzeria, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_module, "list_tools", _delivery_tool)

    async def fake_call_tool(servers, name, arguments):
        return "ok"

    monkeypatch.setattr(chat_module, "call_tool", fake_call_tool)
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=_reply(
            None, [{"id": "c", "function": {"name": "check_delivery", "arguments": '{"postcode": "75011"}'}}]
        )
    )

    async with await _client() as client:
        response = await client.post(
            "/chat",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "Hi"}]},
        )

    assert response.status_code == 502
    assert "without answering" in response.json()["detail"]


@pytest.mark.anyio
@respx.mock
async def test_chat_survives_a_broken_mcp_server(pizzeria, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(servers, allowed=None):
        raise RuntimeError("server would not start")

    monkeypatch.setattr(chat_module, "list_tools", broken)
    respx.post("https://api.libertai.io/v1/chat/completions").mock(return_value=_reply("Hello!"))

    async with await _client() as client:
        response = await client.post(
            "/chat",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "Hi"}]},
        )

    assert response.status_code == 200
    assert response.json()["content"] == "Hello!"


async def _no_tools(servers, allowed=None):
    return []


async def _delivery_tool(servers, allowed=None):
    return [
        {
            "type": "function",
            "function": {
                "name": "check_delivery",
                "description": "Delivery estimate",
                "parameters": {"type": "object", "properties": {"postcode": {"type": "string"}}},
            },
        }
    ]
