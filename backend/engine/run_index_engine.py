from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from math import sqrt
from statistics import mean, median
from typing import Iterable, Optional


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
    usable = [(score, weight) for score, weight in parts if weight > 0]
    if not usable:
        return 0.0
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


def calculate_speed_score(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    runs = _prepare_running_workouts(workouts, reference_date)
    recent_runs = [run for run in runs if run["days_ago"] <= 180]

    race_targets = [
        ("10k", 10.0, 30.0, 80.0),
        ("5k", 5.0, 14.0, 45.0),
        ("half_marathon", 21.1, 66.0, 180.0),
    ]

    race_score = None
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

    vo2_candidates = []
    for run in recent_runs:
        speed = run["avg_speed_kmh"]
        duration = run["duration_minutes"]
        if speed is None or duration < 6:
            continue
        if duration >= 20:
            estimated_vma = speed / 0.85
        elif duration >= 12:
            estimated_vma = speed / 0.90
        else:
            estimated_vma = speed / 0.95
        vo2_candidates.append((estimated_vma * 3.5, run))

    vo2_score = None
    vo2_confidence = 0.0
    if vo2_candidates:
        best_vo2, best_vo2_run = max(vo2_candidates, key=lambda item: item[0])
        vo2_score = _normalize(best_vo2, 32.0, 75.0)
        vo2_confidence = _weighted_average(
            [
                (_confidence_from_count(len(vo2_candidates), 4), 0.5),
                (_freshness_confidence(best_vo2_run["days_ago"], 30, 180), 0.5),
            ]
        )

    threshold_candidates = [
        run for run in recent_runs if 20 <= run["duration_minutes"] <= 75 and run["avg_speed_kmh"] is not None
    ]
    threshold_score = None
    threshold_confidence = 0.0
    if threshold_candidates:
        best_threshold_run = max(threshold_candidates, key=lambda run: run["avg_speed_kmh"])
        threshold_score = _normalize(best_threshold_run["avg_speed_kmh"], 8.5, 18.0)
        threshold_confidence = _weighted_average(
            [
                (_confidence_from_count(len(threshold_candidates), 4), 0.6),
                (_freshness_confidence(best_threshold_run["days_ago"], 30, 180), 0.4),
            ]
        )

    score = _weighted_average(
        [
            (race_score or 0.0, 0.60 if race_score is not None else 0.0),
            (vo2_score or 0.0, 0.25 if vo2_score is not None else 0.0),
            (threshold_score or 0.0, 0.15 if threshold_score is not None else 0.0),
        ]
    )
    confidence = _weighted_average(
        [
            (race_confidence, 0.60),
            (vo2_confidence, 0.25),
            (threshold_confidence, 0.15),
        ]
    )

    return {
        "score": int(round(score)),
        "confidence": int(round(confidence)),
        "components": {
            "race_performance_score": None if race_score is None else int(round(race_score)),
            "vo2max_score": None if vo2_score is None else int(round(vo2_score)),
            "threshold_score": None if threshold_score is None else int(round(threshold_score)),
            "race_source": race_source,
            "days_since_race_performance": race_date_gap,
        },
    }


def calculate_endurance_score(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    runs = _prepare_running_workouts(workouts, reference_date)
    recent_runs = [run for run in runs if run["days_ago"] <= 30]

    if not recent_runs:
        return {
            "score": 0,
            "confidence": 0,
            "components": {"long_run_score": None, "volume_score": None, "durability_score": None},
        }

    distances = [run["distance_km"] for run in recent_runs]
    longest_run = max(distances)
    weekly_km = sum(distances) * 7.0 / 30.0
    long_run_score = _normalize(longest_run, 6.0, 32.0)
    volume_score = _normalize(weekly_km, 15.0, 110.0)

    long_runs = [run for run in recent_runs if run["distance_km"] >= max(12.0, longest_run * 0.7)]
    long_run_frequency_score = _normalize(len(long_runs), 0.0, 4.0)
    long_run_paces = [run["avg_pace_min_km"] for run in long_runs if run["avg_pace_min_km"]]
    long_run_cv = None
    if len(long_run_paces) >= 2:
        long_run_mean_pace = mean(long_run_paces)
        stdev = _safe_stdev(long_run_paces)
        long_run_cv = (stdev / long_run_mean_pace) if stdev is not None and long_run_mean_pace else None
    pace_stability_score = 60.0 if long_run_cv is None else _normalize_inverse(long_run_cv, 0.02, 0.18)
    durability_score = 0.65 * long_run_frequency_score + 0.35 * pace_stability_score

    confidence = _weighted_average(
        [
            (_confidence_from_count(len(recent_runs), 8), 0.4),
            (_confidence_from_count(len(long_runs), 3), 0.3),
            (100.0 if long_run_cv is not None else 55.0, 0.3),
        ]
    )
    score = 0.40 * long_run_score + 0.30 * volume_score + 0.30 * durability_score

    return {
        "score": int(round(score)),
        "confidence": int(round(confidence)),
        "components": {
            "long_run_score": int(round(long_run_score)),
            "volume_score": int(round(volume_score)),
            "durability_score": int(round(durability_score)),
            "longest_run_km": round(longest_run, 1),
            "weekly_km": round(weekly_km, 1),
            "long_run_count_30d": len(long_runs),
        },
    }


def calculate_consistency_score(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    runs = _prepare_running_workouts(workouts, reference_date)
    recent_runs = [run for run in runs if run["days_ago"] <= 56]

    if not recent_runs:
        return {
            "score": 0,
            "confidence": 0,
            "components": {"frequency_score": None, "stability_score": None, "habit_score": None},
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
    frequency_score = 0.5 * _normalize(active_weeks, 2.0, 8.0) + 0.5 * _normalize(avg_runs_per_week, 1.0, 6.0)

    distance_mean = _safe_mean(weekly_distances) or 0.0
    distance_cv = None
    if distance_mean > 0:
        weekly_stdev = _safe_stdev(weekly_distances)
        if weekly_stdev is not None:
            distance_cv = weekly_stdev / distance_mean
    stability_score = 35.0 if distance_cv is None else _normalize_inverse(distance_cv, 0.10, 1.10)

    sorted_dates = sorted(run["date"] for run in recent_runs)
    gaps = [
        (sorted_dates[index + 1] - sorted_dates[index]).days
        for index in range(len(sorted_dates) - 1)
    ]
    avg_gap = _safe_mean(gaps) or 14.0
    max_gap = max(gaps) if gaps else 21
    habit_score = 0.6 * _normalize_inverse(avg_gap, 1.5, 8.5) + 0.4 * _normalize_inverse(max_gap, 3.0, 18.0)

    confidence = _weighted_average(
        [
            (_confidence_from_count(len(recent_runs), 16), 0.5),
            (_confidence_from_count(active_weeks, 6), 0.3),
            (100.0 if len(gaps) >= 3 else 55.0, 0.2),
        ]
    )
    score = 0.40 * frequency_score + 0.40 * stability_score + 0.20 * habit_score

    return {
        "score": int(round(score)),
        "confidence": int(round(confidence)),
        "components": {
            "frequency_score": int(round(frequency_score)),
            "stability_score": int(round(stability_score)),
            "habit_score": int(round(habit_score)),
            "active_weeks_8w": active_weeks,
            "avg_runs_per_week": round(avg_runs_per_week, 2),
            "max_gap_days": max_gap,
        },
    }


def calculate_efficiency_score(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    runs = _prepare_running_workouts(workouts, reference_date)
    recent_runs = [run for run in runs if run["days_ago"] <= 56]

    efficiency_runs = [
        run
        for run in recent_runs
        if run["avg_speed_kmh"] is not None and run["avg_heart_rate"] not in (None, 0)
    ]
    efficiency_indexes = [
        (run["avg_speed_kmh"] * 1000.0) / float(run["avg_heart_rate"])
        for run in efficiency_runs
    ]

    pace_hr_score = None
    if efficiency_indexes:
        pace_hr_score = _normalize(median(efficiency_indexes), 55.0, 90.0)

    drift_candidates = [
        (run["avg_speed_kmh"] * 1000.0) / float(run["avg_heart_rate"])
        for run in efficiency_runs
        if run["duration_minutes"] >= 40
    ]
    drift_score = None
    drift_cv = None
    if len(drift_candidates) >= 2:
        drift_stdev = _safe_stdev(drift_candidates)
        drift_cv = (drift_stdev / mean(drift_candidates)) if drift_stdev is not None and mean(drift_candidates) else None
    if drift_cv is not None:
        drift_score = _normalize_inverse(drift_cv, 0.02, 0.18)

    stability_candidates = [
        run["avg_pace_min_km"]
        for run in recent_runs
        if run["avg_pace_min_km"] is not None and run["distance_km"] >= 5.0
    ]
    pace_stability_score = None
    pace_cv = None
    if len(stability_candidates) >= 2:
        pace_stdev = _safe_stdev(stability_candidates)
        pace_cv = (pace_stdev / mean(stability_candidates)) if pace_stdev is not None and mean(stability_candidates) else None
    if pace_cv is not None:
        pace_stability_score = _normalize_inverse(pace_cv, 0.03, 0.22)

    score = _weighted_average(
        [
            (pace_hr_score or 0.0, 0.50 if pace_hr_score is not None else 0.0),
            (drift_score or 0.0, 0.30 if drift_score is not None else 0.0),
            (pace_stability_score or 0.0, 0.20 if pace_stability_score is not None else 0.0),
        ]
    )
    confidence = _weighted_average(
        [
            (_confidence_from_count(len(efficiency_runs), 8), 0.5),
            (100.0 if drift_score is not None else 35.0, 0.3),
            (100.0 if pace_stability_score is not None else 45.0, 0.2),
        ]
    )

    return {
        "score": int(round(score)),
        "confidence": int(round(confidence)),
        "components": {
            "pace_heart_rate_score": None if pace_hr_score is None else int(round(pace_hr_score)),
            "cardiac_drift_score": None if drift_score is None else int(round(drift_score)),
            "pace_stability_score": None if pace_stability_score is None else int(round(pace_stability_score)),
            "heart_rate_sample_count": len(efficiency_runs),
        },
    }


def calculate_run_index(
    workouts: list[dict],
    reference_date: Optional[date] = None,
) -> dict:
    speed = calculate_speed_score(workouts, reference_date)
    endurance = calculate_endurance_score(workouts, reference_date)
    consistency = calculate_consistency_score(workouts, reference_date)
    efficiency = calculate_efficiency_score(workouts, reference_date)

    run_count = len(_prepare_running_workouts(workouts, reference_date))
    if run_count == 0:
        return {
            "run_index": 0,
            "speed_score": 0,
            "endurance_score": 0,
            "consistency_score": 0,
            "efficiency_score": 0,
            "confidence_score": 0,
            "pillar_details": {
                "speed": speed,
                "endurance": endurance,
                "consistency": consistency,
                "efficiency": efficiency,
            },
        }

    raw_index = (
        0.40 * speed["score"]
        + 0.25 * endurance["score"]
        + 0.20 * consistency["score"]
        + 0.15 * efficiency["score"]
    ) * 10.0
    confidence = _weighted_average(
        [
            (speed["confidence"], 0.40),
            (endurance["confidence"], 0.25),
            (consistency["confidence"], 0.20),
            (efficiency["confidence"], 0.15),
        ]
    )
    if run_count < 6:
        confidence *= 0.75

    return {
        "run_index": int(round(_clamp(raw_index, 0.0, 1000.0))),
        "speed_score": int(round(_clamp(speed["score"], 0.0, 100.0))),
        "endurance_score": int(round(_clamp(endurance["score"], 0.0, 100.0))),
        "consistency_score": int(round(_clamp(consistency["score"], 0.0, 100.0))),
        "efficiency_score": int(round(_clamp(efficiency["score"], 0.0, 100.0))),
        "confidence_score": int(round(_clamp(confidence, 0.0, 100.0))),
        "pillar_details": {
            "speed": speed,
            "endurance": endurance,
            "consistency": consistency,
            "efficiency": efficiency,
        },
    }
