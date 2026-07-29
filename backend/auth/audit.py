"""Audit logger — writes security events to a rotating log file.

The audit file path is controlled by the ``AUDIT_LOG_FILE`` environment variable
(default: ``logs/audit.log`` relative to the working directory).  The parent
directory is created automatically if it does not exist.

Each line is a structured JSON record so that it can be ingested by log
aggregation systems (Loki, Splunk, Datadog, …) without extra parsing.

Usage::

    from auth.audit import audit_event

    audit_event("login_success", user_id="abc", ip="1.2.3.4")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

# ── Configuration ──────────────────────────────────────────────────────────────

_AUDIT_LOG_FILE = os.environ.get("AUDIT_LOG_FILE", "logs/audit.log")
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_BACKUP_COUNT = 5               # keep up to 5 rotated files

# ── Logger setup ───────────────────────────────────────────────────────────────

_audit_logger = logging.getLogger("audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False  # do NOT forward to the root logger / console


def _setup_file_handler() -> None:
    """Attach a RotatingFileHandler to the audit logger (idempotent)."""
    if _audit_logger.handlers:
        return  # already configured

    log_path = _AUDIT_LOG_FILE
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    handler = RotatingFileHandler(
        log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    # Each record is a raw JSON line — no extra formatting needed.
    handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(handler)


_setup_file_handler()

# ── Public API ─────────────────────────────────────────────────────────────────


def audit_event(event: str, **kwargs: Any) -> None:
    """Write a structured audit record to the audit log file.

    Args:
        event:   Short event name, e.g. ``"login_success"``.
        **kwargs: Arbitrary key/value pairs added to the record.
                  ``ip`` and ``user_id`` are conventional keys.
    """
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **kwargs,
    }
    _audit_logger.info(json.dumps(record, default=str))
