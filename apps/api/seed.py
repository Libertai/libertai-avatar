"""Seed the database from the JSON files in the repository.

The files are the versioned source of the example scenarios; the database is where edits
made in the admin UI live. Seeding only inserts what is missing, so a scenario you have
edited is never overwritten by its shipped version.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from apps.api.db import connect
from apps.api.mcp_registry import McpServer, save_server
from apps.api.scenarios import save_scenario, scenario_from_dict

SEED_SCENARIOS_DIR = Path(os.getenv("SEED_SCENARIOS_DIR", "apps/api/scenarios"))
SEED_SERVERS_FILE = Path(os.getenv("SEED_MCP_SERVERS_FILE", "apps/api/mcp_servers.json"))


def _existing(table: str, key: str) -> set[str]:
    with connect() as connection:
        return {row[0] for row in connection.execute(f"SELECT {key} FROM {table}")}


def seed_servers() -> list[str]:
    try:
        config = json.loads(SEED_SERVERS_FILE.read_text())
    except (OSError, ValueError):
        return []

    known = _existing("mcp_servers", "name")
    added = []
    for name, server in config.items():
        if name in known:
            continue
        save_server(McpServer(name=name, **server))
        added.append(name)
    return added


def seed_scenarios() -> list[str]:
    if not SEED_SCENARIOS_DIR.is_dir():
        return []

    known = _existing("scenarios", "slug")
    added = []
    for path in sorted(SEED_SCENARIOS_DIR.glob("*.json")):
        if path.stem in known:
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        save_scenario(scenario_from_dict(path.stem, payload))
        added.append(path.stem)
    return added


def seed() -> dict[str, list[str]]:
    """Insert any missing example servers and scenarios. Safe to run on every startup."""
    return {"servers": seed_servers(), "scenarios": seed_scenarios()}
