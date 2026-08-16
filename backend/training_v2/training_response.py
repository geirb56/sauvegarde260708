"""PR132 — RecentTrainingResponse & WorkoutExecutionFacts.

Design rules
------------
- PURE: no MongoDB, no API calls, no LLM, no cache, no global state.
- Provider-neutral: no garmin.*, no training_engine, no rag_engine, no llm_coach imports.
- reference_date must be supplied explicitly by the caller (datetime.now() never called here).
- None ≠ 0 : absent / unknown values are None, never 0.
- No pass/fail, no workout score, no verdict, no user text.
- Deterministic: same inputs + reference_date → identical output.

Window contract (28-day, max 10 activities)
-------------------------------------------
Selected activities satisfy ALL of the following:
  1. activity_type in RUNNING_TYPES
  2. start_time date ≥ reference_date − timedelta(days=27)   (i.e. within 28 days inclusive)
  3. start_time date ≤ reference_date                        (no future activities)

Among all qualifying activities, the 10 most recent are selected.

Response status
---------------
  0 activities  → "unavailable"
  1–4 activities → "insufficient"   (facts available, structural trends unreliable)
  5–10 activities → "sufficient"    (trends allowed subject to signal coverage)

A signal can remain unavailable even when response_status = "sufficient".
Example: 8 runs but only 2 with HR → HR trend = "unknown".

Cardiac efficiency V1 (TERRAIN INDICATOR, not lab metric)
----------------------------------------------------------
Computed per activity when ALL conditions are met:
    distance_m > 0
    duration_s > 0
    average_hr > 0

Formula:
    speed_mps         = distance_m / duration_s
    cardiac_efficiency = speed_mps / average_hr     (m·s⁻¹ / bpm)

Elevation context (elevation_gain_m) is preserved but NOT used to adjust the
ratio in V1.  Activities are not filtered out for high elevation; the trend
status may fall back to "unknown" when comparability is low.

Comparability rule (PRODUCT CALIBRATION V1):
    A run is comparable for trend purposes if:
        distance_m  is not None AND > 0
        duration_s  is not None AND > 0
        average_hr  is not None AND > 0
    A trend is computed only when ≥ 4 efficiency samples are available across
    both halves of the window.  Otherwise → "unknown".

Volume trend V1 (PRODUCT CALIBRATION V1)
-----------------------------------------
Activities are sorted oldest → newest.
Split into first half (F) and second half (S) by index.
Only activities with distance_m > 0 are included in each half.

    mean_F = mean distance of F-group (km)
    mean_S = mean distance of S-group (km)

    mean_S > mean_F × 1.10  → "increasing"
    mean_S < mean_F × 0.90  → "decreasing"
    otherwise               → "stable"
    < 4 activities with distance   → "unknown"

No coefficient is hidden.  Threshold = ±10 %.

Long-run trend V1
------------------
Same half-split method applied to the single longest_run_km within each half.
Requires ≥ 4 activities with valid distance.  Threshold = ±10 %.

Forbidden computations (V1)
----------------------------
- cardiac decoupling / HR drift intra-workout   (no timeseries)
- LT1 / LT2 / VT1 / VT2
- TRIMP / TSS / EPOC / Recovery Time
- workout score / pass-fail / success / failed
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict

from .domain_activity import DomainActivity
from .training_history import RUNNING_TYPES
from .workout_generator import WorkoutPrescription

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WINDOW_DAYS: int = 28
_MAX_SELECTED: int = 10


# ---------------------------------------------------------------------------
# Response status literals
# ---------------------------------------------------------------------------

ResponseStatus = str  # "unavailable" | "insufficient" | "sufficient"
TrendValue = str      # "increasing" | "decreasing" | "stable" | "unknown"
Confidence = str      # "none" | "low" | "moderate"


# ---------------------------------------------------------------------------
# Helper: resolve a DomainActivity start_time to a date
# ---------------------------------------------------------------------------

def _activity_date(act: DomainActivity) -> Optional[date]:
    """Return the calendar date of the activity start_time, or None."""
    st = act.start_time
    if st is None:
        return None
    if isinstance(st, datetime):
        return st.date()
    if isinstance(st, date):
        return st
    if isinstance(st, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return datetime.strptime(st, fmt).date()
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Helper: mean of a list of floats (empty → None)
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


# ---------------------------------------------------------------------------
# Helper: compute a binary half-split trend
# ---------------------------------------------------------------------------

def _half_split_trend(values_oldest_first: list[float]) -> TrendValue:
    """Compare mean of first half vs mean of second half.

    PRODUCT CALIBRATION V1:
        threshold = 10 %
        mean_S > mean_F × 1.10  → "increasing"
        mean_S < mean_F × 0.90  → "decreasing"
        otherwise               → "stable"
        < 4 values              → "unknown"
    """
    if len(values_oldest_first) < 4:
        return "unknown"
    mid = len(values_oldest_first) // 2
    first_half = values_oldest_first[:mid]
    second_half = values_oldest_first[mid:]
    mean_f = _mean(first_half)
    mean_s = _mean(second_half)
    if mean_f is None or mean_s is None or mean_f == 0:
        return "unknown"
    ratio = mean_s / mean_f
    if ratio > 1.10:
        return "increasing"
    if ratio < 0.90:
        return "decreasing"
    return "stable"


# ---------------------------------------------------------------------------
# Cardiac efficiency
# ---------------------------------------------------------------------------

def _cardiac_efficiency(act: DomainActivity) -> Optional[float]:
    """Return speed_mps / average_hr, or None when any input is absent/zero."""
    if (
        act.distance_m is None
        or act.duration_s is None
        or act.average_hr is None
        or act.distance_m <= 0
        or act.duration_s <= 0
        or act.average_hr <= 0
    ):
        return None
    speed_mps = act.distance_m / act.duration_s
    return speed_mps / act.average_hr


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RecentTrainingResponse(BaseModel):
    """Immutable snapshot of a runner's recent training response.

    Facts and trends only — no verdict, no score, no user-facing text.
    """

    model_config = ConfigDict(frozen=True)

    # ── Window metadata ──────────────────────────────────────────────────
    reference_date: date
    window_days: int = _WINDOW_DAYS

    # ── Selection counts ─────────────────────────────────────────────────
    available_running_activities: int
    """Count of running activities that fall within the 28-day window."""

    selected_running_activities: int
    """Count of activities actually analysed (max 10, most recent first)."""

    # ── Response status ───────────────────────────────────────────────────
    response_status: ResponseStatus
    """'unavailable' | 'insufficient' | 'sufficient'."""

    confidence: Confidence
    """'none' | 'low' | 'moderate' — reflects selected_running_activities count."""

    # ── Volume & frequency facts ─────────────────────────────────────────
    observed_distance_km: Optional[float]
    observed_duration_minutes: Optional[float]
    observed_runs: int

    observed_runs_per_week: Optional[float]
    """Runs per 7-day equivalent across the 28-day window."""

    # ── Long-run facts ────────────────────────────────────────────────────
    longest_run_km: Optional[float]
    longest_run_duration_minutes: Optional[float]

    # ── Signal coverage ───────────────────────────────────────────────────
    hr_coverage_count: int
    """Number of selected activities with a valid average_hr."""

    intensity_coverage_count: int
    """Number of selected activities with at least one intensity minute field."""

    # ── HR & pace aggregates ─────────────────────────────────────────────
    average_hr_recent: Optional[float]
    """Mean of average_hr across activities where average_hr is available."""

    average_pace_recent_s_per_km: Optional[float]
    """Mean pace in s/km across activities where both distance and duration are available."""

    # ── Cardiac efficiency ────────────────────────────────────────────────
    cardiac_efficiency_samples: tuple[Optional[float], ...]
    """Per-activity efficiency = speed_mps / average_hr; None when data missing."""

    cardiac_efficiency_trend: TrendValue
    """'increasing' | 'decreasing' | 'stable' | 'unknown'."""

    # ── Volume trend ──────────────────────────────────────────────────────
    volume_trend: TrendValue
    """'increasing' | 'decreasing' | 'stable' | 'unknown'."""

    # ── Frequency pattern ─────────────────────────────────────────────────
    frequency_pattern: TrendValue
    """'increasing' | 'decreasing' | 'stable' | 'unknown' — based on half-split run counts."""

    # ── Long-run trend ────────────────────────────────────────────────────
    long_run_trend: TrendValue
    """'increasing' | 'decreasing' | 'stable' | 'unknown'."""

    # ── Intensity exposure ────────────────────────────────────────────────
    intensity_exposure_trend: TrendValue
    """Trend of (moderate + vigorous) minutes per run across the window."""

    # ── Reason codes ─────────────────────────────────────────────────────
    reason_codes: tuple[str, ...]
    """Language-neutral deterministic codes for downstream consumers."""


class WorkoutExecutionFacts(BaseModel):
    """Facts extracted from comparing a planned workout to an actual activity.

    No verdict, no score.  distance_ratio = actual / planned.
    """

    model_config = ConfigDict(frozen=True)

    reference_date: date

    # ── Planned ───────────────────────────────────────────────────────────
    planned_type: Optional[str]
    planned_distance_km: Optional[float]
    planned_duration_minutes: Optional[int]

    # ── Actual ────────────────────────────────────────────────────────────
    actual_distance_km: Optional[float]
    actual_duration_minutes: Optional[float]
    actual_average_hr: Optional[float]

    # ── Ratios ────────────────────────────────────────────────────────────
    distance_ratio: Optional[float]
    """actual_distance_km / planned_distance_km, or None when either is absent."""

    duration_ratio: Optional[float]
    """actual_duration_minutes / planned_duration_minutes, or None when either is absent."""

    # ── Reason codes ─────────────────────────────────────────────────────
    reason_codes: tuple[str, ...]


# ---------------------------------------------------------------------------
# build_recent_training_response
# ---------------------------------------------------------------------------

def build_recent_training_response(
    activities: Sequence[Any],
    reference_date: date,
) -> RecentTrainingResponse:
    """Analyse the recent training response from a sequence of DomainActivity-like inputs.

    Parameters
    ----------
    activities:
        Any sequence of objects that can be coerced to DomainActivity via
        ``to_domain_activity``.  Activities from any source are accepted;
        non-running activities are silently excluded.
    reference_date:
        The anchor date for the 28-day window.  Must be supplied explicitly
        (datetime.now() / date.today() is never called here).

    Returns
    -------
    RecentTrainingResponse
        Immutable snapshot.  Deterministic for identical inputs.
    """
    from .domain_activity import to_domain_activity  # local import avoids circular

    # ── Step 1: coerce all inputs ─────────────────────────────────────────
    domain_acts: list[DomainActivity] = [to_domain_activity(a) for a in activities]

    # ── Step 2: define window bounds ──────────────────────────────────────
    window_start: date = reference_date - timedelta(days=_WINDOW_DAYS - 1)

    # ── Step 3: filter running activities within window ───────────────────
    in_window: list[tuple[date, DomainActivity]] = []
    for act in domain_acts:
        if act.activity_type not in RUNNING_TYPES:
            continue
        act_date = _activity_date(act)
        if act_date is None:
            continue
        if act_date > reference_date:
            continue
        if act_date < window_start:
            continue
        in_window.append((act_date, act))

    available_count = len(in_window)

    # ── Step 4: select up to 10 most recent ───────────────────────────────
    in_window.sort(key=lambda t: t[0], reverse=True)
    selected_pairs = in_window[:_MAX_SELECTED]
    selected_count = len(selected_pairs)

    # ── Step 5: determine response status ────────────────────────────────
    if selected_count == 0:
        status: ResponseStatus = "unavailable"
        confidence: Confidence = "none"
    elif selected_count < 5:
        status = "insufficient"
        confidence = "low"
    else:
        status = "sufficient"
        confidence = "moderate"

    reason_codes: list[str] = []

    # ── Step 6: sort selected oldest → newest for trend analysis ─────────
    selected_oldest_first = list(reversed(selected_pairs))
    selected_acts = [pair[1] for pair in selected_oldest_first]

    # ── Step 7: basic facts ───────────────────────────────────────────────
    total_dist_m: float = 0.0
    has_dist = False
    total_dur_s: float = 0.0
    has_dur = False
    longest_dist_m: Optional[float] = None
    longest_dur_s: Optional[float] = None

    for act in selected_acts:
        if act.distance_m is not None and act.distance_m > 0:
            total_dist_m += act.distance_m
            has_dist = True
            if longest_dist_m is None or act.distance_m > longest_dist_m:
                longest_dist_m = act.distance_m
        if act.duration_s is not None and act.duration_s > 0:
            total_dur_s += act.duration_s
            has_dur = True
        # Longest run by distance — track associated duration
        if longest_dist_m == act.distance_m and act.duration_s is not None and act.duration_s > 0:
            longest_dur_s = act.duration_s

    # Recompute longest_dur_s cleanly
    longest_dur_s = None
    if longest_dist_m is not None:
        for act in selected_acts:
            if act.distance_m == longest_dist_m:
                if act.duration_s is not None and act.duration_s > 0:
                    longest_dur_s = act.duration_s
                break

    observed_distance_km: Optional[float] = total_dist_m / 1000.0 if has_dist else None
    observed_duration_minutes: Optional[float] = total_dur_s / 60.0 if has_dur else None
    longest_run_km: Optional[float] = longest_dist_m / 1000.0 if longest_dist_m is not None else None
    longest_run_duration_minutes: Optional[float] = (
        longest_dur_s / 60.0 if longest_dur_s is not None else None
    )

    # runs per week across 28-day window
    observed_runs_per_week: Optional[float] = (
        (selected_count / _WINDOW_DAYS) * 7.0 if selected_count > 0 else None
    )

    # ── Step 8: HR & pace aggregates ─────────────────────────────────────
    hr_values: list[float] = []
    for act in selected_acts:
        if act.average_hr is not None and act.average_hr > 0:
            hr_values.append(act.average_hr)
    hr_coverage_count = len(hr_values)
    average_hr_recent: Optional[float] = _mean(hr_values)

    pace_values: list[float] = []
    for act in selected_acts:
        if (
            act.distance_m is not None
            and act.distance_m > 0
            and act.duration_s is not None
            and act.duration_s > 0
        ):
            pace_s_per_km = (act.duration_s / act.distance_m) * 1000.0
            pace_values.append(pace_s_per_km)
    average_pace_recent: Optional[float] = _mean(pace_values)

    # ── Step 9: intensity coverage ────────────────────────────────────────
    intensity_coverage_count = sum(
        1
        for act in selected_acts
        if act.moderate_intensity_minutes is not None
        or act.vigorous_intensity_minutes is not None
    )

    # ── Step 10: cardiac efficiency ───────────────────────────────────────
    efficiency_samples: list[Optional[float]] = [
        _cardiac_efficiency(act) for act in selected_acts
    ]
    valid_efficiencies = [e for e in efficiency_samples if e is not None]
    cardiac_efficiency_trend: TrendValue = _half_split_trend(valid_efficiencies)

    # ── Step 11: volume trend ─────────────────────────────────────────────
    dist_series = [
        act.distance_m / 1000.0
        for act in selected_acts
        if act.distance_m is not None and act.distance_m > 0
    ]
    volume_trend: TrendValue = _half_split_trend(dist_series)

    # ── Step 12: frequency pattern ────────────────────────────────────────
    # Split the 28-day window in half (14 days each); count runs per half.
    half_window = _WINDOW_DAYS // 2  # 14 days
    midpoint = reference_date - timedelta(days=half_window)
    first_half_count = sum(1 for d, _ in selected_pairs if d < midpoint)
    second_half_count = sum(1 for d, _ in selected_pairs if d >= midpoint)
    if selected_count < 4:
        frequency_pattern: TrendValue = "unknown"
    elif second_half_count > first_half_count * 1.10:
        frequency_pattern = "increasing"
    elif second_half_count < first_half_count * 0.90:
        frequency_pattern = "decreasing"
    else:
        frequency_pattern = "stable"

    # ── Step 13: long-run trend ───────────────────────────────────────────
    # Long run per activity = its own distance (we track the longest per half).
    # Use the same half-split on individual activity distances.
    long_run_trend: TrendValue = _half_split_trend(dist_series)

    # ── Step 14: intensity exposure trend ────────────────────────────────
    intensity_series: list[float] = []
    for act in selected_acts:
        mod = act.moderate_intensity_minutes
        vig = act.vigorous_intensity_minutes
        if mod is not None or vig is not None:
            total = (mod or 0.0) + (vig or 0.0)
            intensity_series.append(total)
    intensity_exposure_trend: TrendValue = _half_split_trend(intensity_series)

    # ── Step 15: if status is not sufficient, suppress structural trends ──
    if status != "sufficient":
        cardiac_efficiency_trend = "unknown"
        volume_trend = "unknown"
        frequency_pattern = "unknown"
        long_run_trend = "unknown"
        intensity_exposure_trend = "unknown"

    # ── Step 16: reason codes ─────────────────────────────────────────────
    if status == "unavailable":
        reason_codes.append("no_recent_running_activities")
    elif status == "insufficient":
        reason_codes.append("insufficient_activities_for_trends")
    if hr_coverage_count == 0 and selected_count > 0:
        reason_codes.append("hr_data_unavailable")
    elif hr_coverage_count < selected_count and selected_count > 0:
        reason_codes.append("hr_data_partial")
    if intensity_coverage_count == 0 and selected_count > 0:
        reason_codes.append("intensity_data_unavailable")
    if available_count > _MAX_SELECTED:
        reason_codes.append("activities_capped_at_10")

    return RecentTrainingResponse(
        reference_date=reference_date,
        window_days=_WINDOW_DAYS,
        available_running_activities=available_count,
        selected_running_activities=selected_count,
        response_status=status,
        confidence=confidence,
        observed_distance_km=observed_distance_km,
        observed_duration_minutes=observed_duration_minutes,
        observed_runs=selected_count,
        observed_runs_per_week=observed_runs_per_week,
        longest_run_km=longest_run_km,
        longest_run_duration_minutes=longest_run_duration_minutes,
        hr_coverage_count=hr_coverage_count,
        intensity_coverage_count=intensity_coverage_count,
        average_hr_recent=average_hr_recent,
        average_pace_recent_s_per_km=average_pace_recent,
        cardiac_efficiency_samples=tuple(efficiency_samples),
        cardiac_efficiency_trend=cardiac_efficiency_trend,
        volume_trend=volume_trend,
        frequency_pattern=frequency_pattern,
        long_run_trend=long_run_trend,
        intensity_exposure_trend=intensity_exposure_trend,
        reason_codes=tuple(reason_codes),
    )


# ---------------------------------------------------------------------------
# analyze_workout_execution
# ---------------------------------------------------------------------------

def analyze_workout_execution(
    planned: WorkoutPrescription,
    actual: Any,
    reference_date: date,
) -> WorkoutExecutionFacts:
    """Produce pure facts from a planned/actual pair.

    No verdict, no score.  Ratios are actual / planned.
    Both inputs must be already paired by the caller (matching is out of scope).

    Parameters
    ----------
    planned:
        WorkoutPrescription from the weekly plan.
    actual:
        A DomainActivity or any object coercible via to_domain_activity.
    reference_date:
        The reference date for this execution (for audit trail).
    """
    from .domain_activity import to_domain_activity  # local import

    act = to_domain_activity(actual)

    planned_dist_km = planned.distance_km
    planned_dur_min = (
        float(planned.duration_minutes)
        if planned.duration_minutes is not None
        else None
    )

    actual_dist_km = (
        act.distance_m / 1000.0
        if act.distance_m is not None and act.distance_m > 0
        else None
    )
    actual_dur_min = (
        act.duration_s / 60.0
        if act.duration_s is not None and act.duration_s > 0
        else None
    )

    distance_ratio: Optional[float] = (
        actual_dist_km / planned_dist_km
        if actual_dist_km is not None and planned_dist_km is not None and planned_dist_km > 0
        else None
    )
    duration_ratio: Optional[float] = (
        actual_dur_min / planned_dur_min
        if actual_dur_min is not None and planned_dur_min is not None and planned_dur_min > 0
        else None
    )

    reason_codes: list[str] = []
    if distance_ratio is None and planned_dist_km is not None:
        reason_codes.append("actual_distance_unavailable")
    if duration_ratio is None and planned_dur_min is not None:
        reason_codes.append("actual_duration_unavailable")

    return WorkoutExecutionFacts(
        reference_date=reference_date,
        planned_type=planned.workout_type,
        planned_distance_km=planned_dist_km,
        planned_duration_minutes=planned.duration_minutes,
        actual_distance_km=actual_dist_km,
        actual_duration_minutes=actual_dur_min,
        actual_average_hr=act.average_hr,
        distance_ratio=distance_ratio,
        duration_ratio=duration_ratio,
        reason_codes=tuple(reason_codes),
    )
