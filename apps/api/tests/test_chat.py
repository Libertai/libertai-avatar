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
    }
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer demo-key"
    assert json.loads(request.content)["messages"][0] == {"role": "system", "content": "You are concise."}
