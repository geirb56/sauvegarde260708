from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from math import sqrt
from statistics import mean, median
from typing import TYPE_CHECKING, Iterable, List, Optional

if TYPE_CHECKING:
    from training_v2.domain_activity import DomainActivity


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 0.0
    return _clamp(((value - minimum) / (maximum - minimum)) * 100.0, 0.0, 100.0)


def _normalize_inverse(value: float, best: float, worst: float) -> float:
    if worst <= best:
        return 0.0
    return _clamp(((worst - value) / (worst - best)) * 100.0, 0.0, 100.0)


def _weighted_average(parts: list[tuple[float, float]]) -> float:
    """Weighted average over (score, weight) pairs.

    Zero-weight pairs are excluded. Returns 0.0 when no usable pair.
    """
    usable = [(score, weight) for score, weight in parts if weight > 0]
    if not usable:
        return 0.0
    total_weight = sum(weight for _, weight in usable)
    return sum(score * weight for score, weight in usable) / total_weight


def _weighted_average_nullable(parts: list[tuple[Optional[float], float]]) -> Optional[float]:
    """Weighted average over (score | None, weight) pairs.

    None scores are excluded from computation (renormalised weights).
    Returns None when no non-None score exists.
    """
    usable = [(score, weight) for score, weight in parts if score is not None and weight > 0]
    if not usable:
        return None
    total_weight = sum(weight for _, weight in usable)
    return sum(score * weight for score, weight in usable) / total_weight


def _safe_mean(values: Iterable[float]) -> Optional[float]:
    values = [value for value in values if value is not None]
    if not values:
        return None
    return mean(values)


def _safe_stdev(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return sqrt(variance)


def _parse_workout_date(raw_value: str) -> Optional[date]:
    if not raw_value:
        return None
    try:
        cleaned = raw_value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        try:
            return datetime.fromisoformat(raw_value.split("T")[0]).date()
        except ValueError:
            return None


def _is_running_workout(workout: dict) -> bool:
    workout_type = str(workout.get("type") or workout.get("activity_type") or "").lower()
    if workout_type in {"run", "running", "trail_running", "treadmill_running"}:
        return True
    name = str(workout.get("name") or "").lower()
    return "run" in workout_type or "course" in name or "running" in name


def _prepare_running_workouts(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> list[dict]:
    today = reference_date or datetime.now(timezone.utc).date()
    prepared: list[dict] = []

    for workout in workouts:
        if not _is_running_workout(workout):
            continue

        workout_date = _parse_workout_date(str(workout.get("date") or workout.get("start_time") or ""))
        if workout_date is None or workout_date > today:
            continue

        distance_km = workout.get("distance_km")
        if distance_km is None and workout.get("distance") is not None:
            distance_km = float(workout["distance"]) / 1000.0

        duration_minutes = workout.get("duration_minutes")
        if duration_minutes is None and workout.get("duration") is not None:
            duration_minutes = float(workout["duration"]) / 60.0

        if not distance_km or not duration_minutes or distance_km <= 0 or duration_minutes <= 0:
            continue

        avg_pace = workout.get("avg_pace_min_km")
        if avg_pace is None:
            avg_pace = duration_minutes / distance_km

        speed_kmh = workout.get("avg_speed_kmh")
        if speed_kmh is None and avg_pace:
            speed_kmh = 60.0 / avg_pace

        prepared.append(
            {
                "date": workout_date,
                "days_ago": (today - workout_date).days,
                "distance_km": float(distance_km),
                "duration_minutes": float(duration_minutes),
                "avg_pace_min_km": float(avg_pace) if avg_pace else None,
                "avg_speed_kmh": float(speed_kmh) if speed_kmh else None,
                "avg_heart_rate": workout.get("avg_heart_rate") or workout.get("avg_hr"),
                "effort_zone_distribution": workout.get("effort_zone_distribution") or {},
            }
        )

    prepared.sort(key=lambda item: item["date"], reverse=True)
    return prepared


def _confidence_from_count(count: int, target: int) -> float:
    if target <= 0:
        return 100.0
    return _clamp((count / target) * 100.0, 0.0, 100.0)


def _freshness_confidence(days_ago: Optional[int], full_confidence_days: int, zero_confidence_days: int) -> float:
    if days_ago is None:
        return 0.0
    if days_ago <= full_confidence_days:
        return 100.0
    if days_ago >= zero_confidence_days:
        return 0.0
    span = zero_confidence_days - full_confidence_days
    return _clamp(((zero_confidence_days - days_ago) / span) * 100.0, 0.0, 100.0)


# ---------------------------------------------------------------------------
# Speed
# ---------------------------------------------------------------------------

def calculate_speed_score(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    """Speed pillar.

    Components:
    - race_performance_score (60 %): best predicted time for 5K/10K/half
      within ±20 % of target distance in last 180 days.
    - speed_proxy_score (25 %): proxy based on estimated sustainable speed
      (NOT a measured VO2max). Named explicitly to avoid false physiological
      claims.
    - sustained_speed_score (15 %): best pace over a 20–75 min effort.
      NOT a lactate threshold. Renamed from threshold_score to avoid LT claims.

    Missing component → None → excluded from weighted average.
    """
    runs = _prepare_running_workouts(workouts, reference_date)
    recent_runs = [run for run in runs if run["days_ago"] <= 180]

    race_targets = [
        ("10k", 10.0, 30.0, 80.0),
        ("5k", 5.0, 14.0, 45.0),
        ("half_marathon", 21.1, 66.0, 180.0),
    ]

    race_score: Optional[float] = None
    race_confidence = 0.0
    race_source = None
    race_date_gap = None
    for race_name, distance_target, elite_time, beginner_time in race_targets:
        candidates = []
        for run in recent_runs:
            distance = run["distance_km"]
            if abs(distance - distance_target) / distance_target > 0.2:
                continue
            pace = run["avg_pace_min_km"]
            if pace is None:
                continue
            predicted_time = pace * distance_target
            candidates.append((predicted_time, run))
        if candidates:
            best_time, best_run = min(candidates, key=lambda item: item[0])
            race_score = _normalize_inverse(best_time, elite_time, beginner_time)
            race_date_gap = best_run["days_ago"]
            race_confidence = _weighted_average(
                [
                    (_freshness_confidence(best_run["days_ago"], 45, 180), 0.6),
                    (_confidence_from_count(len(candidates), 2), 0.4),
                ]
            )
            race_source = race_name
            break

    # speed_proxy_score: proxy for sustainable speed based on effort duration.
    # This is NOT a physiological VO2max measurement — it is an internal proxy only.
    speed_proxy_candidates = []
    for run in recent_runs:
        speed = run["avg_speed_kmh"]
        duration = run["duration_minutes"]
        if speed is None or duration < 6:
            continue
        if duration >= 20:
            estimated_vma_proxy = speed / 0.85
        elif duration >= 12:
            estimated_vma_proxy = speed / 0.90
        else:
            estimated_vma_proxy = speed / 0.95
        speed_proxy_candidates.append((estimated_vma_proxy * 3.5, run))

    speed_proxy_score: Optional[float] = None
    speed_proxy_confidence = 0.0
    if speed_proxy_candidates:
        best_proxy, best_proxy_run = max(speed_proxy_candidates, key=lambda item: item[0])
        speed_proxy_score = _normalize(best_proxy, 32.0, 75.0)
        speed_proxy_confidence = _weighted_average(
            [
                (_confidence_from_count(len(speed_proxy_candidates), 4), 0.5),
                (_freshness_confidence(best_proxy_run["days_ago"], 30, 180), 0.5),
            ]
        )

    # sustained_speed_score: best pace over 20–75 min effort.
    # NOT a lactate threshold measurement. Renamed to avoid LT1/LT2 claims.
    sustained_candidates = [
        run for run in recent_runs if 20 <= run["duration_minutes"] <= 75 and run["avg_speed_kmh"] is not None
    ]
    sustained_speed_score: Optional[float] = None
    sustained_confidence = 0.0
    if sustained_candidates:
        best_run = max(sustained_candidates, key=lambda run: run["avg_speed_kmh"])
        sustained_speed_score = _normalize(best_run["avg_speed_kmh"], 8.5, 18.0)
        sustained_confidence = _weighted_average(
            [
                (_confidence_from_count(len(sustained_candidates), 4), 0.6),
                (_freshness_confidence(best_run["days_ago"], 30, 180), 0.4),
            ]
        )

    score = _weighted_average_nullable(
        [
            (race_score, 0.60),
            (speed_proxy_score, 0.25),
            (sustained_speed_score, 0.15),
        ]
    )
    # Confidence: only components that contributed are included.
    confidence = _weighted_average_nullable(
        [
            (race_confidence if race_score is not None else None, 0.60),
            (speed_proxy_confidence if speed_proxy_score is not None else None, 0.25),
            (sustained_confidence if sustained_speed_score is not None else None, 0.15),
        ]
    )
    if confidence is None:
        confidence = 0.0

    return {
        "score": None if score is None else int(round(score)),
        "confidence": int(round(confidence)),
        "components": {
            "race_performance_score": None if race_score is None else int(round(race_score)),
            "speed_proxy_score": None if speed_proxy_score is None else int(round(speed_proxy_score)),
            "sustained_speed_score": None if sustained_speed_score is None else int(round(sustained_speed_score)),
            "race_source": race_source,
            "days_since_race_performance": race_date_gap,
        },
    }


# ---------------------------------------------------------------------------
# Endurance
# ---------------------------------------------------------------------------

def calculate_endurance_score(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    """Endurance pillar.

    Components (renormalised when unavailable):
    - long_run_score     45 %: longest run in last 30 days
    - volume_score       35 %: weekly km average
    - long_run_frequency 20 %: number of long runs in last 30 days

    NOTE: pace variability between long runs is NOT used as a durability
    proxy — it was unreliable and has been removed.

    Missing component → None → excluded from weighted average.
    """
    runs = _prepare_running_workouts(workouts, reference_date)
    recent_runs = [run for run in runs if run["days_ago"] <= 30]

    if not recent_runs:
        return {
            "score": None,
            "confidence": 0,
            "components": {
                "long_run_score": None,
                "volume_score": None,
                "long_run_frequency_score": None,
                "longest_run_km": None,
                "weekly_km": None,
                "long_run_count_30d": 0,
            },
        }

    distances = [run["distance_km"] for run in recent_runs]
    longest_run = max(distances)
    weekly_km = sum(distances) * 7.0 / 30.0
    long_run_score: Optional[float] = _normalize(longest_run, 6.0, 32.0)
    volume_score: Optional[float] = _normalize(weekly_km, 15.0, 110.0)

    long_runs = [run for run in recent_runs if run["distance_km"] >= max(12.0, longest_run * 0.7)]
    long_run_frequency_score: Optional[float] = _normalize(len(long_runs), 0.0, 4.0)

    score = _weighted_average_nullable(
        [
            (long_run_score, 0.45),
            (volume_score, 0.35),
            (long_run_frequency_score, 0.20),
        ]
    )
    confidence = _weighted_average(
        [
            (_confidence_from_count(len(recent_runs), 8), 0.5),
            (_confidence_from_count(len(long_runs), 3), 0.5),
        ]
    )

    return {
        "score": None if score is None else int(round(score)),
        "confidence": int(round(confidence)),
        "components": {
            "long_run_score": None if long_run_score is None else int(round(long_run_score)),
            "volume_score": None if volume_score is None else int(round(volume_score)),
            "long_run_frequency_score": None if long_run_frequency_score is None else int(round(long_run_frequency_score)),
            "longest_run_km": round(longest_run, 1),
            "weekly_km": round(weekly_km, 1),
            "long_run_count_30d": len(long_runs),
        },
    }


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------

def calculate_consistency_score(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    """Consistency pillar — 8-week window (56 days).

    Components (renormalised when unavailable):
    - frequency_score  40 %: active weeks + avg runs/week
    - stability_score  40 %: weekly volume CV — None when not computable
    - habit_score      20 %: avg and max gap between sessions — None when
                              fewer than 2 sessions (no gaps exist)

    RULE: unknown gap → None, never 14 or 21.
    RULE: unknown stability → None, never 35.
    """
    runs = _prepare_running_workouts(workouts, reference_date)
    recent_runs = [run for run in runs if run["days_ago"] <= 56]

    if not recent_runs:
        return {
            "score": None,
            "confidence": 0,
            "components": {
                "frequency_score": None,
                "stability_score": None,
                "habit_score": None,
                "active_weeks_8w": 0,
                "avg_runs_per_week": 0.0,
                "max_gap_days": None,
            },
        }

    today = reference_date or datetime.now(timezone.utc).date()
    weekly_runs: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for week_offset in range(8):
        week_date = today - timedelta(days=week_offset * 7)
        weekly_runs[(week_date.isocalendar().year, week_date.isocalendar().week)] = []
    for run in recent_runs:
        key = (run["date"].isocalendar().year, run["date"].isocalendar().week)
        if key in weekly_runs:
            weekly_runs[key].append(run)

    week_buckets = list(weekly_runs.values())
    active_weeks = sum(1 for bucket in week_buckets if bucket)
    runs_per_week = [len(bucket) for bucket in week_buckets]
    weekly_distances = [sum(run["distance_km"] for run in bucket) for bucket in week_buckets]

    avg_runs_per_week = sum(runs_per_week) / 8.0
    frequency_score: Optional[float] = (
        0.5 * _normalize(active_weeks, 2.0, 8.0) + 0.5 * _normalize(avg_runs_per_week, 1.0, 6.0)
    )

    # Stability: None when weekly volume variation cannot be computed.
    stability_score: Optional[float] = None
    distance_mean = _safe_mean(weekly_distances) or 0.0
    if distance_mean > 0:
        weekly_stdev = _safe_stdev(weekly_distances)
        if weekly_stdev is not None:
            distance_cv = weekly_stdev / distance_mean
            stability_score = _normalize_inverse(distance_cv, 0.10, 1.10)

    # Habit score: gaps between sessions. None when fewer than 2 sessions.
    habit_score: Optional[float] = None
    max_gap: Optional[int] = None
    avg_gap: Optional[float] = None
    if len(recent_runs) >= 2:
        sorted_dates = sorted(run["date"] for run in recent_runs)
        gaps = [
            (sorted_dates[index + 1] - sorted_dates[index]).days
            for index in range(len(sorted_dates) - 1)
        ]
        if gaps:
            avg_gap = _safe_mean(gaps)
            max_gap = max(gaps)
            habit_score = (
                0.6 * _normalize_inverse(avg_gap, 1.5, 8.5)
                + 0.4 * _normalize_inverse(float(max_gap), 3.0, 18.0)
            )

    confidence = _weighted_average(
        [
            (_confidence_from_count(len(recent_runs), 16), 0.5),
            (_confidence_from_count(active_weeks, 6), 0.5),
        ]
    )

    score = _weighted_average_nullable(
        [
            (frequency_score, 0.40),
            (stability_score, 0.40),
            (habit_score, 0.20),
        ]
    )

    return {
        "score": None if score is None else int(round(score)),
        "confidence": int(round(confidence)),
        "components": {
            "frequency_score": None if frequency_score is None else int(round(frequency_score)),
            "stability_score": None if stability_score is None else int(round(stability_score)),
            "habit_score": None if habit_score is None else int(round(habit_score)),
            "active_weeks_8w": active_weeks,
            "avg_runs_per_week": round(avg_runs_per_week, 2),
            "max_gap_days": max_gap,
        },
    }


# ---------------------------------------------------------------------------
# Efficiency
# ---------------------------------------------------------------------------

def calculate_efficiency_score(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    """Efficiency pillar — 56-day window.

    Components:
    - pace_heart_rate_score                 (score): median speed/HR ratio across HR-tagged runs.
    - inter_run_efficiency_variability_score (informational only): dispersion of speed/HR
      proxy across long runs (≥40 min). NOT used in score aggregation — provided
      for observability only.
      NOTE: This is NOT cardiac drift. It measures dispersion of the speed/HR
      proxy BETWEEN sessions, not within a single session. A true intra-session
      cardiac drift measure requires time-series or split data not available in
      DomainActivity.

    RULE: absence of HR data → efficiency_score = None, never 0.
    """
    runs = _prepare_running_workouts(workouts, reference_date)
    recent_runs = [run for run in runs if run["days_ago"] <= 56]

    efficiency_runs = [
        run
        for run in recent_runs
        if run["avg_speed_kmh"] is not None and run["avg_heart_rate"] not in (None, 0)
    ]

    if not efficiency_runs:
        # No HR data at all → entire pillar is None.
        return {
            "score": None,
            "confidence": 0,
            "components": {
                "pace_heart_rate_score": None,
                "inter_run_efficiency_variability_score": None,
                "heart_rate_sample_count": 0,
            },
        }

    efficiency_indexes = [
        (run["avg_speed_kmh"] * 1000.0) / float(run["avg_heart_rate"])
        for run in efficiency_runs
    ]

    pace_hr_score: Optional[float] = _normalize(median(efficiency_indexes), 55.0, 90.0)

    # inter_run_efficiency_variability: dispersion of speed/HR proxy across long runs.
    # NOT cardiac drift (which requires intra-session time series or splits).
    # Informational only — included in components but NOT in score aggregation,
    # because high variability from adding better runs would penalise improvement.
    inter_run_variability_candidates = [
        (run["avg_speed_kmh"] * 1000.0) / float(run["avg_heart_rate"])
        for run in efficiency_runs
        if run["duration_minutes"] >= 40
    ]
    inter_run_variability_score: Optional[float] = None
    inter_run_cv = None
    if len(inter_run_variability_candidates) >= 2:
        variability_stdev = _safe_stdev(inter_run_variability_candidates)
        variability_mean = mean(inter_run_variability_candidates)
        if variability_stdev is not None and variability_mean:
            inter_run_cv = variability_stdev / variability_mean
        if inter_run_cv is not None:
            inter_run_variability_score = _normalize_inverse(inter_run_cv, 0.02, 0.18)

    # Score: based on median speed/HR only (monotonic: better ratio → better score).
    score: Optional[float] = pace_hr_score

    # Confidence: based only on real data availability.
    confidence = _confidence_from_count(len(efficiency_runs), 8)

    return {
        "score": None if score is None else int(round(score)),
        "confidence": int(round(confidence)),
        "components": {
            "pace_heart_rate_score": None if pace_hr_score is None else int(round(pace_hr_score)),
            "inter_run_efficiency_variability_score": None if inter_run_variability_score is None else int(round(inter_run_variability_score)),
            "heart_rate_sample_count": len(efficiency_runs),
        },
    }


# ---------------------------------------------------------------------------
# INSUFFICIENT gate
# ---------------------------------------------------------------------------

_MIN_ACTIVITIES = 3
_MIN_PILLARS = 2

STATUS_SUFFICIENT = "sufficient"
STATUS_INSUFFICIENT = "insufficient"


def _is_sufficient(run_count: int, pillar_scores: list[Optional[int]]) -> bool:
    """Return True when the INSUFFICIENT gate is satisfied.

    Gate:
    - At least _MIN_ACTIVITIES valid running activities in scope
    - At least _MIN_PILLARS pillars with a non-None score
    """
    if run_count < _MIN_ACTIVITIES:
        return False
    calculable = sum(1 for s in pillar_scores if s is not None)
    return calculable >= _MIN_PILLARS


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def calculate_run_index(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    """Compute RunIndex from a list of workout dicts.

    Output contract:
    {
        "status": "sufficient" | "insufficient",
        "run_index": int (0–1000) | null,
        "speed_score": int (0–100) | null,
        "endurance_score": int (0–100) | null,
        "consistency_score": int (0–100) | null,
        "efficiency_score": int (0–100) | null,
        "confidence_score": int (0–100),
        "pillar_details": {...}
    }

    Rules:
    - INSUFFICIENT gate not met → run_index = null, status = "insufficient".
    - Missing pillar → excluded from weighted average (renormalised).
    - Missing pillar → never replaced with 0.
    - Confidence based only on real data quality and quantity.
    """
    speed = calculate_speed_score(workouts, reference_date)
    endurance = calculate_endurance_score(workouts, reference_date)
    consistency = calculate_consistency_score(workouts, reference_date)
    efficiency = calculate_efficiency_score(workouts, reference_date)

    run_count = len(_prepare_running_workouts(workouts, reference_date))

    pillar_scores = [
        speed["score"],
        endurance["score"],
        consistency["score"],
        efficiency["score"],
    ]

    sufficient = _is_sufficient(run_count, pillar_scores)

    # Global confidence: weighted over contributing pillars only.
    confidence_raw = _weighted_average_nullable(
        [
            (speed["confidence"] if speed["score"] is not None else None, 0.40),
            (endurance["confidence"] if endurance["score"] is not None else None, 0.25),
            (consistency["confidence"] if consistency["score"] is not None else None, 0.20),
            (efficiency["confidence"] if efficiency["score"] is not None else None, 0.15),
        ]
    )
    if confidence_raw is None:
        confidence_raw = 0.0
    if run_count < 6:
        confidence_raw *= 0.75

    if not sufficient:
        return {
            "status": STATUS_INSUFFICIENT,
            "run_index": None,
            "speed_score": speed["score"],
            "endurance_score": endurance["score"],
            "consistency_score": consistency["score"],
            "efficiency_score": efficiency["score"],
            "confidence_score": int(round(_clamp(confidence_raw, 0.0, 100.0))),
            "pillar_details": {
                "speed": speed,
                "endurance": endurance,
                "consistency": consistency,
                "efficiency": efficiency,
            },
        }

    # Global RunIndex: weighted average of non-None pillar scores × 10.
    raw_index = _weighted_average_nullable(
        [
            (speed["score"], 0.40),
            (endurance["score"], 0.25),
            (consistency["score"], 0.20),
            (efficiency["score"], 0.15),
        ]
    )
    if raw_index is None:
        # Theoretically impossible when sufficient (≥2 pillars), but be safe.
        raw_index = 0.0

    return {
        "status": STATUS_SUFFICIENT,
        "run_index": int(round(_clamp(raw_index * 10.0, 0.0, 1000.0))),
        "speed_score": speed["score"],
        "endurance_score": endurance["score"],
        "consistency_score": consistency["score"],
        "efficiency_score": efficiency["score"],
        "confidence_score": int(round(_clamp(confidence_raw, 0.0, 100.0))),
        "pillar_details": {
            "speed": speed,
            "endurance": endurance,
            "consistency": consistency,
            "efficiency": efficiency,
        },
    }


# ---------------------------------------------------------------------------
# DomainActivity → engine boundary (PR179 canonical path)
# ---------------------------------------------------------------------------
_RUNNING_ACTIVITY_TYPES = frozenset({
    "run", "running", "trail_running", "treadmill_running",
})


def _domain_activity_to_workout_dict(activity: "DomainActivity") -> Optional[dict]:
    """Convert a DomainActivity to the internal workout dict understood by the engine.

    Rules (PR179):
    - Only running activity types are accepted; others return None.
    - distance_m → distance_km at the engine boundary only.
    - duration_s → duration_minutes at the engine boundary only.
    - None remains None; 0 is never fabricated.
    - average_hr is preserved as-is (None when absent).
    """
    act_type = (activity.activity_type or "").lower()
    if act_type not in _RUNNING_ACTIVITY_TYPES:
        return None

    if activity.distance_m is None or activity.duration_s is None:
        return None
    if activity.distance_m <= 0 or activity.duration_s <= 0:
        return None

    distance_km = activity.distance_m / 1000.0
    duration_minutes = activity.duration_s / 60.0
    avg_pace = duration_minutes / distance_km
    speed_kmh = 60.0 / avg_pace

    start = activity.start_time
    if start is None:
        return None
    if isinstance(start, str):
        start_str = start
    elif hasattr(start, "isoformat"):
        start_str = start.isoformat()
    else:
        return None

    avg_hr: Optional[float] = activity.average_hr  # None when absent — never 0

    return {
        "type": "run",
        "activity_type": "run",
        "start_time": start_str,
        "date": start_str,
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "avg_pace_min_km": avg_pace,
        "avg_speed_kmh": speed_kmh,
        "avg_heart_rate": avg_hr,
        # source fields — informational, not used by scoring
        "source": activity.source,
        "source_activity_id": activity.source_activity_id,
    }


def prepare_workout_dicts_from_domain(
    activities: "List[DomainActivity]",
) -> list[dict]:
    """Convert a list of DomainActivities to engine workout dicts.

    Non-running or incomplete activities produce no entry (filtered out).
    Pure function — no I/O, deterministic.
    """
    result = []
    for act in activities:
        item = _domain_activity_to_workout_dict(act)
        if item is not None:
            result.append(item)
    return result


def calculate_run_index_from_domain(
    activities: "List[DomainActivity]",
    reference_date: Optional[date] = None,
) -> dict:
    """Canonical RunIndex entry point: list[DomainActivity] → RunIndex score.

    This is the PR179 canonical runtime path:
        garmin_activities → mongo_garmin_activities_to_domain → DomainActivity
        → calculate_run_index_from_domain

    The formula, weights, and thresholds are identical to calculate_run_index().
    The only difference is the data source: DomainActivity fields are converted
    to internal workout dicts at the engine boundary; no db.workouts involved.

    Pure, deterministic, no I/O.
    """
    workout_dicts = prepare_workout_dicts_from_domain(activities)
    return calculate_run_index(workout_dicts, reference_date)
