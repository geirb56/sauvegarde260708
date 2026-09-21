"""
services/training_planned_prescription_memory_index.py
======================================================

PR284 follow-up — enforce UNIQUE index on
training_planned_prescription_memory.(user_id, prescription_id).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def ensure_training_planned_prescription_memory_unique_index(db: Any) -> None:
    """Idempotently enforce a UNIQUE index on
    ``training_planned_prescription_memory.(user_id, prescription_id)``.
    """
    col = db.training_planned_prescription_memory
    await col.create_index(
        [("user_id", 1), ("prescription_id", 1)],
        unique=True,
        name="uniq_user_prescription",
    )
    logger.info(
        "UNIQUE index on training_planned_prescription_memory."
        "(user_id, prescription_id) created/verified"
    )

