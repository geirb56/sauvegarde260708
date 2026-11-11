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


# ---------------------------------------------------------------------------
# C420 — observed fast/slow lap pattern (inferred, never a recorded phase)
# ---------------------------------------------------------------------------
LAP_PATTERN_SCHEMA = "garmin_lap_pattern_v1"
# Detection parameters (not physiological thresholds): they only decide whether
# the laps show a repeatable alternation. Failing them yields "no pattern".
PATTERN_MIN_REPETITIONS = 3
PATTERN_MIN_PACE_CONTRAST = 0.10      # slow cluster at least 10 % slower than the fast one
PATTERN_DURATION_TOLERANCE_S = 10     # same-role laps must match within max(10 s, 15 %)
PATTERN_DURATION_TOLERANCE_RATIO = 0.15
PATTERN_ABERRANT_PACE_RATIO = 3.0     # lap pace > 3x or < 1/3 of the median lap pace is aberrant
# C420B: Garmin start times carry second precision, so consecutive starts may differ from the
# previous elapsed time by rounding (up to 2 s). This is independent from the 1 s pause /
# kilometre-split tolerance (CHRONOLOGY_TOLERANCE_S). Cumulative drift may grow by 0.25 s per lap.
TIMESTAMP_ROUNDING_TOLERANCE_S = 2
TIMESTAMP_DRIFT_PER_LAP_S = 0.25
PAUSE_TOLERANCE_S = CHRONOLOGY_TOLERANCE_S
CHRONOLOGY_MAX_BREAK_RATIO = 0.25     # more broken junctions than this: chronology unusable
PARTIAL_COVERAGE_MIN_RATIO = 0.5      # laps must cover at least half of the summary to be exploited
_BLOCKING_REASONS = frozenset({
    "not_garmin", "activity_missing", "laps_missing", "laps_invalid", "laps_empty",
    "summary_missing", "time_incoherent",
})


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _near(value, reference):
    return abs(value - reference) <= max(
        PATTERN_DURATION_TOLERANCE_S, PATTERN_DURATION_TOLERANCE_RATIO * reference)


def _two_means(paces):
    """Deterministic 1-D split minimising within-cluster variance; None when degenerate."""
    order = sorted(range(len(paces)), key=lambda i: (paces[i], i))
    best = None
    for cut in range(1, len(order)):
        groups = (order[:cut], order[cut:])
        cost = 0.0
        for group in groups:
            mean = sum(paces[i] for i in group) / len(group)
            cost += sum((paces[i] - mean) ** 2 for i in group)
        if best is None or cost < best[0] - 1e-9:
            best = (cost, cut)
    if best is None:
        return None
    return set(order[:best[1]]), set(order[best[1]:])


def _valid_hr(value):
    """Heart rate in bpm only when strictly positive and finite; otherwise unknown (never 0)."""
    return value if _positive(value) else None


def _segment(lap, position):
    distance, duration = lap["distance_m"], lap["duration_s"]
    return {
        "lap_position": position,
        "duration_s": round(duration, 1),
        "length_m": round(distance, 1),
        "pace_sec_per_km": round(duration / distance * 1000, 1),
        "avg_hr_bpm": _valid_hr(lap.get("average_hr")),
    }


def _block(laps, first, last):
    """Aggregate of consecutive laps first..last (0-based, inclusive) with measured values only."""
    chunk = laps[first:last + 1]
    distance = sum(lap["distance_m"] for lap in chunk)
    duration = sum(lap["duration_s"] for lap in chunk)
    return {
        "first_lap_position": first + 1, "last_lap_position": last + 1,
        "lap_count": len(chunk),
        "duration_s": round(duration, 1), "length_m": round(distance, 1),
        "pace_sec_per_km": round(duration / distance * 1000, 1),
    }


def _role_summary(segments):
    hrs = [s["avg_hr_bpm"] for s in segments]
    summary = {
        "typical_duration_s": round(_median([s["duration_s"] for s in segments]), 1),
        "typical_pace_sec_per_km": round(_median([s["pace_sec_per_km"] for s in segments]), 1),
        "segments": segments,
    }
    if all(hr is not None for hr in hrs):
        summary["avg_hr_first_bpm"] = hrs[0]
        summary["avg_hr_last_bpm"] = hrs[-1]
        summary["avg_hr_change_first_to_last_bpm"] = round(hrs[-1] - hrs[0], 1)
        summary["hr_evolution_available"] = True
    else:
        summary["hr_evolution_available"] = False
    return summary


def _chronology_breaks(laps):
    """Lap positions whose start does not follow the previous lap (real gap or overlap).

    Rounding up to TIMESTAMP_ROUNDING_TOLERANCE_S is accepted locally; cumulative drift is
    measured from the last break so a break never hides behind earlier rounding. Returns
    (breaks, junctions); breaks maps position -> "gap" | "overlap". Callers guarantee that
    every start_time_gmt is present and valid.
    """
    stamps = [lap.get("start_time_gmt") for lap in laps]
    if any(stamp is None for stamp in stamps):
        return {}, 0
    starts = [_timestamp(stamp) for stamp in stamps]
    breaks = {}
    anchor, cumulative = 0, 0.0
    for i in range(1, len(laps)):
        previous = laps[i - 1]
        step = previous["elapsed_duration_s"] if previous.get("elapsed_duration_s") is not None \
            else previous["duration_s"]
        cumulative += step
        local = (starts[i] - starts[i - 1]).total_seconds() - step
        drift = (starts[i] - starts[anchor]).total_seconds() - cumulative
        allowed = TIMESTAMP_ROUNDING_TOLERANCE_S + TIMESTAMP_DRIFT_PER_LAP_S * (i - 1 - anchor)
        if starts[i] < starts[i - 1] or abs(local) > TIMESTAMP_ROUNDING_TOLERANCE_S or abs(drift) > allowed:
            signed = local if abs(local) > TIMESTAMP_ROUNDING_TOLERANCE_S else drift
            breaks[i] = "gap" if signed > 0 else "overlap"
            anchor, cumulative = i, 0.0
    return breaks, len(laps) - 1


def _unknown(status, reason, lap_count=0, anomalies=()):
    return {
        "schema": LAP_PATTERN_SCHEMA, "status": status, "reason": reason,
        "source": "garmin_activity_laps_inferred", "lap_count": lap_count,
        "anomalies": list(anomalies),
    }


def _chains(laps, fast, slow, breaks=frozenset()):
    """Maximal runs of fast laps separated by exactly one slow lap, duration-consistent."""
    runs, current = [], []
    for position in sorted(fast):
        if (current and position - current[-1] == 2 and (position - 1) in slow
                and (position - 1) not in breaks and position not in breaks):
            current.append(position)
        else:
            if current:
                runs.append(current)
            current = [position]
    if current:
        runs.append(current)

    def split(run, durations):
        if not run:
            return []
        reference = _median([durations(p) for p in run])
        out, part = [], []
        for p in run:
            if _near(durations(p), reference):
                part.append(p)
            else:
                if part:
                    out.append(part)
                part = []
        if part:
            out.append(part)
        return out

    result = []
    for run in runs:
        for part in split(run, lambda p: laps[p]["duration_s"]):
            gaps = part[:-1]
            if gaps:
                reference = _median([laps[p + 1]["duration_s"] for p in gaps])
                piece = [part[0]]
                for before, after in zip(part, part[1:]):
                    if _near(laps[before + 1]["duration_s"], reference):
                        piece.append(after)
                    else:
                        result.append(piece)
                        piece = [after]
                result.append(piece)
            else:
                result.append(part)
    return result


def detect_lap_pattern(workout: dict, activity_doc: Any) -> dict:
    """Deterministically describe a repeated fast/slow lap alternation; read-only.

    Works on cached activity_laps v1 only (no Garmin call). The result is an
    inference from lap aggregates: it is never a recorded Garmin phase, never a
    prescription, and a slow lap is never called a programmed recovery. Pauses
    (recorded pause or stationary time) are not slow laps and break the chain.
    Anything not provable returns status "unknown"/"unavailable"; nothing is
    interpolated or invented. Laps never replace the kilometre splits.
    """
    assessment = assess_lap_structure(workout, activity_doc)
    blocking = [r for r in assessment.reasons if r in _BLOCKING_REASONS]
    if blocking:
        return _unknown("unavailable", blocking[0], assessment.lap_count)
    laps = activity_doc["activity_laps"]["laps"]
    count = len(laps)
    anomalies = []
    # C420B: chronology and coverage are judged locally here; the shared assessment
    # (C350) keeps its strict 1 s rule and is not weakened.
    try:
        breaks, junctions = _chronology_breaks(laps)
    except (OverflowError, TypeError, ValueError):
        return _unknown("unavailable", "laps_invalid", count)
    if junctions and len(breaks) > CHRONOLOGY_MAX_BREAK_RATIO * junctions:
        return _unknown("unavailable", "chronology_incoherent", count)
    for position, kind in sorted(breaks.items()):
        anomalies.append({"code": "chronology_" + kind, "lap_position": position + 1})
    covered_m = sum(lap["distance_m"] for lap in laps)
    covered_s = sum(lap["duration_s"] for lap in laps)
    summary_m, summary_s = workout["distance_km"] * 1000, workout["duration_minutes"] * 60
    def coverage(covered, summary, tolerance):
        if abs(covered - summary) <= tolerance:
            return "full"
        if summary - tolerance > covered >= PARTIAL_COVERAGE_MIN_RATIO * summary:
            return "partial"
        return "incomplete"

    states = (coverage(covered_m, summary_m, SUMMARY_DISTANCE_TOLERANCE_M),
              coverage(covered_s, summary_s, SUMMARY_DURATION_TOLERANCE_S))
    if "incomplete" in states:
        return _unknown("unavailable", "coverage_incomplete", count)
    partial = "partial" in states
    if partial:
        anomalies.append({
            "code": "laps_cover_partial_session",
            "covered_distance_ratio": round(covered_m / summary_m, 3),
            "covered_duration_ratio": round(covered_s / summary_s, 3),
        })
    if "chronology_missing" in assessment.reasons or "chronology_incomplete" in assessment.reasons:
        anomalies.append({"code": "chronology_unverified"})
    if "pause_unverifiable" in assessment.reasons:
        anomalies.append({"code": "pause_unverifiable"})
    labels = sorted({lap.get("intensity_type") for lap in laps if lap.get("intensity_type") not in (None, "ACTIVE")})
    if labels:
        anomalies.append({
            "code": "intensity_labels_recorded_not_interpreted", "labels": labels,
            "lap_positions_by_label": {
                label: [i + 1 for i, lap in enumerate(laps) if lap.get("intensity_type") == label]
                for label in labels},
        })

    if count < 2 * PATTERN_MIN_REPETITIONS - 1:
        return _unknown("unknown", "too_few_laps", count, anomalies)
    if all(math.isclose(lap["distance_m"], 1000, rel_tol=0, abs_tol=1) for lap in laps[:-1]):
        return _unknown("unknown", "kilometre_laps_hide_intra_lap_structure", count, anomalies)

    # Pauses, stationary time and aberrant laps are never effort or slow laps: they
    # are excluded from clustering and break any chain. The tolerance is the
    # chronology tolerance shared with the structure assessment, not a percentage.
    excluded = set()
    for position, lap in enumerate(laps):
        elapsed, moving = lap.get("elapsed_duration_s"), lap.get("moving_duration_s")
        if elapsed is not None and elapsed - lap["duration_s"] > PAUSE_TOLERANCE_S:
            excluded.add(position)
            anomalies.append({"code": "recorded_pause", "lap_position": position + 1})
        elif moving is not None and lap["duration_s"] - moving > PAUSE_TOLERANCE_S:
            excluded.add(position)
            anomalies.append({"code": "stationary_time", "lap_position": position + 1})
    all_paces = [lap["duration_s"] / lap["distance_m"] * 1000 for lap in laps]
    reference = _median(all_paces)
    for position, pace in enumerate(all_paces):
        if position not in excluded and (
                pace > PATTERN_ABERRANT_PACE_RATIO * reference
                or pace < reference / PATTERN_ABERRANT_PACE_RATIO):
            excluded.add(position)
            anomalies.append({"code": "aberrant_lap", "lap_position": position + 1})

    usable = [i for i in range(count) if i not in excluded]
    paces = {i: all_paces[i] for i in usable}
    if len(usable) < 2 * PATTERN_MIN_REPETITIONS - 1:
        return _unknown("unknown", "too_few_usable_laps", count, anomalies)
    split = _two_means([paces[i] for i in usable])
    if split is None:
        return _unknown("unknown", "no_pace_contrast", count, anomalies)
    fast = {usable[i] for i in split[0]}
    slow = {usable[i] for i in split[1]}
    contrast = (min(paces[i] for i in slow) - max(paces[i] for i in fast)) / max(paces[i] for i in fast)
    if contrast < PATTERN_MIN_PACE_CONTRAST:
        return _unknown("no_pattern_observed", "no_pace_contrast", count, anomalies)

    chains = [c for c in _chains(laps, fast, slow, breaks) if len(c) >= PATTERN_MIN_REPETITIONS]
    if not chains:
        return _unknown("no_pattern_observed", "no_repeated_alternation", count, anomalies)
    chain = max(chains, key=lambda c: (len(c), -c[0]))

    fast_segments = [_segment(laps[p], p + 1) for p in chain]
    between = [_segment(laps[p + 1], p + 2) for p in chain[:-1]]
    after = chain[-1] + 1
    if after < count and after in slow and after not in breaks and _near(
            laps[after]["duration_s"], _median([s["duration_s"] for s in between])):
        between.append(_segment(laps[after], after + 1))
        after += 1
    pattern = {
        "type": "fast_slow_alternation",
        "repetition_count": len(chain),
        "first_lap_position": chain[0] + 1,
        "last_lap_position": after,
        "fast_segments": _role_summary(fast_segments),
        "slow_segments": _role_summary(between),
        "pace_contrast_ratio": round(contrast, 3),
        "slow_segments_meaning": "observed slower laps between fast laps; not proof of a programmed recovery",
    }
    # A final lap is incomplete only relative to the efforts it resembles: a short
    # but complete repetition matching the others stays inside the chain.
    last = count - 1
    if last >= after and last in fast and last not in excluded and laps[last]["duration_s"] < _median(
            [s["duration_s"] for s in fast_segments]) and not _near(
            laps[last]["duration_s"], _median([s["duration_s"] for s in fast_segments])):
        anomalies.append({"code": "incomplete_final_lap", "lap_position": count})

    # Surrounding roles are assigned only when every lap of the prefix/suffix is an
    # eligible slow lap; otherwise those laps stay unclassified.
    unclassified = []
    warmup = cooldown = None
    prefix, suffix = range(0, chain[0]), range(after, count)
    if prefix:
        if all(i in slow for i in prefix) and not partial and not any(
                i in breaks for i in range(1, chain[0] + 1)):
            warmup = {**_block(laps, 0, chain[0] - 1),
                      "basis": "laps before the first repeated fast lap; not a recorded phase"}
        else:
            unclassified.extend(i + 1 for i in prefix)
    if suffix:
        if all(i in slow for i in suffix) and not partial and not any(
                i in breaks for i in range(after, count)):
            cooldown = {**_block(laps, after, count - 1),
                        "basis": "laps after the last repeated segment; not a recorded phase"}
        else:
            unclassified.extend(i + 1 for i in suffix)
    if unclassified:
        anomalies.append({"code": "laps_outside_pattern_unclassified", "lap_positions": unclassified})

    confidence = "medium"
    if len(chain) >= 4 and contrast >= 0.20 and not anomalies:
        confidence = "high"
    elif any(a["code"] in ("recorded_pause", "stationary_time", "aberrant_lap", "incomplete_final_lap",
                           "laps_outside_pattern_unclassified", "laps_cover_partial_session",
                           "chronology_gap", "chronology_overlap") for a in anomalies):
        confidence = "low"
    result = {
        "schema": LAP_PATTERN_SCHEMA, "status": "pattern_observed",
        "source": "garmin_activity_laps_inferred",
        "basis": "inferred from lap aggregates; not a Garmin-recorded phase or a prescription",
        "lap_count": count,
        "confidence": confidence,
        "pattern": pattern,
        "anomalies": anomalies,
    }
    if warmup:
        result["probable_warmup"] = warmup
    if cooldown:
        result["probable_cooldown"] = cooldown
    return result
