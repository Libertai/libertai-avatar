import json

import respx
import pytest
from httpx import ASGITransport, AsyncClient, Response

from apps.api.main import app


@pytest.mark.anyio
async def test_missing_api_key_returns_400(monkeypatch):
    monkeypatch.delenv("LIBERTAI_API_KEY", raising=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 400
    assert "Missing LibertAI API key" in response.json()["detail"]


@pytest.mark.anyio
async def test_cors_preflight_allows_localhost_alias():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/chat",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-libertai-api-key",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


@pytest.mark.anyio
@respx.mock
async def test_chat_maps_to_libertai(monkeypatch):
    monkeypatch.delenv("LIBERTAI_API_KEY", raising=False)
    route = respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hello from LibertAI.",
                        }
                    }
                ]
            },
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/chat",
            headers={"X-LibertAI-API-Key": "demo-key"},
            json={
                "persona": "You are concise.",
                "model": "custom-model",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "role": "assistant",
        "content": "Hello from LibertAI.",
        "model": "custom-model",
        "tool_calls": [],
    }
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer demo-key"
    system_prompt = json.loads(request.content)["messages"][0]
    assert system_prompt["role"] == "system"
    assert system_prompt["content"].startswith("You are concise.")
    assert "no tools" in system_prompt["content"]


@pytest.mark.anyio
@respx.mock
async def test_chat_strips_hallucinated_tool_calls(monkeypatch):
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": 'Sure thing.\n<tool_call>\n{"name": "speech_to_text"}\n</tool_call>',
                        }
                    }
                ]
            },
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 200
    assert response.json()["content"] == "Sure thing."


@pytest.mark.anyio
@respx.mock
async def test_chat_rejects_replies_that_are_only_a_tool_call(monkeypatch):
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"content": '<tool_call>{"name": "speech_to_text"}</tool_call>'}}]},
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 502
    assert "tool call" in response.json()["detail"]


@pytest.mark.anyio
@respx.mock
async def test_chat_adds_no_tools_instruction_without_persona(monkeypatch):
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
    route = respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "Hello."}}]}),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    messages = json.loads(route.calls[0].request.content)["messages"]
    assert messages[0]["role"] == "system"
    assert "no tools" in messages[0]["content"]
