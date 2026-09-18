from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)
_brevo_client: httpx.AsyncClient | None = None


def _env_flag(name: str, default: str = "false") -> bool:
    value = str(os.getenv(name, default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _brevo_account_created_enabled() -> bool:
    return _env_flag("BREVO_ACCOUNT_CREATED_ENABLED", "false")


def _brevo_timeout_seconds() -> float:
    raw = str(os.getenv("BREVO_TRACK_EVENT_TIMEOUT_SECONDS", "5")).strip()
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 5.0
    return max(timeout, 0.1)


def _get_brevo_client() -> httpx.AsyncClient:
    global _brevo_client
    if _brevo_client is None:
        _brevo_client = httpx.AsyncClient()
    return _brevo_client


async def emit_account_created_event(*, email: str, user_id: str, signup_method: str) -> None:
    if not _brevo_account_created_enabled():
        return

    api_key = str(os.getenv("BREVO_API_KEY", "")).strip()
    if not api_key:
        logger.warning("BREVO_ACCOUNT_CREATED_ENABLED=true but BREVO_API_KEY is missing")
        return

    payload = {
        "event_name": "account_created",
        "identifiers": {
            "email_id": email,
        },
        "event_properties": {
            "user_id": user_id,
            "signup_method": signup_method,
        },
    }
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    client = _get_brevo_client()
    response = await client.post(
        "https://api.brevo.com/v3/events",
        headers=headers,
        json=payload,
        timeout=_brevo_timeout_seconds(),
    )
    if response.status_code != 204:
        raise RuntimeError(f"Brevo events API returned unexpected status: {response.status_code}")


async def safe_emit_account_created_event(*, email: str, user_id: str, signup_method: str) -> None:
    try:
        await emit_account_created_event(email=email, user_id=user_id, signup_method=signup_method)
    except Exception:
        logger.warning("Brevo account_created event failed", exc_info=True)
