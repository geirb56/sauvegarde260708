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
    FCmax from the highest credible observed Garmin max HR (150–230 bpm).
    Extrapolation target: 95% of FCmax (aerobic ceiling, conservative).
    If R² < 0.30 or slope <= 0: vma_kmh = null.

  SOURCE A — Explicit performance (DISABLED):
    No Garmin field currently identifies an activity as a race or test.
    The speed+duration heuristic is explicitly rejected.
    The _vma_from_explicit_performance() helper is retained but never called.

  If SOURCE B yields insufficient data or quality: vma_kmh = null.

FCmax policy:
  Runtime FCmax = highest credible observed Garmin max HR across valid activities.
  No user-declared FCmax is available at runtime (USER_MAX_HR_RUNTIME_WIRED = NOT_AVAILABLE).
  No 220-age formula, no population fallback, no hr_max+5.

FORBIDDEN:
  - avg_speed-divided-by-0.70 fallback (removed)
  - Single fastest run auto-qualified as performance source
  - 220-age or any population FCmax formula
  - hr_max+5 adjustment
  - Invented predictions when model is unreliable

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
from typing import List, Optional, Tuple, Union

from training_v2.domain_activity import DomainActivity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RUNNING_TYPES = {
    "running", "run", "trail_running", "treadmill_running",
    "indoor_running", "track_running",
}

RIEGEL_K: float = 1.06

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
MAX_ELEVATION_GAIN_M: float = 400.0           # elevation filter (if available)

# HR-speed model: coverage requirements
MIN_ACTIVITIES_HR_MODEL: int = 4
MIN_DISTINCT_HR_LEVELS: int = 3
MIN_HR_RANGE_BPM: float = 20.0               # min spread across observed HR values

# HR-speed model: quality
MIN_R2: float = 0.30                          # minimum R² — weak correlation → null
MAX_EXTRAPOLATION_RATIO: float = 1.25         # max HR extrapolation beyond observed max

# Explicit performance: minimum duration for qualification
MIN_EXPLICIT_PERFORMANCE_DURATION_S: float = 10 * 60   # 10 min

# Staleness thresholds (days) for confidence
CONFIDENCE_HIGH_DAYS = 21
CONFIDENCE_MEDIUM_DAYS = 56
CONFIDENCE_LOW_DAYS = 120

# Maximum source disagreement ratio before penalising confidence
MAX_SOURCE_AGREEMENT_RATIO: float = 0.15     # 15% difference → SOURCES_DISAGREE

# Source A (explicit performance): DISABLED — no Garmin field identifies races/tests.
# Speed+duration heuristic is not acceptable as explicit performance qualification.
SOURCE_A_DISABLED: bool = True

# Riegel source selection constraints
MAX_RIEGEL_SOURCE_AGE_DAYS: int = 730        # Activities older than 2 years not defensible
MIN_RIEGEL_SOURCE_RATIO: float = 0.12        # Source must be >= 12% of target distance
MIN_RIEGEL_SCORE: float = 0.25               # Minimum score for a defensible source

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

REASON_EXPLICIT_PERFORMANCE_SOURCE = "EXPLICIT_PERFORMANCE_SOURCE"
REASON_HR_SPEED_MODEL_SOURCE = "HR_SPEED_MODEL_SOURCE"
REASON_HR_RANGE_INSUFFICIENT = "HR_RANGE_INSUFFICIENT"
REASON_HR_LEVELS_INSUFFICIENT = "HR_LEVELS_INSUFFICIENT"
REASON_HR_MODEL_POOR_FIT = "HR_MODEL_POOR_FIT"
REASON_EXTRAPOLATION_TOO_LARGE = "EXTRAPOLATION_TOO_LARGE"
REASON_NO_FCMAX = "NO_FCMAX"
REASON_SOURCES_DISAGREE = "SOURCES_DISAGREE"
REASON_NO_DATA = "NO_DATA"
REASON_INSUFFICIENT_ACTIVITIES = "INSUFFICIENT_ACTIVITIES"

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


def _speed_kmh(a: DomainActivity) -> Optional[float]:
    if not a.distance_m or not a.duration_s:
        return None
    if a.distance_m <= 0 or a.duration_s <= 0:
        return None
    return (a.distance_m / 1000.0) / (a.duration_s / 3600.0)


def _days_ago(activity_date: date, reference_date: date) -> int:
    return (reference_date - activity_date).days


def _validate_activity(a: DomainActivity, reference_date: date) -> bool:
    """Return True if the activity is a valid running candidate (basic validation)."""
    if not _is_running(a):
        return False
    d = _activity_date(a)
    if d is None or d > reference_date:
        return False
    if not a.distance_m or a.distance_m < MIN_DISTANCE_M:
        return False
    if not a.duration_s or a.duration_s <= 0:
        return False
    speed = _speed_kmh(a)
    if speed is None or speed < MIN_SPEED_KMH or speed > MAX_SPEED_KMH:
        return False
    return True


# ---------------------------------------------------------------------------
# HR-speed model filtering
# ---------------------------------------------------------------------------


def _is_usable_for_hr_model(a: DomainActivity, reference_date: date) -> bool:
    """Additional filters for HR-speed model activities.

    On top of _validate_activity, also requires:
    - HR present and plausible
    - Duration >= MIN_DURATION_HR_MODEL_S (no short sprints)
    - Low elevation gain (trail/hilly → not comparable)
    - Not a future activity
    """
    if not _validate_activity(a, reference_date):
        return False
    hr = a.average_hr
    if hr is None or hr < MIN_AVG_HR or hr > MAX_AVG_HR:
        return False
    if (a.duration_s or 0) < MIN_DURATION_HR_MODEL_S:
        return False
    # Elevation: reject if data exists and exceeds threshold
    if a.elevation_gain_m is not None and a.elevation_gain_m > MAX_ELEVATION_GAIN_M:
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
# FCmax resolution — NO 220-age formula
# ---------------------------------------------------------------------------


def _resolve_fcmax(
    activities: List[DomainActivity],
    user_max_hr: Optional[float] = None,
    reference_date: Optional[date] = None,
) -> Optional[float]:
    """Resolve FCmax from reliable sources only.

    Order:
    1. user_max_hr (from user profile/configuration)
    2. Maximum HR observed in Garmin activities (if credible: >= 150 bpm, <= 230 bpm)
    3. None — no fallback formula

    220-age is FORBIDDEN.
    """
    # 1. User-configured FCmax
    if user_max_hr is not None and 130 <= user_max_hr <= 230:
        return float(user_max_hr)

    # 2. Observed maximum from activities
    if activities and reference_date is not None:
        observed = [
            a.max_hr
            for a in activities
            if _validate_activity(a, reference_date)
            and a.max_hr is not None
            and 150 <= a.max_hr <= 230
        ]
        if observed:
            return float(max(observed))

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
) -> _HRModelResult:
    """Fit a personal HR-speed linear model and extrapolate to aerobic VMA.

    Requirements:
    - >= MIN_ACTIVITIES_HR_MODEL usable activities
    - >= MIN_DISTINCT_HR_LEVELS distinct HR levels
    - HR range >= MIN_HR_RANGE_BPM
    - R² >= MIN_R2
    - Extrapolation ratio <= MAX_EXTRAPOLATION_RATIO

    FCmax from user profile or observed max only (no 220-age).
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

    # FCmax resolution — no hr_max+5 or 220-age fallback
    fcmax = _resolve_fcmax(activities, user_max_hr, reference_date)

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
# Explicit performance (Source A)
# ---------------------------------------------------------------------------


def _is_explicit_performance(a: DomainActivity, reference_date: date) -> bool:
    """Source A (explicit performance) is DISABLED.

    No Garmin field currently identifies an activity as a race, test, or competition.
    The speed+duration heuristic (speed >= 10 km/h, duration >= 10 min) is not an
    acceptable proxy for explicit performance qualification.

    SOURCE_A_DISABLED = True.  Returns False always.
    """
    return False


def _select_explicit_performance(
    activities: List[DomainActivity],
    reference_date: date,
) -> Optional[DomainActivity]:
    """Select the best explicit performance candidate.

    Among qualifying performances, prefer:
    1. Longest effort (most informative)
    2. Then fastest
    3. Then most recent
    """
    candidates = [a for a in activities if _is_explicit_performance(a, reference_date)]
    if not candidates:
        return None

    def sort_key(a: DomainActivity):
        dur = a.duration_s or 0.0
        spd = _speed_kmh(a) or 0.0
        d = _activity_date(a) or date.min
        return (dur, spd, d.toordinal())

    return max(candidates, key=sort_key)


def _vma_from_explicit_performance(a: DomainActivity) -> float:
    """Convert explicit performance to VMA using duration-based fraction."""
    speed = _speed_kmh(a) or 0.0
    duration_min = (a.duration_s or 0.0) / 60.0

    if duration_min >= 60:
        fraction = 0.78
    elif duration_min >= 20:
        fraction = 0.85
    elif duration_min >= 12:
        fraction = 0.90
    else:
        fraction = 0.95

    return round(speed / fraction, 2)


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


def _explicit_confidence(a: DomainActivity, reference_date: date) -> str:
    """Confidence for an explicit performance source."""
    d = _activity_date(a)
    days = _days_ago(d, reference_date) if d else 999
    dur = a.duration_s or 0.0

    if days <= CONFIDENCE_HIGH_DAYS and dur >= 20 * 60:
        return "high"
    if days <= CONFIDENCE_MEDIUM_DAYS and dur >= 10 * 60:
        return "medium"
    if days <= CONFIDENCE_LOW_DAYS:
        return "low"
    return "insufficient"


def _merge_confidence(ca: str, cb: str, agree: bool) -> str:
    """Merge two confidence levels.

    If sources agree, take the better one (or bump up).
    If sources disagree, downgrade by one level.
    """
    order = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}
    rev = {0: "insufficient", 1: "low", 2: "medium", 3: "high"}

    va = order.get(ca, 0)
    vb = order.get(cb, 0)
    combined = max(va, vb)

    if agree:
        combined = min(combined + 1, 3)
    else:
        combined = max(combined - 1, 0)

    return rev[combined]


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
    model_version: str = "v2"


@dataclass
class PerformanceEstimate:
    """Top-level result for a user snapshot."""
    has_data: bool
    vma: VMAEstimate
    predictions: List[RacePrediction] = field(default_factory=list)
    athlete_profile: dict = field(default_factory=dict)
    model_version: str = "v2"


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

    Returns VMAEstimate(vma_kmh=None) when the model yields insufficient data.

    FCmax: from user profile or observed Garmin max_hr only.
    220-age and hr_max+5 are forbidden.
    """
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    # --- Source A: DISABLED ---
    # SOURCE_A_DISABLED = True: no Garmin field identifies explicit performances.

    # --- Source B: HR-speed model ---
    hr_model = _fit_hr_speed_model(activities, reference_date, user_max_hr)
    vma_b: Optional[float] = hr_model.vma_kmh
    conf_b: Optional[str] = (
        _hr_model_confidence(hr_model, reference_date, activities)
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
    relative_hr: Optional[float] = None,
) -> str:
    """Confidence for a Riegel prediction.

    HIGH requires relative_hr >= 0.85 in addition to a close, recent source with good
    endurance support.  Without confirmed high effort the best achievable is MEDIUM.
    """
    ratio = target_distance_m / source_distance_m
    if ratio > 4.0 or days_since_source > CONFIDENCE_LOW_DAYS or endurance_factor < 0.65:
        return "low"
    if ratio > 2.0 or days_since_source > CONFIDENCE_MEDIUM_DAYS or endurance_factor < 0.80:
        return "medium"
    # Close source, recent, good endurance: require confirmed high effort for HIGH
    if relative_hr is not None and relative_hr >= 0.85:
        return "high"
    return "medium"  # No relative_hr data or effort was easy → cap at medium


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
    fcmax: Optional[float],
) -> float:
    """Score an activity as a Riegel source for a given target distance.

    Returns a score in [0, 1].  Higher = more informative for this target.
    Returns 0.0 when the activity is not a defensible source.

    Weights:
      proximity  0.50  — how close source distance is to target
      recency    0.30  — how recent the activity is
      rel_hr     0.20  — effort level relative to FCmax (neutral 0.5 when unknown)

    Minimum defensible conditions:
      - activity distance >= MIN_RIEGEL_SOURCE_RATIO * target_distance
      - activity date within MAX_RIEGEL_SOURCE_AGE_DAYS
    """
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

    # Relative HR (effort level); neutral 0.5 when HR data unavailable
    if fcmax is not None and fcmax > 0 and a.average_hr is not None:
        rel_hr_score = min(a.average_hr / fcmax, 1.0)
    else:
        rel_hr_score = 0.50

    score = proximity * 0.50 + recency * 0.30 + rel_hr_score * 0.20
    return round(score, 4)


def _select_riegel_source(
    activities: List[DomainActivity],
    reference_date: date,
    target_distance_m: float,
    fcmax: Optional[float],
) -> Optional[Tuple[DomainActivity, float, Optional[float]]]:
    """Select the best observed activity as Riegel source for a given target.

    Returns (activity, score, relative_hr) or None when no defensible source exists.

    relative_hr = avg_hr / fcmax when both are available, else None.
    source_type for all results from this function is "observed_activity".
    """
    candidates = [a for a in activities if _validate_activity(a, reference_date)]
    if not candidates:
        return None

    best_score = 0.0
    best_act: Optional[DomainActivity] = None
    for a in candidates:
        s = _score_riegel_candidate(a, target_distance_m, reference_date, fcmax)
        if s > best_score:
            best_score = s
            best_act = a

    if best_act is None or best_score < MIN_RIEGEL_SCORE:
        return None

    rel_hr: Optional[float] = None
    if fcmax is not None and fcmax > 0 and best_act.average_hr is not None:
        rel_hr = round(best_act.average_hr / fcmax, 4)

    return best_act, best_score, rel_hr


# ---------------------------------------------------------------------------
# Race predictions V2
# ---------------------------------------------------------------------------


def predict_races(
    activities: List[DomainActivity],
    reference_date: Union[date, datetime],
    user_max_hr: Optional[float] = None,
) -> PerformanceEstimate:
    """Compute VMA V2 estimate and race predictions V2.

    VMA is estimated via the HR-speed model (SOURCE A is disabled).

    Race predictions use only real observed activities as Riegel source.
    A separate best source is selected per target distance.
    No synthetic effort (20 min @ 85% VMA) is ever created.

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

    # Resolve FCmax for relative_hr computation in source scoring
    fcmax = _resolve_fcmax(activities, user_max_hr, reference_date)

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

    for label, dist_m in RACE_DISTANCES_M.items():
        endurance = _endurance_support(activities, reference_date, dist_m)
        target_km = dist_m / 1000.0
        vol_factor = min(weekly_km / max(target_km * 0.5, 1.0), 1.0)

        # Select per-target observed source — no synthetic effort
        riegel_src = _select_riegel_source(activities, reference_date, dist_m, fcmax)

        if riegel_src is None:
            # No defensible observed source for this target → null prediction
            predictions.append(RacePrediction(
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
                source_distance_m=None,
                source_type=None,
            ))
            continue

        src_act, _src_score, relative_hr = riegel_src
        source_distance_m = src_act.distance_m or 0.0
        source_duration_s = src_act.duration_s or 0.0
        source_date = _activity_date(src_act)
        days_since_source = _days_ago(source_date, reference_date) if source_date else 999

        try:
            raw_time_s = _riegel(source_duration_s, source_distance_m, dist_m)
        except (ValueError, ZeroDivisionError):
            predictions.append(RacePrediction(
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
                source_type="observed_activity",
            ))
            continue

        endurance_penalty = 1.0 + (1.0 - endurance) * 0.4
        adjusted_time_s = raw_time_s * endurance_penalty

        readiness_score_raw = endurance * 0.6 + vol_factor * 0.4
        r_key, r_label, r_color = _readiness(readiness_score_raw)

        conf = _riegel_confidence(
            source_distance_m, dist_m, days_since_source, endurance,
            relative_hr=relative_hr,
        )

        # Downgrade prediction confidence if VMA model itself is low/insufficient
        if vma_est.confidence in ("low", "insufficient") and conf == "high":
            conf = "medium"

        predictions.append(RacePrediction(
            distance_label=label,
            distance_km=target_km,
            predicted_time_s=round(adjusted_time_s, 1),
            predicted_time_str=_seconds_to_str(adjusted_time_s),
            predicted_pace_str=_pace_str(adjusted_time_s, dist_m),
            confidence=conf,
            readiness=r_key,
            readiness_label=r_label,
            readiness_color=r_color,
            readiness_score=round(readiness_score_raw * 100),
            endurance_factor=round(endurance * 100),
            volume_factor=round(vol_factor * 100),
            source_distance_m=source_distance_m,
            source_type="observed_activity",
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
    )

# ---------------------------------------------------------------------------
# Public aliases — for callers that need these utilities
# ---------------------------------------------------------------------------

RUNNING_TYPES = _RUNNING_TYPES
seconds_to_str = _seconds_to_str
validate_activity = _validate_activity
