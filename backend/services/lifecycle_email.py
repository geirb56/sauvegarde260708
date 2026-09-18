from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: str = "false") -> bool:
    value = str(os.getenv(name, default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _brevo_account_created_enabled() -> bool:
    return _env_flag("BREVO_ACCOUNT_CREATED_ENABLED", "false")


def _brevo_track_event_url() -> str:
    return str(
        os.getenv("BREVO_TRACK_EVENT_URL", "https://in-automate.brevo.com/api/v2/trackEvent")
    ).strip()


def _brevo_account_created_event_name() -> str:
    return str(os.getenv("BREVO_ACCOUNT_CREATED_EVENT_NAME", "account_created")).strip()


def _brevo_timeout_seconds() -> float:
    raw = str(os.getenv("BREVO_TRACK_EVENT_TIMEOUT_SECONDS", "5")).strip()
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 5.0
    return max(timeout, 0.1)


async def emit_account_created_event(*, email: str, user_id: str, signup_method: str) -> None:
    if not _brevo_account_created_enabled():
        return

    api_key = str(os.getenv("BREVO_API_KEY", "")).strip()
    if not api_key:
        logger.warning("BREVO_ACCOUNT_CREATED_ENABLED=true but BREVO_API_KEY is missing")
        return

    payload = {
        "event": _brevo_account_created_event_name(),
        "email": email,
        "properties": {
            "user_id": user_id,
            "signup_method": signup_method,
        },
    }
    headers = {
        "ma-key": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=_brevo_timeout_seconds()) as client:
        response = await client.post(_brevo_track_event_url(), headers=headers, json=payload)
        response.raise_for_status()


async def safe_emit_account_created_event(*, email: str, user_id: str, signup_method: str) -> None:
    try:
        await emit_account_created_event(email=email, user_id=user_id, signup_method=signup_method)
    except Exception:
        logger.warning("Brevo account_created event failed", exc_info=True)
