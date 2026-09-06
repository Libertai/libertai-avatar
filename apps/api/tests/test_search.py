import json

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response

from apps.api import chat as chat_module
from apps.api import search
from apps.api.main import app
from apps.api.scenarios import save_scenario, scenario_from_dict

RESULTS = {
    "results": [
        {
            "title": "The Rust Programming Language",
            "url": "https://doc.rust-lang.org/book/",
            "snippet": "Official documentation for the Rust programming language.",
            "engine": "google",
            "rank": 1,
            "found_in": ["google", "bing"],
            "search_type": "web",
        },
        {
            "title": "Rust",
            "url": "https://www.rust-lang.org/",
            "snippet": "A language empowering everyone.",
            "engine": "bing",
            "rank": 2,
            "found_in": ["bing"],
            "search_type": "web",
        },
    ],
    "meta": {"duration_ms": 900, "engines_used": ["google", "bing"], "engines_failed": []},
}


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestFormatting:
    def test_results_carry_title_url_and_snippet(self) -> None:
        rendered = search.format_results(RESULTS)

        assert "1. The Rust Programming Language" in rendered
        assert "https://doc.rust-lang.org/book/" in rendered
        assert "Official documentation" in rendered

    def test_cross_engine_agreement_is_shown(self) -> None:
        """found_in is the only ranking signal the model gets, so it has to survive."""
        rendered = search.format_results(RESULTS)

        assert "found by 2 engines" in rendered
        assert rendered.count("found by") == 1

    def test_long_snippets_are_truncated(self) -> None:
        rendered = search.format_results(
            {"results": [{"title": "t", "url": "u", "snippet": "x" * 900, "found_in": []}]}
        )

        assert len(rendered) < 500

    def test_no_results_says_so(self) -> None:
        assert search.format_results({"results": []}) == "No results found."

    def test_engine_failures_are_reported_rather_than_hidden(self) -> None:
        rendered = search.format_results({"results": [], "meta": {"engines_failed": ["google"]}})

        assert "google" in rendered

    def test_a_fetched_page_is_truncated(self) -> None:
        rendered = search.format_page({"title": "Article", "content": "word " * 5000})

        assert rendered.startswith("Article")
        assert "truncated" in rendered
        assert len(rendered) < search.MAX_PAGE_CHARS + 200

    def test_an_empty_page_says_so(self) -> None:
        assert "no readable text" in search.format_page({"title": "x", "content": ""})


class TestRunTool:
    @pytest.mark.anyio
    @respx.mock
    async def test_searching_posts_the_query(self) -> None:
        route = respx.post("https://api.libertai.io/search").mock(return_value=Response(200, json=RESULTS))

        result = await search.run_tool(search.WEB_SEARCH, {"query": "rust"}, "key")

        assert "Rust Programming Language" in result
        sent = json.loads(route.calls[0].request.content)
        assert sent["query"] == "rust"
        assert sent["search_type"] == "web"
        assert route.calls[0].request.headers["authorization"] == "Bearer key"

    @pytest.mark.anyio
    @respx.mock
    async def test_an_unknown_search_type_falls_back_to_web(self) -> None:
        route = respx.post("https://api.libertai.io/search").mock(return_value=Response(200, json=RESULTS))

        await search.run_tool(search.WEB_SEARCH, {"query": "x", "search_type": "telepathy"}, "key")

        assert json.loads(route.calls[0].request.content)["search_type"] == "web"

    @pytest.mark.anyio
    async def test_an_empty_query_is_refused_without_calling_out(self) -> None:
        assert "No search query" in await search.run_tool(search.WEB_SEARCH, {"query": "  "}, "key")

    @pytest.mark.anyio
    @respx.mock
    async def test_fetching_a_page_returns_its_text(self) -> None:
        respx.post("https://api.libertai.io/search/fetch").mock(
            return_value=Response(200, json={"title": "Article Title", "content": "The cleaned text."})
        )

        result = await search.run_tool(search.FETCH_PAGE, {"url": "https://example.com/a"}, "key")

        assert "Article Title" in result
        assert "The cleaned text." in result

    @pytest.mark.anyio
    async def test_non_http_urls_are_refused(self) -> None:
        """A model that invents file:// or a private scheme must not reach the fetcher."""
        assert "http and https" in await search.run_tool(search.FETCH_PAGE, {"url": "file:///etc/passwd"}, "key")

    @pytest.mark.anyio
    @respx.mock
    async def test_an_api_failure_becomes_text_for_the_conversation(self) -> None:
        respx.post("https://api.libertai.io/search").mock(return_value=Response(402, json={"detail": "payment"}))

        result = await search.run_tool(search.WEB_SEARCH, {"query": "rust"}, "key")

        assert "402" in result
        assert "could not look that up" in result

    @pytest.mark.anyio
    async def test_an_unknown_tool_name_is_reported(self) -> None:
        assert "Unknown search tool" in await search.run_tool("teleport", {}, "key")


SCENARIO = {"name": "Concierge", "rules": "Help the caller.", "mcp": []}


def reply(content: str | None, tool_calls: list | None = None) -> Response:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return Response(200, json={"choices": [{"message": message}]})


class TestChatIntegration:
    @pytest.mark.anyio
    @respx.mock
    async def test_search_tools_are_offered_when_the_scenario_enables_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_scenario(scenario_from_dict("concierge", {**SCENARIO, "search": True}))
        monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
        route = respx.post("https://api.libertai.io/v1/chat/completions").mock(return_value=reply("Hello."))

        async with await _client() as client:
            await client.post(
                "/chat", json={"scenario": "concierge", "messages": [{"role": "user", "content": "Hi"}]}
            )

        sent = json.loads(route.calls[0].request.content)
        assert [tool["function"]["name"] for tool in sent["tools"]] == ["web_search", "fetch_page"]
        assert "search the web" in sent["messages"][0]["content"]

    @pytest.mark.anyio
    @respx.mock
    async def test_no_search_tools_when_the_scenario_does_not_enable_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_scenario(scenario_from_dict("concierge", SCENARIO))
        monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
        route = respx.post("https://api.libertai.io/v1/chat/completions").mock(return_value=reply("Hello."))

        async with await _client() as client:
            await client.post(
                "/chat", json={"scenario": "concierge", "messages": [{"role": "user", "content": "Hi"}]}
            )

        assert "tools" not in json.loads(route.calls[0].request.content)

    @pytest.mark.anyio
    @respx.mock
    async def test_a_search_call_runs_and_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_scenario(scenario_from_dict("concierge", {**SCENARIO, "search": True}))
        monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
        respx.post("https://api.libertai.io/search").mock(return_value=Response(200, json=RESULTS))
        respx.post("https://api.libertai.io/v1/chat/completions").mock(
            side_effect=[
                reply(None, [{"id": "c1", "function": {"name": "web_search", "arguments": '{"query": "rust"}'}}]),
                reply("Rust is a systems language."),
            ]
        )

        async with await _client() as client:
            response = await client.post(
                "/chat", json={"scenario": "concierge", "messages": [{"role": "user", "content": "what is rust"}]}
            )

        body = response.json()
        assert body["content"] == "Rust is a systems language."
        assert body["tool_calls"][0]["name"] == "web_search"
        assert "Rust Programming Language" in body["tool_calls"][0]["result"]

    @pytest.mark.anyio
    @respx.mock
    async def test_search_is_refused_when_it_is_not_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The model may ask for a tool it was never offered; the flag is the real gate."""
        save_scenario(scenario_from_dict("concierge", SCENARIO))
        monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
        respx.post("https://api.libertai.io/v1/chat/completions").mock(
            side_effect=[
                reply(None, [{"id": "c1", "function": {"name": "web_search", "arguments": '{"query": "x"}'}}]),
                reply("I cannot search."),
            ]
        )

        async with await _client() as client:
            response = await client.post(
                "/chat", json={"scenario": "concierge", "messages": [{"role": "user", "content": "search"}]}
            )

        assert response.json()["tool_calls"][0]["result"] == "Tool 'web_search' is not available."

    @pytest.mark.anyio
    @respx.mock
    async def test_a_scenario_tool_allowlist_does_not_block_search(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """search is its own opt-in; the allowlist governs MCP tools."""
        save_scenario(
            scenario_from_dict("concierge", {**SCENARIO, "search": True, "tools": ["something_else"]})
        )
        monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
        respx.post("https://api.libertai.io/search").mock(return_value=Response(200, json=RESULTS))
        respx.post("https://api.libertai.io/v1/chat/completions").mock(
            side_effect=[
                reply(None, [{"id": "c1", "function": {"name": "web_search", "arguments": '{"query": "rust"}'}}]),
                reply("Done."),
            ]
        )

        async with await _client() as client:
            response = await client.post(
                "/chat", json={"scenario": "concierge", "messages": [{"role": "user", "content": "search"}]}
            )

        assert "not available" not in response.json()["tool_calls"][0]["result"]

    @pytest.mark.anyio
    @respx.mock
    async def test_the_sandbox_can_enable_search_without_a_scenario(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
        respx.post("https://api.libertai.io/search").mock(return_value=Response(200, json=RESULTS))
        respx.post("https://api.libertai.io/v1/chat/completions").mock(
            side_effect=[
                reply(None, [{"id": "c1", "function": {"name": "web_search", "arguments": '{"query": "rust"}'}}]),
                reply("Found it."),
            ]
        )

        async with await _client() as client:
            response = await client.post(
                "/chat",
                json={"search": True, "persona": "Be helpful.", "messages": [{"role": "user", "content": "rust?"}]},
            )

        assert response.json()["content"] == "Found it."
        assert response.json()["tool_calls"][0]["name"] == "web_search"
