"""Performance Model V2 — Pure business logic for VMA estimation and race predictions.

This module is intentionally I/O-free:
  - No Mongo / database calls
  - No FastAPI / HTTP
  - No datetime.now() (reference_date is always an explicit parameter)
  - No references to the workouts collection

Inputs:
    List[DomainActivity]   — running activities already filtered to the user
    reference_date         — the "now" snapshot date (date or datetime)

Outputs (dataclasses, not Pydantic, to keep this layer dependency-free):
    VMAEstimate
    RacePrediction
    PerformanceEstimate
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional, Union

from training_v2.domain_activity import DomainActivity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Running activity types (case-normalised)
_RUNNING_TYPES = {
    "running", "run", "trail_running", "treadmill_running",
    "indoor_running", "track_running",
}

# Riegel exponent k — conservative, well-documented value
RIEGEL_K: float = 1.06

# Minimum duration (seconds) for an effort to be considered informative
MIN_INFORMATIVE_DURATION_S: float = 5 * 60  # 5 minutes

# Minimum distance (metres) for an effort to be considered
MIN_DISTANCE_M: float = 500.0

# Plausible speed bounds (km/h) for a running activity
MIN_SPEED_KMH: float = 3.0
MAX_SPEED_KMH: float = 30.0

# Staleness thresholds (days)
CONFIDENCE_HIGH_DAYS = 21
CONFIDENCE_MEDIUM_DAYS = 56
CONFIDENCE_LOW_DAYS = 120

# Target race distances (m)
RACE_DISTANCES_M = {
    "5K": 5_000.0,
    "10K": 10_000.0,
    "Semi": 21_097.5,
    "Marathon": 42_195.0,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_date(value: Union[str, date, datetime, None]) -> Optional[date]:
    """Coerce a start_time value to a ``date``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:19], fmt[:len(value[:19])]).date()
            except ValueError:
                pass
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
    """Compute average speed (km/h) from distance_m / duration_s."""
    if not a.distance_m or not a.duration_s:
        return None
    if a.distance_m <= 0 or a.duration_s <= 0:
        return None
    return (a.distance_m / 1000.0) / (a.duration_s / 3600.0)


def _days_ago(activity_date: date, reference_date: date) -> int:
    return (reference_date - activity_date).days


def _validate_activity(a: DomainActivity, reference_date: date) -> bool:
    """Return True if the activity is a valid running candidate."""
    if not _is_running(a):
        return False
    d = _activity_date(a)
    if d is None:
        return False
    # Future activities are excluded
    if d > reference_date:
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
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VMAEstimate:
    """VMA estimation result.

    vma_kmh=None means insufficient data to estimate.
    """
    vma_kmh: Optional[float]
    confidence: str  # "high" | "medium" | "low" | "insufficient"
    method: Optional[str]  # e.g. "riegel_from_5K", "direct_effort_12min"
    source_activity_date: Optional[date]
    source_distance_m: Optional[float]
    source_duration_s: Optional[float]
    model_version: str = "v2"

    @property
    def has_data(self) -> bool:
        return self.vma_kmh is not None


@dataclass(frozen=True)
class RacePrediction:
    """Predicted race time for a single distance."""
    distance_label: str        # "5K" | "10K" | "Semi" | "Marathon"
    distance_km: float
    predicted_time_s: Optional[float]   # None = insufficient data
    predicted_time_str: Optional[str]   # "1h23" | "45:30" | None
    predicted_pace_str: Optional[str]   # "5:30/km" | None
    confidence: str                     # "high" | "medium" | "low" | "insufficient"
    readiness: str                      # "ready" | "possible" | "challenging" | "not_ready"
    readiness_label: str
    readiness_color: str
    readiness_score: int                # 0-100
    endurance_factor: int               # 0-100
    volume_factor: int                  # 0-100
    source_distance_m: Optional[float]
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
# Candidate selection
# ---------------------------------------------------------------------------


def _select_best_performance(
    activities: List[DomainActivity],
    reference_date: date,
) -> Optional[DomainActivity]:
    """Select the single most informative recent running performance.

    Priority rules:
    1. Effort >= 5 minutes with the highest average speed (most informative
       physiologically because it required sustained aerobic output).
    2. A short effort can be informative if duration >= MIN_INFORMATIVE_DURATION_S.
    3. Never select based solely on distance + duration with no plausibility check.
    4. Among equally informative efforts, prefer more recent ones.

    Returns None when no activity passes the filters (VMA = null).
    """
    candidates = [a for a in activities if _validate_activity(a, reference_date)]
    if not candidates:
        return None

    # Filter to efforts >= MIN_INFORMATIVE_DURATION_S
    informative = [a for a in candidates if (a.duration_s or 0) >= MIN_INFORMATIVE_DURATION_S]
    if not informative:
        return None

    # Sort by speed DESC, then by date DESC (prefer recent among equal speed)
    def sort_key(a: DomainActivity):
        spd = _speed_kmh(a) or 0.0
        d = _activity_date(a) or date.min
        return (spd, d.toordinal())

    return max(informative, key=sort_key)


# ---------------------------------------------------------------------------
# VMA estimation
# ---------------------------------------------------------------------------


def _vma_confidence(days: int, duration_s: float) -> str:
    """Determine confidence level from staleness and effort duration."""
    if days > CONFIDENCE_LOW_DAYS:
        return "low"
    # A longer effort is a more reliable proxy: >= 20 min is direct estimation territory
    if days <= CONFIDENCE_HIGH_DAYS and duration_s >= 20 * 60:
        return "high"
    if days <= CONFIDENCE_MEDIUM_DAYS and duration_s >= 10 * 60:
        return "medium"
    if days <= CONFIDENCE_MEDIUM_DAYS:
        return "medium"
    return "low"


def estimate_vma(
    activities: List[DomainActivity],
    reference_date: Union[date, datetime],
) -> VMAEstimate:
    """Estimate VMA from a list of DomainActivity objects.

    The algorithm:
    - Selects the best informative running performance (see _select_best_performance).
    - Never uses avg_speed divided by 0.70 as a fallback (removed per spec).
    - If no informative effort exists, returns VMAEstimate(vma_kmh=None, ...).
    - VMA is computed as speed / fraction_of_vma, where fraction depends on
      effort duration (longer effort → closer to aerobic max).
    """
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    best = _select_best_performance(activities, reference_date)
    if best is None:
        return VMAEstimate(
            vma_kmh=None,
            confidence="insufficient",
            method=None,
            source_activity_date=None,
            source_distance_m=None,
            source_duration_s=None,
        )

    speed = _speed_kmh(best)
    duration_s = best.duration_s or 0.0
    duration_min = duration_s / 60.0

    # Fraction of VMA sustained during an effort of this duration.
    # Derived from well-established exercise physiology:
    #   >= 60 min → ~78 % VMA  (long tempo / threshold)
    #   >= 20 min → ~85 % VMA  (threshold run)
    #   >= 12 min → ~90 % VMA  (cruise interval / time trial)
    #   >= 5 min  → ~95 % VMA  (short hard effort)
    if duration_min >= 60:
        fraction = 0.78
        method = f"direct_effort_{int(duration_min)}min_78pct"
    elif duration_min >= 20:
        fraction = 0.85
        method = f"direct_effort_{int(duration_min)}min_85pct"
    elif duration_min >= 12:
        fraction = 0.90
        method = f"direct_effort_{int(duration_min)}min_90pct"
    else:
        fraction = 0.95
        method = f"direct_effort_{int(duration_min)}min_95pct"

    vma_kmh = round(speed / fraction, 2)

    act_date = _activity_date(best)
    days = _days_ago(act_date, reference_date) if act_date else 999
    confidence = _vma_confidence(days, duration_s)

    return VMAEstimate(
        vma_kmh=vma_kmh,
        confidence=confidence,
        method=method,
        source_activity_date=act_date,
        source_distance_m=best.distance_m,
        source_duration_s=duration_s,
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
    """Return an endurance adjustment factor in [0, 1].

    Uses relative signals from the athlete's own history:
    - recent weekly volume (km/week over last 28 days)
    - longest single run in the window
    - ratio of target distance to longest supported distance

    The factor is monotone, bounded [0,1], and approaches 1.0 when the athlete
    regularly runs close to the target distance.
    """
    cutoff = date.fromordinal(reference_date.toordinal() - window_days)
    recent = [
        a for a in activities
        if _validate_activity(a, reference_date)
        and (_activity_date(a) or date.min) >= cutoff
    ]

    if not recent:
        return 0.5  # conservative default, not zero

    # Weekly volume — last 28 days
    cutoff_28 = date.fromordinal(reference_date.toordinal() - 28)
    recent_28 = [a for a in recent if (_activity_date(a) or date.min) >= cutoff_28]
    weekly_km = sum((a.distance_m or 0) for a in recent_28) / 1000.0 / 4.0

    # Longest single run
    max_run_m = max((a.distance_m or 0) for a in recent)

    # For short races (<= 10K), endurance support is nearly always full
    if target_distance_m <= 10_000:
        return 1.0

    # For longer races, penalise if long runs are well below the target
    # Use a sigmoid-like transition between 0.6 and 1.0
    ratio = min(max_run_m / target_distance_m, 1.0)  # 0–1

    # Volume signal: penalise if weekly volume < target_distance_m / 1000 * 0.5
    target_km = target_distance_m / 1000.0
    vol_ratio = min(weekly_km / max(target_km * 0.5, 1.0), 1.0)

    # Combine — both signals matter equally
    raw = (ratio * 0.6 + vol_ratio * 0.4)
    # Monotone, bounded: map [0,1] → [0.55, 1.0] to avoid catastrophic penalties
    support = 0.55 + raw * 0.45
    return round(min(max(support, 0.55), 1.0), 4)


# ---------------------------------------------------------------------------
# Riegel extrapolation
# ---------------------------------------------------------------------------


def _riegel(t1_s: float, d1_m: float, d2_m: float, k: float = RIEGEL_K) -> float:
    """Riegel formula: T2 = T1 × (D2/D1)^k."""
    if d1_m <= 0 or d2_m <= 0 or t1_s <= 0:
        raise ValueError("All values must be positive")
    return t1_s * (d2_m / d1_m) ** k


def _riegel_confidence(
    source_distance_m: float,
    target_distance_m: float,
    days_since_source: int,
    endurance_factor: float,
) -> str:
    """Confidence degrades with large extrapolation gap, staleness, and low endurance."""
    ratio = target_distance_m / source_distance_m
    if ratio > 4.0 or days_since_source > CONFIDENCE_LOW_DAYS or endurance_factor < 0.65:
        return "low"
    if ratio > 2.0 or days_since_source > CONFIDENCE_MEDIUM_DAYS or endurance_factor < 0.80:
        return "medium"
    return "high"


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


def _readiness(score: float) -> tuple[str, str, str]:
    if score >= 0.80:
        return "ready", "Prêt", "#22c55e"
    if score >= 0.60:
        return "possible", "Possible", "#f59e0b"
    if score >= 0.40:
        return "challenging", "Ambitieux", "#f97316"
    return "not_ready", "Pas prêt", "#ef4444"


# ---------------------------------------------------------------------------
# Race predictions V2
# ---------------------------------------------------------------------------


def predict_races(
    activities: List[DomainActivity],
    reference_date: Union[date, datetime],
) -> PerformanceEstimate:
    """Compute VMA V2 estimate and race predictions V2.

    Uses the observed best performance as source, not VMA-derived formulas.
    Extrapolates using Riegel with endurance adjustment for longer races.
    Never invents predictions when data is insufficient.
    """
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    vma_est = estimate_vma(activities, reference_date)

    if not vma_est.has_data:
        return PerformanceEstimate(
            has_data=False,
            vma=vma_est,
            predictions=[],
        )

    # Source performance: use the same activity that produced the VMA estimate
    source_duration_s = vma_est.source_duration_s or 0.0
    source_distance_m = vma_est.source_distance_m or 0.0
    source_date = vma_est.source_activity_date
    days_since_source = _days_ago(source_date, reference_date) if source_date else 999

    # Build weekly volume & long-run stats for athlete profile
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

        # Riegel extrapolation from source performance
        try:
            raw_time_s = _riegel(source_duration_s, source_distance_m, dist_m)
        except (ValueError, ZeroDivisionError):
            predictions.append(RacePrediction(
                distance_label=label,
                distance_km=dist_m / 1000.0,
                predicted_time_s=None,
                predicted_time_str=None,
                predicted_pace_str=None,
                confidence="insufficient",
                readiness="not_ready",
                readiness_label="Pas prêt",
                readiness_color="#ef4444",
                readiness_score=0,
                endurance_factor=0,
                volume_factor=0,
                source_distance_m=source_distance_m,
            ))
            continue

        # Apply endurance penalty (multiplicative slowdown factor)
        # endurance=1.0 → no penalty; endurance=0.55 → ~18 % slower
        # penalty = 1 + (1 - endurance) * 0.4  maps [0.55, 1.0] → [1.18, 1.0]
        endurance_penalty = 1.0 + (1.0 - endurance) * 0.4
        adjusted_time_s = raw_time_s * endurance_penalty

        # Volume factor for readiness display
        target_km = dist_m / 1000.0
        vol_factor = min(weekly_km / max(target_km * 0.5, 1.0), 1.0)

        readiness_score_raw = endurance * 0.6 + vol_factor * 0.4
        r_key, r_label, r_color = _readiness(readiness_score_raw)

        conf = _riegel_confidence(source_distance_m, dist_m, days_since_source, endurance)

        predictions.append(RacePrediction(
            distance_label=label,
            distance_km=dist_m / 1000.0,
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
        ))

    # VO2max note: documented as derived estimate, NOT a Garmin/lab measurement
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
        "source_date": source_date.isoformat() if source_date else None,
        "source_distance_km": round(source_distance_m / 1000.0, 2) if source_distance_m else None,
        "calculation_window": "garmin_activities (all available)",
        "model_version": "v2",
    }

    return PerformanceEstimate(
        has_data=True,
        vma=vma_est,
        predictions=predictions,
        athlete_profile=athlete_profile,
    )
