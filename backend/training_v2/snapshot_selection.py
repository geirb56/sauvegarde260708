"""Canonical selection of the authoritative served snapshots of one week.

Single source for /training/today and /training/v2/week.  The query is bounded
to one user and the seven ``prescription_id`` of the week (the unique
``(user_id, prescription_id)`` index serves it); ``planned_date`` is stored as
an ISO string, so the date bounds compare lexicographically.

Selection rules (never rewrites anything):
- the document must belong to ``user_id`` and match the canonical
  ``prescription_id`` of its own ``planned_date``/``day``;
- only snapshots authoritative as of ``reference_date`` are candidates, so a
  newer but non-authoritative version can never replace an authoritative one;
- if several authoritative versions exist for one id, the earliest served
  wins (``served_at`` ascending, legacy ``None`` first), ties broken on the
  serialized content for determinism.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

from .prescription_snapshot import PrescriptionSnapshot, is_snapshot_authoritative
from .week_execution import prescription_id_for
from .workout_generator import WorkoutPrescription

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def week_prescription_ids(user_id: str, week_start: date) -> list[str]:
    return [
        prescription_id_for(user_id, week_start + timedelta(days=i), day)
        for i, day in enumerate(_DAYS)
    ]


def _order_key(snapshot: PrescriptionSnapshot) -> tuple:
    served = snapshot.served_at.isoformat() if snapshot.served_at else ""
    return (served, json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, default=str))


def select_authoritative_week_snapshots(
    docs: Iterable[Mapping[str, Any]],
    *,
    user_id: str,
    week_start: date,
    reference_date: date,
) -> dict[str, PrescriptionSnapshot]:
    """prescription_id → winning authoritative snapshot for the week."""
    week_end = week_start + timedelta(days=6)
    expected = set(week_prescription_ids(user_id, week_start))
    best: dict[str, PrescriptionSnapshot] = {}
    for doc in docs:
        try:
            snapshot = PrescriptionSnapshot(**{k: v for k, v in doc.items() if k != "_id"})
        except Exception:
            continue
        if snapshot.user_id != user_id or snapshot.prescription_id not in expected:
            continue
        if not (week_start <= snapshot.planned_date <= week_end):
            continue
        if snapshot.prescription_id != prescription_id_for(
            user_id, snapshot.planned_date, snapshot.day
        ):
            continue
        if not is_snapshot_authoritative(snapshot=snapshot, reference_date=reference_date):
            continue
        current = best.get(snapshot.prescription_id)
        if current is None or _order_key(snapshot) < _order_key(current):
            best[snapshot.prescription_id] = snapshot
    return best


async def load_authoritative_week_snapshots(
    db: Any, *, user_id: str, reference_date: date
) -> dict[str, PrescriptionSnapshot]:
    """Bounded read (<= 7 ids, one user, one week) + canonical selection."""
    week_start = reference_date - timedelta(days=reference_date.weekday())
    docs = await db.training_prescription_snapshots.find(
        {
            "user_id": user_id,
            "prescription_id": {"$in": week_prescription_ids(user_id, week_start)},
            "planned_date": {
                "$gte": week_start.isoformat(),
                "$lte": (week_start + timedelta(days=6)).isoformat(),
            },
        },
        {"_id": 0},
    ).to_list(50)
    return select_authoritative_week_snapshots(
        docs, user_id=user_id, week_start=week_start, reference_date=reference_date
    )


def frozen_sessions_from_snapshots(
    snapshots: Mapping[str, PrescriptionSnapshot],
) -> dict[str, WorkoutPrescription]:
    """day → served prescription, copied as-is from the snapshots."""
    return {
        s.day.lower(): WorkoutPrescription(
            day=s.day.lower(),
            workout_type=s.workout_type,
            intensity_class=s.intensity_class,
            distance_km=s.distance_km,
            duration_minutes=s.duration_minutes,
            reason_codes=s.reason_codes,
        )
        for s in snapshots.values()
    }


__all__ = [
    "frozen_sessions_from_snapshots",
    "load_authoritative_week_snapshots",
    "select_authoritative_week_snapshots",
    "week_prescription_ids",
]
