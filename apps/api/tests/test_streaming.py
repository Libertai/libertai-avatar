import json

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response

from apps.api import chat as chat_module
from apps.api.chat import ToolCallScrubber, merge_tool_call_delta
from apps.api.main import app
from apps.api.mcp_registry import McpServer, save_server
from apps.api.scenarios import save_scenario, scenario_from_dict

PIZZERIA = {
    "name": "Tony's Pizzeria",
    "rules": "Take the order.",
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


def sse_stream(*chunks: dict) -> Response:
    """A streamed completion, in the wire format the API sends."""
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    return Response(200, text=body, headers={"Content-Type": "text/event-stream"})


def deltas(*texts: str) -> list[dict]:
    return [{"choices": [{"delta": {"content": text}}]} for text in texts]


async def collect(response) -> list[dict]:
    events = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :]))
    return events


async def _no_tools(servers, allowed=None):
    return []


async def _delivery_tool(servers, allowed=None):
    return [
        {
            "type": "function",
            "function": {"name": "check_delivery", "description": "", "parameters": {"type": "object"}},
        }
    ]


@pytest.mark.anyio
@respx.mock
async def test_text_arrives_as_deltas_then_done(pizzeria, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_module, "list_tools", _no_tools)
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=sse_stream(*deltas("Tony's ", "Pizzeria, ", "good evening!"))
    )

    async with await _client() as client:
        async with client.stream(
            "POST", "/chat/stream", json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "Hi"}]}
        ) as response:
            events = await collect(response)

    assert [e["text"] for e in events if e["type"] == "delta"] == ["Tony's ", "Pizzeria, ", "good evening!"]
    assert events[-1] == {"type": "done", "content": "Tony's Pizzeria, good evening!", "model": chat_module.DEFAULT_MODEL}


@pytest.mark.anyio
@respx.mock
async def test_a_tool_call_is_run_and_reported_mid_stream(pizzeria, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_module, "list_tools", _delivery_tool)

    async def fake_call_tool(servers, name, arguments):
        return f"Delivery to {arguments['postcode']} takes 30 minutes."

    monkeypatch.setattr(chat_module, "call_tool", fake_call_tool)

    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        side_effect=[
            # The model asks for a tool, its arguments split across chunks as they stream.
            sse_stream(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "id": "c1", "function": {"name": "check_delivery", "arguments": '{"post'}}
                                ]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'code": "75011"}'}}]}}]},
            ),
            sse_stream(*deltas("About ", "thirty minutes.")),
        ]
    )

    async with await _client() as client:
        async with client.stream(
            "POST",
            "/chat/stream",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "How long to 75011?"}]},
        ) as response:
            events = await collect(response)

    tool_events = [e for e in events if e["type"] == "tool"]
    assert tool_events == [
        {
            "type": "tool",
            "name": "check_delivery",
            "arguments": {"postcode": "75011"},
            "result": "Delivery to 75011 takes 30 minutes.",
        }
    ]
    assert events[-1]["content"] == "About thirty minutes."


@pytest.mark.anyio
@respx.mock
async def test_an_upstream_failure_becomes_an_error_event(pizzeria, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_module, "list_tools", _no_tools)
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=Response(429, json={"error": {"message": "rate limited"}})
    )

    async with await _client() as client:
        async with client.stream(
            "POST", "/chat/stream", json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "Hi"}]}
        ) as response:
            events = await collect(response)

    assert events == [{"type": "error", "detail": "rate limited"}]


@pytest.mark.anyio
@respx.mock
async def test_hallucinated_tool_tags_never_reach_the_stream(pizzeria, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no tools offered, a block in the content would otherwise be spoken aloud."""
    monkeypatch.setattr(chat_module, "list_tools", _no_tools)
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=sse_stream(*deltas("Sure. <tool_", 'call>{"name": "x"}</tool_', "call> Anything else?"))
    )

    async with await _client() as client:
        async with client.stream(
            "POST", "/chat/stream", json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "Hi"}]}
        ) as response:
            events = await collect(response)

    spoken = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "tool_call" not in spoken
    assert spoken.strip() == "Sure.  Anything else?".strip()


@pytest.mark.anyio
async def test_a_missing_api_key_is_rejected_before_streaming(pizzeria, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIBERTAI_API_KEY", raising=False)

    async with await _client() as client:
        response = await client.post(
            "/chat/stream", json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "Hi"}]}
        )

    assert response.status_code == 400


class TestToolCallScrubber:
    def test_passes_ordinary_text_through(self) -> None:
        scrubber = ToolCallScrubber()
        assert scrubber.feed("Hello there.") == "Hello there."
        assert scrubber.flush() == ""

    def test_drops_a_block_split_across_chunks(self) -> None:
        scrubber = ToolCallScrubber()
        out = "".join(scrubber.feed(chunk) for chunk in ["Sure. <tool_", 'call>{"a":1}</tool_', "call> Done."])
        assert out + scrubber.flush() == "Sure.  Done."

    def test_holds_back_a_tail_that_might_become_a_tag(self) -> None:
        scrubber = ToolCallScrubber()
        assert scrubber.feed("Ready <") == "Ready "
        assert scrubber.feed("tool_call>hidden</tool_call>!") == "!"

    def test_a_lone_angle_bracket_is_released_once_it_cannot_be_a_tag(self) -> None:
        scrubber = ToolCallScrubber()
        first = scrubber.feed("2 < 3 and that is arithmetic, not markup")
        assert "< 3" in first + scrubber.flush()

    def test_an_unclosed_block_swallows_the_rest(self) -> None:
        scrubber = ToolCallScrubber()
        scrubber.feed("Sure. <tool_call>{unterminated")
        assert scrubber.flush() == ""


class TestMergeToolCallDelta:
    def test_fragments_are_joined_per_call(self) -> None:
        calls: dict[int, dict] = {}
        merge_tool_call_delta(calls, {"index": 0, "id": "a", "function": {"name": "f", "arguments": '{"x":'}})
        merge_tool_call_delta(calls, {"index": 0, "function": {"arguments": "1}"}})

        assert calls[0]["id"] == "a"
        assert calls[0]["function"] == {"name": "f", "arguments": '{"x":1}'}

    def test_parallel_calls_stay_separate(self) -> None:
        calls: dict[int, dict] = {}
        merge_tool_call_delta(calls, {"index": 0, "function": {"name": "first", "arguments": "{}"}})
        merge_tool_call_delta(calls, {"index": 1, "function": {"name": "second", "arguments": "{}"}})

        assert [calls[i]["function"]["name"] for i in sorted(calls)] == ["first", "second"]


SUMMARY_SCENARIO = {**PIZZERIA, "collect": ["phone", "items", "total"]}


def summary_reply(content: str) -> Response:
    return Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.mark.anyio
@respx.mock
async def test_summary_returns_only_the_declared_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    save_scenario(scenario_from_dict("pizzeria", SUMMARY_SCENARIO))
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=summary_reply(
            '{"phone": "0600000000", "items": "2 margheritas", "total": "27 EUR", '
            '"outcome": "Order placed for delivery.", "unexpected": "ignored"}'
        )
    )

    async with await _client() as client:
        response = await client.post(
            "/chat/summary",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "two margheritas"}]},
        )

    body = response.json()
    assert body["fields"] == {"phone": "0600000000", "items": "2 margheritas", "total": "27 EUR"}
    assert body["outcome"] == "Order placed for delivery."


@pytest.mark.anyio
@respx.mock
async def test_a_field_the_caller_never_gave_comes_back_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    save_scenario(scenario_from_dict("pizzeria", SUMMARY_SCENARIO))
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=summary_reply('{"items": "1 diavola", "outcome": "Started an order."}')
    )

    async with await _client() as client:
        response = await client.post(
            "/chat/summary",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "a diavola"}]},
        )

    assert response.json()["fields"] == {"phone": "", "items": "1 diavola", "total": ""}


@pytest.mark.anyio
@respx.mock
async def test_a_fenced_or_padded_reply_is_still_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    save_scenario(scenario_from_dict("pizzeria", SUMMARY_SCENARIO))
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=summary_reply('Here you go:\n```json\n{"phone": "0600", "outcome": "Done."}\n```\nHope that helps.')
    )

    async with await _client() as client:
        response = await client.post(
            "/chat/summary",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.json()["fields"]["phone"] == "0600"


@pytest.mark.anyio
@respx.mock
async def test_a_reply_with_no_object_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    save_scenario(scenario_from_dict("pizzeria", SUMMARY_SCENARIO))
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")
    respx.post("https://api.libertai.io/v1/chat/completions").mock(
        return_value=summary_reply("I could not summarize that.")
    )

    async with await _client() as client:
        response = await client.post(
            "/chat/summary",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 502
    assert "summary object" in response.json()["detail"]


@pytest.mark.anyio
async def test_a_scenario_that_collects_nothing_cannot_be_summarized(monkeypatch: pytest.MonkeyPatch) -> None:
    save_scenario(scenario_from_dict("pizzeria", {**PIZZERIA, "collect": []}))
    monkeypatch.setenv("LIBERTAI_API_KEY", "server-key")

    async with await _client() as client:
        response = await client.post(
            "/chat/summary",
            json={"scenario": "pizzeria", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 422
    assert "does not declare" in response.json()["detail"]
