"""C231 — Garmin-consistent local reference date.

Problem
-------
``datetime.now(timezone.utc).date()`` disagrees with the athlete's own
calendar day close to UTC midnight: a run finished at 23:40 local time can
already be "tomorrow" in UTC (or the reverse), silently shifting week
boundaries and turning a legitimate "today" session into a future/missed one
for several hours a day, depending on the athlete's timezone.

Fix
---
Derive the local UTC offset from the most recent ``garmin_activities``
document that carries BOTH a GMT and a local start time (the same evidence
already used for matching by ``garmin_local_start_time``), and apply that
offset to the current UTC clock to obtain "today" as the athlete's Garmin
device would report it.

When no such evidence exists (new user, or a degraded Garmin payload with
no local timestamp), this falls back to the UTC calendar date. This is a
CLOCK fallback only — no activity data is invented, and matching itself
never uses this fallback (see ``performed_workout.py``, which is unaffected
by this module).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Sequence

_MAX_OFFSET_MINUTES = 14 * 60
"""No real UTC offset exceeds ±14h (UTC+14 / UTC-12 are the extremes)."""


def _parse_naive(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or raw == "":
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        return None


def _offset_minutes_from_doc(doc: Dict[str, Any]) -> Optional[int]:
    """Return the (local - GMT) offset in minutes for one raw activity doc.

    Mirrors the REAL persisted contract (``garmin/gccli_provider.py`` +
    ``garmin/data_layer.py::GarminActivity``):

    - ``garmin_activity.start_time`` is the canonical GMT time (model
      convention: GMT first, local as fallback) — there is NO
      ``garmin_activity.start_time_gmt`` field in the modern sub-document.
    - ``garmin_activity.start_time_local`` is the explicit device-local time,
      only populated when Garmin really provided ``startTimeLocal``.
    - Legacy top-level ``startTimeGMT``/``startTimeLocal`` are used only as a
      fallback for documents that pre-date the sub-document convention.
    """
    sub: Dict[str, Any] = doc.get("garmin_activity") or {}

    gmt_raw = sub.get("start_time") if "start_time" in sub else doc.get("startTimeGMT")
    local_raw = sub.get("start_time_local") if "start_time_local" in sub else doc.get("startTimeLocal")

    gmt_dt = _parse_naive(gmt_raw)
    local_dt = _parse_naive(local_raw)
    if gmt_dt is None or local_dt is None:
        return None

    minutes = round((local_dt - gmt_dt).total_seconds() / 60)
    if abs(minutes) > _MAX_OFFSET_MINUTES:
        return None
    return minutes


def resolve_local_reference_date(
    *,
    now_utc: datetime,
    garmin_activities: Sequence[Dict[str, Any]],
) -> date:
    """Return "today" aligned with the athlete's Garmin-observed local time.

    Parameters
    ----------
    now_utc
        Current instant, timezone-aware UTC.
    garmin_activities
        Raw ``db.garmin_activities`` documents already fetched by the caller
        (any recency window). Only used to derive a UTC offset — never to
        fabricate a "today" activity.

    Returns
    -------
    date
        The athlete's local calendar date, or the UTC calendar date when no
        activity carries usable local/GMT evidence.
    """
    best_offset: Optional[int] = None
    best_start_key: Optional[str] = None

    for doc in garmin_activities or ():
        if not isinstance(doc, dict):
            continue
        start_key = doc.get("start_time")
        if not isinstance(start_key, str) or start_key == "":
            continue
        if best_start_key is not None and start_key <= best_start_key:
            continue
        offset = _offset_minutes_from_doc(doc)
        if offset is None:
            continue
        best_start_key = start_key
        best_offset = offset

    if best_offset is None:
        return now_utc.astimezone(timezone.utc).date()

    local_now = now_utc.astimezone(timezone.utc) + timedelta(minutes=best_offset)
    return local_now.date()


__all__ = ["resolve_local_reference_date"]
