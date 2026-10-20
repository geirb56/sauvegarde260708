"""Read-only adapter for the normalized Garmin activity_laps schema v1.

Only consecutive measured kilometres can populate km_splits. A measured tail
is validated for coverage but not published as a kilometre. Eligibility is not
evidence of a continuous session.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any

# Chronology tolerance shared by km splits and structure assessment (C349-A).
CHRONOLOGY_TOLERANCE_S = 1
# Representation allowances for a summary rounded to 0.01 km / whole minutes.
SUMMARY_DISTANCE_TOLERANCE_M = 5
SUMMARY_DURATION_TOLERANCE_S = 30

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
                        rel_tol=0, abs_tol=CHRONOLOGY_TOLERANCE_S,
                    ) or not math.isclose(
                        (start - first_start).total_seconds(), total_elapsed,
                        rel_tol=0, abs_tol=CHRONOLOGY_TOLERANCE_S,
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
        if not math.isclose(total_distance, workout["distance_km"] * 1000, rel_tol=0,
                            abs_tol=SUMMARY_DISTANCE_TOLERANCE_M):
            return GarminLapSplits("incoherent_distance")
        if not math.isclose(total_duration, workout["duration_minutes"] * 60, rel_tol=0,
                            abs_tol=SUMMARY_DURATION_TOLERANCE_S):
            return GarminLapSplits("incoherent_duration")
    except (OverflowError, TypeError, ValueError, ZeroDivisionError):
        return GarminLapSplits("invalid_measurement")
    # A lone partial lap is not a kilometre split.
    if not rows:
        return GarminLapSplits("non_kilometric")
    return GarminLapSplits("eligible", rows)


# Final blocking reason whenever activity_laps v1 is otherwise fully coherent:
# laps are aggregates without lap trigger or sub-lap samples, so an effort /
# recovery alternation inside a lap can never be excluded from them.
LAP_ALTERNATION_UNOBSERVABLE = "intra_lap_alternation_unobservable"


@dataclass(frozen=True)
class LapStructureAssessment:
    """Read-only diagnostic of what activity_laps v1 can prove about structure.

    ``status`` is always "unknown": the schema carries no positive evidence of
    continuity (no lap trigger, no sub-lap series, ``intensity_type`` ACTIVE is
    also what an unstructured fartlek records). ``reasons`` lists every
    observed blocker, in a fixed order; it never classifies a session.
    """
    status: str = "unknown"
    reasons: tuple = ()
    lap_count: int = 0


def assess_lap_structure(workout: dict, activity_doc: Any) -> LapStructureAssessment:
    """Deterministically audit laps for structure evidence; never mutate inputs.

    Checked in order: Garmin origin, cache envelope, summary, lap validity,
    chronology (same 1 s tolerance as km splits), pauses / stationary time,
    explicit intensity, coverage of the summary. No pace, heart-rate or
    physiological threshold is used: lap homogeneity is never evidence.
    """
    def result(*reasons, count=0):
        return LapStructureAssessment(reasons=tuple(reasons), lap_count=count)

    if not (
        str(workout.get("id") or "").startswith("garmin-")
        or str(workout.get("data_source") or "").lower() == "garmin"
    ):
        return result("not_garmin")
    if not isinstance(activity_doc, dict):
        return result("activity_missing")
    cache = activity_doc.get("activity_laps")
    if cache is None:
        return result("laps_missing")
    if not isinstance(cache, dict) or (
        type(cache.get("schema_version")) is not int or cache["schema_version"] != 1
        or cache.get("source") != "garmin" or cache.get("endpoint") != "splits"
    ):
        return result("laps_invalid")
    laps = cache.get("laps")
    if cache.get("status") == "empty" and laps == []:
        return result("laps_empty")
    if (cache.get("status") != "complete" or not isinstance(laps, list)
            or not laps or len(laps) > 1000):
        return result("laps_invalid")
    count = len(laps)
    if not all(_positive(workout.get(key)) for key in ("distance_km", "duration_minutes")):
        return result("summary_missing", count=count)

    reasons = []
    previous_index, previous_order = 0, -1
    total_distance = total_duration = 0.0
    try:
        for lap in laps:
            if not isinstance(lap, dict):
                return result("laps_invalid", count=count)
            lap_index, order = lap.get("lap_index"), lap.get("order")
            if (type(lap_index) is not int or lap_index <= previous_index
                    or type(order) is not int or order <= previous_order):
                return result("laps_invalid", count=count)
            previous_index, previous_order = lap_index, order
            distance, duration = lap.get("distance_m"), lap.get("duration_s")
            if not _positive(distance) or not _positive(duration):
                return result("laps_invalid", count=count)
            for key in ("moving_duration_s", "elapsed_duration_s", "average_speed_mps"):
                if lap.get(key) is not None and not _positive(lap[key]):
                    return result("laps_invalid", count=count)
            if lap.get("average_speed_mps") is not None and not math.isclose(
                lap["average_speed_mps"], distance / duration, rel_tol=0.01,
            ):
                return result("laps_invalid", count=count)
            total_distance += distance
            total_duration += duration

        # Chronology: every lap must start where the previous one ended.
        stamps = [lap.get("start_time_gmt") for lap in laps]
        if all(stamp is None for stamp in stamps):
            reasons.append("chronology_missing")
        elif any(stamp is None for stamp in stamps):
            reasons.append("chronology_incomplete")
        else:
            first = previous = _timestamp(stamps[0])
            elapsed_total = 0.0
            previous_elapsed = None
            for lap, stamp in zip(laps, stamps):
                start = _timestamp(stamp)
                if previous_elapsed is not None and (
                    start < previous or not math.isclose(
                        (start - previous).total_seconds(), previous_elapsed,
                        rel_tol=0, abs_tol=CHRONOLOGY_TOLERANCE_S,
                    ) or not math.isclose(
                        (start - first).total_seconds(), elapsed_total,
                        rel_tol=0, abs_tol=CHRONOLOGY_TOLERANCE_S,
                    )
                ):
                    reasons.append("chronology_incoherent")
                    break
                previous = start
                elapsed_value = lap.get("elapsed_duration_s")
                previous_elapsed = elapsed_value if elapsed_value is not None else lap["duration_s"]
                elapsed_total += previous_elapsed

        # Pauses and stationary time: absence of the fields is not absence of pauses.
        moving = [lap.get("moving_duration_s") for lap in laps]
        elapsed = [lap.get("elapsed_duration_s") for lap in laps]
        if any(value is None for value in moving + elapsed):
            reasons.append("pause_unverifiable")
        if any(value is not None and value > lap["duration_s"] + 0.01
               for lap, value in zip(laps, moving)) or any(
            value is not None and value < lap["duration_s"] - 0.01
            for lap, value in zip(laps, elapsed)
        ):
            reasons.append("time_incoherent")
        if any(value is not None and value > lap["duration_s"] + 0.01
               for lap, value in zip(laps, elapsed)):
            reasons.append("pause_recorded")
        if any(value is not None and value < lap["duration_s"] - 0.01
               for lap, value in zip(laps, moving)):
            reasons.append("stationary_time_recorded")

        # Explicit intensities are opaque source values: a non-ACTIVE value is a
        # possible alternation hint, never mapped to effort or recovery.
        intensities = [lap.get("intensity_type") for lap in laps]
        if any(value is None for value in intensities):
            reasons.append("intensity_missing")
        if any(value is not None and value != "ACTIVE" for value in intensities):
            reasons.append("intensity_variation_recorded")

        if not (
            math.isclose(total_distance, workout["distance_km"] * 1000, rel_tol=0,
                         abs_tol=SUMMARY_DISTANCE_TOLERANCE_M)
            and math.isclose(total_duration, workout["duration_minutes"] * 60, rel_tol=0,
                             abs_tol=SUMMARY_DURATION_TOLERANCE_S)
        ):
            reasons.append("coverage_incomplete")
    except (OverflowError, TypeError, ValueError, ZeroDivisionError):
        return result("laps_invalid", count=count)
    reasons.append(LAP_ALTERNATION_UNOBSERVABLE)
    return result(*reasons, count=count)
