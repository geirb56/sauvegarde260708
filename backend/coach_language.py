"""Deterministic, evidence-bound display language; never a prescription engine."""

from itertools import combinations
import math
from statistics import mean
from typing import Dict, List, Literal

from pydantic import BaseModel, Field, field_validator


# Display-only reuse of V2's 0.4 min/km change boundary. Not a physiological limit.
PACE_DISPLAY_CHANGE_SEC_KM = 24.0


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value):
    return _finite(value) and value > 0


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
    direction, pace_text = _pace_description(paces, language)
    delta = last_hr - first_hr
    hr_direction = _localized(
        language,
        "plus élevée" if delta > 0 else "plus basse" if delta < 0 else "identique",
        "higher" if delta > 0 else "lower" if delta < 0 else "unchanged",
        "más alta" if delta > 0 else "más baja" if delta < 0 else "igual",
    )
    if direction == "stable":
        if delta == 0:
            return _localized(
                language, "Tu maintiens une allure régulière avec la même FC moyenne sur le premier et le dernier segment.",
                "You maintain a steady pace with the same average heart rate on the first and last segments.",
                "Mantienes un ritmo estable con la misma FC media en el primer y el último segmento.",
            )
        return _localized(
            language, f"Tu maintiens une allure régulière avec une FC moyenne {hr_direction} sur le dernier segment que sur le premier ({_n(first_hr)} à {_n(last_hr)} bpm).",
            f"You maintain a steady pace with {hr_direction} average heart rate on the last segment than on the first ({_n(first_hr)} to {_n(last_hr)} bpm).",
            f"Mantienes un ritmo estable con una FC media {hr_direction} en el último segmento que en el primero ({_n(first_hr)} a {_n(last_hr)} lpm).",
        )
    return pace_text.rstrip(".") + _localized(
        language, f", avec une FC moyenne {hr_direction} sur le dernier ({_n(first_hr)} à {_n(last_hr)} bpm).",
        f", with {hr_direction} average heart rate on the last ({_n(first_hr)} to {_n(last_hr)} bpm).",
        f", con una FC media {hr_direction} en el último ({_n(first_hr)} a {_n(last_hr)} lpm).",
    )


def _has_mixed_structure(workout, phases):
    structure = workout.get("session_structure")
    if isinstance(structure, dict):
        structure = structure.get("code")
    return (
        structure == "intervals"
        or len(phases.efforts) > 1
        or any(phase.phase_type in {"recovery", "warmup", "cooldown"} for phase in phases.phases)
    )


def _whole_km_rows(workout):
    rows = workout.get("km_splits")
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    for index, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict) or not _finite(row.get("km"))
            or row["km"] != index or not _positive(row.get("pace_min_km"))
            or not _finite(row["pace_min_km"] * 60)
        ):
            return []
        # An explicitly partial split must not masquerade as a whole kilometre.
        for key, expected in (("distance_km", 1), ("distance_m", 1000)):
            if key in row and (not _positive(row[key]) or row[key] != expected):
                return []
    distance = workout.get("distance_km")
    if not _positive(distance) or distance < len(rows):
        return []
    return rows


def build_coach_language(workout, phase_analysis, comparison, cohort, basis, comparable, language="en"):
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
            priority=90 if kind == "descriptive" else priority,
            kind=kind, replaces_factual_codes=replaces,
        ))

    rows = [] if _has_mixed_structure(workout, phase_analysis) else _whole_km_rows(workout)
    if rows:
        paces = [row["pace_min_km"] * 60 for row in rows]
        direction, description = _pace_description(paces, language)
        complete = workout["distance_km"] == len(rows)
        evidence = {
            "split_count": len(rows), "first_km": 1, "last_km": len(rows),
            "coverage": "whole_session" if complete else "measured_full_km",
            "pace_range_sec_per_km": max(paces) - min(paces),
            "first_to_last_pace_change_sec_per_km": paces[-1] - paces[0],
            "first_pace_sec_per_km": paces[0],
            "last_pace_sec_per_km": paces[-1],
            "direction": direction,
        }
        scope = _localized(
            language, f"Sur tes {len(rows)} kilomètres entiers mesurés : ",
            f"Across your {len(rows)} measured whole kilometres: ",
            f"En tus {len(rows)} kilómetros completos medidos: ",
        )
        if complete and len(rows) % 2 == 0:
            middle = len(rows) // 2
            first_half_pace = mean(paces[:middle])
            second_half_pace = mean(paces[middle:])
            half_delta = second_half_pace - first_half_pace
            evidence["first_half_pace_sec_per_km"] = first_half_pace
            evidence["second_half_pace_sec_per_km"] = second_half_pace
            evidence["second_half_pace_change_sec_per_km"] = half_delta
            if abs(half_delta) >= PACE_DISPLAY_CHANGE_SEC_KM:
                description = _localized(
                    language, f"Tu cours la seconde moitié de ta séance {_n(abs(half_delta))} s/km plus {'lentement' if half_delta > 0 else 'vite'}.",
                    f"You run the second half of your session {_n(abs(half_delta))} s/km {'slower' if half_delta > 0 else 'faster'}.",
                    f"Corres la segunda mitad de tu sesión {_n(abs(half_delta))} s/km más {'lento' if half_delta > 0 else 'rápido'}.",
                )
        hr_complete = all(_positive(row.get("avg_hr")) for row in rows)
        if hr_complete:
            hr_delta = rows[-1]["avg_hr"] - rows[0]["avg_hr"]
            evidence.update(first_hr_bpm=rows[0]["avg_hr"], last_hr_bpm=rows[-1]["avg_hr"],
                            heart_rate_change_bpm=hr_delta)
            # Endpoint HR must accompany endpoint pace, not a different half-session statistic.
            description = _crossed_description(paces, rows[0]["avg_hr"], rows[-1]["avg_hr"], language)
            add("coach.execution.pace_hr", scope + description,
                evidence, "execution", 10, ["fact.pace_change", "fact.negative_split"],
                "descriptive" if direction == "variable" else "conclusion")
        else:
            add("coach.pacing", scope + description, evidence, "pacing", 30,
                ["fact.pace_change", "fact.negative_split"],
                "descriptive" if direction == "variable" else "conclusion")

    # Legacy anchor selection is retained, but no conclusion uses incompatible extremes.
    valid_cohort = (
        len(cohort) >= 2 and basis is not None
        and all(comparable(left, right, basis) for left, right in combinations(cohort, 2))
        and all(_positive(phase.pace_sec_per_km) for phase in cohort)
    )
    if valid_cohort:
        paces = [phase.pace_sec_per_km for phase in cohort]
        direction, description = _pace_description(paces, language)
        first, last = cohort[0], cohort[-1]
        numbers = ", ".join(str(phase.effort_number) for phase in cohort)
        evidence = {
            "comparable_effort_count": len(cohort), "total_effort_count": len(phase_analysis.efforts),
            "first_effort_number": first.effort_number, "last_effort_number": last.effort_number,
            "comparability_basis": basis, "pace_range_sec_per_km": max(paces) - min(paces),
            "first_to_last_pace_change_sec_per_km": paces[-1] - paces[0], "direction": direction,
            "first_pace_sec_per_km": paces[0], "last_pace_sec_per_km": paces[-1],
            "effort_numbers": numbers,
        }
        scope = _localized(
            language, f"Sur tes {len(cohort)} répétitions comparables (n° {numbers}) : ",
            f"Across your {len(cohort)} comparable repetitions (numbers {numbers}): ",
            f"En tus {len(cohort)} repeticiones comparables (n.º {numbers}): ",
        )
        crossed = all(_positive(phase.average_hr) for phase in cohort)
        if crossed:
            hr_delta = last.average_hr - first.average_hr
            description = _crossed_description(paces, first.average_hr, last.average_hr, language)
            evidence.update(first_hr_bpm=first.average_hr, last_hr_bpm=last.average_hr,
                            heart_rate_change_bpm=hr_delta)
        add("coach.repetitions.pace_hr" if crossed else "coach.repetitions.pacing",
            scope + description, evidence, "repetitions", 15 if crossed else 20,
            ["fact.effort_dispersion", "fact.effort_extremes"]
            + (["fact.effort_hr_evolution"] if crossed else []),
            "descriptive" if direction == "variable" else "conclusion")

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
                 "population": "pace_only"}, "history", 40, ["fact.similar_pace"])
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
                 "population": "hr_only"}, "history", 40, ["fact.similar_hr"])

    candidates.sort(key=lambda item: (item.priority, item.code))
    selected = []
    seen = set()
    for item in candidates:
        if item.category not in seen:
            selected.append(item)
            seen.add(item.category)
    return CoachLanguageV1(conclusions=selected[:3])
