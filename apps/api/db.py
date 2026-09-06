"""SQLite storage for scenarios and the MCP server registry.

The schema is small and stable enough that a migration framework would cost more than it
saves: ``migrate()`` runs the statements a fresh or older database is missing, and is safe
to call on every startup.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(os.getenv("AVATAR_DB", "apps/api/avatar.db"))

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS scenarios (
        slug        TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        language    TEXT NOT NULL DEFAULT 'en-US',
        voice       TEXT,
        avatar      TEXT,
        greeting    TEXT NOT NULL DEFAULT '',
        rules       TEXT NOT NULL DEFAULT '',
        data        TEXT NOT NULL DEFAULT '{}',
        mcp         TEXT NOT NULL DEFAULT '[]',
        tools       TEXT,
        model       TEXT,
        speed       REAL NOT NULL DEFAULT 1.0,
        published   INTEGER NOT NULL DEFAULT 1,
        collect     TEXT NOT NULL DEFAULT '[]',
        search      INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_servers (
        name        TEXT PRIMARY KEY,
        description TEXT NOT NULL DEFAULT '',
        transport   TEXT NOT NULL DEFAULT 'stdio',
        url         TEXT,
        command     TEXT,
        args        TEXT NOT NULL DEFAULT '[]',
        headers     TEXT NOT NULL DEFAULT '{}',
        env         TEXT NOT NULL DEFAULT '{}',
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection with foreign keys on and rows accessible by column name."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS skips an existing
# table entirely, so a database made before them needs each one added.
ADDED_COLUMNS = {
    "scenarios": {
        "collect": "TEXT NOT NULL DEFAULT '[]'",
        "search": "INTEGER NOT NULL DEFAULT 0",
    },
}


def migrate() -> None:
    with connect() as connection:
        for statement in SCHEMA:
            connection.execute(statement)

        for table, columns in ADDED_COLUMNS.items():
            present = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in present:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def json_column(row: sqlite3.Row, column: str, default: Any) -> Any:
    """Decode a JSON column, falling back when a hand-edited row holds invalid JSON."""
    raw = row[column]
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default
