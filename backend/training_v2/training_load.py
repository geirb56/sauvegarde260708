"""PR06 — TrainingLoadSnapshot: pure deterministic training-load engine V2.

Design rules
------------
- PURE: no MongoDB, no Garmin calls, no API calls, no LLM, no cache,
  no global mutable state, no environment variables.
- reference_date must be supplied explicitly by the caller — datetime.now()
  is NEVER called inside this module.
- All results are deterministic and fully reproducible for identical inputs.

Distinction with TrainingHistory
---------------------------------
Two separate modules handle training data with different objectives:

  TrainingHistory (PR05)
      Business / overview windows: 7 days, 30 days, 90 days.
      Aggregates volume (distance, duration) for display and trend analysis.

  TrainingLoadSnapshot (PR06, this module)
      Technical ACWR windows: acute = 7 days, chronic = 28 days (= 4 exact weeks).
      Computes the Acute:Chronic Workload Ratio from duration-based load only.

These two modules serve different purposes; the difference in window sizes
(30 vs 28 days) is intentional, not an inconsistency.

Training-load definition (duration only)
-----------------------------------------
The load of an activity is a *volume proxy based solely on duration*.
No physiological metric is involved:

  load (minutes) = valid duration in seconds / 60

Activities with absent, zero, or negative duration contribute NO load,
even when a valid distance is present.  Distance is NOT used as a fallback
for load computation in this module.

Specifically excluded from load calculation:
  - TRIMP (Training Impulse)
  - TSS (Training Stress Score)
  - Garmin Training Load
  - Heart rate / HR zones
  - Intensity factor
  - Elevation / gradient
  - RPE (Rate of Perceived Exertion)
  - Distance × pace estimation

Window convention (inclusive on both ends)
------------------------------------------
For a given reference_date:

  Acute 7-day window   : [reference_date - 6 days  , reference_date]
  Chronic 28-day window: [reference_date - 27 days  , reference_date]
  Previous 7-day window: [reference_date - 13 days  , reference_date - 7 days]

Derived metrics
---------------
  chronic_weekly_load   = load_28d / 4
  acwr                  = acute_load_7d / chronic_weekly_load
                          (None when chronic_weekly_load == 0)

  load_change_percent   = (acute_load_7d - previous_7d_load)
                          / previous_7d_load × 100
                          (None when previous_7d_load == 0)

History depth and confidence
-----------------------------
  "none"   : no exploitable load at all
  "low"    : load present but fewer than 14 calendar days of history
  "medium" : 14 to 27 calendar days of history
  "high"   : at least 28 calendar days of history

ACWR status labels
------------------
  "unavailable" : acwr is None
  "very_low"    : acwr < 0.50
  "low"         : 0.50 ≤ acwr < 0.80
  "balanced"    : 0.80 ≤ acwr ≤ 1.30
  "elevated"    : 1.30 < acwr ≤ 1.50
  "high"        : acwr > 1.50

Rounding
--------
Rounding is applied only to final model fields:
  - loads              : 2 decimal places
  - acwr               : 3 decimal places
  - load_change_percent: 1 decimal place
Internal calculations use full floating-point precision.

Run from the backend directory
------------------------------
    python -m pytest tests/test_training_v2_training_load.py -q
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict

# Reuse the shared extraction helpers from PR05 to avoid code duplication.
from training_v2.training_history import (
    RUNNING_TYPES,
    _extract_fields,
    _valid_duration,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Confidence thresholds (calendar days of available history)
_HISTORY_MEDIUM_DAYS = 14
_HISTORY_HIGH_DAYS = 28

# ACWR thresholds
_ACWR_VERY_LOW = 0.50
_ACWR_LOW = 0.80
_ACWR_BALANCED_HIGH = 1.30
_ACWR_ELEVATED_HIGH = 1.50


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class TrainingLoadSnapshot(BaseModel):
    """Immutable snapshot of the training load for a given reference_date.

    All monetary / physiological fields are intentionally absent from PR06.
    This model captures pure volume-proxy metrics.
    """

    model_config = ConfigDict(frozen=True)

    reference_date: date

    # Core load metrics (minutes, rounded to 2 d.p.)
    acute_load_7d: float
    load_28d: float
    chronic_weekly_load: float

    # ACWR
    acwr: Optional[float]  # None when chronic_weekly_load == 0
    status: str

    # Availability flags
    is_available: bool
    has_sufficient_history: bool  # True when available_history_days >= 28
    confidence: str  # "none" | "low" | "medium" | "high"

    # Activity counts within each window
    activities_7d: int
    activities_28d: int

    # Load evolution
    previous_7d_load: float  # load of the 7-day window immediately before the acute window
    load_change_percent: Optional[float]  # None when previous_7d_load == 0

    # ---------------------------------------------------------------------------
    # Factory convenience
    # ---------------------------------------------------------------------------

    @classmethod
    def from_activities(
        cls,
        activities: Sequence[Any],
        reference_date: date,
    ) -> "TrainingLoadSnapshot":
        """Build a TrainingLoadSnapshot from a sequence of raw activity objects."""
        return build_training_load(activities, reference_date)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _activity_load_minutes(fields: Dict[str, Any]) -> Optional[float]:
    """Return the load (minutes) of a single activity.

    Only valid duration is accepted: load (minutes) = duration_s / 60.
    Activities with absent, zero, or negative duration produce no load.
    Distance is intentionally NOT used as a fallback — this module must not
    manufacture a synthetic duration from pace estimates.
    """
    dur_s = _valid_duration(fields.get("duration_s"))
    if dur_s is not None:
        return dur_s / 60.0
    return None


def _window_load(
    run_activities: List[Dict[str, Any]],
    window_start: date,
    window_end: date,
) -> tuple[float, int]:
    """Return (total_load_minutes, activity_count) for the given inclusive window."""
    total = 0.0
    count = 0
    for act in run_activities:
        act_date = act.get("activity_date")
        if act_date is None:
            continue
        if act_date < window_start or act_date > window_end:
            continue
        load = _activity_load_minutes(act)
        if load is None:
            continue
        total += load
        count += 1
    return total, count


def _acwr_status(acwr: Optional[float]) -> str:
    """Return the descriptive ACWR status label."""
    if acwr is None:
        return "unavailable"
    if acwr < _ACWR_VERY_LOW:
        return "very_low"
    if acwr < _ACWR_LOW:
        return "low"
    if acwr <= _ACWR_BALANCED_HIGH:
        return "balanced"
    if acwr <= _ACWR_ELEVATED_HIGH:
        return "elevated"
    return "high"


def _confidence(available_history_days: int, total_any_load: float) -> str:
    """Return the confidence level based on history depth and load presence."""
    if total_any_load <= 0.0:
        return "none"
    if available_history_days >= _HISTORY_HIGH_DAYS:
        return "high"
    if available_history_days >= _HISTORY_MEDIUM_DAYS:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def build_training_load(
    activities: Sequence[Any],
    reference_date: date,
) -> TrainingLoadSnapshot:
    """Build a :class:`TrainingLoadSnapshot` from a sequence of activity records.

    Parameters
    ----------
    activities:
        Iterable of raw activity records — dicts with an optional
        ``garmin_activity`` sub-document (PR02 convention) or Pydantic
        GarminActivity objects.
    reference_date:
        Anchor date for all window calculations.  Activities strictly after
        this date are ignored.  Must be supplied explicitly by the caller.
    """
    # Step 1 — extract and filter running activities ≤ reference_date
    run_activities: List[Dict[str, Any]] = []
    for raw in activities:
        fields = _extract_fields(raw)
        if fields is None:
            continue
        act_type = fields.get("activity_type") or ""
        if act_type not in RUNNING_TYPES:
            continue
        act_date = fields.get("activity_date")
        if act_date is not None and act_date > reference_date:
            continue  # future activity — ignore
        run_activities.append(fields)

    # Step 2 — define window boundaries
    acute_start = reference_date - timedelta(days=6)       # J-6 inclusive
    chronic_start = reference_date - timedelta(days=27)    # J-27 inclusive
    prev_start = reference_date - timedelta(days=13)       # J-13 inclusive
    prev_end = reference_date - timedelta(days=7)          # J-7 inclusive

    # Step 3 — compute raw loads (full precision)
    acute_load_raw, activities_7d = _window_load(run_activities, acute_start, reference_date)
    load_28d_raw, activities_28d = _window_load(run_activities, chronic_start, reference_date)
    prev_load_raw, _ = _window_load(run_activities, prev_start, prev_end)

    # Step 4 — derived metrics (full precision before rounding)
    chronic_weekly_raw = load_28d_raw / 4.0

    if chronic_weekly_raw > 0.0:
        acwr_raw: Optional[float] = acute_load_raw / chronic_weekly_raw
    else:
        acwr_raw = None

    if prev_load_raw > 0.0:
        load_change_raw: Optional[float] = (
            (acute_load_raw - prev_load_raw) / prev_load_raw
        ) * 100.0
    else:
        load_change_raw = None

    # Step 5 — history depth
    valid_dates = [
        act["activity_date"]
        for act in run_activities
        if act["activity_date"] is not None
        and act["activity_date"] <= reference_date
        and _activity_load_minutes(act) is not None
    ]

    if valid_dates:
        first_date = min(valid_dates)
        # Inclusive convention: J-27 to J = 28 calendar days (both ends counted)
        available_history_days = (reference_date - first_date).days + 1
    else:
        available_history_days = 0

    # Step 6 — flags and labels
    total_any_load = sum(
        _activity_load_minutes(act) or 0.0
        for act in run_activities
        if act.get("activity_date") is not None and act["activity_date"] <= reference_date
    )
    has_sufficient_history = available_history_days >= _HISTORY_HIGH_DAYS
    confidence = _confidence(available_history_days, total_any_load)
    status = _acwr_status(acwr_raw)
    is_available = acwr_raw is not None

    # Step 7 — round final fields only
    return TrainingLoadSnapshot(
        reference_date=reference_date,
        acute_load_7d=round(acute_load_raw, 2),
        load_28d=round(load_28d_raw, 2),
        chronic_weekly_load=round(chronic_weekly_raw, 2),
        acwr=round(acwr_raw, 3) if acwr_raw is not None else None,
        status=status,
        is_available=is_available,
        has_sufficient_history=has_sufficient_history,
        confidence=confidence,
        activities_7d=activities_7d,
        activities_28d=activities_28d,
        previous_7d_load=round(prev_load_raw, 2),
        load_change_percent=round(load_change_raw, 1) if load_change_raw is not None else None,
    )
