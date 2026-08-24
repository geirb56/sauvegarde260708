"""Performance Model V2 — Pure business logic for VMA estimation and race predictions.

This module is intentionally I/O-free:
  - No Mongo / database calls
  - No FastAPI / HTTP
  - No datetime.now() (reference_date is always an explicit parameter)
  - No references to the workouts collection

VMA V2 — ACTIVE PATH:

  SOURCE B — Individual HR-speed model (modèle individuel vitesse–FC):
    Linear regression speed = a * HR + b on multiple clean running activities.
    Requires >= 4 activities with average HR spanning >= 20 bpm.
    FCmax from the robust observed Garmin max HR (see _resolve_fcmax_robust).
    Extrapolation target: 95% of FCmax (aerobic ceiling, conservative).
    If R² < 0.30 or slope <= 0: vma_kmh = null.

  SOURCE A — Explicit performance: REMOVED.
    No Garmin field identifies an activity as a race or test.
    All related code has been deleted.

  If SOURCE B yields insufficient data or quality: vma_kmh = null.

FCmax policy:
  FCMAX_RUNTIME_SOURCE = ROBUST_OBSERVED_GARMIN_MAX_HR
  FCMAX_OUTLIER_PROTECTION = YES (active when n >= 3 observations)
  USER_MAX_HR_RUNTIME_WIRED = NOT_AVAILABLE
  No 220-age formula, no population fallback, no hr_max+5.

  Robust estimator: for n >= 3, if the highest observed max_hr is > 10% above
  the second-highest, it is treated as a Garmin artefact and discarded.
  For n < 3: raw max (no outlier protection, documented).

Race predictions — ROAD ONLY:
  RIEGEL_SOURCE = QUALIFIED_OBSERVED_ACTIVITY_ONLY
  trail_running activities are never used as road prediction sources.
  Activities with elevation_gain_per_km > MAX_ROAD_ELEVATION_GAIN_PER_KM are excluded.
Performance qualification is separate from curve fitting:
  - qualification uses only effort quality signals (personal speed percentile, relative HR)
  - race predictions fit one shared time-distance curve from qualified performances
Personal speed percentile uses a 90-day strictly-prior benchmark (no look-ahead, never self-inclusive).
Without HR: qualification is still possible, but only via a stricter speed-only fallback and
the resulting prediction confidence is capped at MEDIUM.

VMA / Predictions independence:
  RIEGEL_VMA_CONFIDENCE_DEPENDENCY = NO
  Prediction confidence is determined solely by source proximity, recency,
  relative HR, and endurance support.  VMA confidence never downgrade predictions.

VMA history:
  VMA_WINDOW_DAYS = 42 (rolling window, non-cumulative)
  Each snapshot uses only activities within the 42-day window ending at snapshot_date.
  estimate_vma() applies this window internally.
  NO look-ahead.

duration_s semantics:
  GARMIN_DURATION_SOURCE = summaryDTO.movingDuration (preferred) → summaryDTO.duration (fallback)
  Performance duration authority: _performance_duration_s() prefers moving_duration_s when
  moving_duration_s > 0 and moving_duration_s <= duration_s (or duration_s absent).
  This is the single authority for speed, VMA, and Riegel calculations.

FORBIDDEN:
  - avg_speed-divided-by-0.70 fallback (removed)
  - Single fastest run auto-qualified as source
  - 220-age or any population FCmax formula
  - hr_max+5 adjustment
  - Synthetic/invented predictions
  - VMA confidence affecting prediction confidence

Inputs:
    List[DomainActivity]   — running activities already filtered to the user
    reference_date         — the "now" snapshot date (date or datetime)
    user_max_hr            — optional known FCmax from user profile (wired to None at runtime)

Outputs (dataclasses, not Pydantic):
    VMAEstimate
    RacePrediction
    PerformanceEstimate
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from training_v2.domain_activity import DomainActivity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RUNNING_TYPES = {
    "running", "run", "trail_running", "treadmill_running",
    "indoor_running", "track_running",
}

# Road-eligible types for Riegel source selection (trail excluded)
_ROAD_TYPES = _RUNNING_TYPES - {"trail_running"}

RIEGEL_K: float = 1.06
# Conservative RunIndex business guardrails for plausibility/conflict handling.
# They are not universal physiological truths.
CURVE_K_MIN: float = 1.0
CURVE_K_MAX: float = 1.25
# Symmetric extrapolation policy guardrails for RunIndex runtime behavior.
# They are operational thresholds, not universal physiological constants.
CURVE_MAX_EXTRAPOLATION_RATIO: float = 6.0
CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO: float = 4.5
CURVE_K_CONFLICT_WEIGHT_PENALTY: float = 0.60

# Speed bounds (km/h) for a plausible running activity
MIN_SPEED_KMH: float = 3.0
MAX_SPEED_KMH: float = 30.0

# Minimum distance (m) for any candidate activity
MIN_DISTANCE_M: float = 500.0

# Minimum duration (s) for an effort to be informative
MIN_INFORMATIVE_DURATION_S: float = 5 * 60   # 5 min

# HR-speed model: activity filtering
MIN_DURATION_HR_MODEL_S: float = 10 * 60     # 10 min — short sprints not representative
MIN_AVG_HR: float = 90.0                      # bpm floor — below this is likely invalid
MAX_AVG_HR: float = 220.0                     # bpm ceiling — above this is aberrant

# HR-speed model: coverage requirements
MIN_ACTIVITIES_HR_MODEL: int = 4
MIN_DISTINCT_HR_LEVELS: int = 3
MIN_HR_RANGE_BPM: float = 20.0               # min spread across observed HR values

# HR-speed model: quality
MIN_R2: float = 0.30                          # minimum R² — weak correlation → null
MAX_EXTRAPOLATION_RATIO: float = 1.25         # max HR extrapolation beyond observed max

# Staleness thresholds (days) for confidence
CONFIDENCE_HIGH_DAYS = 21
CONFIDENCE_MEDIUM_DAYS = 56
CONFIDENCE_LOW_DAYS = 120

# Riegel source selection constraints
MAX_RIEGEL_SOURCE_AGE_DAYS: int = 730        # Activities older than 2 years not defensible
MIN_RIEGEL_SOURCE_RATIO: float = 0.12        # Source must be >= 12% of target distance
MIN_RIEGEL_SCORE: float = 0.25               # Minimum score for a defensible source
MAX_ROAD_ELEVATION_GAIN_PER_KM: float = 30.0  # m/km — above this, not road-equivalent

# Performance qualification business constants
PERSONAL_SPEED_WINDOW_DAYS: int = 90
MIN_SPEED_BENCHMARK_RUNS: int = 5
PERFORMANCE_HR_WEIGHT: float = 0.55
PERFORMANCE_SPEED_WEIGHT: float = 0.45
PERFORMANCE_SCORE_THRESHOLD: float = 0.65
PERFORMANCE_HR_COMPONENT_FLOOR: float = 0.75
PERFORMANCE_HR_COMPONENT_CEILING: float = 0.90
PERFORMANCE_MIN_RELATIVE_HR: float = 0.80
PERFORMANCE_MIN_SPEED_PERCENTILE_WITH_HR: float = 70.0
PERFORMANCE_NO_HR_MIN_SPEED_PERCENTILE: float = 90.0
PERFORMANCE_HIGH_CONFIDENCE_SCORE: float = 0.80
PERFORMANCE_HIGH_CONFIDENCE_RELATIVE_HR: float = 0.85
PERFORMANCE_HIGH_CONFIDENCE_SPEED_PERCENTILE: float = 90.0
MIN_RIEGEL_RELATIVE_HR: float = PERFORMANCE_MIN_RELATIVE_HR

# VMA rolling window (used for both CURRENT and HISTORY)
VMA_WINDOW_DAYS: int = 42

# Target race distances (m)
RACE_DISTANCES_M = {
    "5K": 5_000.0,
    "10K": 10_000.0,
    "Semi": 21_097.5,
    "Marathon": 42_195.0,
}

# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------

REASON_HR_SPEED_MODEL_SOURCE = "HR_SPEED_MODEL_SOURCE"
REASON_HR_RANGE_INSUFFICIENT = "HR_RANGE_INSUFFICIENT"
REASON_HR_LEVELS_INSUFFICIENT = "HR_LEVELS_INSUFFICIENT"
REASON_HR_MODEL_POOR_FIT = "HR_MODEL_POOR_FIT"
REASON_EXTRAPOLATION_TOO_LARGE = "EXTRAPOLATION_TOO_LARGE"
REASON_NO_FCMAX = "NO_FCMAX"
REASON_NO_DATA = "NO_DATA"
REASON_INSUFFICIENT_ACTIVITIES = "INSUFFICIENT_ACTIVITIES"

REASON_PERF_QUALIFIED_HR_SPEED = "PERF_QUALIFIED_HR_SPEED"
REASON_PERF_QUALIFIED_SPEED_ONLY = "PERF_QUALIFIED_SPEED_ONLY"
REASON_PERF_NO_SPEED_BENCHMARK = "PERF_NO_SPEED_BENCHMARK"
REASON_PERF_SPEED_TOO_LOW = "PERF_SPEED_TOO_LOW"
REASON_PERF_RELATIVE_HR_TOO_LOW = "PERF_RELATIVE_HR_TOO_LOW"
REASON_PERF_SCORE_TOO_LOW = "PERF_SCORE_TOO_LOW"
REASON_PERF_MISSING_DATA = "PERF_MISSING_DATA"
REASON_PERF_TERRAIN_REJECTED = "PERF_TERRAIN_REJECTED"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_date(value: Union[str, date, datetime, None]) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return None


def _activity_date(a: DomainActivity) -> Optional[date]:
    return _as_date(a.start_time)


def _is_running(a: DomainActivity) -> bool:
    if not a.activity_type:
        return False
    return a.activity_type.strip().lower().replace(" ", "_") in _RUNNING_TYPES


def _performance_duration_s(a: DomainActivity) -> Optional[float]:
    """Select the authoritative performance duration for speed and Riegel calculations.

    Priority:
      1. moving_duration_s when > 0 AND (duration_s absent OR moving_duration_s <= duration_s)
      2. duration_s when > 0
      3. None

    This function is the single authority for duration used in:
    - _speed_kmh()
    - _validate_activity() duration check
    - _is_usable_for_hr_model() duration check
    - Riegel source duration in predict_races()
    """
    moving = a.moving_duration_s
    elapsed = a.duration_s
    if moving is not None and moving > 0:
        if elapsed is None or moving <= elapsed:
            return moving
    if elapsed is not None and elapsed > 0:
        return elapsed
    return None


def _speed_kmh(a: DomainActivity) -> Optional[float]:
    dur = _performance_duration_s(a)
    if not a.distance_m or not dur:
        return None
    if a.distance_m <= 0 or dur <= 0:
        return None
    return (a.distance_m / 1000.0) / (dur / 3600.0)


def _days_ago(activity_date: date, reference_date: date) -> int:
    return (reference_date - activity_date).days


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _strictly_prior_activities(
    activity: DomainActivity,
    activities: List[DomainActivity],
) -> List[DomainActivity]:
    """Return only activities dated strictly before the evaluated activity."""
    activity_dt = _activity_date(activity)
    if activity_dt is None:
        return []
    return [
        other
        for other in activities
        if (other_dt := _activity_date(other)) is not None and other_dt < activity_dt
    ]


def _validate_activity(a: DomainActivity, reference_date: date) -> bool:
    """Return True if the activity is a valid running candidate (basic validation)."""
    if not _is_running(a):
        return False
    d = _activity_date(a)
    if d is None or d > reference_date:
        return False
    if not a.distance_m or a.distance_m < MIN_DISTANCE_M:
        return False
    dur = _performance_duration_s(a)
    if not dur or dur <= 0:
        return False
    speed = _speed_kmh(a)
    if speed is None or speed < MIN_SPEED_KMH or speed > MAX_SPEED_KMH:
        return False
    return True


def _is_road_comparable(a: DomainActivity, reference_date: date) -> bool:
    """Return True when the activity is road-comparable for speed/performance purposes."""
    if not _validate_activity(a, reference_date):
        return False
    act_type = (a.activity_type or "").strip().lower().replace(" ", "_")
    if act_type == "trail_running":
        return False
    if a.elevation_gain_m is not None and a.distance_m and a.distance_m > 0:
        elev_per_km = a.elevation_gain_m / (a.distance_m / 1000.0)
        if elev_per_km > MAX_ROAD_ELEVATION_GAIN_PER_KM:
            return False
    return True


# ---------------------------------------------------------------------------
# HR-speed model filtering
# ---------------------------------------------------------------------------


def _is_usable_for_hr_model(a: DomainActivity, reference_date: date) -> bool:
    """Additional filters for HR-speed model activities.

    On top of _validate_activity, also requires:
    - Not trail_running (road/track only for HR-speed model)
    - HR present and plausible
    - Duration >= MIN_DURATION_HR_MODEL_S (no short sprints)
    - Elevation gain per km <= MAX_ROAD_ELEVATION_GAIN_PER_KM (trail/hilly → not comparable)
    - Not a future activity
    """
    if not _validate_activity(a, reference_date):
        return False
    # trail_running excluded from road HR-speed model
    act_type = (a.activity_type or "").strip().lower().replace(" ", "_")
    if act_type == "trail_running":
        return False
    hr = a.average_hr
    if hr is None or hr < MIN_AVG_HR or hr > MAX_AVG_HR:
        return False
    dur = _performance_duration_s(a)
    if (dur or 0) < MIN_DURATION_HR_MODEL_S:
        return False
    # Elevation: reject if data exists and per-km exceeds road threshold
    if a.elevation_gain_m is not None and a.distance_m and a.distance_m > 0:
        elev_per_km = a.elevation_gain_m / (a.distance_m / 1000.0)
        if elev_per_km > MAX_ROAD_ELEVATION_GAIN_PER_KM:
            return False
    return True


# ---------------------------------------------------------------------------
# Linear regression: speed = a * HR + b
# ---------------------------------------------------------------------------


def _linear_regression(
    xs: List[float], ys: List[float]
) -> Tuple[float, float, float]:
    """Ordinary least-squares: y = a*x + b.

    Returns (a, b, r_squared).
    r_squared in [-inf, 1]; negative means regression is worse than flat mean.
    """
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    ss_xx = sum((xs[i] - mean_x) ** 2 for i in range(n))
    ss_yy = sum((ys[i] - mean_y) ** 2 for i in range(n))

    if ss_xx < 1e-12:
        return 0.0, mean_y, 0.0

    a = ss_xy / ss_xx
    b = mean_y - a * mean_x

    if ss_yy < 1e-12:
        r2 = 1.0
    else:
        r2 = (ss_xy ** 2) / (ss_xx * ss_yy)

    return a, b, r2


# ---------------------------------------------------------------------------
# FCmax resolution — robust observed Garmin max HR
# ---------------------------------------------------------------------------


def _resolve_fcmax_robust(observed: List[float]) -> Optional[float]:
    """Return a robust FCmax from a list of valid observed max_hr values.

    Rules:
      n = 0  → None
      n = 1  → raw value (no outlier protection, single observation)
      n = 2  → raw max (no outlier protection, two observations)
      n >= 3 → outlier protection: if the highest value exceeds the
               second-highest by more than 10%, it is treated as a
               Garmin artefact and discarded; second-highest is used instead.

    Examples:
      [178, 180, 182, 181, 218] → 218 > 182 * 1.10 → 182  (artefact rejected)
      [178, 182, 185, 188, 190] → 190 ≤ 188 * 1.10 → 190  (credible)
    """
    n = len(observed)
    if n == 0:
        return None
    if n < 3:
        # Single or pair — no outlier protection; return raw max
        return float(max(observed))
    sorted_hr = sorted(observed)
    high = sorted_hr[-1]
    second = sorted_hr[-2]
    if high > second * 1.10:
        return float(second)
    return float(high)


def _resolve_fcmax(
    activities: List[DomainActivity],
    user_max_hr: Optional[float] = None,
    reference_date: Optional[date] = None,
) -> Optional[float]:
    """Resolve FCmax from reliable sources only.

    Priority:
    1. user_max_hr (from user profile/configuration, validated 130–230 bpm)
    2. Robust observed max HR from Garmin activities (credible: 150–230 bpm)
       with outlier protection when n >= 3 observations.
    3. None — no fallback formula

    220-age, hr_max+5, and any formula-derived FCmax are FORBIDDEN.
    """
    if user_max_hr is not None and 130 <= user_max_hr <= 230:
        return float(user_max_hr)

    if activities and reference_date is not None:
        observed = [
            a.max_hr
            for a in activities
            if _validate_activity(a, reference_date)
            and a.max_hr is not None
            and 150 <= a.max_hr <= 230
        ]
        return _resolve_fcmax_robust(observed)

    return None


# ---------------------------------------------------------------------------
# HR-speed model (Source B)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _HRModelResult:
    """Internal result of the HR-speed model."""
    vma_kmh: Optional[float]
    slope: Optional[float]           # a in speed = a*HR + b
    intercept: Optional[float]       # b
    r_squared: Optional[float]
    n_activities: int
    hr_range_bpm: float
    max_observed_hr: float
    target_hr: Optional[float]       # FCmax used for extrapolation
    extrapolation_ratio: float       # target_hr / max_observed_hr
    reason_code: str                 # why null if null


def _fit_hr_speed_model(
    activities: List[DomainActivity],
    reference_date: date,
    user_max_hr: Optional[float] = None,
    resolved_fcmax: Optional[float] = None,
) -> _HRModelResult:
    """Fit a personal HR-speed linear model and extrapolate to aerobic VMA.

    Requirements:
    - >= MIN_ACTIVITIES_HR_MODEL usable activities
    - >= MIN_DISTINCT_HR_LEVELS distinct HR levels
    - HR range >= MIN_HR_RANGE_BPM
    - R² >= MIN_R2
    - Extrapolation ratio <= MAX_EXTRAPOLATION_RATIO

    FCmax: resolved_fcmax when provided, else from user profile or observed max only (no 220-age).
    Extrapolation target: 95% of FCmax (aerobic ceiling, not 100%).
    """
    usable = [a for a in activities if _is_usable_for_hr_model(a, reference_date)]

    null_base = _HRModelResult(
        vma_kmh=None, slope=None, intercept=None, r_squared=None,
        n_activities=len(usable), hr_range_bpm=0.0,
        max_observed_hr=0.0, target_hr=None, extrapolation_ratio=0.0,
        reason_code=REASON_INSUFFICIENT_ACTIVITIES,
    )

    if len(usable) < MIN_ACTIVITIES_HR_MODEL:
        return null_base

    hrs = [a.average_hr for a in usable]  # type: ignore[misc]
    speeds = [_speed_kmh(a) for a in usable]  # type: ignore[misc]

    # HR range check
    hr_min = min(hrs)
    hr_max = max(hrs)
    hr_range = hr_max - hr_min

    if hr_range < MIN_HR_RANGE_BPM:
        return _HRModelResult(
            vma_kmh=None, slope=None, intercept=None, r_squared=None,
            n_activities=len(usable), hr_range_bpm=round(hr_range, 1),
            max_observed_hr=round(hr_max, 1), target_hr=None,
            extrapolation_ratio=0.0, reason_code=REASON_HR_RANGE_INSUFFICIENT,
        )

    # Distinct HR levels check (bin into ~5 bpm buckets)
    bucket_size = 5.0
    buckets = set(int(hr / bucket_size) for hr in hrs)
    if len(buckets) < MIN_DISTINCT_HR_LEVELS:
        return _HRModelResult(
            vma_kmh=None, slope=None, intercept=None, r_squared=None,
            n_activities=len(usable), hr_range_bpm=round(hr_range, 1),
            max_observed_hr=round(hr_max, 1), target_hr=None,
            extrapolation_ratio=0.0, reason_code=REASON_HR_LEVELS_INSUFFICIENT,
        )

    # Linear regression
    a, b, r2 = _linear_regression(hrs, speeds)

    if r2 < MIN_R2:
        return _HRModelResult(
            vma_kmh=None, slope=round(a, 5), intercept=round(b, 4),
            r_squared=round(r2, 4),
            n_activities=len(usable), hr_range_bpm=round(hr_range, 1),
            max_observed_hr=round(hr_max, 1), target_hr=None,
            extrapolation_ratio=0.0, reason_code=REASON_HR_MODEL_POOR_FIT,
        )

    # Slope sanity: speed must increase with HR (positive slope)
    if a <= 0:
        return _HRModelResult(
            vma_kmh=None, slope=round(a, 5), intercept=round(b, 4),
            r_squared=round(r2, 4),
            n_activities=len(usable), hr_range_bpm=round(hr_range, 1),
            max_observed_hr=round(hr_max, 1), target_hr=None,
            extrapolation_ratio=0.0, reason_code=REASON_HR_MODEL_POOR_FIT,
        )

    # FCmax resolution — use pre-resolved value when provided; else from all valid activities
    fcmax = resolved_fcmax if resolved_fcmax is not None else _resolve_fcmax(activities, user_max_hr, reference_date)

    # FCmax is mandatory for extrapolation; no synthetic fallback allowed
    if fcmax is None:
        return _HRModelResult(
            vma_kmh=None, slope=round(a, 5), intercept=round(b, 4),
            r_squared=round(r2, 4),
            n_activities=len(usable), hr_range_bpm=round(hr_range, 1),
            max_observed_hr=round(hr_max, 1), target_hr=None,
            extrapolation_ratio=0.0, reason_code=REASON_NO_FCMAX,
        )

    # Extrapolation target: 95% of FCmax (aerobic ceiling, conservative)
    target_hr = fcmax * 0.95

    extrapolation_ratio = target_hr / hr_max if hr_max > 0 else 999.0

    if extrapolation_ratio > MAX_EXTRAPOLATION_RATIO:
        return _HRModelResult(
            vma_kmh=None, slope=round(a, 5), intercept=round(b, 4),
            r_squared=round(r2, 4),
            n_activities=len(usable), hr_range_bpm=round(hr_range, 1),
            max_observed_hr=round(hr_max, 1), target_hr=round(target_hr, 1),
            extrapolation_ratio=round(extrapolation_ratio, 4),
            reason_code=REASON_EXTRAPOLATION_TOO_LARGE,
        )

    # Predicted speed at target_hr
    predicted_speed = a * target_hr + b

    # Sanity bounds
    if predicted_speed < MIN_SPEED_KMH or predicted_speed > MAX_SPEED_KMH:
        return _HRModelResult(
            vma_kmh=None, slope=round(a, 5), intercept=round(b, 4),
            r_squared=round(r2, 4),
            n_activities=len(usable), hr_range_bpm=round(hr_range, 1),
            max_observed_hr=round(hr_max, 1), target_hr=round(target_hr, 1),
            extrapolation_ratio=round(extrapolation_ratio, 4),
            reason_code=REASON_HR_MODEL_POOR_FIT,
        )

    vma = round(predicted_speed, 2)

    return _HRModelResult(
        vma_kmh=vma, slope=round(a, 5), intercept=round(b, 4),
        r_squared=round(r2, 4),
        n_activities=len(usable), hr_range_bpm=round(hr_range, 1),
        max_observed_hr=round(hr_max, 1), target_hr=round(target_hr, 1),
        extrapolation_ratio=round(extrapolation_ratio, 4),
        reason_code=REASON_HR_SPEED_MODEL_SOURCE,
    )


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def _hr_model_confidence(
    model: _HRModelResult,
    reference_date: date,
    activities: List[DomainActivity],
) -> str:
    """Confidence for HR-speed model result.

    HIGH:   n >= 6, r² >= 0.6, extrapolation <= 1.10, recent data
    MEDIUM: n >= 4, r² >= 0.3, extrapolation <= 1.20
    LOW:    barely valid
    """
    if model.vma_kmh is None:
        return "insufficient"

    # Recency of activities used in model
    usable = [a for a in activities if _is_usable_for_hr_model(a, reference_date)]
    most_recent_days = min(
        (_days_ago(_activity_date(a) or date.min, reference_date) for a in usable),
        default=999,
    )

    n = model.n_activities
    r2 = model.r_squared or 0.0
    ext = model.extrapolation_ratio

    if n >= 6 and r2 >= 0.60 and ext <= 1.10 and most_recent_days <= CONFIDENCE_HIGH_DAYS:
        return "high"
    if n >= 4 and r2 >= 0.40 and ext <= 1.20 and most_recent_days <= CONFIDENCE_MEDIUM_DAYS:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Performance qualification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerformanceQuality:
    qualified: bool
    score: Optional[float]
    confidence: str
    personal_speed_percentile: Optional[float]
    benchmark_count: int
    relative_avg_hr: Optional[float]
    historical_fcmax: Optional[float]
    reason_code: str


def _personal_speed_percentile_90d(
    activity: DomainActivity,
    activities: List[DomainActivity],
    reference_date: date,
) -> Tuple[Optional[float], int]:
    """Return the strictly-prior personal speed percentile and benchmark count."""
    activity_dt = _activity_date(activity)
    current_speed = _speed_kmh(activity)
    if activity_dt is None or current_speed is None or activity_dt > reference_date:
        return None, 0

    cutoff = date.fromordinal(activity_dt.toordinal() - PERSONAL_SPEED_WINDOW_DAYS)
    benchmark_speeds = [
        speed
        for other in _strictly_prior_activities(activity, activities)
        if (other_dt := _activity_date(other)) is not None
        and cutoff <= other_dt
        and _is_road_comparable(other, activity_dt)
        and (speed := _speed_kmh(other)) is not None
    ]
    benchmark_count = len(benchmark_speeds)
    if benchmark_count < MIN_SPEED_BENCHMARK_RUNS:
        return None, benchmark_count

    percentile = (sum(1 for speed in benchmark_speeds if speed <= current_speed) / benchmark_count) * 100.0
    return round(_clamp(percentile, 0.0, 100.0), 4), benchmark_count


def evaluate_performance_quality(
    activity: DomainActivity,
    prior_activities: List[DomainActivity],
    reference_date: date,
    user_max_hr: Optional[float] = None,
) -> PerformanceQuality:
    """Evaluate whether an observed activity is a qualified performance."""
    if not _validate_activity(activity, reference_date):
        return PerformanceQuality(
            qualified=False,
            score=None,
            confidence="insufficient",
            personal_speed_percentile=None,
            benchmark_count=0,
            relative_avg_hr=None,
            historical_fcmax=None,
            reason_code=REASON_PERF_MISSING_DATA,
        )

    if not _is_road_comparable(activity, reference_date):
        return PerformanceQuality(
            qualified=False,
            score=None,
            confidence="insufficient",
            personal_speed_percentile=None,
            benchmark_count=0,
            relative_avg_hr=None,
            historical_fcmax=None,
            reason_code=REASON_PERF_TERRAIN_REJECTED,
        )

    activity_dt = _activity_date(activity)
    if activity_dt is None:
        return PerformanceQuality(
            qualified=False,
            score=None,
            confidence="insufficient",
            personal_speed_percentile=None,
            benchmark_count=0,
            relative_avg_hr=None,
            historical_fcmax=None,
            reason_code=REASON_PERF_MISSING_DATA,
        )

    speed_percentile, benchmark_count = _personal_speed_percentile_90d(
        activity, prior_activities, reference_date
    )
    strictly_prior_activities = _strictly_prior_activities(activity, prior_activities)
    historical_fcmax = _resolve_fcmax(strictly_prior_activities, user_max_hr, activity_dt)
    relative_avg_hr: Optional[float] = None
    if activity.average_hr is not None and historical_fcmax is not None and historical_fcmax > 0:
        relative_avg_hr = round(activity.average_hr / historical_fcmax, 4)

    if speed_percentile is None:
        return PerformanceQuality(
            qualified=False,
            score=None,
            confidence="insufficient",
            personal_speed_percentile=None,
            benchmark_count=benchmark_count,
            relative_avg_hr=relative_avg_hr,
            historical_fcmax=historical_fcmax,
            reason_code=REASON_PERF_NO_SPEED_BENCHMARK,
        )

    speed_component = _clamp(speed_percentile / 100.0, 0.0, 1.0)

    if relative_avg_hr is None:
        score = round(speed_component, 4)
        qualified = (
            benchmark_count >= MIN_SPEED_BENCHMARK_RUNS
            and speed_percentile >= PERFORMANCE_NO_HR_MIN_SPEED_PERCENTILE
        )
        return PerformanceQuality(
            qualified=qualified,
            score=score,
            confidence="low" if qualified else "insufficient",
            personal_speed_percentile=speed_percentile,
            benchmark_count=benchmark_count,
            relative_avg_hr=None,
            historical_fcmax=historical_fcmax,
            reason_code=(
                REASON_PERF_QUALIFIED_SPEED_ONLY if qualified else REASON_PERF_SPEED_TOO_LOW
            ),
        )

    hr_component = _clamp(
        (relative_avg_hr - PERFORMANCE_HR_COMPONENT_FLOOR)
        / (PERFORMANCE_HR_COMPONENT_CEILING - PERFORMANCE_HR_COMPONENT_FLOOR),
        0.0,
        1.0,
    )
    score = round(
        PERFORMANCE_HR_WEIGHT * hr_component
        + PERFORMANCE_SPEED_WEIGHT * speed_component,
        4,
    )

    if speed_percentile < PERFORMANCE_MIN_SPEED_PERCENTILE_WITH_HR:
        reason_code = REASON_PERF_SPEED_TOO_LOW
        qualified = False
    elif relative_avg_hr < PERFORMANCE_MIN_RELATIVE_HR:
        reason_code = REASON_PERF_RELATIVE_HR_TOO_LOW
        qualified = False
    elif score < PERFORMANCE_SCORE_THRESHOLD:
        reason_code = REASON_PERF_SCORE_TOO_LOW
        qualified = False
    else:
        reason_code = REASON_PERF_QUALIFIED_HR_SPEED
        qualified = True

    confidence = "insufficient"
    if qualified:
        confidence = (
            "high"
            if (
                score >= PERFORMANCE_HIGH_CONFIDENCE_SCORE
                and relative_avg_hr >= PERFORMANCE_HIGH_CONFIDENCE_RELATIVE_HR
                and speed_percentile >= PERFORMANCE_HIGH_CONFIDENCE_SPEED_PERCENTILE
            )
            else "medium"
        )

    return PerformanceQuality(
        qualified=qualified,
        score=score,
        confidence=confidence,
        personal_speed_percentile=speed_percentile,
        benchmark_count=benchmark_count,
        relative_avg_hr=relative_avg_hr,
        historical_fcmax=historical_fcmax,
        reason_code=reason_code,
    )


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VMAEstimate:
    """VMA estimation result.

    vma_kmh=None means insufficient data to estimate.
    """
    vma_kmh: Optional[float]
    confidence: str              # "high" | "medium" | "low" | "insufficient"
    method: Optional[str]
    source_activity_date: Optional[date]
    source_distance_m: Optional[float]
    source_duration_s: Optional[float]
    reason_code: str = REASON_NO_DATA
    # HR-speed model details (None when not used)
    hr_model_r_squared: Optional[float] = None
    hr_model_n_activities: int = 0
    hr_model_hr_range_bpm: float = 0.0
    hr_model_extrapolation_ratio: float = 0.0
    model_version: str = "v2"

    @property
    def has_data(self) -> bool:
        return self.vma_kmh is not None


@dataclass(frozen=True)
class RacePrediction:
    """Predicted race time for a single distance."""
    distance_label: str
    distance_km: float
    predicted_time_s: Optional[float]
    predicted_time_str: Optional[str]
    predicted_pace_str: Optional[str]
    confidence: str
    readiness: str
    readiness_label: str
    readiness_color: str
    readiness_score: int
    endurance_factor: int
    volume_factor: int
    source_distance_m: Optional[float]
    source_type: Optional[str] = None   # "observed_activity" when from real data
    source_quality_score: Optional[float] = None
    source_quality_confidence: Optional[str] = None
    source_speed_percentile: Optional[float] = None
    source_relative_hr: Optional[float] = None
    extrapolation_ratio: Optional[float] = None
    curve_method: Optional[str] = None
    curve_k: Optional[float] = None
    contributors_count: int = 0
    model_version: str = "v2"


@dataclass
class PerformanceEstimate:
    """Top-level result for a user snapshot."""
    has_data: bool
    vma: VMAEstimate
    predictions: List[RacePrediction] = field(default_factory=list)
    athlete_profile: dict = field(default_factory=dict)
    race_curve_diagnostics: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "v2"


# ---------------------------------------------------------------------------
# VMA window helper
# ---------------------------------------------------------------------------


def _activities_in_vma_window(
    activities: List[DomainActivity],
    reference_date: date,
    window_days: int = VMA_WINDOW_DAYS,
) -> List[DomainActivity]:
    """Return activities within [reference_date - (window_days-1), reference_date].

    Window is inclusive on both ends.  A window_days of 42 covers days 0..41,
    i.e. [reference_date - 41 days, reference_date].
    """
    window_start = date.fromordinal(reference_date.toordinal() - (window_days - 1))
    return [
        a for a in activities
        if (_activity_date(a) or date.min) >= window_start
        and (_activity_date(a) or date.max) <= reference_date
    ]


# ---------------------------------------------------------------------------
# VMA estimation — dual-path
# ---------------------------------------------------------------------------


def estimate_vma(
    activities: List[DomainActivity],
    reference_date: Union[date, datetime],
    user_max_hr: Optional[float] = None,
) -> VMAEstimate:
    """Estimate VMA from DomainActivity objects using the HR-speed model.

    SOURCE A (explicit performance) is DISABLED — no Garmin field currently
    identifies a race/test/competition.  Only SOURCE B (HR-speed linear model)
    is used.

    The model is fitted on activities within the VMA_WINDOW_DAYS (42-day) rolling
    window ending at reference_date.  No look-ahead; no fallback to older data.

    FCmax is resolved from the same 42-day window as the model activities.
    This ensures that estimate_vma(all_activities, ref) ==
    estimate_vma(_activities_in_vma_window(all_activities, ref), ref),
    making CURRENT and HISTORY snapshots strictly identical.

    Returns VMAEstimate(vma_kmh=None) when the model yields insufficient data.

    220-age and hr_max+5 are forbidden.
    """
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    # Apply 42-day VMA window for model fitting
    windowed = _activities_in_vma_window(activities, reference_date)

    # FCmax resolved from the same 42-day window used for the model.
    # Using the identical window for both ensures CURRENT == HISTORY snapshots
    # are strictly deterministic: an activity outside the window cannot influence
    # the FCmax used by the extrapolation step.
    fcmax = _resolve_fcmax(windowed, user_max_hr, reference_date)

    # --- Source A: DISABLED ---
    # SOURCE_A_DISABLED = True: no Garmin field identifies explicit performances.

    # --- Source B: HR-speed model (windowed activities, pre-resolved FCmax) ---
    hr_model = _fit_hr_speed_model(windowed, reference_date, user_max_hr, resolved_fcmax=fcmax)
    vma_b: Optional[float] = hr_model.vma_kmh
    conf_b: Optional[str] = (
        _hr_model_confidence(hr_model, reference_date, windowed)
        if vma_b is not None else None
    )
    method_b: Optional[str] = (
        f"hr_speed_model_n{hr_model.n_activities}_r2{hr_model.r_squared:.2f}"
        if vma_b is not None and hr_model.r_squared is not None else None
    )

    if vma_b is None:
        reason = hr_model.reason_code if hr_model.reason_code else REASON_NO_DATA
        return VMAEstimate(
            vma_kmh=None,
            confidence="insufficient",
            method=None,
            source_activity_date=None,
            source_distance_m=None,
            source_duration_s=None,
            reason_code=reason,
            hr_model_n_activities=hr_model.n_activities,
            hr_model_hr_range_bpm=hr_model.hr_range_bpm,
        )

    return VMAEstimate(
        vma_kmh=vma_b,
        confidence=conf_b or "low",
        method=method_b,
        source_activity_date=None,
        source_distance_m=None,
        source_duration_s=None,
        reason_code=REASON_HR_SPEED_MODEL_SOURCE,
        hr_model_r_squared=hr_model.r_squared,
        hr_model_n_activities=hr_model.n_activities,
        hr_model_hr_range_bpm=hr_model.hr_range_bpm,
        hr_model_extrapolation_ratio=hr_model.extrapolation_ratio,
    )


# ---------------------------------------------------------------------------
# Endurance support
# ---------------------------------------------------------------------------


def _endurance_support(
    activities: List[DomainActivity],
    reference_date: date,
    target_distance_m: float,
    window_days: int = 90,
) -> float:
    """Return an endurance adjustment factor in [0.55, 1.0].

    Uses relative signals from the athlete's own history:
    - Recent weekly volume (last 28 days)
    - Longest single run in the window

    Monotone, bounded, documented.
    """
    cutoff = date.fromordinal(reference_date.toordinal() - window_days)
    recent = [
        a for a in activities
        if _validate_activity(a, reference_date)
        and (_activity_date(a) or date.min) >= cutoff
    ]

    if not recent:
        return 0.55   # lower bound of the [0.55, 1.0] contract

    cutoff_28 = date.fromordinal(reference_date.toordinal() - 28)
    recent_28 = [a for a in recent if (_activity_date(a) or date.min) >= cutoff_28]
    weekly_km = sum((a.distance_m or 0) for a in recent_28) / 1000.0 / 4.0

    max_run_m = max((a.distance_m or 0) for a in recent)

    if target_distance_m <= 10_000:
        return 1.0

    ratio = min(max_run_m / target_distance_m, 1.0)
    target_km = target_distance_m / 1000.0
    vol_ratio = min(weekly_km / max(target_km * 0.5, 1.0), 1.0)

    raw = ratio * 0.6 + vol_ratio * 0.4
    support = 0.55 + raw * 0.45
    return round(min(max(support, 0.55), 1.0), 4)


# ---------------------------------------------------------------------------
# Riegel extrapolation
# ---------------------------------------------------------------------------


def _riegel(t1_s: float, d1_m: float, d2_m: float, k: float = RIEGEL_K) -> float:
    if d1_m <= 0 or d2_m <= 0 or t1_s <= 0:
        raise ValueError("All values must be positive")
    return t1_s * (d2_m / d1_m) ** k


def _riegel_confidence(
    source_distance_m: float,
    target_distance_m: float,
    days_since_source: int,
    endurance_factor: float,
    performance_quality_score: Optional[float] = None,
    performance_quality_confidence: str = "insufficient",
) -> str:
    """Confidence for a Riegel prediction.

    Confidence depends on:
      - source proximity to target
      - source recency
      - endurance support
      - qualified performance quality

    A speed-only source (no HR) is capped at MEDIUM.
    """
    ratio = target_distance_m / source_distance_m
    if ratio > 4.0 or days_since_source > CONFIDENCE_LOW_DAYS or endurance_factor < 0.65:
        base_confidence = "low"
    elif ratio > 2.0 or days_since_source > CONFIDENCE_MEDIUM_DAYS or endurance_factor < 0.80:
        base_confidence = "medium"
    else:
        base_confidence = "high"

    if performance_quality_score is None or performance_quality_confidence == "insufficient":
        return "low"

    if performance_quality_confidence == "low":
        if base_confidence == "low":
            return "low"
        return "medium"

    if (
        base_confidence == "high"
        and performance_quality_confidence == "high"
        and performance_quality_score >= PERFORMANCE_HIGH_CONFIDENCE_SCORE
    ):
        return "high"

    if base_confidence == "high":
        return "medium"
    return base_confidence


def _seconds_to_str(total_s: float) -> str:
    total_s = round(total_s)
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = int(total_s % 60)
    if h > 0:
        return f"{h}h{m:02d}"
    return f"{m}:{s:02d}"


def _pace_str(total_s: float, distance_m: float) -> str:
    pace_s_per_km = total_s / (distance_m / 1000.0)
    pm = int(pace_s_per_km // 60)
    ps = int(pace_s_per_km % 60)
    return f"{pm}:{ps:02d}/km"


def _readiness(score: float) -> tuple:
    if score >= 0.80:
        return "ready", "Prêt", "#22c55e"
    if score >= 0.60:
        return "possible", "Possible", "#f59e0b"
    if score >= 0.40:
        return "challenging", "Ambitieux", "#f97316"
    return "not_ready", "Pas prêt", "#ef4444"


# ---------------------------------------------------------------------------
# Per-target Riegel source selection
# ---------------------------------------------------------------------------


def _score_riegel_candidate(
    a: DomainActivity,
    target_distance_m: float,
    reference_date: date,
    quality: PerformanceQuality,
) -> float:
    """Score an activity as a Riegel road-prediction source for a given target.

    Returns a score in [0, 1].  Higher = more informative for this target.
    Returns 0.0 when the activity is not a defensible source.

    Hard exclusions (return 0.0):
      - activity is not a qualified performance
      - distance < MIN_RIEGEL_SOURCE_RATIO * target_distance
      - activity older than MAX_RIEGEL_SOURCE_AGE_DAYS

    Weights (for eligible activities):
      proximity  0.50  — how close source distance is to target
      recency    0.20  — how recent the activity is
      quality    0.30  — how strong the qualified effort is
    """
    if not quality.qualified or quality.score is None:
        return 0.0
    if not _is_road_comparable(a, reference_date):
        return 0.0

    src_dist = a.distance_m or 0.0
    if src_dist < max(MIN_DISTANCE_M, target_distance_m * MIN_RIEGEL_SOURCE_RATIO):
        return 0.0

    d = _activity_date(a)
    if d is None:
        return 0.0
    days = _days_ago(d, reference_date)
    if days > MAX_RIEGEL_SOURCE_AGE_DAYS:
        return 0.0

    # Proximity: prefer source ≈ target (ratio approaching 1.0 from below is ideal)
    ratio = src_dist / target_distance_m
    if ratio >= 1.2:
        proximity = 0.50   # source longer than target — acceptable but not ideal
    elif ratio >= 0.50:
        proximity = 0.70 + 0.30 * min((ratio - 0.50) / 0.50, 1.0)
    elif ratio >= 0.20:
        proximity = 0.30 + 0.40 * (ratio - 0.20) / 0.30
    else:
        proximity = 0.10 + 0.20 * ratio / 0.20   # very short relative to target

    # Recency
    if days <= CONFIDENCE_HIGH_DAYS:
        recency = 1.0
    elif days <= CONFIDENCE_MEDIUM_DAYS:
        recency = 0.70
    elif days <= CONFIDENCE_LOW_DAYS:
        recency = 0.40
    else:
        recency = 0.15   # old but within MAX_RIEGEL_SOURCE_AGE_DAYS

    score = proximity * 0.50 + recency * 0.20 + quality.score * 0.30
    return round(score, 4)


def _build_qualified_performance_pool(
    activities: List[DomainActivity],
    reference_date: date,
    user_max_hr: Optional[float] = None,
) -> List[Tuple[DomainActivity, PerformanceQuality]]:
    return [
        (activity, quality)
        for activity in activities
        if _validate_activity(activity, reference_date)
        for quality in [evaluate_performance_quality(activity, activities, reference_date, user_max_hr)]
        if quality.qualified
    ]


def _select_riegel_source(
    qualified_pool: List[Tuple[DomainActivity, PerformanceQuality]],
    reference_date: date,
    target_distance_m: float,
) -> Optional[Tuple[DomainActivity, float, PerformanceQuality]]:
    """Select the best observed activity as Riegel source for a given target.

    Returns (activity, source_score, quality) or None when no defensible source exists.
    """
    if not qualified_pool:
        return None

    best_score = 0.0
    best_act: Optional[DomainActivity] = None
    best_quality: Optional[PerformanceQuality] = None
    for a, quality in qualified_pool:
        s = _score_riegel_candidate(
            a,
            target_distance_m,
            reference_date,
            quality=quality,
        )
        if s > best_score:
            best_score = s
            best_act = a
            best_quality = quality

    if best_act is None or best_score < MIN_RIEGEL_SCORE:
        return None

    return best_act, best_score, best_quality


# ---------------------------------------------------------------------------
# Race predictions V2
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CurveObservation:
    activity: DomainActivity
    quality: PerformanceQuality
    distance_m: float
    duration_s: float
    days_ago: int
    base_weight: float
    robust_weight: float


@dataclass(frozen=True)
class _CurveModel:
    method: str
    a: float
    k: float
    fit_quality: Optional[float]
    k_conflict: bool
    k_fallback_applied: bool
    k_raw: Optional[float]
    two_point_evidence_strength: Optional[float]
    qualified_performance_count: int
    contributors: Tuple[_CurveObservation, ...]
    observed_distance_min: float
    observed_distance_max: float


def _recency_weight(days_ago: int) -> float:
    if days_ago <= CONFIDENCE_HIGH_DAYS:
        return 1.0
    if days_ago <= CONFIDENCE_MEDIUM_DAYS:
        return 0.85
    if days_ago <= CONFIDENCE_LOW_DAYS:
        return 0.70
    if days_ago <= MAX_RIEGEL_SOURCE_AGE_DAYS:
        return 0.55
    return 0.0


def _quality_confidence_weight(confidence: str) -> float:
    if confidence == "high":
        return 1.0
    if confidence == "medium":
        return 0.90
    if confidence == "low":
        return 0.75
    return 0.0


def _weighted_linear_fit(
    xs: List[float],
    ys: List[float],
    ws: List[float],
) -> Optional[Tuple[float, float]]:
    sum_w = sum(ws)
    if sum_w <= 0:
        return None
    x_bar = sum(w * x for x, w in zip(xs, ws)) / sum_w
    y_bar = sum(w * y for y, w in zip(ys, ws)) / sum_w
    s_xx = sum(w * (x - x_bar) ** 2 for x, w in zip(xs, ws))
    if s_xx <= 0:
        return None
    s_xy = sum(w * (x - x_bar) * (y - y_bar) for x, y, w in zip(xs, ys, ws))
    slope = s_xy / s_xx
    intercept = y_bar - slope * x_bar
    if not math.isfinite(intercept) or not math.isfinite(slope):
        return None
    return intercept, slope


def _weighted_r2(
    xs: List[float],
    ys: List[float],
    ws: List[float],
    intercept: float,
    slope: float,
) -> Optional[float]:
    sum_w = sum(ws)
    if sum_w <= 0:
        return None
    y_bar = sum(w * y for y, w in zip(ys, ws)) / sum_w
    ss_tot = sum(w * (y - y_bar) ** 2 for y, w in zip(ys, ws))
    if ss_tot <= 0:
        return 1.0
    ss_res = sum(w * (y - (intercept + slope * x)) ** 2 for x, y, w in zip(xs, ys, ws))
    return round(_clamp(1.0 - ss_res / ss_tot, 0.0, 1.0), 4)


def _fixed_slope_log_intercept(
    xs: List[float],
    ys: List[float],
    ws: List[float],
    slope: float,
) -> Optional[float]:
    sum_w = sum(ws)
    if sum_w <= 0:
        return None
    intercept = sum(w * (y - slope * x) for x, y, w in zip(xs, ys, ws)) / sum_w
    if not math.isfinite(intercept):
        return None
    return intercept


def _two_point_evidence_strength(ws: List[float]) -> float:
    """Return deterministic evidence strength in [0, 1] for N==2 shrinkage."""
    if len(ws) != 2:
        return 0.0
    w1 = _clamp(ws[0], 0.0, 1.0)
    w2 = _clamp(ws[1], 0.0, 1.0)
    return round(_clamp(math.sqrt(w1 * w2), 0.0, 1.0), 6)


def _build_performance_curve(
    qualified_pool: List[Tuple[DomainActivity, PerformanceQuality]],
    reference_date: date,
) -> Optional[_CurveModel]:
    observations: List[_CurveObservation] = []
    for activity, quality in qualified_pool:
        dist = activity.distance_m or 0.0
        dur = _performance_duration_s(activity) or 0.0
        act_date = _activity_date(activity)
        if dist <= 0 or dur <= 0 or act_date is None:
            continue
        days_ago = _days_ago(act_date, reference_date)
        if days_ago < 0 or days_ago > MAX_RIEGEL_SOURCE_AGE_DAYS:
            continue
        recency_w = _recency_weight(days_ago)
        quality_score = _clamp(quality.score or 0.0, 0.0, 1.0)
        conf_w = _quality_confidence_weight(quality.confidence)
        base_weight = round(quality_score * recency_w * conf_w, 6)
        if base_weight <= 0:
            continue
        observations.append(
            _CurveObservation(
                activity=activity,
                quality=quality,
                distance_m=dist,
                duration_s=dur,
                days_ago=days_ago,
                base_weight=base_weight,
                robust_weight=base_weight,
            )
        )

    if not observations:
        return None

    observations = sorted(
        observations,
        key=lambda o: (o.days_ago, o.distance_m, o.duration_s),
    )
    obs_distances = [o.distance_m for o in observations]

    if len(observations) == 1:
        obs = observations[0]
        a = obs.duration_s / (obs.distance_m ** RIEGEL_K)
        return _CurveModel(
            method="single_performance_riegel",
            a=a,
            k=RIEGEL_K,
            fit_quality=1.0,
            k_conflict=False,
            k_fallback_applied=False,
            k_raw=RIEGEL_K,
            two_point_evidence_strength=None,
            qualified_performance_count=len(qualified_pool),
            contributors=(obs,),
            observed_distance_min=min(obs_distances),
            observed_distance_max=max(obs_distances),
        )

    xs = [math.log(o.distance_m) for o in observations]
    ys = [math.log(o.duration_s) for o in observations]
    base_ws = [o.base_weight for o in observations]
    fit = _weighted_linear_fit(xs, ys, base_ws)
    if fit is None:
        sum_w = sum(base_ws)
        if sum_w <= 0:
            return None
        representative_distance = sum(w * o.distance_m for o, w in zip(observations, base_ws)) / sum_w
        representative_duration = sum(w * o.duration_s for o, w in zip(observations, base_ws)) / sum_w
        if representative_distance <= 0 or representative_duration <= 0:
            return None
        a = representative_duration / (representative_distance ** RIEGEL_K)
        return _CurveModel(
            method="same_distance_prior_k_fallback",
            a=a,
            k=RIEGEL_K,
            fit_quality=None,
            k_conflict=False,
            k_fallback_applied=False,
            k_raw=None,
            two_point_evidence_strength=None,
            qualified_performance_count=len(qualified_pool),
            contributors=tuple(observations),
            observed_distance_min=min(obs_distances),
            observed_distance_max=max(obs_distances),
        )
    intercept, slope = fit

    method = "weighted_log_fit"
    robust_ws = list(base_ws)
    two_point_evidence_strength: Optional[float] = None
    k_raw: Optional[float] = slope
    if len(observations) == 2:
        method = "two_point_prior_shrinkage_fit"
        two_point_evidence_strength = _two_point_evidence_strength(base_ws)
        slope = RIEGEL_K + two_point_evidence_strength * (slope - RIEGEL_K)
        fixed_intercept = _fixed_slope_log_intercept(xs, ys, robust_ws, slope)
        if fixed_intercept is None:
            return None
        intercept = fixed_intercept
    elif len(observations) >= 3:
        method = "robust_weighted_log_fit"
        for _ in range(2):
            robust_fit = _weighted_linear_fit(xs, ys, robust_ws)
            if robust_fit is None:
                break
            r_intercept, r_slope = robust_fit
            residuals = [y - (r_intercept + r_slope * x) for x, y in zip(xs, ys)]
            abs_res = sorted(abs(r) for r in residuals)
            median_abs = abs_res[len(abs_res) // 2]
            if median_abs <= 1e-9:
                intercept, slope = r_intercept, r_slope
                break
            delta = 1.5 * median_abs
            updated_ws = []
            for base_w, residual in zip(base_ws, residuals):
                abs_r = abs(residual)
                huber_mult = 1.0 if abs_r <= delta else (delta / abs_r)
                updated_ws.append(base_w * huber_mult)
            robust_ws = updated_ws
        final_robust_fit = _weighted_linear_fit(xs, ys, robust_ws)
        if final_robust_fit is not None:
            intercept, slope = final_robust_fit
            k_raw = slope

    k_fallback_applied = False
    k_conflict = not (CURVE_K_MIN <= slope <= CURVE_K_MAX)
    if k_conflict:
        # Contradictory observations: keep a coherent prior curve and lower trust.
        log_a = _fixed_slope_log_intercept(xs, ys, robust_ws, RIEGEL_K)
        if log_a is None:
            return None
        intercept = log_a
        slope = RIEGEL_K
        method = "prior_k_conflict_fallback"
        robust_ws = [w * CURVE_K_CONFLICT_WEIGHT_PENALTY for w in robust_ws]
        k_fallback_applied = True

    fit_quality = _weighted_r2(xs, ys, robust_ws, intercept, slope)
    max_w = max(robust_ws) if robust_ws else 0.0
    contributors = tuple(
        _CurveObservation(
            activity=o.activity,
            quality=o.quality,
            distance_m=o.distance_m,
            duration_s=o.duration_s,
            days_ago=o.days_ago,
            base_weight=o.base_weight,
            robust_weight=rw,
        )
        for o, rw in zip(observations, robust_ws)
        if max_w > 0 and rw >= max_w * 0.05
    )
    if not contributors:
        contributors = tuple(
            _CurveObservation(
                activity=o.activity,
                quality=o.quality,
                distance_m=o.distance_m,
                duration_s=o.duration_s,
                days_ago=o.days_ago,
                base_weight=o.base_weight,
                robust_weight=rw,
            )
            for o, rw in zip(observations, robust_ws)
        )

    return _CurveModel(
        method=method,
        a=math.exp(intercept),
        k=slope,
        fit_quality=fit_quality,
        k_conflict=k_conflict,
        k_fallback_applied=k_fallback_applied,
        k_raw=k_raw,
        two_point_evidence_strength=two_point_evidence_strength,
        qualified_performance_count=len(qualified_pool),
        contributors=contributors,
        observed_distance_min=min(obs_distances),
        observed_distance_max=max(obs_distances),
    )


def _curve_time_s(curve: _CurveModel, distance_m: float) -> float:
    return curve.a * (distance_m ** curve.k)


def _symmetric_extrapolation_ratio(target_distance_m: float, observed_distances_m: List[float]) -> Optional[float]:
    if target_distance_m <= 0 or not observed_distances_m:
        return None
    ratios = [
        max(target_distance_m / observed, observed / target_distance_m)
        for observed in observed_distances_m
        if observed > 0
    ]
    if not ratios:
        return None
    return round(min(ratios), 4)


def _degrade_confidence(confidence: str, steps: int = 1) -> str:
    order = ["insufficient", "low", "medium", "high"]
    idx = order.index(confidence) if confidence in order else 0
    return order[max(0, idx - steps)]


def _curve_prediction_confidence(
    curve: _CurveModel,
    extrapolation_ratio: Optional[float],
) -> str:
    if extrapolation_ratio is None:
        return "insufficient"
    if extrapolation_ratio > CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO:
        return "insufficient"
    if extrapolation_ratio > 3.0:
        base = "low"
    elif extrapolation_ratio > 1.8:
        base = "medium"
    else:
        base = "high"

    if curve.k_conflict:
        base = _degrade_confidence(base, 1)

    if curve.fit_quality is not None and curve.fit_quality < 0.4:
        base = _degrade_confidence(base, 1)
    elif curve.fit_quality is not None and curve.fit_quality < 0.7:
        base = _degrade_confidence(base, 1)

    if curve.contributors:
        if len(curve.contributors) == 1 and base == "high":
            base = "medium"
        days = min(c.days_ago for c in curve.contributors)
        if days > CONFIDENCE_LOW_DAYS:
            base = _degrade_confidence(base, 1)
        best_quality_conf = max(
            (_quality_confidence_weight(c.quality.confidence) for c in curve.contributors),
            default=0.0,
        )
        if best_quality_conf < _quality_confidence_weight("medium"):
            base = _degrade_confidence(base, 1)

    return base


def _null_prediction(
    label: str,
    target_km: float,
    endurance: float,
    vol_factor: float,
    source_distance_m: Optional[float] = None,
    source_type: Optional[str] = None,
    source_quality_score: Optional[float] = None,
    source_quality_confidence: Optional[str] = None,
    source_speed_percentile: Optional[float] = None,
    source_relative_hr: Optional[float] = None,
    extrapolation_ratio: Optional[float] = None,
    curve_method: Optional[str] = None,
    curve_k: Optional[float] = None,
    contributors_count: int = 0,
) -> RacePrediction:
    return RacePrediction(
        distance_label=label,
        distance_km=target_km,
        predicted_time_s=None,
        predicted_time_str=None,
        predicted_pace_str=None,
        confidence="insufficient",
        readiness="not_ready",
        readiness_label="Pas prêt",
        readiness_color="#ef4444",
        readiness_score=0,
        endurance_factor=round(endurance * 100),
        volume_factor=round(vol_factor * 100),
        source_distance_m=source_distance_m,
        source_type=source_type,
        source_quality_score=source_quality_score,
        source_quality_confidence=source_quality_confidence,
        source_speed_percentile=source_speed_percentile,
        source_relative_hr=source_relative_hr,
        extrapolation_ratio=extrapolation_ratio,
        curve_method=curve_method,
        curve_k=curve_k,
        contributors_count=contributors_count,
    )


def predict_races(
    activities: List[DomainActivity],
    reference_date: Union[date, datetime],
    user_max_hr: Optional[float] = None,
) -> PerformanceEstimate:
    """Compute VMA V2 estimate and race predictions V2.

    VMA is estimated via the HR-speed model (SOURCE A is disabled).

    Race predictions use only #188-qualified observed performances and one
    shared time-distance curve for all targets.
    No synthetic effort is ever created.

    If no defensible observed source exists for a target distance, the
    prediction for that distance is null (predicted_time_s = None).
    VMA and race predictions are independent: VMA can be available while
    some or all predictions are null.
    """
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    vma_est = estimate_vma(activities, reference_date, user_max_hr)

    # VMA and predictions are INDEPENDENT.
    # Do NOT return early when VMA is null — predictions may still exist from
    # observed Riegel sources.

    # Weekly volume & long run for athlete profile
    cutoff_28 = date.fromordinal(reference_date.toordinal() - 28)
    recent_28 = [
        a for a in activities
        if _validate_activity(a, reference_date)
        and (_activity_date(a) or date.min) >= cutoff_28
    ]
    weekly_km = sum((a.distance_m or 0) for a in recent_28) / 1000.0 / 4.0
    all_valid = [a for a in activities if _validate_activity(a, reference_date)]
    max_long_run_m = max((a.distance_m or 0) for a in all_valid) if all_valid else 0.0

    predictions: List[RacePrediction] = []
    qualified_pool = _build_qualified_performance_pool(activities, reference_date, user_max_hr)
    curve = _build_performance_curve(qualified_pool, reference_date)

    sorted_contributors = sorted(
        curve.contributors if curve else (),
        key=lambda c: (-c.robust_weight, c.days_ago, c.distance_m),
    )
    primary = sorted_contributors[0] if sorted_contributors else None
    observed_distances = [c.distance_m for c in sorted_contributors]
    source_type = "observed_activity" if (curve and len(sorted_contributors) == 1) else (
        "performance_curve_v2" if curve else None
    )

    for label, dist_m in RACE_DISTANCES_M.items():
        endurance = _endurance_support(activities, reference_date, dist_m)
        target_km = dist_m / 1000.0
        vol_factor = min(weekly_km / max(target_km * 0.5, 1.0), 1.0)

        if curve is None:
            predictions.append(_null_prediction(
                label=label,
                target_km=target_km,
                endurance=endurance,
                vol_factor=vol_factor,
            ))
            continue

        extrapolation_ratio = _symmetric_extrapolation_ratio(dist_m, observed_distances)
        if extrapolation_ratio is None or extrapolation_ratio > CURVE_MAX_EXTRAPOLATION_RATIO:
            predictions.append(_null_prediction(
                label=label,
                target_km=target_km,
                endurance=endurance,
                vol_factor=vol_factor,
                source_distance_m=primary.distance_m if primary else None,
                source_type=source_type,
                source_quality_score=primary.quality.score if primary else None,
                source_quality_confidence=primary.quality.confidence if primary else None,
                source_speed_percentile=(
                    primary.quality.personal_speed_percentile if primary else None
                ),
                source_relative_hr=primary.quality.relative_avg_hr if primary else None,
                extrapolation_ratio=extrapolation_ratio,
                curve_method=curve.method,
                curve_k=round(curve.k, 4),
                contributors_count=len(sorted_contributors),
            ))
            continue

        try:
            raw_time_s = _curve_time_s(curve, dist_m)
        except (ValueError, ZeroDivisionError):
            predictions.append(_null_prediction(
                label=label,
                target_km=target_km,
                endurance=endurance,
                vol_factor=vol_factor,
                source_distance_m=primary.distance_m if primary else None,
                source_type=source_type,
                source_quality_score=primary.quality.score if primary else None,
                source_quality_confidence=primary.quality.confidence if primary else None,
                source_speed_percentile=(
                    primary.quality.personal_speed_percentile if primary else None
                ),
                source_relative_hr=primary.quality.relative_avg_hr if primary else None,
                extrapolation_ratio=extrapolation_ratio,
                curve_method=curve.method,
                curve_k=round(curve.k, 4),
                contributors_count=len(sorted_contributors),
            ))
            continue

        readiness_score_raw = endurance * 0.6 + vol_factor * 0.4
        r_key, r_label, r_color = _readiness(readiness_score_raw)
        conf = _curve_prediction_confidence(curve, extrapolation_ratio)

        predictions.append(RacePrediction(
            distance_label=label,
            distance_km=target_km,
            predicted_time_s=round(raw_time_s, 1),
            predicted_time_str=_seconds_to_str(raw_time_s),
            predicted_pace_str=_pace_str(raw_time_s, dist_m),
            confidence=conf,
            readiness=r_key,
            readiness_label=r_label,
            readiness_color=r_color,
            readiness_score=round(readiness_score_raw * 100),
            endurance_factor=round(endurance * 100),
            volume_factor=round(vol_factor * 100),
            source_distance_m=primary.distance_m if primary else None,
            source_type=source_type,
            source_quality_score=primary.quality.score if primary else None,
            source_quality_confidence=primary.quality.confidence if primary else None,
            source_speed_percentile=(
                primary.quality.personal_speed_percentile if primary else None
            ),
            source_relative_hr=primary.quality.relative_avg_hr if primary else None,
            extrapolation_ratio=extrapolation_ratio,
            curve_method=curve.method,
            curve_k=round(curve.k, 4),
            contributors_count=len(sorted_contributors),
        ))

    vo2max_estimated: Optional[float] = None
    if vma_est.vma_kmh is not None:
        vo2max_estimated = round(vma_est.vma_kmh * 3.5, 1)

    athlete_profile = {
        "weekly_km": round(weekly_km, 1),
        "max_long_run_km": round(max_long_run_m / 1000.0, 1),
        "estimated_vma": vma_est.vma_kmh,
        "estimated_vo2max": vo2max_estimated,
        "vo2max_note": "Derived estimate (VMA × 3.5). Not a lab or Garmin measurement.",
        "vma_method": vma_est.method,
        "vma_confidence": vma_est.confidence,
        "vma_reason_code": vma_est.reason_code,
        "calculation_window": "garmin_activities (all available)",
        "model_version": "v2",
    }

    # has_data = True when VMA is available OR at least one prediction has a time
    has_any_prediction = any(p.predicted_time_s is not None for p in predictions)
    result_has_data = vma_est.has_data or has_any_prediction

    return PerformanceEstimate(
        has_data=result_has_data,
        vma=vma_est,
        predictions=predictions,
        athlete_profile=athlete_profile,
        race_curve_diagnostics={
            "curve_method": curve.method if curve else None,
            "curve_a": round(curve.a, 8) if curve else None,
            "curve_k": round(curve.k, 6) if curve else None,
            "curve_k_raw": round(curve.k_raw, 6) if (curve and curve.k_raw is not None) else None,
            "curve_k_prior": RIEGEL_K if curve else None,
            "curve_k_min": CURVE_K_MIN if curve else None,
            "curve_k_max": CURVE_K_MAX if curve else None,
            "k_fallback_applied": curve.k_fallback_applied if curve else None,
            "two_point_evidence_strength": (
                curve.two_point_evidence_strength if curve else None
            ),
            "qualified_performance_count": curve.qualified_performance_count if curve else 0,
            "contributors_count": len(sorted_contributors),
            "observed_distance_min": curve.observed_distance_min if curve else None,
            "observed_distance_max": curve.observed_distance_max if curve else None,
            "observed_distance_min_km": (
                round(curve.observed_distance_min / 1000.0, 4) if curve else None
            ),
            "observed_distance_max_km": (
                round(curve.observed_distance_max / 1000.0, 4) if curve else None
            ),
            "fit_quality": curve.fit_quality if curve else None,
            "k_conflict": curve.k_conflict if curve else None,
            "contributors": [
                {
                    "distance_m": c.distance_m,
                    "duration_s": c.duration_s,
                    "days_ago": c.days_ago,
                    "quality_score": c.quality.score,
                    "quality_confidence": c.quality.confidence,
                    "relative_hr": c.quality.relative_avg_hr,
                    "speed_percentile": c.quality.personal_speed_percentile,
                    "base_weight": c.base_weight,
                    "robust_weight": round(c.robust_weight, 6),
                }
                for c in sorted_contributors
            ],
        },
    )

# ---------------------------------------------------------------------------
# Public aliases — for callers that need these utilities
# ---------------------------------------------------------------------------

RUNNING_TYPES = _RUNNING_TYPES
seconds_to_str = _seconds_to_str
validate_activity = _validate_activity
activity_date = _activity_date
performance_duration_s = _performance_duration_s
activities_in_vma_window = _activities_in_vma_window
is_road_comparable = _is_road_comparable
personal_speed_percentile_90d = _personal_speed_percentile_90d
