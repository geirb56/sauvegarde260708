"""PR132 — RecentTrainingResponse & WorkoutExecutionFacts.

Design rules
------------
- PURE: no MongoDB, no API calls, no LLM, no cache, no global state.
- Provider-neutral: no garmin.*, no training_engine, no rag_engine, no llm_coach imports.
- reference_date must be supplied explicitly by the caller (datetime.now() never called here).
- None ≠ 0 : absent / unknown values are None, never 0.
- No pass/fail, no workout score, no verdict, no user text.
- Deterministic: same inputs + reference_date → identical output.

Window contract (28-day, max 10 for fine analysis)
--------------------------------------------------
All qualifying activities satisfy:
  1. activity_type in RUNNING_TYPES
  2. start_time date ≥ reference_date − timedelta(days=27)   (i.e. within 28 days inclusive)
  3. start_time date ≤ reference_date                        (no future activities)

GLOBAL 28-DAY FACTS use ALL qualifying activities in the window:
  observed_runs, observed_runs_per_week, observed_distance_km, observed_duration_minutes,
  volume_trend, frequency_pattern, long_run_trend, intensity_exposure_trend.

RECENT SAMPLE (fine analysis) is limited to the 10 most recent activities
(selected_running_activities ≤ 10):
  cardiac_efficiency_samples, average_hr_recent, average_pace_recent_s_per_km.

The cap of 10 must NEVER reduce global facts.

Response status
---------------
  0 activities  → "unavailable"
  1–4 activities → "insufficient"   (facts available, structural trends unreliable)
  5–10 activities → "sufficient"    (trends allowed subject to signal coverage)

A signal can remain unavailable even when response_status = "sufficient".
Example: 8 runs but only 2 with HR → HR trend = "unknown".

Cardiac efficiency V1 (TERRAIN INDICATOR, not lab metric)
----------------------------------------------------------
Computed per activity (from selected_running_activities, max 10) when ALL met:
    distance_m > 0
    duration_s > 0
    average_hr > 0

Formula:
    speed_mps         = distance_m / duration_s
    cardiac_efficiency = speed_mps / average_hr     (m·s⁻¹ / bpm)

Terrain comparability guard (PRODUCT CALIBRATION V1 — RECALIBRABLE):
    elevation_rate = elevation_gain_m / distance_km   (m D+/km)

    A trend is calculated only when ≥ 4 samples have BOTH valid efficiency
    AND known elevation_rate (elevation_gain_m not None, distance_m > 0).
    → Otherwise: "unknown"  (conservative, None ≠ 0)

    Among those ≥ 4 comparable samples, if:
        terrain_max − terrain_min > _TERRAIN_DISPERSION_THRESHOLD_M_PER_KM (30 m D+/km)
    → "unknown"  (incompatible terrain, no invented GAP correction)

    Threshold = 30 m D+/km.  Centralized, documented, recalibrable for V2.
    NO speed correction / GAP formula / trail bonus ever applied.

Volume trend V1 (PRODUCT CALIBRATION V1)
-----------------------------------------
Calendar-based: the 28-day window is split into two equal 14-day halves.
Uses ALL in-window activities (not capped at 10).

    old half   : window_start (J-27) → J-14 inclusive
    recent half: J-13          → reference_date (J) inclusive

For each half, total_distance_km = sum of distances of ALL running
activities in that half with valid distance.

    recent_total > old_total × 1.10  → "increasing"
    recent_total < old_total × 0.90  → "decreasing"
    otherwise                        → "stable"

    Conditions for computation:
        - at least 1 activity with valid distance in EACH half
        - at least 4 activities with valid distance total in the 28-day window
    Otherwise → "unknown"

No coefficient is hidden.  Threshold = ±10 %.

Frequency pattern V1 (PRODUCT CALIBRATION V1)
----------------------------------------------
Calendar-based: same 14-day half-split.
Uses ALL in-window activities (not capped at 10).
Count of runs in old half vs recent half, ±10 % threshold.
If available_count < 4 → "unknown".

Long-run trend V1 (PRODUCT CALIBRATION V1)
-------------------------------------------
Calendar-based: compare the longest single run in the old 14d half
vs the longest single run in the recent 14d half.
Uses ALL in-window activities (not capped at 10).
Requires at least 1 valid distance in each half AND ≥ 4 valid distances total.
Threshold = ±10 %.

Intensity exposure trend V1 (PRODUCT CALIBRATION V1)
------------------------------------------------------
Calendar-based: compare total (moderate + vigorous) intensity minutes
in old 14d half vs recent 14d half.
Uses ALL in-window activities (not capped at 10).
moderate + vigorous as plain sum (no weighting factor).
Threshold = ±10 %.

Forbidden computations (V1)
----------------------------
- cardiac decoupling / HR drift intra-workout   (no timeseries)
- LT1 / LT2 / VT1 / VT2
- TRIMP / TSS / EPOC / Recovery Time
- workout score / pass-fail / success / failed
- GAP / grade-adjusted pace / terrain speed correction
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

# PRODUCT CALIBRATION V1 — RECALIBRABLE — NOT PHYSIOLOGICAL LAW
# Maximum allowed elevation-rate spread (m D+/km) among comparable cardiac-
# efficiency samples.  If terrain_max − terrain_min exceeds this threshold,
# the samples are considered non-comparable and cardiac_efficiency_trend falls
# back to "unknown".  No speed correction is ever applied.
_TERRAIN_DISPERSION_THRESHOLD_M_PER_KM: float = 30.0


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
    """Total running distance in km across ALL activities in the 28-day window."""

    observed_duration_minutes: Optional[float]
    """Total running duration in minutes across ALL activities in the 28-day window."""

    observed_runs: int
    """Total number of running activities in the 28-day window (not capped at 10)."""

    observed_runs_per_week: Optional[float]
    """Runs per 7-day equivalent: available_running_activities / 28 × 7."""

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

    # ── Step 7: global 28-day facts (ALL activities in window, not capped) ──
    # Iterate over in_window (all available), not selected_pairs.
    total_dist_m: float = 0.0
    has_dist = False
    total_dur_s: float = 0.0
    has_dur = False
    longest_dist_m: Optional[float] = None

    for _d, act in in_window:
        if act.distance_m is not None and act.distance_m > 0:
            total_dist_m += act.distance_m
            has_dist = True
            if longest_dist_m is None or act.distance_m > longest_dist_m:
                longest_dist_m = act.distance_m
        if act.duration_s is not None and act.duration_s > 0:
            total_dur_s += act.duration_s
            has_dur = True

    # Recompute longest_dur_s from ALL in-window activities
    longest_dur_s: Optional[float] = None
    if longest_dist_m is not None:
        for _d, act in in_window:
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

    # Global runs per week: use ALL in-window activities
    observed_runs_per_week: Optional[float] = (
        (available_count / _WINDOW_DAYS) * 7.0 if available_count > 0 else None
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
    # Efficiency per selected activity (fine analysis, ≤ 10 most recent).
    efficiency_samples: list[Optional[float]] = [
        _cardiac_efficiency(act) for act in selected_acts
    ]

    # Terrain comparability guard (PRODUCT CALIBRATION V1 — RECALIBRABLE)
    # elevation_rate = elevation_gain_m / distance_km  (m D+/km)
    # Condition for trend computation:
    #   ≥ 4 samples with BOTH valid efficiency AND known elevation_rate
    #   AND terrain_max − terrain_min ≤ _TERRAIN_DISPERSION_THRESHOLD_M_PER_KM
    # NO speed correction / GAP formula is ever applied.
    known_terrain_rates: list[float] = []
    for act, eff in zip(selected_acts, efficiency_samples):
        if (
            eff is not None
            and act.elevation_gain_m is not None
            and act.distance_m is not None
            and act.distance_m > 0
        ):
            known_terrain_rates.append(act.elevation_gain_m / (act.distance_m / 1000.0))

    valid_efficiencies = [e for e in efficiency_samples if e is not None]
    if len(known_terrain_rates) < 4:
        # Fewer than 4 samples have both valid efficiency and known elevation_rate.
        # Conservative: terrain comparability cannot be verified → unknown.
        cardiac_efficiency_trend: TrendValue = "unknown"
    else:
        terrain_min = min(known_terrain_rates)
        terrain_max = max(known_terrain_rates)
        if terrain_max - terrain_min > _TERRAIN_DISPERSION_THRESHOLD_M_PER_KM:
            # Terrain dispersion exceeds threshold → samples not comparable → unknown.
            cardiac_efficiency_trend = "unknown"
        else:
            cardiac_efficiency_trend = _half_split_trend(valid_efficiencies)

    # ── Step 11: volume trend — calendar-based, ALL in-window activities ─────
    # Split 28-day window into two 14-day halves:
    #   old half   : window_start (J-27) → freq_boundary - 1 day  (J-14 inclusive)
    #   recent half: freq_boundary (J-13) → reference_date (J) inclusive
    # The same freq_boundary is used for frequency_pattern (step 12).
    # Compares TOTAL distances, not per-run averages.
    # PRODUCT CALIBRATION V1 — threshold = ±10 %
    freq_boundary = reference_date - timedelta(days=13)
    old_half_dist_m: float = sum(
        act.distance_m
        for d, act in in_window
        if d < freq_boundary and act.distance_m is not None and act.distance_m > 0
    )
    recent_half_dist_m: float = sum(
        act.distance_m
        for d, act in in_window
        if d >= freq_boundary and act.distance_m is not None and act.distance_m > 0
    )
    old_half_has_valid = any(
        act.distance_m is not None and act.distance_m > 0
        for d, act in in_window
        if d < freq_boundary
    )
    recent_half_has_valid = any(
        act.distance_m is not None and act.distance_m > 0
        for d, act in in_window
        if d >= freq_boundary
    )
    total_valid_dist_count = sum(
        1 for _d, act in in_window
        if act.distance_m is not None and act.distance_m > 0
    )
    if (
        not old_half_has_valid
        or not recent_half_has_valid
        or old_half_dist_m == 0
        or total_valid_dist_count < 4
    ):
        volume_trend: TrendValue = "unknown"
    elif recent_half_dist_m > old_half_dist_m * 1.10:
        volume_trend = "increasing"
    elif recent_half_dist_m < old_half_dist_m * 0.90:
        volume_trend = "decreasing"
    else:
        volume_trend = "stable"

    # ── Step 12: frequency pattern ────────────────────────────────────────
    # Uses ALL in-window activities (not capped at 10).
    # Calendar-based 14d vs 14d split on the same freq_boundary.
    # PRODUCT CALIBRATION V1 — threshold = ±10 %
    first_half_count = sum(1 for d, _ in in_window if d < freq_boundary)
    second_half_count = sum(1 for d, _ in in_window if d >= freq_boundary)
    if available_count < 4 or first_half_count == 0:
        frequency_pattern: TrendValue = "unknown"
    elif second_half_count > first_half_count * 1.10:
        frequency_pattern = "increasing"
    elif second_half_count < first_half_count * 0.90:
        frequency_pattern = "decreasing"
    else:
        frequency_pattern = "stable"

    # ── Step 13: long-run trend ───────────────────────────────────────────
    # Calendar-based: compare the longest run in the old 14d half vs the
    # longest run in the recent 14d half.
    # Uses ALL in-window activities (not capped at 10).
    # PRODUCT CALIBRATION V1 — threshold = ±10 %.
    # Requires ≥ 1 valid distance in each half AND ≥ 4 valid distances total.
    old_half_run_dists_km = [
        act.distance_m / 1000.0
        for d, act in in_window
        if d < freq_boundary and act.distance_m is not None and act.distance_m > 0
    ]
    recent_half_run_dists_km = [
        act.distance_m / 1000.0
        for d, act in in_window
        if d >= freq_boundary and act.distance_m is not None and act.distance_m > 0
    ]
    if (
        not old_half_run_dists_km
        or not recent_half_run_dists_km
        or len(old_half_run_dists_km) + len(recent_half_run_dists_km) < 4
    ):
        long_run_trend: TrendValue = "unknown"
    else:
        lr_old = max(old_half_run_dists_km)
        lr_recent = max(recent_half_run_dists_km)
        if lr_recent > lr_old * 1.10:
            long_run_trend = "increasing"
        elif lr_recent < lr_old * 0.90:
            long_run_trend = "decreasing"
        else:
            long_run_trend = "stable"

    # ── Step 14: intensity exposure trend ────────────────────────────────
    # Calendar-based: compare total (moderate + vigorous) intensity minutes
    # in old 14d half vs recent 14d half.
    # Uses ALL in-window activities (not capped at 10).
    # moderate + vigorous as plain sum — no weighting factor.
    # PRODUCT CALIBRATION V1 — threshold = ±10 %
    old_intensity_total: float = 0.0
    old_intensity_has_data: bool = False
    recent_intensity_total: float = 0.0
    recent_intensity_has_data: bool = False
    for d, act in in_window:
        mod = act.moderate_intensity_minutes
        vig = act.vigorous_intensity_minutes
        if mod is not None or vig is not None:
            mins = (mod or 0.0) + (vig or 0.0)
            if d < freq_boundary:
                old_intensity_total += mins
                old_intensity_has_data = True
            else:
                recent_intensity_total += mins
                recent_intensity_has_data = True
    if not old_intensity_has_data or not recent_intensity_has_data or old_intensity_total == 0:
        intensity_exposure_trend: TrendValue = "unknown"
    elif recent_intensity_total > old_intensity_total * 1.10:
        intensity_exposure_trend = "increasing"
    elif recent_intensity_total < old_intensity_total * 0.90:
        intensity_exposure_trend = "decreasing"
    else:
        intensity_exposure_trend = "stable"

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
        observed_runs=available_count,
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
