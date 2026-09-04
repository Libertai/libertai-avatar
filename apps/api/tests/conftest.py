from pathlib import Path

import pytest

from apps.api import db, mcp_client


@pytest.fixture(autouse=True)
def temp_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give every test its own database, so no test can see another's scenarios."""
    path = tmp_path / "avatar.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.migrate()
    mcp_client.clear_discovery_cache()
    return path


@pytest.fixture(autouse=True)
def isolated_secret_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AVATAR_SECRET_KEY", "test-key-not-used-in-production")


@pytest.fixture(autouse=True)
def no_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
