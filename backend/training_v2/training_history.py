"""PR05 — TrainingHistory: pure business layer (7 / 30 / 90 days).

Design rules
------------
- PURE: no MongoDB, no API calls, no LLM, no cache, no global state.
- reference_date must be supplied explicitly by the caller so that all
  calculations are deterministic and fully testable.
- datetime.now() is never called inside this module.

Window convention (inclusive on both ends)
------------------------------------------
A window of N days ending at *reference_date* covers:

    [reference_date - timedelta(days=N-1), reference_date]

Examples with reference_date = 2026-08-06:
  7-day  window: 2026-07-31 … 2026-08-06  (7 days inclusive)
  30-day window: 2026-07-08 … 2026-08-06  (30 days inclusive)
  90-day window: 2026-05-09 … 2026-08-06  (90 days inclusive)

Activities dated strictly after reference_date are ignored.

Units
-----
- Distances are stored in metres  → distance_km = distance_m / 1000
- Durations are stored in seconds → duration_hours = duration_s / 3600
- Rounding is applied only to final model fields (2 decimal places).

Activity filter
---------------
Only the following activity_type values are treated as running:
  "running", "trail_running", "treadmill_running"

Input model
-----------
Training V2 consumes provider-neutral ``DomainActivity`` objects.
Generic dict/object inputs are coerced to this minimal model by using only the
shared business fields: activity_type, start_time, distance_m, duration_s.
Flat aliases ``distance`` and ``duration`` are still accepted for compatibility.

Invalid values
--------------
distance: None / 0 / negative / non-numeric → excluded from statistics.
duration: None / 0 / negative / non-numeric → excluded from statistics.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict

from .domain_activity import DomainActivity, to_domain_activity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUNNING_TYPES = frozenset({"running", "trail_running", "treadmill_running"})

_ROUND = 2  # decimal places for all output fields


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TrainingWindow(BaseModel):
    """Aggregated statistics for a sliding window of N days."""

    model_config = ConfigDict(frozen=True)

    days: int
    distance_km: float
    duration_hours: float
    activity_count: int
    average_speed_kmh: Optional[float]
    longest_run_km: Optional[float]


class TrainingHistory(BaseModel):
    """Complete training history built from provider-neutral DomainActivity inputs.

    Computed for three overlapping sliding windows (7, 30, 90 days) ending
    at *reference_date* (inclusive).
    """

    model_config = ConfigDict(frozen=True)

    window_7d: TrainingWindow
    window_30d: TrainingWindow
    window_90d: TrainingWindow

    days_since_last_run: Optional[int]
    last_run_date: Optional[str]  # ISO-8601 date string (YYYY-MM-DD)

    available_history_days: int
    has_7d_history: bool
    has_30d_history: bool
    has_90d_history: bool
    has_any_running_history: bool

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_activities(
        cls,
        activities: Sequence[Any],
        reference_date: date,
    ) -> "TrainingHistory":
        """Build a TrainingHistory from a sequence of activity records.

        Parameters
        ----------
        activities:
            Any iterable of activity records coercible to ``DomainActivity``.
        reference_date:
            The anchor date for all window calculations.  Activities strictly
            after this date are silently ignored.
        """
        return build_training_history(activities, reference_date)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _extract_fields(activity: Any) -> Dict[str, Any]:
    """Return the business fields extracted from a DomainActivity input."""
    domain_activity = to_domain_activity(activity)
    act_date = _parse_date(domain_activity.start_time)
    return {
        "activity_type": domain_activity.activity_type,
        "activity_date": act_date,
        "distance_m": domain_activity.distance_m,
        "duration_s": domain_activity.duration_s,
    }


def _parse_date(value: Any) -> Optional[date]:
    """Parse a date/datetime value into a ``date``, or return None.

    Accepted string formats (non-exhaustive):
      - "2026-08-02"
      - "2026-08-02T10:08:20"
      - "2026-08-02T10:08:20.0"
      - "2026-08-02T10:08:20Z"          (Z → +00:00)
      - "2026-08-02T10:08:20+02:00"     (timezone-aware)
      - "2026-08-02 10:08:20"           (Garmin space-separated format)
      - "2026-08-02 10:08:20.0"
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str) or value == "":
        return None

    s = value.strip()

    # Normalise Z suffix so fromisoformat can handle it (Python < 3.11)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # Try datetime.fromisoformat first (handles T-separated and tz-aware)
    try:
        return datetime.fromisoformat(s).date()
    except (ValueError, TypeError):
        pass

    # Fallback: Garmin space-separated format "YYYY-MM-DD HH:MM:SS[.f]"
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue

    return None


def _valid_distance(value: Any) -> Optional[float]:
    """Return value as float if it is a strictly positive number, else None."""
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return float(value)


def _valid_duration(value: Any) -> Optional[float]:
    """Return value as float if it is a strictly positive number, else None."""
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Window builder
# ---------------------------------------------------------------------------


def _build_window(
    run_activities: List[Dict[str, Any]],
    days: int,
    reference_date: date,
) -> TrainingWindow:
    """Compute aggregated statistics for a sliding window of *days* days.

    The window covers [reference_date - timedelta(days - 1), reference_date]
    (both ends inclusive).
    """
    window_start = reference_date - timedelta(days=days - 1)

    total_distance_km = 0.0
    total_duration_hours = 0.0
    # Accumulators for speed: only activities with BOTH valid dist AND dur
    speed_distance_km = 0.0
    speed_duration_hours = 0.0
    count = 0
    longest_km: Optional[float] = None

    for act in run_activities:
        act_date = act["activity_date"]
        if act_date is None:
            continue
        if act_date < window_start or act_date > reference_date:
            continue

        dist_m = _valid_distance(act["distance_m"])
        dur_s = _valid_duration(act["duration_s"])

        # An activity with neither valid distance nor valid duration is
        # effectively empty — skip it entirely.
        if dist_m is None and dur_s is None:
            continue

        count += 1

        if dist_m is not None:
            dist_km = dist_m / 1000.0
            total_distance_km += dist_km
            if longest_km is None or dist_km > longest_km:
                longest_km = dist_km

        if dur_s is not None:
            total_duration_hours += dur_s / 3600.0

        # Speed pool: only when both are valid simultaneously
        if dist_m is not None and dur_s is not None:
            speed_distance_km += dist_m / 1000.0
            speed_duration_hours += dur_s / 3600.0

    if speed_duration_hours > 0:
        avg_speed = round(speed_distance_km / speed_duration_hours, _ROUND)
    else:
        avg_speed = None

    return TrainingWindow(
        days=days,
        distance_km=round(total_distance_km, _ROUND),
        duration_hours=round(total_duration_hours, _ROUND),
        activity_count=count,
        average_speed_kmh=avg_speed,
        longest_run_km=round(longest_km, _ROUND) if longest_km is not None else None,
    )


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def build_training_history(
    activities: Sequence[Any],
    reference_date: date,
) -> TrainingHistory:
    """Build a :class:`TrainingHistory` from a sequence of activity records.

    Parameters
    ----------
    activities:
        Iterable of activity records coercible to ``DomainActivity``.
    reference_date:
        Anchor date (inclusive upper bound for all windows).  Activities
        strictly after this date are ignored.
    """
    # Step 1 — extract and filter running activities
    run_activities: List[Dict[str, Any]] = []
    for raw in activities:
        fields = _extract_fields(raw)
        act_type = fields.get("activity_type") or ""
        if act_type not in RUNNING_TYPES:
            continue
        act_date = fields.get("activity_date")
        if act_date is not None and act_date > reference_date:
            continue  # future activity — ignore
        run_activities.append(fields)

    # Step 2 — compute windows
    window_7d = _build_window(run_activities, 7, reference_date)
    window_30d = _build_window(run_activities, 30, reference_date)
    window_90d = _build_window(run_activities, 90, reference_date)

    # Step 3 — last run and history depth
    valid_dates = [
        act["activity_date"]
        for act in run_activities
        if act["activity_date"] is not None
        and act["activity_date"] <= reference_date
        and (_valid_distance(act["distance_m"]) is not None or _valid_duration(act["duration_s"]) is not None)
    ]

    if valid_dates:
        last_date = max(valid_dates)
        first_date = min(valid_dates)
        days_since = (reference_date - last_date).days
        available_days = (reference_date - first_date).days + 1
    else:
        last_date = None
        days_since = None
        available_days = 0

    has_any = len(valid_dates) > 0

    return TrainingHistory(
        window_7d=window_7d,
        window_30d=window_30d,
        window_90d=window_90d,
        days_since_last_run=days_since,
        last_run_date=last_date.isoformat() if last_date else None,
        available_history_days=available_days,
        has_any_running_history=has_any,
        has_7d_history=has_any and available_days >= 7,
        has_30d_history=has_any and available_days >= 30,
        has_90d_history=has_any and available_days >= 90,
    )
