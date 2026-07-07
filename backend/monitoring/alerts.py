"""Queue-health alerting — pure evaluation + provider-agnostic notification.

Design goals (per SRE spec):
  - `evaluate_queue_health` is a PURE function: given a health snapshot and the
    previous alert state, it returns the new state + the alert decision. No I/O,
    no globals, no background loop. Fully unit-testable and decoupled, ready to
    be plugged into a background worker, a scheduled job or a monitoring service.
  - `send_alert` ALWAYS emits a structured log. If ALERT_WEBHOOK_URL is set it
    also POSTs asynchronously (best-effort, one retry). Webhook failures never
    impact the app/worker. The layer is provider-agnostic (Slack/Discord/Teams
    can be added later without touching business logic).

Thresholds:
  - status == "unhealthy" 2 times in a row  -> CRITICAL alert
  - status == "degraded"  5 times in a row  -> WARNING alert
  - any "healthy" resets both streaks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config.secrets import get_secret

logger = logging.getLogger(__name__)

UNHEALTHY_THRESHOLD = 2
DEGRADED_THRESHOLD = 5

LEVEL_CRITICAL = "critical"
LEVEL_WARNING = "warning"

_LOG_LEVELS = {LEVEL_CRITICAL: logging.ERROR, LEVEL_WARNING: logging.WARNING}


@dataclass
class AlertState:
    """Consecutive-status streaks. Immutable-style: evaluate returns a new one."""
    unhealthy_streak: int = 0
    degraded_streak: int = 0


@dataclass
class AlertEvaluation:
    """Result of evaluating one snapshot."""
    state: AlertState
    level: str | None = None      # None when nothing should be emitted
    message: str | None = None
    fields: dict = field(default_factory=dict)


def evaluate_queue_health(payload: dict, state: AlertState | None = None) -> AlertEvaluation:
    """Pure: map a health snapshot (+ prior streak state) to an alert decision.

    Returns an AlertEvaluation carrying the NEW state and, when a threshold is
    crossed, the alert level+message to hand to `send_alert`. The caller owns
    persistence of `state` between calls (worker/scheduler/service).
    """
    state = state or AlertState()
    status = (payload or {}).get("status")

    if status == "healthy":
        return AlertEvaluation(state=AlertState())  # reset streaks

    if status == "unhealthy":
        new = AlertState(unhealthy_streak=state.unhealthy_streak + 1, degraded_streak=0)
        if new.unhealthy_streak >= UNHEALTHY_THRESHOLD:
            msg = f"Queue UNHEALTHY {new.unhealthy_streak}x consecutively"
            return AlertEvaluation(state=new, level=LEVEL_CRITICAL, message=msg,
                                   fields=_extract(payload))
        return AlertEvaluation(state=new)

    if status == "degraded":
        new = AlertState(unhealthy_streak=0, degraded_streak=state.degraded_streak + 1)
        if new.degraded_streak >= DEGRADED_THRESHOLD:
            msg = f"Queue DEGRADED {new.degraded_streak}x consecutively"
            return AlertEvaluation(state=new, level=LEVEL_WARNING, message=msg,
                                   fields=_extract(payload))
        return AlertEvaluation(state=new)

    # Unknown / missing status: don't alert, don't touch streaks.
    return AlertEvaluation(state=state)


def _extract(payload: dict) -> dict:
    keys = ("status", "redis_connected", "queue_length", "processing_length",
            "active_workers", "oldest_processing_seconds", "failed_jobs_total")
    return {k: payload.get(k) for k in keys if k in payload}


async def send_alert(level: str, message: str, payload: dict) -> None:
    """Emit a structured log always; POST to ALERT_WEBHOOK_URL if configured.

    Best-effort webhook: at most one retry, failures are logged and swallowed so
    they can never affect the application or worker execution.
    """
    log_level = _LOG_LEVELS.get(level, logging.WARNING)
    logger.log(log_level, "[alert] level=%s message=%s payload=%s",
               level, message, _extract(payload or {}))

    url = get_secret("ALERT_WEBHOOK_URL")
    if not url:
        return  # webhook not configured -> silently skip

    body = {
        "level": level,
        "message": message,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "cardiocoach.queue_health",
    }
    await _post_webhook(url, body)


async def _post_webhook(url: str, body: dict) -> None:
    import httpx  # local import: keeps the module import-light

    for attempt in (1, 2):  # initial try + at most one retry
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
            return
        except Exception as exc:  # never propagate
            if attempt == 2:
                logger.warning("[alert] webhook delivery failed after retry: %r", exc)
            else:
                logger.info("[alert] webhook attempt %s failed, retrying: %r", attempt, exc)
