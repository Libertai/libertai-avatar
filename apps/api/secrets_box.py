"""Encrypt MCP credentials at rest.

Third-party MCP servers need tokens, and a scenario author supplies them through the admin
UI rather than the shell. Storing them as plaintext in SQLite would mean any database copy
— a backup, a bug report, a stray volume — carries live credentials, so values are
encrypted with a key that lives outside the database.

Two forms are supported and neither exposes a secret through the API:

- ``${ENV_VAR}``: a reference resolved at call time. Nothing is stored.
- Anything else: encrypted here, decrypted only when a tool call is made.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_FILE = Path(os.getenv("AVATAR_SECRET_KEY_FILE", "apps/api/.secret_key"))
ENCRYPTED_PREFIX = "enc:"
ENV_REFERENCE = re.compile(r"\$\{[A-Z0-9_]+\}")
MASK = "••••••••"


def _key() -> bytes:
    """Return the Fernet key, taking it from the environment or a generated key file."""
    from_env = os.getenv("AVATAR_SECRET_KEY")
    if from_env:
        return base64.urlsafe_b64encode(hashlib.sha256(from_env.encode()).digest())

    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(secrets.token_urlsafe(32))
        KEY_FILE.chmod(0o600)

    return base64.urlsafe_b64encode(hashlib.sha256(KEY_FILE.read_text().strip().encode()).digest())


def is_reference(value: str) -> bool:
    """True when the value defers to the environment rather than holding a secret itself.

    Matches anywhere in the string, because the usual form is ``Bearer ${TOKEN}`` rather
    than a bare placeholder. A value that mixes a literal secret with a placeholder is
    therefore stored in the clear — write one or the other, not both.
    """
    return bool(ENV_REFERENCE.search(value))


def encrypt(value: str) -> str:
    """Encrypt a secret, leaving environment references and already-encrypted values alone."""
    if not value or is_reference(value) or value.startswith(ENCRYPTED_PREFIX):
        return value
    return ENCRYPTED_PREFIX + Fernet(_key()).encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a stored value; non-encrypted values pass through unchanged."""
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    try:
        return Fernet(_key()).decrypt(value[len(ENCRYPTED_PREFIX) :].encode()).decode()
    except InvalidToken:
        # A rotated or missing key must not crash a request; the call will fail on auth.
        return ""


def mask(value: str) -> str:
    """Render a value for the admin UI: references stay readable, secrets never leave."""
    if not value or is_reference(value):
        return value
    return MASK


def unmask(new_value: str, stored: str) -> str:
    """Keep the stored secret when the UI submits the mask unchanged."""
    return stored if new_value == MASK else encrypt(new_value)
