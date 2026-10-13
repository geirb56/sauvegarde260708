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
    """Remove future legacy snapshots and any incoherent provenance.

    The predicates are evaluated by Mongo at deletion time. A snapshot with
    ``served_reference_date == planned_date`` never matches either delete,
    even when this caller holds a stale reference date across midnight.
    """
    await db.training_prescription_snapshots.delete_many(
        {
            "user_id": user_id,
            "served_reference_date": {"$exists": True, "$ne": None},
            "$expr": {"$ne": ["$served_reference_date", "$planned_date"]},
        }
    )
    await db.training_prescription_snapshots.delete_many(
        {
            "user_id": user_id,
            "planned_date": {"$gt": reference_date.isoformat()},
            "$or": [
                {"served_reference_date": {"$exists": False}},
                {"served_reference_date": None},
            ],
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
    if (
        snapshot.planned_date != reference_date
        or snapshot.served_reference_date != reference_date
    ):
        raise ValueError(
            "A served snapshot requires planned_date and "
            "served_reference_date to match reference_date."
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
