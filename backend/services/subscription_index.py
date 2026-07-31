"""
services/subscription_index.py
================================

Idempotent enforcement of the UNIQUE index on subscriptions.user_id.

Extracted from server.py startup so it can be unit-tested without importing
the full FastAPI application.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def ensure_subscriptions_unique_index(db: Any) -> None:
    """
    Idempotently enforce a UNIQUE index on subscriptions.user_id.

    If a non-unique index with key {user_id: 1} already exists (legacy schema),
    it is dropped before the unique one is created.  If the unique index already
    exists, this is a no-op.

    NOTE: This does NOT remove duplicate documents — that must be done via the
    migration script (backend/migrations/deduplicate_subscriptions.py) before
    this function can succeed on a database that contains duplicates.
    """
    col = db.subscriptions
    indexes = {}
    async for idx in col.list_indexes():
        indexes[idx["name"]] = idx

    target_key = [("user_id", 1)]
    for name, idx in indexes.items():
        key_pairs = list(idx.get("key", {}).items())
        if key_pairs == target_key:
            if idx.get("unique"):
                # Already unique — nothing to do.
                logger.info("subscriptions.user_id unique index already exists (%s)", name)
                return
            # Non-unique legacy index — drop it so we can recreate as unique.
            logger.warning(
                "Found non-unique index '%s' on subscriptions.user_id — dropping to recreate as UNIQUE. "
                "Run migrations/deduplicate_subscriptions.py first if duplicates exist.",
                name,
            )
            await col.drop_index(name)
            break

    await col.create_index("user_id", unique=True, sparse=True)
    logger.info("UNIQUE index on subscriptions.user_id created/verified")
