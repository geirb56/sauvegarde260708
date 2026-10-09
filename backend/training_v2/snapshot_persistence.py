"""Persistence-boundary validation for served prescription snapshots."""

from __future__ import annotations

from datetime import date
from typing import Any

from .prescription_snapshot import PrescriptionSnapshot


async def invalidate_future_snapshots(
    db: Any,
    *,
    user_id: str,
    reference_date: date,
) -> None:
    """Permanently remove snapshots that could not yet have been served."""
    await db.training_prescription_snapshots.delete_many(
        {
            "user_id": user_id,
            "planned_date": {"$gt": reference_date.isoformat()},
        }
    )


async def persist_served_snapshot(
    db: Any,
    snapshot: PrescriptionSnapshot,
    *,
    reference_date: date,
) -> None:
    """Persist only a snapshot for the date being served.

    Existing documents are never rewritten.
    """
    if snapshot.planned_date != reference_date:
        raise ValueError(
            "A served prescription snapshot can only be persisted for "
            "reference_date."
        )
    await db.training_prescription_snapshots.update_one(
        {
            "user_id": snapshot.user_id,
            "prescription_id": snapshot.prescription_id,
        },
        {"$setOnInsert": snapshot.model_dump(mode="json")},
        upsert=True,
    )


__all__ = ["invalidate_future_snapshots", "persist_served_snapshot"]
