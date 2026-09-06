"""Web search and page fetching, exposed to the model as tools.

LibertAI's search API queries several engines at once and returns a deduplicated list, with
``found_in`` naming every engine that returned a URL. These are offered to the model in the
same shape as MCP tools, so the avatar decides when to look something up.

https://docs.libertai.io/apis/search/usage.html
"""

from __future__ import annotations

import os
from typing import Any

import httpx

LIBERTAI_BASE_URL = os.getenv("LIBERTAI_BASE_URL", "https://api.libertai.io").rstrip("/")
SEARCH_TIMEOUT_SECONDS = float(os.getenv("SEARCH_TIMEOUT", "20"))

# Enough for the model to answer from, without burying the conversation in the prompt.
MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "6"))
MAX_SNIPPET_CHARS = 300
MAX_PAGE_CHARS = int(os.getenv("SEARCH_MAX_PAGE_CHARS", "6000"))
SEARCH_TYPES = ("web", "news", "images", "academic")

WEB_SEARCH = "web_search"
FETCH_PAGE = "fetch_page"
TOOL_NAMES = frozenset({WEB_SEARCH, FETCH_PAGE})

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": WEB_SEARCH,
            "description": (
                "Search the web for current information. Use this whenever the answer depends on "
                "something you cannot know, such as recent events, prices, or facts you are unsure of."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                    "search_type": {
                        "type": "string",
                        "enum": list(SEARCH_TYPES),
                        "description": "Kind of search. Defaults to web.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": FETCH_PAGE,
            "description": (
                "Fetch one web page and read its text. Use it after a search when a result "
                "looks like it holds the detail you need."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "The page to read."}},
                "required": ["url"],
            },
        },
    },
]


async def _post(path: str, payload: dict, api_key: str) -> dict:
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{LIBERTAI_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def format_results(data: dict) -> str:
    """Render search results as compact text the model can quote and cite from."""
    results = data.get("results") or []
    if not results:
        failed = (data.get("meta") or {}).get("engines_failed") or []
        if failed:
            return f"No results. These engines failed: {', '.join(map(str, failed))}."
        return "No results found."

    lines = []
    for position, result in enumerate(results[:MAX_RESULTS], start=1):
        title = str(result.get("title") or "Untitled").strip()
        url = str(result.get("url") or "").strip()
        snippet = " ".join(str(result.get("snippet") or "").split())[:MAX_SNIPPET_CHARS]

        line = f"{position}. {title}\n   {url}"
        if snippet:
            line += f"\n   {snippet}"
        # Several engines returning the same URL is the strongest signal available here.
        found_in = result.get("found_in") or []
        if len(found_in) > 1:
            line += f"\n   (found by {len(found_in)} engines)"
        if result.get("published_at"):
            line += f"\n   published {result['published_at']}"
        lines.append(line)

    return "\n".join(lines)


def format_page(data: dict) -> str:
    """Render a fetched page, truncated so one long article cannot fill the context."""
    title = str(data.get("title") or "").strip()
    content = " ".join(str(data.get("content") or "").split())
    if not content:
        return "That page had no readable text."

    body = content[:MAX_PAGE_CHARS]
    if len(content) > MAX_PAGE_CHARS:
        body += " […truncated]"
    return f"{title}\n\n{body}" if title else body


async def run_tool(name: str, arguments: dict, api_key: str) -> str:
    """Run one search tool, returning text for the conversation rather than raising.

    Args:
        name: Tool the model asked for.
        arguments: Its arguments, as parsed from the model's request.
        api_key: LibertAI key; search bills against the same account as inference.
    """
    try:
        if name == WEB_SEARCH:
            query = str(arguments.get("query") or "").strip()
            if not query:
                return "No search query was given."

            search_type = str(arguments.get("search_type") or "web")
            if search_type not in SEARCH_TYPES:
                search_type = "web"

            data = await _post(
                "/search",
                {"query": query, "max_results": MAX_RESULTS, "search_type": search_type},
                api_key,
            )
            return format_results(data)

        if name == FETCH_PAGE:
            url = str(arguments.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                return "Only http and https URLs can be fetched."

            return format_page(await _post("/search/fetch", {"url": url}, api_key))
    except httpx.HTTPStatusError as exc:
        return f"Search failed with status {exc.response.status_code}. Tell the caller you could not look that up."
    except httpx.HTTPError as exc:
        return f"Search was unreachable: {exc}. Tell the caller you could not look that up."

    return f"Unknown search tool '{name}'."
