"""Read-only adapter for the normalized Garmin activity_laps schema v1.

Only consecutive measured kilometres can populate km_splits. A measured tail
is validated for coverage but not published as a kilometre. Eligibility is not
evidence of a continuous session.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any


@dataclass(frozen=True)
class GarminLapSplits:
    status: str
    km_splits: list[dict[str, Any]] = field(default_factory=list)


def _positive(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _timestamp(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Invalid GMT timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("Invalid GMT offset")
    return parsed


def adapt_garmin_laps(workout: dict, activity_doc: dict) -> GarminLapSplits:
    """Return eligible UI rows or an explicit abstention; never mutate inputs.

    Input: activity_laps {schema_version: 1, status: complete, source: garmin,
    endpoint: splits, laps: [...]}. Required lap fields: lap_index (positive
    integer, strictly increasing, gaps allowed), order (nonnegative integer,
    strictly increasing), distance_m and duration_s > 0.
    Output rows carry ordinal km, original distance_m/duration_s, min/km pace
    calculated from those measurements, and nullable measured avg_hr (bpm).
    The km ordinal is the measured position, never the native lap_index.

    Only explicit ACTIVE or absent intensity is eligible. The producer has no
    intensity enum; the repository fixture demonstrates ACTIVE, not all Garmin
    runtime values. Other explicit values fail closed without a semantic mapping.
    Missing intensity never establishes a continuous-session classification.

    Full laps and cumulative km boundaries allow 1 m recording error; only the
    last lap may be shorter (excluded from output). Coverage reconciles to the summary within 5 m
    (distance_km rounded to .01 km) and 30 s (whole-minute duration). These are
    representation allowances, not interpolation or physiological thresholds.
    """
    if not (
        str(workout.get("id") or "").startswith("garmin-")
        or str(workout.get("data_source") or "").lower() == "garmin"
    ):
        return GarminLapSplits("not_garmin")
    cache = activity_doc.get("activity_laps")
    if cache is None:
        return GarminLapSplits("missing")
    if not isinstance(cache, dict) or (
        type(cache.get("schema_version")) is not int
        or cache["schema_version"] != 1
        or cache.get("source") != "garmin" or cache.get("endpoint") != "splits"
        or cache.get("status") not in ("complete", "empty")
    ):
        return GarminLapSplits("invalid_cache")
    laps = cache.get("laps")
    if cache["status"] == "empty" and laps == []:
        return GarminLapSplits("empty")
    if (cache["status"] != "complete" or not isinstance(laps, list)
            or not laps or len(laps) > 1000):
        return GarminLapSplits("invalid_cache")
    if not all(_positive(workout.get(key)) for key in ("distance_km", "duration_minutes")):
        return GarminLapSplits("missing_summary")

    rows = []
    total_distance = total_duration = 0.0
    previous_index = 0
    previous_order = -1
    first_start = previous_start = previous_elapsed = None
    total_elapsed = 0.0
    timestamps = [isinstance(lap, dict) and lap.get("start_time_gmt") is not None for lap in laps]
    if any(timestamps) and not all(timestamps):
        return GarminLapSplits("incomplete_chronology")
    try:
        for index, lap in enumerate(laps, 1):
            if not isinstance(lap, dict):
                return GarminLapSplits("invalid_lap")
            lap_index = lap.get("lap_index")
            order = lap.get("order")
            if (type(lap_index) is not int or lap_index <= previous_index
                    or type(order) is not int or order <= previous_order):
                return GarminLapSplits("invalid_order")
            previous_index = lap_index
            previous_order = order
            distance, duration = lap.get("distance_m"), lap.get("duration_s")
            if not _positive(distance) or not _positive(duration):
                return GarminLapSplits("invalid_measurement")
            for key in (
                "average_hr", "max_hr", "average_speed_mps", "average_moving_speed_mps",
                "max_speed_mps", "moving_duration_s", "elapsed_duration_s",
            ):
                if lap.get(key) is not None and not _positive(lap[key]):
                    return GarminLapSplits("invalid_measurement")
            if (lap.get("average_hr") is not None and lap.get("max_hr") is not None
                    and lap["average_hr"] > lap["max_hr"]):
                return GarminLapSplits("invalid_heart_rate")
            moving = lap.get("moving_duration_s")
            elapsed = lap.get("elapsed_duration_s")
            if ((moving is not None and moving > duration + 0.01)
                    or (elapsed is not None and elapsed < duration - 0.01)):
                return GarminLapSplits("incoherent_time")
            for key, seconds in (
                ("average_speed_mps", duration),
                ("average_moving_speed_mps", moving),
            ):
                if lap.get(key) is not None and seconds is not None and not math.isclose(
                    lap[key], distance / seconds, rel_tol=0.01,
                ):
                    return GarminLapSplits("incoherent_speed")
            if all(timestamps):
                start = _timestamp(lap["start_time_gmt"])
                if first_start is None:
                    first_start = start
                if previous_start is not None:
                    # Garmin start times may have only second precision. Bound
                    # both local and cumulative error so tolerance cannot accrue.
                    if (start < previous_start or not math.isclose(
                        (start - previous_start).total_seconds(), previous_elapsed,
                        rel_tol=0, abs_tol=1,
                    ) or not math.isclose(
                        (start - first_start).total_seconds(), total_elapsed,
                        rel_tol=0, abs_tol=1,
                    )):
                        return GarminLapSplits("incoherent_chronology")
                previous_start, previous_elapsed = start, elapsed if elapsed is not None else duration
                total_elapsed += previous_elapsed
            intensity = lap.get("intensity_type")
            if intensity is not None and intensity != "ACTIVE":
                return GarminLapSplits("non_kilometric")
            total_distance += distance
            total_duration += duration
            full_km = math.isclose(distance, 1000, rel_tol=0, abs_tol=1)
            if not full_km and (index != len(laps) or distance >= 999):
                return GarminLapSplits("non_kilometric")
            if full_km and not math.isclose(total_distance, index * 1000, rel_tol=0, abs_tol=1):
                return GarminLapSplits("non_kilometric")
            pace = duration / (distance / 1000) / 60
            if not _positive(pace):
                return GarminLapSplits("invalid_measurement")
            if full_km:
                rows.append({
                    "km": index, "distance_m": distance, "duration_s": duration,
                    "pace_min_km": pace, "avg_hr": lap.get("average_hr"),
                })
        if not math.isclose(total_distance, workout["distance_km"] * 1000, rel_tol=0, abs_tol=5):
            return GarminLapSplits("incoherent_distance")
        if not math.isclose(total_duration, workout["duration_minutes"] * 60, rel_tol=0, abs_tol=30):
            return GarminLapSplits("incoherent_duration")
    except (OverflowError, TypeError, ValueError, ZeroDivisionError):
        return GarminLapSplits("invalid_measurement")
    # A lone partial lap is not a kilometre split.
    if not rows:
        return GarminLapSplits("non_kilometric")
    return GarminLapSplits("eligible", rows)
