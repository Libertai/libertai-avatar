"""Guard for the endpoints that create, edit, or delete configuration.

Scenario and MCP editing are administrative: they choose which prompts run and which
servers the API contacts. Set ``ADMIN_TOKEN`` before exposing this to a network. When it
is unset the endpoints stay open so local development needs no setup, and every response
advertises that fact so an unprotected deployment is obvious rather than silent.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def admin_token() -> str | None:
    token = os.getenv("ADMIN_TOKEN", "").strip()
    return token or None


def is_protected() -> bool:
    return admin_token() is not None


def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    expected = admin_token()
    if expected is None:
        return

    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Admin token missing or invalid.")
