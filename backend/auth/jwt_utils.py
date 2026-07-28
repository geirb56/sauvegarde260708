"""JWT creation and verification utilities.

Environment variables consumed (must be set at runtime):
    JWT_SECRET_KEY                  Long random key (required)
    JWT_ALGORITHM                   e.g. "HS256"           (default: HS256)
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES Token lifetime in min   (default: 60)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from config.secrets import get_secret

# ── Configuration ──────────────────────────────────────────────────────────────

JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
)


def _get_secret_key() -> str:
    """Lazy-load the secret key so it fails fast at first use, not at import."""
    return get_secret("JWT_SECRET_KEY", required=True)


# ── Public API ─────────────────────────────────────────────────────────────────


def create_access_token(user_id: str, email: str) -> str:
    """Return a signed JWT for *user_id*.

    Claims:
        sub  — stable user UUID
        email — user email (convenience, not sensitive)
        iat  — issued-at timestamp
        exp  — expiry timestamp
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate *token*.

    Raises:
        jwt.ExpiredSignatureError  — token is past its expiry
        jwt.InvalidTokenError      — signature invalid or claims malformed
    """
    return jwt.decode(
        token,
        _get_secret_key(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat"]},
    )


def create_short_lived_token(data: dict, expires_minutes: int = 60) -> str:
    """Generic signed token for password-reset / email-verification flows."""
    now = datetime.now(timezone.utc)
    payload = {**data, "iat": now, "exp": now + timedelta(minutes=expires_minutes)}
    return jwt.encode(payload, _get_secret_key(), algorithm=JWT_ALGORITHM)


def decode_short_lived_token(token: str) -> Optional[dict]:
    """Return the payload or None if the token is invalid/expired."""
    try:
        return jwt.decode(
            token,
            _get_secret_key(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat"]},
        )
    except jwt.InvalidTokenError:
        return None
