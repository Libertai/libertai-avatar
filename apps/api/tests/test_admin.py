import pytest
from httpx import ASGITransport, AsyncClient

from apps.api import secrets_box
from apps.api.db import connect, json_column
from apps.api.main import app
from apps.api.mcp_registry import McpServer, load_servers, save_server
from apps.api.scenarios import save_scenario, scenario_from_dict

SCENARIO = {
    "name": "Tony's Pizzeria",
    "rules": "Take the order.",
    "data": {"menu": ["Margherita"]},
    "mcp": [],
}


async def _client(token: str | None = None) -> AsyncClient:
    headers = {"X-Admin-Token": token} if token else {}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


def _payload(**overrides) -> dict:
    return {"slug": "pizzeria", **SCENARIO, **overrides}


@pytest.mark.anyio
async def test_creating_and_reading_back_a_scenario() -> None:
    async with await _client() as client:
        created = await client.put("/admin/scenarios/pizzeria", json=_payload())
        listed = await client.get("/admin/scenarios")

    assert created.status_code == 200
    assert created.json()["rules"] == "Take the order."
    assert [s["slug"] for s in listed.json()["scenarios"]] == ["pizzeria"]


@pytest.mark.anyio
async def test_slug_must_match_the_path() -> None:
    async with await _client() as client:
        response = await client.put("/admin/scenarios/pizzeria", json=_payload(slug="other"))

    assert response.status_code == 422


@pytest.mark.anyio
async def test_slugs_are_url_safe() -> None:
    async with await _client() as client:
        response = await client.put("/admin/scenarios/Bad Slug", json=_payload(slug="Bad Slug"))

    assert response.status_code == 422


@pytest.mark.anyio
async def test_a_scenario_cannot_reference_an_unregistered_server() -> None:
    async with await _client() as client:
        response = await client.put("/admin/scenarios/pizzeria", json=_payload(mcp=["ghost"]))

    assert response.status_code == 422
    assert "ghost" in response.json()["detail"]


@pytest.mark.anyio
async def test_deleting_a_scenario() -> None:
    save_scenario(scenario_from_dict("pizzeria", SCENARIO))

    async with await _client() as client:
        deleted = await client.delete("/admin/scenarios/pizzeria")
        missing = await client.delete("/admin/scenarios/pizzeria")

    assert deleted.status_code == 204
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_duplicating_a_scenario_makes_an_unpublished_copy() -> None:
    save_scenario(scenario_from_dict("pizzeria", SCENARIO))

    async with await _client() as client:
        first = await client.post("/admin/scenarios/pizzeria/duplicate")
        second = await client.post("/admin/scenarios/pizzeria/duplicate")

    assert first.json()["slug"] == "pizzeria-2"
    assert first.json()["published"] is False
    assert second.json()["slug"] == "pizzeria-3"


@pytest.mark.anyio
async def test_admin_endpoints_require_the_token_when_one_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")

    async with await _client() as anonymous:
        refused = await anonymous.get("/admin/scenarios")
    async with await _client("wrong") as wrong:
        rejected = await wrong.get("/admin/scenarios")
    async with await _client("s3cret") as allowed:
        accepted = await allowed.get("/admin/scenarios")

    assert refused.status_code == 401
    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["protected"] is True


@pytest.mark.anyio
async def test_public_endpoints_stay_open_when_admin_is_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    save_scenario(scenario_from_dict("pizzeria", SCENARIO))

    async with await _client() as client:
        response = await client.get("/scenarios")

    assert response.status_code == 200


@pytest.mark.anyio
async def test_mcp_credentials_are_encrypted_at_rest_and_masked_in_responses() -> None:
    async with await _client() as client:
        created = await client.put(
            "/mcp-servers/agenda",
            json={
                "name": "agenda",
                "transport": "http",
                "url": "https://mcp.example.com/mcp",
                "headers": {"Authorization": "Bearer live-token"},
            },
        )

    assert created.status_code == 200
    assert created.json()["headers"]["Authorization"] == secrets_box.MASK

    with connect() as connection:
        row = connection.execute("SELECT headers FROM mcp_servers WHERE name = 'agenda'").fetchone()
    stored = json_column(row, "headers", {})["Authorization"]
    assert "live-token" not in stored
    assert stored.startswith(secrets_box.ENCRYPTED_PREFIX)

    # The client still receives the real credential when it opens a session.
    assert load_servers(reveal=True)["agenda"].headers["Authorization"] == "Bearer live-token"


@pytest.mark.anyio
async def test_saving_a_masked_secret_keeps_the_stored_one() -> None:
    save_server(
        McpServer(name="agenda", transport="http", url="https://x/mcp", headers={"Authorization": "Bearer keep-me"})
    )

    async with await _client() as client:
        await client.put(
            "/mcp-servers/agenda",
            json={
                "name": "agenda",
                "transport": "http",
                "url": "https://x/mcp",
                "headers": {"Authorization": secrets_box.MASK},
            },
        )

    assert load_servers(reveal=True)["agenda"].headers["Authorization"] == "Bearer keep-me"


@pytest.mark.anyio
async def test_environment_references_are_stored_readable_not_encrypted() -> None:
    async with await _client() as client:
        created = await client.put(
            "/mcp-servers/agenda",
            json={
                "name": "agenda",
                "transport": "http",
                "url": "https://x/mcp",
                "headers": {"Authorization": "Bearer ${AGENDA_TOKEN}"},
            },
        )

    assert created.json()["headers"]["Authorization"] == "Bearer ${AGENDA_TOKEN}"


@pytest.mark.anyio
async def test_a_transport_must_have_what_it_needs() -> None:
    async with await _client() as client:
        no_url = await client.put("/mcp-servers/agenda", json={"name": "agenda", "transport": "http"})
        no_command = await client.put("/mcp-servers/local", json={"name": "local", "transport": "stdio"})

    assert no_url.status_code == 422
    assert no_command.status_code == 422


@pytest.mark.anyio
async def test_a_server_in_use_cannot_be_deleted() -> None:
    save_server(McpServer(name="pizzeria", transport="stdio", command="python"))
    save_scenario(scenario_from_dict("pizzeria", {**SCENARIO, "mcp": ["pizzeria"]}))

    async with await _client() as client:
        response = await client.delete("/mcp-servers/pizzeria")

    assert response.status_code == 409
    assert "still uses" in response.json()["detail"]


@pytest.mark.anyio
async def test_testing_an_unknown_server_is_a_404() -> None:
    async with await _client() as client:
        response = await client.post("/mcp-servers/ghost/test")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_a_failing_server_reports_why_instead_of_raising() -> None:
    save_server(McpServer(name="broken", transport="stdio", command="definitely-not-a-real-binary"))

    async with await _client() as client:
        response = await client.post("/mcp-servers/broken/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["tools"] == []


@pytest.mark.anyio
async def test_cors_preflight_allows_the_admin_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The admin UI saves with PUT and removes with DELETE; a preflight refusal blocks both."""
    async with await _client() as client:
        for method in ("PUT", "DELETE"):
            response = await client.options(
                "/admin/scenarios/pizzeria",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type,x-admin-token",
                },
            )
            assert response.status_code == 200, method
            assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.anyio
async def test_health_reports_whether_admin_is_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scenarios page reads this without a token, which /admin/scenarios cannot give it."""
    async with await _client() as client:
        open_api = await client.get("/health")
        monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
        guarded = await client.get("/health")

    assert open_api.json()["admin_protected"] is False
    assert guarded.json()["admin_protected"] is True
