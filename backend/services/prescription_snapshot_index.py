"""
services/prescription_snapshot_index.py
========================================

C231 — Idempotent enforcement of the UNIQUE index on
training_prescription_snapshots.(user_id, prescription_id).

This is the real Mongo-level immutability guarantee for prescription
snapshots: even under concurrent writers racing to freeze the same
``(user_id, prescription_id)`` for the first time, the database itself
rejects any second insert, so at most one document can ever exist for that
key — combined with the ``$setOnInsert`` upsert used by the caller, no
snapshot is ever overwritten.

Extracted into its own module (mirrors services/subscription_index.py and
services/paddle_event_index.py) so it can be unit-tested without importing
the full FastAPI application, and wired into server.py's startup index
creation instead of being created ad-hoc inside a request handler.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def ensure_prescription_snapshot_unique_index(db: Any) -> None:
    """Idempotently enforce a UNIQUE index on
    ``training_prescription_snapshots.(user_id, prescription_id)``.

    This is a brand-new collection (introduced by C231) with no legacy
    documents, so unlike ``subscriptions``/``paddle_events`` there is no
    duplicate-migration concern — a straightforward ``create_index`` call
    is safe and idempotent (Mongo no-ops if an identical index already
    exists).
    """
    col = db.training_prescription_snapshots
    await col.create_index(
        [("user_id", 1), ("prescription_id", 1)],
        unique=True,
        name="uniq_user_prescription",
    )
    logger.info(
        "UNIQUE index on training_prescription_snapshots.(user_id, prescription_id) "
        "created/verified"
    )
