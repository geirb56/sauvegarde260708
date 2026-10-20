"""Deterministic, evidence-bound display language; never a prescription engine."""

from itertools import combinations
import math
from statistics import mean, median
from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Display-only reuse of V2's 0.4 min/km change boundary. Not a physiological limit.
PACE_DISPLAY_CHANGE_SEC_KM = 24.0
# The workout summary may round duration_minutes to the nearest whole minute.
# This absolute representation allowance must not grow with session duration.
WORKOUT_DURATION_ROUNDING_TOLERANCE_S = 30.0
# Reconcile independently rounded pace/distance observations, not physiology.
MEASUREMENT_RECONCILIATION_REL_TOL = 0.01


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value):
    return _finite(value) and value > 0


def _matches_workout_duration(duration_s, duration_minutes):
    return (
        _positive(duration_s) and _positive(duration_minutes)
        and _positive(duration_minutes * 60)
        and math.isclose(duration_s, duration_minutes * 60, rel_tol=0,
                         abs_tol=WORKOUT_DURATION_ROUNDING_TOLERANCE_S + 1e-8)
    )


class CoachConclusionV1(BaseModel):
    code: str
    text: str
    evidence: Dict[str, float]
    metadata: Dict[str, str] = Field(default_factory=dict)
    category: Literal["execution", "repetitions", "pacing", "history"]
    priority: int
    available: bool = True
    kind: Literal["conclusion", "descriptive"] = "conclusion"
    replaces_factual_codes: List[str] = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def _valid_evidence(cls, value):
        if not isinstance(value, dict) or not value or not all(
            _finite(item) for item in value.values()
        ):
            raise ValueError("Coach conclusions require finite numeric evidence")
        return value


class CoachLanguageV1(BaseModel):
    version: Literal["v1"] = "v1"
    conclusions: List[CoachConclusionV1] = Field(default_factory=list, max_length=3)
    limitations: List[str] = Field(default_factory=list)


class RepetitionJudgmentConfig(BaseModel):
    """Descriptive display bands, not training targets or physiological limits."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    homogeneous_relative: float = Field(default=0.01, gt=0)
    variable_relative: float = Field(default=0.04, gt=0)
    rounding_floor_sec_km: float = Field(default=1.0, gt=0)
    pace_uncertainty_sec_km: float = Field(default=0.5, ge=0)
    atypical_relative: float = Field(default=0.04, gt=0)
    atypical_floor_sec_km: float = Field(default=3.0, gt=0)
    trend_relative: float = Field(default=0.02, gt=0)

    @model_validator(mode="after")
    def _ordered_bands(self):
        if self.variable_relative <= self.homogeneous_relative:
            raise ValueError("Regularity bands must be increasing")
        return self


def _repetition_judgment(phases, cohort, basis, comparable, language, config):
    """Interpret V2's individual paces without changing its legacy statistics."""
    if not phases.available or not phases.phases:
        return None, "repetitions.phases_unavailable"
    if len(phases.efforts) < 2:
        return None, "repetitions.insufficient_efforts"
    orders = [phase.order for phase in phases.phases]
    if any(order < 0 for order in orders) or any(
        right <= left for left, right in zip(orders, orders[1:])
    ):
        return None, "repetitions.unreliable_order"
    if (
        [phase for phase in phases.phases if phase.phase_type == "effort"] != phases.efforts
        or any(phase.phase_type == "unknown" for phase in phases.phases
               if phases.efforts[0].order < phase.order < phases.efforts[-1].order)
        or "incoherent_pace" in phases.limitations
    ):
        return None, "repetitions.incoherent_structure"
    if any(
        not all(_positive(value) for value in (
            phase.duration_s, phase.distance_m, phase.pace_sec_per_km,
        ))
        or (phase.average_speed_mps is not None and not _positive(phase.average_speed_mps))
        for phase in phases.efforts
    ):
        return None, "repetitions.invalid_measurements"
    if (
        len(cohort) != len(phases.efforts) or basis is None
        or not all(comparable(left, right, basis) for left, right in combinations(cohort, 2))
    ):
        return None, "repetitions.insufficient_comparability"
    # V2 permits a 20% speed/distance discrepancy for factual observations.
    # A categorical judgment needs the tighter existing display reconciliation.
    if any(
        not math.isclose(phase.pace_sec_per_km, phase.duration_s * 1000 / phase.distance_m,
                         rel_tol=MEASUREMENT_RECONCILIATION_REL_TOL)
        for phase in cohort
    ):
        return None, "repetitions.imprecise_measurements"

    paces = [phase.pace_sec_per_km for phase in cohort]
    reference = median(paces)
    # L1 dispersion uses EVERY effort. Median anchoring and linear deviations
    # reduce sensitivity to extremes versus the legacy squared-deviation metric.
    dispersion = mean(abs(pace - reference) for pace in paces)
    low = max(config.rounding_floor_sec_km, config.homogeneous_relative * reference)
    high = max(2 * config.rounding_floor_sec_km, config.variable_relative * reference)
    uncertainty = config.pace_uncertainty_sec_km
    error = uncertainty * (2 + config.variable_relative)
    if len(paces) >= 3 and uncertainty and any(
        abs(dispersion - boundary) <= error for boundary in (low, high)
    ):
        return None, "repetitions.category_uncertain"
    band = "homogeneous" if dispersion <= low else "noticeable" if dispersion <= high else "variable"
    direction, _ = _pace_description(paces, language)
    first, last = cohort[0], cohort[-1]
    evidence = {
        "comparable_effort_count": len(cohort), "total_effort_count": len(phases.efforts),
        "first_effort_number": first.effort_number, "last_effort_number": last.effort_number,
        "comparability_basis": basis, "effort_numbers": ", ".join(str(p.effort_number) for p in cohort),
        "pace_range_sec_per_km": max(paces) - min(paces),
        "first_to_last_pace_change_sec_per_km": paces[-1] - paces[0],
        "first_pace_sec_per_km": paces[0], "last_pace_sec_per_km": paces[-1],
        "direction": direction, "judgment_version": "v1",
        "metric": "mean_absolute_deviation_from_median",
        "median_pace_sec_per_km": reference, "absolute_deviation_sec_per_km": dispersion,
        "relative_deviation": dispersion / reference,
        "homogeneous_limit_sec_per_km": low, "variable_limit_sec_per_km": high,
        "pace_uncertainty_sec_per_km": uncertainty,
        **{f"effort_{phase.effort_number}_pace_sec_per_km": phase.pace_sec_per_km for phase in cohort},
    }
    delta = paces[-1] - paces[0]
    trend_limit = max(config.atypical_floor_sec_km, reference * config.trend_relative)
    if len(paces) == 2:
        evidence["comparison_scope"] = "two_efforts_only"
        evidence["regularity_band"] = "not_assessed"
        text = _localized(
            language,
            f"Sur tes deux répétitions comparables, l'écart d'allure est de {_n(abs(delta))} s/km ; cela ne suffit pas à juger la régularité d'une série.",
            f"Your two comparable repetitions differ by {_n(abs(delta))} s/km; this is not enough to judge a whole series.",
            f"Tus dos repeticiones comparables difieren {_n(abs(delta))} s/km; no basta para juzgar la regularidad de una serie.",
        )
        return (text, evidence, False), None

    evidence.update(regularity_band=band, comparison_scope="all_comparable_efforts")
    label = {
        "homogeneous": _localized(language, "Allures homogènes", "Homogeneous paces", "Ritmos homogéneos"),
        "noticeable": _localized(language, "Variations d'allure perceptibles", "Noticeable pace variations", "Variaciones de ritmo perceptibles"),
        "variable": _localized(language, "Variations d'allure importantes", "Large pace variations", "Variaciones de ritmo importantes"),
    }[band]
    text = _localized(
        language,
        f"{label} sur tes {len(paces)} répétitions : écart moyen de {_n(dispersion)} s/km par rapport à l'allure centrale.",
        f"{label} across your {len(paces)} repetitions: an average gap of {_n(dispersion)} s/km from the central pace.",
        f"{label} en tus {len(paces)} repeticiones: diferencia media de {_n(dispersion)} s/km respecto al ritmo central.",
    )
    atypical = []
    if len(paces) >= 4:
        for index, pace in enumerate(paces):
            others = paces[:index] + paces[index + 1:]
            center = median(others)
            mad = median(abs(value - center) for value in others)
            limit = max(config.atypical_floor_sec_km, config.atypical_relative * center, 3 * mad)
            if (abs(pace - center) > limit + 2 * uncertainty
                    and max(abs(value - center) for value in others) <= limit):
                atypical.append((index, center, limit))
    if len(atypical) == 1:
        index, center, limit = atypical[0]
        pace = paces[index]
        seconds = int(math.floor(pace + 0.5))
        formatted = f"{seconds // 60}:{seconds % 60:02d}/km"
        number = cohort[index].effort_number
        evidence.update(atypical_effort_number=number, atypical_pace_sec_per_km=pace,
                        atypical_reference_sec_per_km=center,
                        atypical_difference_sec_per_km=pace - center, atypical_limit_sec_per_km=limit)
        text += " " + _localized(
            language,
            f"La répétition n° {number} se distingue à {formatted}, {_n(abs(pace - center))} s/km plus {'rapide' if pace < center else 'lente'} que l'allure centrale des autres répétitions.",
            f"Repetition {number} stands out at {formatted}, {_n(abs(pace - center))} s/km {'faster' if pace < center else 'slower'} than the central pace of the other repetitions.",
            f"La repetición n.º {number} destaca a {formatted}, {_n(abs(pace - center))} s/km más {'rápida' if pace < center else 'lenta'} que el ritmo central de las demás repeticiones.",
        )
        # Endpoint proximity adds context without interpreting an outlier as a trend.
        if abs(delta) + 2 * uncertainty <= trend_limit:
            text += " " + _localized(
                language, f"La première et la dernière restent proches ({_n(abs(delta))} s/km d'écart).",
                f"The first and last remain close ({_n(abs(delta))} s/km apart).",
                f"La primera y la última siguen próximas ({_n(abs(delta))} s/km de diferencia).",
            )
            evidence["endpoint_relationship"] = "close"
    elif len(paces) >= 4:
        size = len(paces) // 2
        start, end = median(paces[:size]), median(paces[-size:])
        change = end - start
        evidence.update(start_group_pace_sec_per_km=start, end_group_pace_sec_per_km=end,
                        group_pace_change_sec_per_km=change, group_size=size,
                        trend_limit_sec_per_km=trend_limit,
                        trend_scope="equal_count_endpoint_groups_middle_excluded")
        # Require a consistent direction within both groups, not just their centers.
        monotonic = (all(b <= a for a, b in zip(paces, paces[1:])) if change < 0
                     else all(b >= a for a, b in zip(paces, paces[1:])))
        if abs(change) > trend_limit + 2 * uncertainty and monotonic:
            evidence["group_direction"] = "faster" if change < 0 else "slower"
            text += " " + _localized(
                language, f"La fin est plus {'rapide' if change < 0 else 'lente'} : {_n(abs(change))} s/km entre les {size} premières et les {size} dernières répétitions.",
                f"The finish is {'faster' if change < 0 else 'slower'}: {_n(abs(change))} s/km between the first {size} and last {size} repetitions.",
                f"El final es más {'rápido' if change < 0 else 'lento'}: {_n(abs(change))} s/km entre las primeras {size} y las últimas {size} repeticiones.",
            )
        elif abs(change) + 2 * uncertainty <= trend_limit:
            evidence["group_direction"] = "close"
    return (text, evidence, True), None


def _localized(language, fr, en, es):
    return {"fr": fr, "en": en, "es": es}.get(language, en)


def _n(value):
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _pace_description(paces, language):
    spread = max(paces) - min(paces)
    delta = paces[-1] - paces[0]
    # At the boundary, reuse V2's inclusive significant-change convention.
    if spread < PACE_DISPLAY_CHANGE_SEC_KM:
        return "stable", _localized(
            language, f"Ton allure reste régulière (écart maximal de {_n(spread)} s/km).",
            f"Your pace stays steady (a range of {_n(spread)} s/km).",
            f"Tu ritmo se mantiene estable (rango de {_n(spread)} s/km).",
        )
    if abs(delta) < PACE_DISPLAY_CHANGE_SEC_KM:
        return "variable", _localized(
            language, f"Ton allure varie de {_n(spread)} s/km entre les segments mesurés.",
            f"Your pace varies by {_n(spread)} s/km across the measured segments.",
            f"Tu ritmo varía {_n(spread)} s/km entre los segmentos medidos.",
        )
    return ("slower" if delta > 0 else "faster"), _localized(
        language, f"Ton dernier segment est {_n(abs(delta))} s/km plus {'lent' if delta > 0 else 'rapide'} que le premier.",
        f"Your last segment is {_n(abs(delta))} s/km {'slower' if delta > 0 else 'faster'} than your first.",
        f"Tu último segmento es {_n(abs(delta))} s/km más {'lento' if delta > 0 else 'rápido'} que el primero.",
    )


def _crossed_description(paces, first_hr, last_hr, language):
    # HR here describes endpoints only: never attach it to whole-series regularity.
    _, pace_text = _pace_description([paces[0], paces[-1]], language)
    pace_delta = paces[-1] - paces[0]
    delta = last_hr - first_hr
    hr_direction = _localized(
        language,
        "plus élevée" if delta > 0 else "plus basse" if delta < 0 else "identique",
        "higher" if delta > 0 else "lower" if delta < 0 else "unchanged",
        "más alta" if delta > 0 else "más baja" if delta < 0 else "igual",
    )
    if abs(pace_delta) < PACE_DISPLAY_CHANGE_SEC_KM:
        return _localized(
            language, f"Entre ton premier et ton dernier segment, l'allure diffère de {_n(abs(pace_delta))} s/km et la FC moyenne passe de {_n(first_hr)} à {_n(last_hr)} bpm.",
            f"Between your first and last segments, pace differs by {_n(abs(pace_delta))} s/km and average heart rate goes from {_n(first_hr)} to {_n(last_hr)} bpm.",
            f"Entre tu primer y último segmento, el ritmo difiere {_n(abs(pace_delta))} s/km y la FC media pasa de {_n(first_hr)} a {_n(last_hr)} lpm.",
        )
    return pace_text.rstrip(".") + _localized(
        language, f", avec une FC moyenne {hr_direction} sur le dernier ({_n(first_hr)} à {_n(last_hr)} bpm).",
        f", with {hr_direction} average heart rate on the last ({_n(first_hr)} to {_n(last_hr)} bpm).",
        f", con una FC media {hr_direction} en el último ({_n(first_hr)} a {_n(last_hr)} lpm).",
    )


def _continuous_structure(workout, phases, session_structure):
    """Require V2's classification plus coherent full-session observations."""
    if (getattr(session_structure, "available", None) is not True
            or getattr(session_structure, "code", None) != "continuous"):
        return False
    if phases.phases:
        if len(phases.phases) != 1 or phases.phases[0].phase_type != "effort":
            return False
        phase = phases.phases[0]
        return (
            _positive(workout.get("duration_minutes"))
            and _positive(workout.get("distance_km"))
            and _positive(phase.duration_s) and _positive(phase.distance_m)
            and _matches_workout_duration(phase.duration_s, workout["duration_minutes"])
            and math.isclose(phase.distance_m, workout["distance_km"] * 1000,
                             rel_tol=MEASUREMENT_RECONCILIATION_REL_TOL)
            and "incoherent_pace" not in phases.limitations
        )
    return True


def _measured_rows(workout):
    """Read the untyped UI km/pace_min_km/avg_hr schema, not an invented producer.

    Legacy sequential km rows denote full kilometres only. Optional explicit
    distances/time are used only when present and coherent. No fractional tail
    or subdivision of a recorded aggregate is inferred. Pace-derived full-km
    time supports pace aggregation only, never duration-weighted HR.

    Recognized fields carry units: distance_km, distance_m, duration_s and
    pace_min_km. Optional distance_unit must be "km" or "m" and match a present
    distance field (implicit legacy full-km rows permit "km" only). When both
    distance fields exist they must agree. Optional duration_unit="s" and
    pace_unit="min/km" are consistency declarations, never conversion hints.
    """
    rows = workout.get("km_splits")
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    measured = []
    previous_km = 0
    explicit_distances = [
        isinstance(row, dict) and ("distance_km" in row or "distance_m" in row)
        for row in rows
    ]
    for index, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict) or not _finite(row.get("km"))
            or row["km"] <= previous_km or not _positive(row.get("pace_min_km"))
            or not _finite(row["pace_min_km"] * 60)
        ):
            return []
        previous_km = row["km"]
        distances = []
        for key, scale in (("distance_km", 1), ("distance_m", 0.001)):
            if key in row:
                if not _positive(row[key]):
                    return []
                distances.append(row[key] * scale)
        if len(distances) == 2 and not math.isclose(*distances, rel_tol=1e-9):
            return []
        distance = distances[0] if distances else 1.0
        if not all(explicit_distances):
            # Mixed implicit rows permit only a measured final tail after full km.
            if distance != 1 and index != len(rows):
                return []
        if "distance_unit" in row:
            unit = row["distance_unit"]
            if (unit not in ("km", "m")
                    or (distances and f"distance_{unit}" not in row)
                    or (not distances and unit != "km")):
                return []
        for key, unit in (("duration_unit", "s"), ("pace_unit", "min/km")):
            if key in row and row[key] != unit:
                return []
        pace = row["pace_min_km"] * 60
        derived_time = pace * distance
        if not _positive(derived_time):
            return []
        if "duration_s" in row:
            if (not _positive(row["duration_s"])
                    or not math.isclose(row["duration_s"], derived_time,
                                        rel_tol=MEASUREMENT_RECONCILIATION_REL_TOL)):
                return []
        elif distance != 1:
            return []
        # Unusable HR prevents crossing, not an independently reliable pace
        # observation. Never replace it with session HR or an invented value.
        heart_rate = row.get("avg_hr")
        measured.append(dict(distance=distance, pace=pace,
                             time=row.get("duration_s", derived_time),
                             measured_time="duration_s" in row,
                             hr=heart_rate if _positive(heart_rate) else None))
    # Labels must describe either consecutive segment numbers or coherent
    # cumulative endpoints. Distances always come from explicit units above,
    # never from subtracting ambiguous km labels.
    ordinal_labels = all(row["km"] == index for index, row in enumerate(rows, 1))
    covered = 0
    cumulative_labels = True
    for raw, measured_row in zip(rows, measured):
        covered += measured_row["distance"]
        cumulative_labels &= math.isclose(raw["km"], covered, abs_tol=1e-8)
    if not ordinal_labels and not cumulative_labels:
        return []
    distance = workout.get("distance_km")
    duration = workout.get("duration_minutes")
    total_distance = sum(row["distance"] for row in measured)
    total_time = sum(row["time"] for row in measured)
    if (not _positive(distance) or not _positive(duration) or not _positive(total_time)
            or not _positive(duration * 60)
            or total_distance > distance + 1e-8
            or total_time > duration * 60 + WORKOUT_DURATION_ROUNDING_TOLERANCE_S + 1e-8):
        return []
    if (math.isclose(total_distance, distance, abs_tol=1e-8)
            and not _matches_workout_duration(total_time, duration)):
        return []
    return measured


def _halves(rows, distance):
    """Exact equal-distance halves exist only at a recorded segment boundary."""
    if not math.isclose(sum(row["distance"] for row in rows), distance, abs_tol=1e-8):
        return None
    covered = 0
    for index, row in enumerate(rows[:-1], 1):
        covered += row["distance"]
        if math.isclose(covered, distance / 2, abs_tol=1e-8):
            return rows[:index], rows[index:]
    return None


def _semantic_priority(direction, crossed=False, hr_values=None, equality=False):
    """Rank information, not code order or invented physiological confidence.

    Informative aligned pace+HR (10), significant pace evolution (20), measured
    regularity/variability (30), relevant history (40), bare equality (60).
    A cross with unchanged endpoints cannot suppress informative interior pace.
    HR is informative for ranking only when its two values differ at the same
    one-decimal precision used in the text. This is a display-rounding rule,
    not a physiological threshold; significant pace crosses still rank first.
    """
    visible_hr_change = (
        crossed and hr_values is not None and _n(hr_values[0]) != _n(hr_values[1])
    )
    if crossed and (direction in {"faster", "slower"} or visible_hr_change):
        return 10
    if direction in {"faster", "slower"}:
        return 20
    return 60 if equality and not visible_hr_change else 30


def build_coach_language(workout, phase_analysis, comparison, cohort, basis, comparable, language="en",
                         *, session_structure=None, repetition_config=None):
    """Consume validated phase output and raw measured km rows, without legacy changes."""
    candidates = []

    def add(code, text, evidence, category, priority, replaces, kind="conclusion"):
        if not all(_finite(value) or isinstance(value, str) for value in evidence.values()):
            return
        candidates.append(CoachConclusionV1(
            code=code, text=text,
            evidence={key: value for key, value in evidence.items() if _finite(value)},
            metadata={key: value for key, value in evidence.items() if isinstance(value, str)},
            category=category,
            priority=priority,
            kind=kind, replaces_factual_codes=replaces,
        ))

    rows = _measured_rows(workout) if _continuous_structure(
        workout, phase_analysis, session_structure,
    ) else []
    if rows:
        paces = [row["pace"] for row in rows]
        direction, description = _pace_description(paces, language)
        complete = math.isclose(sum(row["distance"] for row in rows),
                                workout["distance_km"], abs_tol=1e-8)
        evidence = {
            "split_count": len(rows),
            "measured_distance_km": sum(row["distance"] for row in rows),
            "coverage": "whole_session" if complete else "measured_segments",
            "comparison_scope": "measured_segments",
            "pace_range_sec_per_km": max(paces) - min(paces),
            "first_to_last_pace_change_sec_per_km": paces[-1] - paces[0],
            "first_pace_sec_per_km": paces[0],
            "last_pace_sec_per_km": paces[-1],
            "direction": direction,
        }
        scope = _localized(
            language, f"Sur tes {len(rows)} segments mesurés ({evidence['measured_distance_km']:g} km) : ",
            f"Across your {len(rows)} measured segments ({evidence['measured_distance_km']:g} km): ",
            f"En tus {len(rows)} segmentos medidos ({evidence['measured_distance_km']:g} km): ",
        )
        crossed = False
        hr_delta = 0
        halves = _halves(rows, workout["distance_km"])
        if halves:
            first_half, second_half = halves
            first_half_pace, second_half_pace = [
                sum(row["time"] for row in half) / sum(row["distance"] for row in half)
                for half in halves
            ]
            half_delta = second_half_pace - first_half_pace
            evidence.update(first_half_pace_sec_per_km=first_half_pace,
                            second_half_pace_sec_per_km=second_half_pace,
                            second_half_pace_change_sec_per_km=half_delta)
            significant = abs(half_delta) >= PACE_DISPLAY_CHANGE_SEC_KM
            # A nonsignificant half-pace comparison must not erase informative
            # series evolution/variability, regardless of the half-HR difference.
            half_hr = (
                (significant or direction == "stable")
                and all(row["measured_time"] and _positive(row["hr"]) for row in rows)
            )
            if half_hr:
                first_hr, last_hr = [
                    sum(row["hr"] * row["time"] for row in half)
                    / sum(row["time"] for row in half) for half in halves
                ]
            # Preserve an informative half evolution even when only endpoint HR exists.
            # Otherwise prefer representative aligned halves; never pair half pace
            # with endpoint HR or divide an aggregate at an unobserved midpoint.
            if significant or half_hr:
                evidence["comparison_scope"] = "equal_distance_halves"
                direction = ("slower" if half_delta > 0 else "faster") if significant else "stable"
                if significant:
                    description = _localized(
                        language, f"Tu cours la seconde moitié en distance de ta séance {_n(abs(half_delta))} s/km plus {'lentement' if half_delta > 0 else 'vite'}.",
                        f"You run the second distance half of your session {_n(abs(half_delta))} s/km {'slower' if half_delta > 0 else 'faster'}.",
                        f"Corres la segunda mitad en distancia de tu sesión {_n(abs(half_delta))} s/km más {'lento' if half_delta > 0 else 'rápido'}.",
                    )
                else:
                    description = _localized(
                        language, f"Entre les deux moitiés en distance de ta séance, l'allure moyenne diffère de {_n(abs(half_delta))} s/km.",
                        f"Between the two distance halves of your session, average pace differs by {_n(abs(half_delta))} s/km.",
                        f"Entre las dos mitades en distancia de tu sesión, el ritmo medio difiere {_n(abs(half_delta))} s/km.",
                    )
                if half_hr:
                    hr_delta = last_hr - first_hr
                    evidence.update(first_half_hr_bpm=first_hr, second_half_hr_bpm=last_hr,
                                    heart_rate_change_bpm=hr_delta,
                                    hr_aggregation="duration_weighted_measured")
                    description = description.rstrip(".") + _localized(
                        language, f", avec une FC moyenne de {_n(first_hr)} puis {_n(last_hr)} bpm sur ces mêmes moitiés.",
                        f", with average heart rate of {_n(first_hr)} then {_n(last_hr)} bpm over those same halves.",
                        f", con una FC media de {_n(first_hr)} y luego {_n(last_hr)} lpm en esas mismas mitades.",
                    )
                    crossed = True
        if evidence["comparison_scope"] == "measured_segments":
            endpoint_delta = paces[-1] - paces[0]
            # Endpoint equality must not erase measured interior variability.
            informative_endpoints = (abs(endpoint_delta) >= PACE_DISPLAY_CHANGE_SEC_KM
                                     or direction == "stable")
            if informative_endpoints and all(_positive(row["hr"]) for row in rows):
                first_hr, last_hr = rows[0]["hr"], rows[-1]["hr"]
                hr_delta = last_hr - first_hr
                evidence.update(first_hr_bpm=first_hr, last_hr_bpm=last_hr,
                                heart_rate_change_bpm=hr_delta,
                                comparison_scope="first_last_measured_segments")
                description = _crossed_description(paces, first_hr, last_hr, language)
                crossed = True
        evidence["direction"] = direction
        priority = _semantic_priority(
            direction, crossed, (first_hr, last_hr) if crossed else None,
            equality=max(paces) == min(paces),
        )
        add("coach.execution.pace_hr" if crossed else "coach.pacing", scope + description,
            evidence, "execution" if crossed else "pacing", priority,
            ["fact.pace_change", "fact.negative_split"],
            "descriptive" if direction in {"stable", "variable"} else "conclusion")

    judgment, abstention = _repetition_judgment(
        phase_analysis, cohort, basis, comparable, language,
        repetition_config or RepetitionJudgmentConfig(),
    )
    if judgment:
        description, evidence, series = judgment
        paces = [phase.pace_sec_per_km for phase in cohort]
        direction = evidence["direction"]
        first, last = cohort[0], cohort[-1]
        crossed = (all(_positive(phase.average_hr) for phase in cohort)
                  and (direction == "stable"
                        or abs(paces[-1] - paces[0]) >= PACE_DISPLAY_CHANGE_SEC_KM))
        if crossed:
            evidence.update(first_hr_bpm=first.average_hr, last_hr_bpm=last.average_hr,
                           heart_rate_change_bpm=last.average_hr - first.average_hr)
            description += " " + _localized(
               language, f"La FC moyenne passe de {_n(first.average_hr)} à {_n(last.average_hr)} bpm entre la première et la dernière.",
               f"Average heart rate goes from {_n(first.average_hr)} to {_n(last.average_hr)} bpm between the first and last.",
               f"La FC media pasa de {_n(first.average_hr)} a {_n(last.average_hr)} lpm entre la primera y la última.",
            )
        add("coach.repetitions.pace_hr" if crossed else "coach.repetitions.pacing",
            description, evidence, "repetitions",
            _semantic_priority(
                direction, crossed, (first.average_hr, last.average_hr) if crossed else None,
                equality=max(paces) == min(paces),
            ),
            ["fact.effort_dispersion", "fact.effort_extremes"]
            + (["fact.effort_hr_evolution"] if crossed else []),
            "conclusion" if series else "descriptive")

    similar = comparison.similar
    # Separate populations are never crossed. At most one historical phenomenon is selected.
    if similar and similar.available and similar.comparable and not similar.limitations:
        delta = similar.pace_difference_min_km
        if (_finite(delta) and _positive(similar.avg_pace_min_km)
                and _positive(workout.get("avg_pace_min_km"))
                and similar.pace_sample_count >= similar.min_comparable_sample):
            seconds = delta * 60
            direction = _localized(
                language, "plus lentement" if delta > 0 else "plus vite",
                "slower" if delta > 0 else "faster",
                "más lento" if delta > 0 else "más rápido",
            )
            text = _localized(
                language, f"Tu cours {_n(abs(seconds))} s/km {direction} que sur tes {similar.pace_sample_count} séances comparables avec allure mesurée.",
                f"You run {_n(abs(seconds))} s/km {direction} than in your {similar.pace_sample_count} comparable sessions with recorded pace.",
                f"Corres {_n(abs(seconds))} s/km {direction} que en tus {similar.pace_sample_count} sesiones comparables con ritmo registrado.",
            )
            if delta == 0:
                text = _localized(
                    language, f"Tu retrouves la même allure moyenne que sur tes {similar.pace_sample_count} séances comparables avec allure mesurée.",
                    f"Your average pace matches your {similar.pace_sample_count} comparable sessions with recorded pace.",
                    f"Tu ritmo medio coincide con el de tus {similar.pace_sample_count} sesiones comparables con ritmo registrado.",
                )
            add("coach.history.pace", text,
                {"pace_sample_count": similar.pace_sample_count, "pace_difference_sec_per_km": seconds,
                 "baseline_pace_min_km": similar.avg_pace_min_km,
                 "current_pace_min_km": workout["avg_pace_min_km"],
                 "population": "pace_only"}, "history", 60 if delta == 0 else 40, ["fact.similar_pace"])
        elif (_finite(similar.heart_rate_difference_bpm)
              and _positive(similar.avg_heart_rate) and _positive(workout.get("avg_heart_rate"))
              and similar.hr_sample_count >= similar.min_comparable_sample):
            delta = similar.heart_rate_difference_bpm
            direction = _localized(
                language, "plus élevée" if delta > 0 else "plus basse" if delta < 0 else "identique",
                "higher" if delta > 0 else "lower" if delta < 0 else "unchanged",
                "más alta" if delta > 0 else "más baja" if delta < 0 else "igual",
            )
            text = _localized(
                language, f"Ta FC moyenne est {direction} que sur tes {similar.hr_sample_count} séances comparables avec FC mesurée ({_n(workout['avg_heart_rate'])} contre {_n(similar.avg_heart_rate)} bpm).",
                f"Your average heart rate is {direction} than in your {similar.hr_sample_count} comparable sessions with recorded heart rate ({_n(workout['avg_heart_rate'])} versus {_n(similar.avg_heart_rate)} bpm).",
                f"Tu FC media es {direction} que en tus {similar.hr_sample_count} sesiones comparables con FC registrada ({_n(workout['avg_heart_rate'])} frente a {_n(similar.avg_heart_rate)} lpm).",
            )
            if delta == 0:
                text = _localized(
                    language, f"Tu retrouves la même FC moyenne que sur tes {similar.hr_sample_count} séances comparables avec FC mesurée ({_n(similar.avg_heart_rate)} bpm).",
                    f"Your average heart rate matches your {similar.hr_sample_count} comparable sessions with recorded heart rate ({_n(similar.avg_heart_rate)} bpm).",
                    f"Tu FC media coincide con la de tus {similar.hr_sample_count} sesiones comparables con FC registrada ({_n(similar.avg_heart_rate)} lpm).",
                )
            add("coach.history.hr", text,
                {"hr_sample_count": similar.hr_sample_count, "heart_rate_difference_bpm": delta,
                 "baseline_heart_rate_bpm": similar.avg_heart_rate,
                 "current_heart_rate_bpm": workout["avg_heart_rate"],
                 "population": "hr_only"}, "history", 60 if delta == 0 else 40, ["fact.similar_hr"])

    candidates.sort(key=lambda item: (item.priority, item.code))
    selected = []
    seen = set()
    for item in candidates:
        if item.category not in seen:
            selected.append(item)
            seen.add(item.category)
    return CoachLanguageV1(conclusions=selected[:3], limitations=[abstention] if abstention else [])
