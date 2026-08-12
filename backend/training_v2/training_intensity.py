"""R1.7B — TrainingIntensityProfile: pure, provider-neutral intensity facts.

Design rules
------------
- PURE: no MongoDB, no API calls, no LLM, no cache, no global state.
- Provider-neutral: no garmin.*, no terra.*, no strava.* imports.
- reference_date must be supplied explicitly by the caller so that all
  calculations are deterministic and fully testable.
- datetime.now() is never called inside this module.
- None ≠ 0 : unknown intensity is represented by None, not zero.
- No physiological interpretation: no LT1/LT2, no TRIMP/TSS, no EPOC,
  no recovery score, no weighting of moderate vs vigorous.

Window V1 (window_days = 2)
---------------------------
Covers J-1 → J inclusive where J = reference_date:

    [reference_date - timedelta(days=1), reference_date]

Activities dated strictly before this window or strictly after
reference_date are excluded.

Activity filter
---------------
Only the following activity_type values are treated as running:
  "running", "trail_running", "treadmill_running"

Non-running, future, and out-of-window activities are silently ignored.

Duration
--------
duration_minutes = sum(duration_s / 60) for each running activity in the
window where duration_s is numeric (int or float, not bool) and > 0.

Intensity minutes
-----------------
moderate_minutes = sum of all *known* moderate_intensity_minutes values.
vigorous_minutes = sum of all *known* vigorous_intensity_minutes values.
None means the value was unavailable; 0 means it was known to be zero.
If no activity in the window has a known value, the aggregate is None.
A known 0 combined with None still yields 0, not None.

Coverage
--------
An activity is counted as "with_intensity" if at least one of
  moderate_intensity_minutes is not None
  vigorous_intensity_minutes is not None
is true for that activity.

intensity_coverage_ratio = activities_with_intensity / activities_total
When activities_total == 0 the ratio is None (not 0.0).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, List, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict

# Reuse the canonical set of running activity types from training_history to
# avoid duplication.  Import at function level only if needed to sidestep any
# future circular-import risk; here a direct module-level import is safe
# because training_history does NOT import training_intensity.
from .training_history import RUNNING_TYPES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_WINDOW_DAYS = 2


def _activity_date(activity: Any) -> Optional[date]:
    """Return the calendar date for an activity's start_time, or None."""
    start = getattr(activity, "start_time", None)
    if start is None:
        return None
    if isinstance(start, datetime):
        return start.date()
    if isinstance(start, date):
        return start
    if isinstance(start, str):
        try:
            return datetime.fromisoformat(start).date()
        except ValueError:
            pass
    return None


def _valid_duration(value: Any) -> bool:
    """Return True when *value* is a numeric, non-bool, positive duration."""
    if value is None or isinstance(value, bool):
        return False
    return isinstance(value, (int, float)) and value > 0


def _add_intensity(accumulator: Optional[float], value: Optional[float]) -> Optional[float]:
    """Add *value* to *accumulator* following the None ≠ 0 rule.

    - None + None  → None   (both unknown)
    - known + None → known  (partial knowledge preserved)
    - None + known → known
    - known + known→ sum
    """
    if value is None:
        return accumulator  # unknown contribution: leave accumulator unchanged
    if accumulator is None:
        return float(value)  # first known value initialises the accumulator
    return accumulator + float(value)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class TrainingIntensityProfile(BaseModel):
    """Immutable snapshot of intensity facts for a short training window.

    All fields are descriptive; no physiological interpretation is performed.
    """

    model_config = ConfigDict(frozen=True)

    reference_date: date
    window_days: int

    # --- Duration ---
    duration_minutes: float

    # --- Intensity minutes (None = data unavailable for the whole window) ---
    moderate_minutes: Optional[float]
    vigorous_minutes: Optional[float]

    # --- Activity counts ---
    activities_total: int
    activities_with_intensity: int
    activities_without_intensity: int

    # --- Coverage ---
    intensity_coverage_ratio: Optional[float]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_training_intensity_profile(
    activities: Sequence[Any],
    reference_date: date,
    *,
    window_days: int = _DEFAULT_WINDOW_DAYS,
) -> TrainingIntensityProfile:
    """Build a :class:`TrainingIntensityProfile` from a collection of activities.

    Parameters
    ----------
    activities:
        Any sequence of objects that expose the following attributes
        (provider-neutral ``DomainActivity`` instances are the canonical
        input, but plain objects or dicts with the same fields work too):

        - ``activity_type`` (str or None)
        - ``start_time``    (date | datetime | ISO-8601 str | None)
        - ``duration_s``    (int | float | None)
        - ``moderate_intensity_minutes`` (int | float | None)
        - ``vigorous_intensity_minutes`` (int | float | None)

    reference_date:
        The anchor date J.  The window covers [J - (window_days - 1), J].

    window_days:
        Width of the window in calendar days (inclusive). Default is 2,
        covering J-1 and J.

    Returns
    -------
    TrainingIntensityProfile
    """
    window_start = reference_date - timedelta(days=window_days - 1)

    total = 0
    with_intensity = 0
    duration_s_sum: float = 0.0
    moderate_acc: Optional[float] = None
    vigorous_acc: Optional[float] = None

    for activity in activities:
        # --- Type filter ---
        act_type = getattr(activity, "activity_type", None)
        if act_type not in RUNNING_TYPES:
            continue

        # --- Window filter ---
        act_date = _activity_date(activity)
        if act_date is None:
            continue
        if act_date < window_start or act_date > reference_date:
            continue

        total += 1

        # --- Duration ---
        dur = getattr(activity, "duration_s", None)
        if _valid_duration(dur):
            duration_s_sum += float(dur)  # type: ignore[arg-type]

        # --- Intensity ---
        moderate = getattr(activity, "moderate_intensity_minutes", None)
        vigorous = getattr(activity, "vigorous_intensity_minutes", None)

        moderate_acc = _add_intensity(moderate_acc, moderate)
        vigorous_acc = _add_intensity(vigorous_acc, vigorous)

        # --- Coverage classification ---
        if moderate is not None or vigorous is not None:
            with_intensity += 1

    without_intensity = total - with_intensity
    coverage: Optional[float] = (
        with_intensity / total if total > 0 else None
    )

    return TrainingIntensityProfile(
        reference_date=reference_date,
        window_days=window_days,
        duration_minutes=duration_s_sum / 60.0,
        moderate_minutes=moderate_acc,
        vigorous_minutes=vigorous_acc,
        activities_total=total,
        activities_with_intensity=with_intensity,
        activities_without_intensity=without_intensity,
        intensity_coverage_ratio=coverage,
    )
