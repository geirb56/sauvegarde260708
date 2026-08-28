"""Performance Model V2 — Pure business logic for race predictions.

This module is intentionally I/O-free:
  - No Mongo / database calls
  - No FastAPI / HTTP
  - No datetime.now() (reference_date is always an explicit parameter)
  - No references to the workouts collection

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

duration_s semantics:
  GARMIN_DURATION_SOURCE = summaryDTO.movingDuration (preferred) → summaryDTO.duration (fallback)
  Performance duration authority: _performance_duration_s() prefers moving_duration_s when
  moving_duration_s > 0 and moving_duration_s <= duration_s (or duration_s absent).
  This is the single authority for speed and Riegel calculations.

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

# PR #190/#191 — k identifiability / slope-evidence
# Minimum quality-weighted variance of log(distance) required to trust a
# data-driven k learned from N≥3 qualified performances.
# PR #191: identifiability is measured exclusively on HIGH-confidence
# (slope-evidence) observations.  Medium/low observations are excluded
# even if they span a wide distance range.
# Threshold justification:
#   - Two observations at 5 km and 21 km with equal weight → score ≈ 0.52 (identifiable)
#   - Many observations all within 8–12 km → score ≈ 0.013 (not identifiable)
#   - 0.05 corresponds roughly to needing meaningful spread like 5–15 km
#     in the slope-evidence (high-confidence) observation set.
K_IDENTIFIABILITY_MIN_WX_VAR: float = 0.05

# PR #190 — Huber quality-aware floors
# Minimum Huber multiplier as a fraction of base_weight for high/medium
# confidence observations.  This prevents the majority of low-quality
# speed-only observations from systematically zeroing the slope signal
# carried by a minority of high-quality HR-supported performances.
# Constraints:
#   - high observations can still be reduced to 50% of base_weight
#   - medium observations can still be reduced to 25%
#   - a truly aberrant high-confidence point will still be down-weighted
#   - low/speed-only observations retain full Huber protection (floor=0)
HUBER_QUALITY_FLOOR_HIGH: float = 0.50
HUBER_QUALITY_FLOOR_MEDIUM: float = 0.25

# Speed bounds (km/h) for a plausible running activity
MIN_SPEED_KMH: float = 3.0
MAX_SPEED_KMH: float = 30.0

# Minimum distance (m) for any candidate activity
MIN_DISTANCE_M: float = 500.0

# Minimum duration (s) for an effort to be informative
MIN_INFORMATIVE_DURATION_S: float = 5 * 60   # 5 min

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
    predictions: List[RacePrediction] = field(default_factory=list)
    athlete_profile: dict = field(default_factory=dict)
    race_curve_diagnostics: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "v2"


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
    # PR #190 — k identifiability diagnostics
    # PR #191 — slope-evidence diagnostics
    # slope_evidence = qualified observations with confidence == "high"
    # Only these can authorise a data-driven k.
    slope_evidence_count: int = 0
    slope_evidence_distance_min: float = 0.0
    slope_evidence_distance_max: float = 0.0
    # For N<3 (single_performance_riegel, two_point_prior_shrinkage_fit,
    # same_distance_prior_k_fallback, two_point_prior_k_low_slope_evidence_fallback)
    # k was never learned from data, so k_identifiable defaults to False
    # and reason to "not_applicable".
    k_identifiable: bool = False
    k_identifiability_score: float = 0.0
    k_identifiability_reason: str = "not_applicable"


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


def _huber_quality_floor(confidence: str) -> float:
    """Return the minimum Huber multiplier for an observation's quality confidence.

    PR #190 — quality-aware Huber.

    The Huber M-estimator can reduce an observation's effective weight when its
    residual is large relative to the median.  This function enforces a floor on
    that multiplier based on the observation's quality confidence level.

    Rationale: when 14 speed-only/low-confidence observations span a wide distance
    range and one HR-supported high-confidence observation is more intense, the
    Huber iteration may label the high-confidence point as an outlier and reduce
    its weight by 3×.  That single point carries most of the slope information, so
    silencing it destroys k identifiability.

    The floor is NOT a bypass:
      - A high-confidence point can still be reduced to 50% of its base weight.
      - A truly aberrant high-confidence artefact (e.g. GPS glitch logged as high)
        will still receive a meaningful weight penalty.
      - Low and speed-only observations retain full Huber protection (floor = 0).
    """
    if confidence == "high":
        return HUBER_QUALITY_FLOOR_HIGH
    if confidence == "medium":
        return HUBER_QUALITY_FLOOR_MEDIUM
    return 0.0


def _compute_k_identifiability(
    observations: List["_CurveObservation"],
    robust_ws: List[float],
) -> Tuple[bool, float, str]:
    """Measure whether the k slope is identifiable from slope-evidence observations.

    PR #191 — slope-evidence identifiability.

    Returns (k_identifiable, k_identifiability_score, k_identifiability_reason).

    The score is the quality-weighted variance of log(distance), computed using
    ONLY high-confidence (slope-evidence) observations.  Medium and low-confidence
    observations are excluded from this calculation even when they span a wide
    distance range.

    Rationale (PR #191): slope_evidence = confidence == "high".  Medium observations
    may be sustained efforts rather than true multi-distance comparable performances,
    so they do not carry enough information to personalise k.  Restricting the
    variance to HIGH-quality observations ensures the metric answers:

        "Can k be learned from defensible, genuinely comparable observations?"

    and not:

        "Are there many high/medium points in total?"

    The threshold K_IDENTIFIABILITY_MIN_WX_VAR (0.05) corresponds to needing
    observations with meaningful distance spread (roughly 5–15 km range) among
    the slope-evidence subset.  A tight 8–12 km cluster scores ≈ 0.013
    (not identifiable); a 5 km + semi spread scores ≈ 0.35 (identifiable).

    This is NOT a physiological prior on k — it measures available evidence,
    not whether k resembles 1.06.
    """
    xs = [math.log(o.distance_m) for o in observations]
    ident_ws = [
        rw if o.quality.confidence == "high" else 0.0
        for o, rw in zip(observations, robust_ws)
    ]
    sum_ident_w = sum(ident_ws)
    if sum_ident_w <= 0:
        return False, 0.0, "no_slope_evidence_high_observations"

    x_bar = sum(iw * x for iw, x in zip(ident_ws, xs)) / sum_ident_w
    score = sum(
        iw * (x - x_bar) ** 2 for iw, x in zip(ident_ws, xs)
    ) / sum_ident_w
    score = round(score, 8)
    identifiable = score >= K_IDENTIFIABILITY_MIN_WX_VAR
    reason = (
        "sufficient_slope_evidence_spread"
        if identifiable
        else "insufficient_slope_evidence_spread"
    )
    return identifiable, score, reason


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

    # PR #191 — slope-evidence: only HIGH-confidence observations can authorise k.
    slope_evidence_obs = [o for o in observations if o.quality.confidence == "high"]
    slope_evidence_count = len(slope_evidence_obs)
    _se_dists = [o.distance_m for o in slope_evidence_obs]
    slope_evidence_distance_min = min(_se_dists) if _se_dists else 0.0
    slope_evidence_distance_max = max(_se_dists) if _se_dists else 0.0

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
            slope_evidence_count=slope_evidence_count,
            slope_evidence_distance_min=slope_evidence_distance_min,
            slope_evidence_distance_max=slope_evidence_distance_max,
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
            slope_evidence_count=slope_evidence_count,
            slope_evidence_distance_min=slope_evidence_distance_min,
            slope_evidence_distance_max=slope_evidence_distance_max,
        )
    intercept, slope = fit

    method = "weighted_log_fit"
    robust_ws = list(base_ws)
    two_point_evidence_strength: Optional[float] = None
    k_raw: Optional[float] = slope
    k_fallback_applied = False
    if len(observations) == 2:
        # PR #191 — N==2 slope-evidence gate.
        # k is only personalised via shrinkage when BOTH observations are
        # slope-evidence (confidence == "high").  A HIGH + MEDIUM, two MEDIUM,
        # or any LOW pair cannot learn k.
        if slope_evidence_count == 2:
            method = "two_point_prior_shrinkage_fit"
            two_point_evidence_strength = _two_point_evidence_strength(base_ws)
            slope = RIEGEL_K + two_point_evidence_strength * (slope - RIEGEL_K)
            fixed_intercept = _fixed_slope_log_intercept(xs, ys, robust_ws, slope)
            if fixed_intercept is None:
                return None
            intercept = fixed_intercept
        else:
            # Fallback: recompute A at k=prior using all qualified observations.
            method = "two_point_prior_k_low_slope_evidence_fallback"
            two_point_evidence_strength = _two_point_evidence_strength(base_ws)
            log_a_se = _fixed_slope_log_intercept(xs, ys, robust_ws, RIEGEL_K)
            if log_a_se is None:
                return None
            intercept = log_a_se
            slope = RIEGEL_K
            k_fallback_applied = True
    elif len(observations) >= 3:
        method = "robust_weighted_log_fit"
        final_robust_fit: Optional[Tuple[float, float]] = None
        for _ in range(2):
            robust_fit = _weighted_linear_fit(xs, ys, robust_ws)
            if robust_fit is None:
                break
            r_intercept, r_slope = robust_fit
            residuals = [y - (r_intercept + r_slope * x) for x, y in zip(xs, ys)]
            abs_res = sorted(abs(r) for r in residuals)
            median_abs = abs_res[len(abs_res) // 2]
            if median_abs <= 1e-9:
                final_robust_fit = (r_intercept, r_slope)
                break
            delta = 1.5 * median_abs
            updated_ws = []
            # PR #190 — quality-aware Huber: apply floor per observation confidence.
            # Prevents the Huber M-estimator from zeroing out slope signal carried
            # by a minority of high-confidence HR-supported performances when a
            # majority of low-quality speed-only observations dominate the residual
            # distribution.
            for obs, base_w, residual in zip(observations, base_ws, residuals):
                abs_r = abs(residual)
                huber_mult = 1.0 if abs_r <= delta else (delta / abs_r)
                floor_mult = _huber_quality_floor(obs.quality.confidence)
                updated_ws.append(base_w * max(huber_mult, floor_mult))
            robust_ws = updated_ws
        if final_robust_fit is None:
            final_robust_fit = _weighted_linear_fit(xs, ys, robust_ws)
        if final_robust_fit is not None:
            intercept, slope = final_robust_fit
            k_raw = slope

    # PR #190 — identifiability check for N≥3 (robust_weighted_log_fit).
    # PR #191 — slope-evidence check: identifiability now uses HIGH-only observations.
    # For N=1 and N=2, k is already prior or prior-shrunk/fallback, so identifiability
    # is not applicable (k_identifiable defaults to False via _CurveModel defaults).
    k_identifiable = False
    k_identifiability_score = 0.0
    k_identifiability_reason = "not_applicable"
    if len(observations) >= 3:
        k_identifiable, k_identifiability_score, k_identifiability_reason = (
            _compute_k_identifiability(observations, robust_ws)
        )

    # k_conflict is evaluated from k_raw (the data-driven slope) BEFORE any fallback.
    # For N>=3, k_raw is the robust fit slope; evaluating it before applying any
    # identifiability fallback ensures the conflict diagnosis reflects the actual fit.
    # For N=2, slope is already shrunk toward the prior (or set to RIEGEL_K for fallback);
    # k_raw holds the pre-shrinkage OLS value but the shrunk slope is the N=2
    # data-driven result, so we use slope there.
    # k_fallback_applied may already be True from the N==2 low-slope-evidence branch.
    _k_for_conflict = (k_raw if (len(observations) >= 3 and k_raw is not None) else slope)
    k_conflict = not (CURVE_K_MIN <= _k_for_conflict <= CURVE_K_MAX)
    if k_conflict:
        # Contradictory observations: keep a coherent prior curve and lower trust.
        robust_ws = [w * CURVE_K_CONFLICT_WEIGHT_PENALTY for w in robust_ws]
        log_a = _fixed_slope_log_intercept(xs, ys, robust_ws, RIEGEL_K)
        if log_a is None:
            return None
        intercept = log_a
        slope = RIEGEL_K
        method = "prior_k_conflict_fallback"
        k_fallback_applied = True
    elif len(observations) >= 3 and not k_identifiable:
        # Insufficient slope-evidence spread to trust data-driven k.
        # Fall back to prior k and recompute intercept from final robust weights.
        # A uses ALL qualified observations via the final robust weights.
        log_a_ident = _fixed_slope_log_intercept(xs, ys, robust_ws, RIEGEL_K)
        if log_a_ident is not None:
            intercept = log_a_ident
            slope = RIEGEL_K
            method = "prior_k_low_slope_evidence_fallback"
            k_fallback_applied = True
            # k_raw retains the data-driven slope from the robust fit (diagnostic)
        # If log_a_ident is None (degenerate weights), retain the data-driven k.
        # k_identifiable remains False (honest: evidence is weak), but
        # k_fallback_applied will be False since the slope was not actually replaced.

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
        k_identifiable=k_identifiable,
        k_identifiability_score=k_identifiability_score,
        k_identifiability_reason=k_identifiability_reason,
        slope_evidence_count=slope_evidence_count,
        slope_evidence_distance_min=slope_evidence_distance_min,
        slope_evidence_distance_max=slope_evidence_distance_max,
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


def _curve_confidence_aggregates(
    contributors: Tuple[_CurveObservation, ...],
) -> Dict[str, float]:
    if not contributors:
        return {
            "weighted_recency": 0.0,
            "weighted_quality_confidence": 0.0,
            "weighted_quality_score": 0.0,
            "effective_contributors": 0.0,
        }

    weights = [max(c.robust_weight, 0.0) for c in contributors]
    sum_w = sum(weights)
    if sum_w <= 0:
        return {
            "weighted_recency": 0.0,
            "weighted_quality_confidence": 0.0,
            "weighted_quality_score": 0.0,
            "effective_contributors": 0.0,
        }

    probs = [w / sum_w for w in weights]
    weighted_recency = sum(
        p * _recency_weight(c.days_ago)
        for p, c in zip(probs, contributors)
    )
    weighted_quality_confidence = sum(
        p * _quality_confidence_weight(c.quality.confidence)
        for p, c in zip(probs, contributors)
    )
    weighted_quality_score = sum(
        p * _clamp(c.quality.score or 0.0, 0.0, 1.0)
        for p, c in zip(probs, contributors)
    )
    sum_w_sq = sum(w * w for w in weights)
    effective_contributors = ((sum_w * sum_w) / sum_w_sq) if sum_w_sq > 0 else 0.0

    return {
        "weighted_recency": weighted_recency,
        "weighted_quality_confidence": weighted_quality_confidence,
        "weighted_quality_score": weighted_quality_score,
        "effective_contributors": effective_contributors,
    }


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

    aggregates = _curve_confidence_aggregates(curve.contributors)
    penalty_steps = 0

    if curve.k_conflict:
        penalty_steps += 1

    fit_q = curve.fit_quality
    if fit_q is None or fit_q < 0.40:
        penalty_steps += 2
    elif fit_q < 0.70:
        penalty_steps += 1

    weighted_recency = aggregates["weighted_recency"]
    if weighted_recency < 0.60:
        penalty_steps += 2
    elif weighted_recency < 0.80:
        penalty_steps += 1

    weighted_quality_confidence = aggregates["weighted_quality_confidence"]
    if weighted_quality_confidence < 0.80:
        penalty_steps += 2
    elif weighted_quality_confidence < 0.92:
        penalty_steps += 1

    weighted_quality_score = aggregates["weighted_quality_score"]
    if weighted_quality_score < 0.60:
        penalty_steps += 2
    elif weighted_quality_score < 0.80:
        penalty_steps += 1

    effective_contributors = aggregates["effective_contributors"]
    if effective_contributors < 1.15:
        penalty_steps += 2
    elif effective_contributors < 1.60:
        penalty_steps += 1

    # PR #191 — k-prior fallback: uncertainty grows with extrapolation distance.
    # When k is fixed at RIEGEL_K (not data-driven), the curve is anchored at A
    # but the slope is uncertain.  Close predictions remain reliable; distant
    # extrapolations accumulate k-uncertainty.
    # Reuse existing extrapolation thresholds (1.8, 3.0) to avoid a parallel system.
    _slope_evidence_fallback_methods = {
        "prior_k_low_slope_evidence_fallback",
        "two_point_prior_k_low_slope_evidence_fallback",
    }
    if curve.k_fallback_applied and curve.method in _slope_evidence_fallback_methods:
        if extrapolation_ratio > 3.0:
            penalty_steps += 2
        elif extrapolation_ratio > 1.8:
            penalty_steps += 1

    if penalty_steps > 0:
        base = _degrade_confidence(base, penalty_steps)

    if len(curve.contributors) == 1 and base == "high":
        base = "medium"

    # PR216: a numeric prediction produced from a real curve within the hard
    # extrapolation guardrail remains defendable, even when cumulative penalties
    # stack. Reserve INSUFFICIENT for true absence of defendable prediction:
    # no curve, no extrapolation anchor, or extrapolation beyond the null limit.
    if base == "insufficient":
        return "low"

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
    """Compute race predictions V2 from qualified observed performances.

    VMA is removed (#214); predictions use the performance curve only.
    """
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

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

    athlete_profile = {
        "weekly_km": round(weekly_km, 1),
        "max_long_run_km": round(max_long_run_m / 1000.0, 1),
        "estimated_vma": None,
        "estimated_vo2max": None,
        "vo2max_note": None,
        "vma_method": None,
        "vma_confidence": None,
        "vma_reason_code": None,
        "calculation_window": "garmin_activities (all available)",
        "model_version": "v2",
    }

    # has_data = True when at least one prediction has a time
    has_any_prediction = any(p.predicted_time_s is not None for p in predictions)
    result_has_data = has_any_prediction

    confidence_aggregates = _curve_confidence_aggregates(tuple(sorted_contributors))

    # PR #190 — compute quality weight shares for diagnostics
    _sum_bw = sum(c.base_weight for c in sorted_contributors)
    _hm_bw = sum(
        c.base_weight for c in sorted_contributors
        if c.quality.confidence in ("high", "medium")
    )
    _sol_bw = sum(
        c.base_weight for c in sorted_contributors
        if c.quality.confidence == "low"
    )
    high_medium_quality_weight_share = round(_hm_bw / _sum_bw, 6) if _sum_bw > 0 else 0.0
    # "low" confidence is the exact predicate for speed-only (#188 fallback) observations.
    # Renamed from speed_only_low_weight_share to clarify that this is the confidence tier,
    # not a separate classification.
    low_confidence_weight_share = round(_sol_bw / _sum_bw, 6) if _sum_bw > 0 else 0.0

    return PerformanceEstimate(
        has_data=result_has_data,
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
            # PR #190/#191 — k identifiability diagnostics (slope-evidence)
            "k_identifiable": curve.k_identifiable if curve else None,
            "k_identifiability_score": (
                round(curve.k_identifiability_score, 8) if curve else None
            ),
            "k_identifiability_reason": curve.k_identifiability_reason if curve else None,
            # PR #191 — slope-evidence diagnostics
            "slope_evidence_count": curve.slope_evidence_count if curve else 0,
            "slope_evidence_distance_min": (
                curve.slope_evidence_distance_min if (curve and curve.slope_evidence_count > 0) else None
            ),
            "slope_evidence_distance_max": (
                curve.slope_evidence_distance_max if (curve and curve.slope_evidence_count > 0) else None
            ),
            "slope_evidence_distance_min_km": (
                round(curve.slope_evidence_distance_min / 1000.0, 4)
                if (curve and curve.slope_evidence_count > 0)
                else None
            ),
            "slope_evidence_distance_max_km": (
                round(curve.slope_evidence_distance_max / 1000.0, 4)
                if (curve and curve.slope_evidence_count > 0)
                else None
            ),
            "high_medium_quality_weight_share": high_medium_quality_weight_share if curve else None,
            "low_confidence_weight_share": low_confidence_weight_share if curve else None,
            # --- existing fields ---
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
            "weighted_recency": round(confidence_aggregates["weighted_recency"], 6) if curve else None,
            "weighted_quality_confidence": (
                round(confidence_aggregates["weighted_quality_confidence"], 6) if curve else None
            ),
            "weighted_quality_score": (
                round(confidence_aggregates["weighted_quality_score"], 6) if curve else None
            ),
            "effective_contributors": (
                round(confidence_aggregates["effective_contributors"], 6) if curve else None
            ),
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
is_road_comparable = _is_road_comparable
personal_speed_percentile_90d = _personal_speed_percentile_90d
