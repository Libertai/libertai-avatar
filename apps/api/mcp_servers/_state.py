"""File-backed state for the demo MCP servers.

A stdio server is spawned per tool call, so anything held in module globals is gone by the
next call: an avatar could book an appointment and then fail to find it a sentence later.
These servers keep their demo state in a small JSON file instead.

Real servers would use their own database; this exists so the examples behave like one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.getenv("MCP_DEMO_STATE_DIR", "apps/api/.mcp_demo_state"))


def _path(name: str) -> Path:
    return STATE_DIR / f"{name}.json"


def load(name: str) -> dict[str, Any]:
    """Read a server's state, returning an empty mapping when there is none yet."""
    try:
        return json.loads(_path(name).read_text())
    except (OSError, ValueError):
        return {}


def save(name: str, state: dict[str, Any]) -> None:
    """Write a server's state, creating the directory on first use."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _path(name).write_text(json.dumps(state, ensure_ascii=False, indent=2))
