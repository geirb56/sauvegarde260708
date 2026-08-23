"""Performance Model V2 — VMA estimation and Race Predictions.

Data-quality design decisions (PR #186):

1. moving_duration_s is preferred over duration_s for speed and Riegel.
2. VMA window is 42 days, unified for CURRENT and HISTORY.
3. Trail running is excluded from the HR-speed VMA model.
4. Riegel sources must have relative_hr >= 0.80 AND average_hr AND FCmax.
5. total_sessions_6w counts running activities in 42-day window only.
6. VMA and Race Predictions are fully independent.

Constants that must NOT be changed:
    RIEGEL_K, MIN_ACTIVITIES_HR_MODEL, MIN_HR_RANGE_BPM,
    MIN_DISTINCT_HR_LEVELS, MIN_R2
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from training_v2.domain_activity import DomainActivity

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

VMA_WINDOW_DAYS: int = 42
"""Unified 42-day window for both CURRENT VMA and HISTORY snapshots."""

MAX_ROAD_ELEVATION_GAIN_PER_KM: float = 30.0
"""Maximum acceptable elevation gain per km for road-comparable activities."""

MIN_RIEGEL_RELATIVE_HR: float = 0.80
"""Minimum relative HR (avg_hr / fcmax) required to qualify as a Riegel source."""

RIEGEL_K: float = 1.06
"""Riegel exponent — must NOT be changed."""

MIN_ACTIVITIES_HR_MODEL: int = 3
"""Minimum number of eligible activities required to fit the HR-speed model."""

MIN_HR_RANGE_BPM: float = 20.0
"""Minimum range of HR values (bpm) across activities for a valid regression."""

MIN_DISTINCT_HR_LEVELS: int = 3
"""Minimum number of distinct HR levels in the regression dataset."""

MIN_R2: float = 0.50
"""Minimum R² coefficient for the HR-speed regression to be accepted."""

# ---------------------------------------------------------------------------
# Activity-type sets
# ---------------------------------------------------------------------------

#: Running types that are road-comparable for the HR-speed VMA model.
#: Trail running is intentionally excluded.
_VMA_ROAD_TYPES: frozenset = frozenset(
    {
        "running",
        "street_running",
        "indoor_running",
        "treadmill_running",
        "track_running",
        "road_running",
        "run",
    }
)

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _to_date(value: Any) -> Optional[date]:
    """Coerce a start_time field to a plain date, or return None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            pass
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return None


def _performance_duration_s(activity: DomainActivity) -> Optional[float]:
    """Return the authoritative performance duration for speed calculations.

    Priority:
    1. moving_duration_s if valid (> 0 and <= duration_s when duration_s exists)
    2. duration_s if valid (> 0)
    3. None
    """
    moving = activity.moving_duration_s
    total = activity.duration_s

    if (
        moving is not None
        and isinstance(moving, (int, float))
        and float(moving) > 0
    ):
        m = float(moving)
        # Guard: moving_duration_s must not exceed duration_s
        if total is not None and isinstance(total, (int, float)) and float(total) > 0:
            if m <= float(total):
                return m
        else:
            # duration_s not available or invalid — accept moving_duration_s
            return m

    if total is not None and isinstance(total, (int, float)) and float(total) > 0:
        return float(total)

    return None


def _speed_kmh(activity: DomainActivity) -> Optional[float]:
    """Return speed in km/h using the authoritative performance duration."""
    dur = _performance_duration_s(activity)
    dist = activity.distance_m
    if dur is None or dist is None:
        return None
    if not isinstance(dist, (int, float)) or float(dist) <= 0:
        return None
    if dur <= 0:
        return None
    return (float(dist) / float(dur)) * 3.6  # m/s → km/h


def _elevation_gain_per_km(activity: DomainActivity) -> Optional[float]:
    """Return elevation gain per km, or None if distance is missing."""
    elev = activity.elevation_gain_m
    dist = activity.distance_m
    if elev is None or dist is None:
        return None
    if not isinstance(dist, (int, float)) or float(dist) <= 0:
        return None
    dist_km = float(dist) / 1000.0
    if dist_km <= 0:
        return None
    return float(elev) / dist_km


def _is_vma_eligible(activity: DomainActivity) -> bool:
    """Return True if the activity is eligible for the HR-speed VMA model.

    Rules:
    - activity_type must be in _VMA_ROAD_TYPES (trail_running is excluded)
    - elevation_gain_per_km <= MAX_ROAD_ELEVATION_GAIN_PER_KM if elevation known
    - must have average_hr > 0
    - must have valid distance and performance duration
    """
    # Type check
    act_type = activity.activity_type
    if act_type is None or act_type.lower() not in _VMA_ROAD_TYPES:
        return False

    # Elevation: reject if known and exceeds threshold
    epk = _elevation_gain_per_km(activity)
    if epk is not None and epk > MAX_ROAD_ELEVATION_GAIN_PER_KM:
        return False

    # Must have HR
    if activity.average_hr is None:
        return False

    # Must have valid speed
    if _speed_kmh(activity) is None:
        return False

    return True


def _activities_in_vma_window(
    activities: Sequence[DomainActivity],
    reference_date: date,
    window_days: int = VMA_WINDOW_DAYS,
) -> List[DomainActivity]:
    """Return activities in [reference_date - (window_days-1) days, reference_date].

    The window is exactly ``window_days`` days long:
    - reference_date is included (J+0)
    - reference_date - (window_days-1) is included (J-(window_days-1))
    - reference_date - window_days is excluded (J-window_days)
    """
    window_start = reference_date - timedelta(days=window_days - 1)
    result = []
    for act in activities:
        d = _to_date(act.start_time)
        if d is None:
            continue
        if window_start <= d <= reference_date:
            result.append(act)
    return result


# ---------------------------------------------------------------------------
# FCmax robust
# ---------------------------------------------------------------------------


def _robust_fcmax(activities: Sequence[DomainActivity]) -> Optional[float]:
    """Compute a robust observed FCmax from activity max_hr values.

    n >= 3: if highest > second_highest * 1.10, use second_highest.
    n < 3: use highest available.
    Returns None if no valid max_hr is found.

    No fallback to 220-age or population norms.
    """
    values = sorted(
        [float(a.max_hr) for a in activities if a.max_hr is not None and float(a.max_hr) > 0],
        reverse=True,
    )
    if not values:
        return None
    if len(values) >= 3:
        highest = values[0]
        second = values[1]
        if highest > second * 1.10:
            return second
        return highest
    return values[0]


# ---------------------------------------------------------------------------
# HR-speed linear regression
# ---------------------------------------------------------------------------


def _linear_regression(
    xs: List[float], ys: List[float]
) -> Tuple[float, float, float]:
    """Return (slope, intercept, r_squared) for simple linear regression."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_yy = sum((y - mean_y) ** 2 for y in ys)
    ss_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    if ss_xx == 0:
        return 0.0, mean_y, 0.0
    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x
    if ss_yy == 0:
        r2 = 1.0
    else:
        r2 = (ss_xy ** 2) / (ss_xx * ss_yy)
    return slope, intercept, r2


# ---------------------------------------------------------------------------
# VMA estimation result
# ---------------------------------------------------------------------------


class VmaEstimate:
    """Result of the VMA HR-speed estimation."""

    __slots__ = (
        "vma_kmh",
        "confidence",
        "reason_code",
        "fcmax",
        "n_activities",
        "hr_model_r_squared",
    )

    def __init__(
        self,
        *,
        vma_kmh: Optional[float],
        confidence: str,
        reason_code: Optional[str] = None,
        fcmax: Optional[float] = None,
        n_activities: int = 0,
        hr_model_r_squared: Optional[float] = None,
    ) -> None:
        self.vma_kmh = vma_kmh
        self.confidence = confidence
        self.reason_code = reason_code
        self.fcmax = fcmax
        self.n_activities = n_activities
        self.hr_model_r_squared = hr_model_r_squared

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vma_kmh": self.vma_kmh,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
            "fcmax": self.fcmax,
            "n_activities": self.n_activities,
            "hr_model_r_squared": self.hr_model_r_squared,
        }


def _make_insufficient(reason: str) -> VmaEstimate:
    return VmaEstimate(
        vma_kmh=None,
        confidence="insufficient",
        reason_code=reason,
    )


def estimate_vma(
    activities: Sequence[DomainActivity],
    reference_date: Optional[Union[date, datetime]] = None,
) -> VmaEstimate:
    """Estimate VMA using the HR-speed linear regression model.

    Uses only activities within the 42-day window ending at reference_date.
    Does NOT look ahead of reference_date.

    Returns VmaEstimate with confidence in {"good", "moderate", "insufficient"}.
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc).date()
    elif isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    window = _activities_in_vma_window(activities, reference_date)

    # FCmax is computed from the full window (not just VMA-eligible)
    fcmax = _robust_fcmax(window)
    if fcmax is None:
        return _make_insufficient("no_fcmax")

    target_hr = fcmax * 0.95

    # Filter VMA-eligible activities
    eligible = [a for a in window if _is_vma_eligible(a)]

    if len(eligible) < MIN_ACTIVITIES_HR_MODEL:
        return VmaEstimate(
            vma_kmh=None,
            confidence="insufficient",
            reason_code="insufficient_activities",
            fcmax=fcmax,
            n_activities=len(eligible),
        )

    hrs = [float(a.average_hr) for a in eligible]  # type: ignore[arg-type]
    speeds = [_speed_kmh(a) for a in eligible]

    # Keep only pairs where both HR and speed are valid
    pairs = [(h, s) for h, s in zip(hrs, speeds) if s is not None]
    if len(pairs) < MIN_ACTIVITIES_HR_MODEL:
        return _make_insufficient("insufficient_activities")
    hrs_clean = [p[0] for p in pairs]
    speeds_clean = [p[1] for p in pairs]

    # HR range check
    hr_range = max(hrs_clean) - min(hrs_clean)
    if hr_range < MIN_HR_RANGE_BPM:
        return VmaEstimate(
            vma_kmh=None,
            confidence="insufficient",
            reason_code="insufficient_hr_range",
            fcmax=fcmax,
            n_activities=len(pairs),
        )

    # Distinct HR levels
    distinct_hr = len({round(h) for h in hrs_clean})
    if distinct_hr < MIN_DISTINCT_HR_LEVELS:
        return VmaEstimate(
            vma_kmh=None,
            confidence="insufficient",
            reason_code="insufficient_hr_levels",
            fcmax=fcmax,
            n_activities=len(pairs),
        )

    slope, intercept, r2 = _linear_regression(hrs_clean, speeds_clean)

    if r2 < MIN_R2:
        return VmaEstimate(
            vma_kmh=None,
            confidence="insufficient",
            reason_code="low_r_squared",
            fcmax=fcmax,
            n_activities=len(pairs),
            hr_model_r_squared=round(r2, 3),
        )

    vma = slope * target_hr + intercept
    if vma <= 0:
        return VmaEstimate(
            vma_kmh=None,
            confidence="insufficient",
            reason_code="negative_extrapolation",
            fcmax=fcmax,
            n_activities=len(pairs),
            hr_model_r_squared=round(r2, 3),
        )

    confidence = "good" if r2 >= 0.70 else "moderate"

    return VmaEstimate(
        vma_kmh=round(vma, 1),
        confidence=confidence,
        fcmax=fcmax,
        n_activities=len(pairs),
        hr_model_r_squared=round(r2, 3),
    )


# ---------------------------------------------------------------------------
# Riegel helpers
# ---------------------------------------------------------------------------


def _riegel_predict(t1_s: float, d1_m: float, d2_m: float, k: float = RIEGEL_K) -> float:
    """Predict time T2 for distance D2 given observed time T1 for distance D1."""
    return t1_s * (d2_m / d1_m) ** k


def _is_riegel_eligible(
    activity: DomainActivity,
    fcmax: Optional[float],
) -> bool:
    """Return True if the activity qualifies as a Riegel source.

    Requirements:
    - activity_type must be in _VMA_ROAD_TYPES (trail excluded)
    - elevation_gain_per_km <= 30 if known
    - FCmax must be available
    - average_hr must be available
    - relative_hr = average_hr / fcmax >= MIN_RIEGEL_RELATIVE_HR (0.80)
    - valid distance and performance duration
    """
    if fcmax is None:
        return False

    act_type = activity.activity_type
    if act_type is None or act_type.lower() not in _VMA_ROAD_TYPES:
        return False

    epk = _elevation_gain_per_km(activity)
    if epk is not None and epk > MAX_ROAD_ELEVATION_GAIN_PER_KM:
        return False

    if activity.average_hr is None:
        return False

    relative_hr = float(activity.average_hr) / float(fcmax)
    if relative_hr < MIN_RIEGEL_RELATIVE_HR:
        return False

    # Must have distance and duration for speed
    if activity.distance_m is None:
        return False
    dur = _performance_duration_s(activity)
    if dur is None:
        return False

    return True


# ---------------------------------------------------------------------------
# Race predictions result
# ---------------------------------------------------------------------------

_RACE_DISTANCES_M: List[Tuple[str, float]] = [
    ("5K", 5_000.0),
    ("10K", 10_000.0),
    ("Semi", 21_097.5),
    ("Marathon", 42_195.0),
]

_ULTRA_DISTANCES_M: List[Tuple[str, float]] = [
    ("Ultra", 50_000.0),
]


def get_race_predictions(
    activities: Sequence[DomainActivity],
    reference_date: Optional[Union[date, datetime]] = None,
) -> Dict[str, Any]:
    """Compute Riegel-based race predictions.

    Predictions are INDEPENDENT of VMA: same source → same predictions
    regardless of whether VMA is available.

    Returns a dict with keys: has_data, predictions, source.
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc).date()
    elif isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    window = _activities_in_vma_window(activities, reference_date)
    fcmax = _robust_fcmax(window)

    # No FCmax → no predictions (by design)
    if fcmax is None:
        return {"has_data": False, "predictions": [], "source": None}

    eligible = [a for a in window if _is_riegel_eligible(a, fcmax)]

    if not eligible:
        return {"has_data": False, "predictions": [], "source": None}

    # Select best Riegel source: longest distance among eligible activities
    source = max(eligible, key=lambda a: float(a.distance_m or 0))

    t1_s = _performance_duration_s(source)
    d1_m = float(source.distance_m or 0)

    if t1_s is None or d1_m <= 0:
        return {"has_data": False, "predictions": [], "source": None}

    predictions = []
    for label, d2_m in _RACE_DISTANCES_M + _ULTRA_DISTANCES_M:
        t2_s = _riegel_predict(t1_s, d1_m, d2_m)
        predictions.append({
            "distance": label,
            "distance_m": d2_m,
            "predicted_time_s": round(t2_s),
            "predicted_time": _format_time(t2_s),
        })

    return {
        "has_data": True,
        "predictions": predictions,
        "source": {
            "distance_m": d1_m,
            "duration_s": t1_s,
            "relative_hr": round(float(source.average_hr) / fcmax, 3),  # type: ignore[arg-type]
        },
    }


def _format_time(seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    s = int(round(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


# ---------------------------------------------------------------------------
# Athlete profile
# ---------------------------------------------------------------------------


def compute_athlete_profile(
    activities: Sequence[DomainActivity],
    reference_date: Optional[Union[date, datetime]] = None,
) -> Dict[str, Any]:
    """Compute athlete profile stats for the 42-day window.

    total_sessions_6w counts only running activities within the window.
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc).date()
    elif isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    window = _activities_in_vma_window(activities, reference_date)

    running_types = _VMA_ROAD_TYPES | frozenset({"trail_running", "hiking"})
    running_sessions = [
        a for a in window
        if a.activity_type is not None and a.activity_type.lower() in running_types
    ]
    total_sessions_6w = len(running_sessions)

    return {
        "total_sessions_6w": total_sessions_6w,
        "window_days": VMA_WINDOW_DAYS,
        "reference_date": reference_date.isoformat(),
    }


# ---------------------------------------------------------------------------
# VMA history snapshots
# ---------------------------------------------------------------------------


def get_vma_history_snapshots(
    activities: Sequence[DomainActivity],
    reference_date: Optional[Union[date, datetime]] = None,
    num_snapshots: int = 24,
) -> List[Dict[str, Any]]:
    """Generate VMA history snapshots using exactly the same 42-day window logic.

    Each snapshot uses _activities_in_vma_window(reference=snapshot_date).
    NO look-ahead: snapshot_date <= today.

    The last snapshot corresponds to today. Its VMA == estimate_vma(today).
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc).date()
    elif isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    snapshots = []
    for i in range(num_snapshots - 1, -1, -1):
        # Spread snapshots ~2 weeks apart over num_snapshots periods
        snapshot_date = reference_date - timedelta(days=i * 14)
        vma_est = estimate_vma(activities, reference_date=snapshot_date)
        window_acts = _activities_in_vma_window(activities, snapshot_date)
        snapshots.append({
            "date": snapshot_date.isoformat(),
            "vma_kmh": vma_est.vma_kmh,
            "confidence": vma_est.confidence,
            "reason_code": vma_est.reason_code,
            "sessions": len(window_acts),
            "window_days": VMA_WINDOW_DAYS,
        })
    return snapshots
