"""Deterministic, evidence-bound display language; never a prescription engine."""

from itertools import combinations
import math
from statistics import mean
from typing import Dict, List, Literal, Optional, Union

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
    evidence: Dict[str, Union[float, str]]
    category: Literal["execution", "repetitions", "pacing", "history"]
    priority: int
    available: bool = True
    kind: Literal["conclusion", "descriptive"] = "conclusion"
    replaces_factual_codes: List[str] = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def _valid_evidence(cls, value):
        if not isinstance(value, dict) or not value or not all(
            _finite(item) or (isinstance(item, str) and bool(item.strip()))
            for item in value.values()
        ):
            raise ValueError("Coach evidence requires finite numbers or nonempty categories")
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
        language, f"Tu {'ralentis' if delta > 0 else 'accélères'} de {_n(abs(delta))} s/km du premier au dernier segment.",
        f"You run {_n(abs(delta))} s/km {'slower' if delta > 0 else 'faster'} from the first to the last segment.",
        f"Tu ritmo es {_n(abs(delta))} s/km más {'lento' if delta > 0 else 'rápido'} del primer al último segmento.",
    )


def _hr_description(first, last, language):
    return _localized(
        language, f"Sur ces mêmes segments, ta FC moyenne passe de {_n(first)} à {_n(last)} bpm.",
        f"On those same segments, your average heart rate goes from {_n(first)} to {_n(last)} bpm.",
        f"En esos mismos segmentos, tu FC media pasa de {_n(first)} a {_n(last)} lpm.",
    ), last - first


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
            code=code, text=text, evidence=evidence, category=category,
            priority=90 if kind == "descriptive" else priority,
            kind=kind, replaces_factual_codes=replaces,
        ))

    rows = _whole_km_rows(workout)
    if rows:
        paces = [row["pace_min_km"] * 60 for row in rows]
        direction, description = _pace_description(paces, language)
        complete = workout["distance_km"] == len(rows)
        evidence = {
            "split_count": len(rows), "first_km": 1, "last_km": len(rows),
            "coverage": "whole_session" if complete else "measured_full_km",
            "pace_range_sec_per_km": max(paces) - min(paces),
            "first_to_last_pace_change_sec_per_km": paces[-1] - paces[0],
            "direction": direction,
        }
        scope = _localized(
            language, f"Sur tes {len(rows)} kilomètres entiers mesurés : ",
            f"Across your {len(rows)} measured whole kilometres: ",
            f"En tus {len(rows)} kilómetros completos medidos: ",
        )
        if complete and len(rows) % 2 == 0:
            middle = len(rows) // 2
            half_delta = mean(paces[middle:]) - mean(paces[:middle])
            evidence["second_half_pace_change_sec_per_km"] = half_delta
            if abs(half_delta) >= PACE_DISPLAY_CHANGE_SEC_KM:
                description = _localized(
                    language, f"Tu cours la seconde moitié de ta séance {_n(abs(half_delta))} s/km plus {'lentement' if half_delta > 0 else 'vite'}.",
                    f"You run the second half of your session {_n(abs(half_delta))} s/km {'slower' if half_delta > 0 else 'faster'}.",
                    f"Corres la segunda mitad de tu sesión {_n(abs(half_delta))} s/km más {'lento' if half_delta > 0 else 'rápido'}.",
                )
        hr_complete = all(_positive(row.get("avg_hr")) for row in rows)
        if hr_complete:
            hr_text, hr_delta = _hr_description(rows[0]["avg_hr"], rows[-1]["avg_hr"], language)
            evidence.update(first_hr_bpm=rows[0]["avg_hr"], last_hr_bpm=rows[-1]["avg_hr"],
                            heart_rate_change_bpm=hr_delta)
            # Endpoint HR must accompany endpoint pace, not a different half-session statistic.
            _, endpoint_description = _pace_description(paces, language)
            add("coach.execution.pace_hr", scope + endpoint_description + " " + hr_text,
                evidence, "execution", 10, ["fact.pace_change", "fact.negative_split"])
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
            "effort_numbers": numbers,
        }
        scope = _localized(
            language, f"Sur tes {len(cohort)} répétitions comparables (n° {numbers}) : ",
            f"Across your {len(cohort)} comparable repetitions (numbers {numbers}): ",
            f"En tus {len(cohort)} repeticiones comparables (n.º {numbers}): ",
        )
        crossed = all(_positive(phase.average_hr) for phase in cohort)
        if crossed:
            hr_text, hr_delta = _hr_description(first.average_hr, last.average_hr, language)
            description += " " + hr_text
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
        if _finite(delta) and similar.pace_sample_count >= similar.min_comparable_sample:
            seconds = delta * 60
            text = _localized(
                language, f"Par rapport à tes {similar.pace_sample_count} séances comparables avec allure mesurée, ton écart d'allure est de {_n(seconds)} s/km (positif = plus lent).",
                f"Against your {similar.pace_sample_count} comparable sessions with recorded pace, your pace gap is {_n(seconds)} s/km (positive means slower).",
                f"Respecto a tus {similar.pace_sample_count} sesiones comparables con ritmo registrado, tu diferencia es de {_n(seconds)} s/km (positivo = más lento).",
            )
            add("coach.history.pace", text,
                {"pace_sample_count": similar.pace_sample_count, "pace_difference_sec_per_km": seconds,
                 "population": "pace_only"}, "history", 40, ["fact.similar_pace"])
        elif (_finite(similar.heart_rate_difference_bpm)
              and similar.hr_sample_count >= similar.min_comparable_sample):
            delta = similar.heart_rate_difference_bpm
            text = _localized(
                language, f"Par rapport à tes {similar.hr_sample_count} séances comparables avec FC mesurée, ton écart de FC moyenne est de {_n(delta)} bpm.",
                f"Against your {similar.hr_sample_count} comparable sessions with recorded heart rate, your average heart-rate gap is {_n(delta)} bpm.",
                f"Respecto a tus {similar.hr_sample_count} sesiones comparables con FC registrada, tu diferencia de FC media es de {_n(delta)} lpm.",
            )
            add("coach.history.hr", text,
                {"hr_sample_count": similar.hr_sample_count, "heart_rate_difference_bpm": delta,
                 "population": "hr_only"}, "history", 40, ["fact.similar_hr"])

    candidates.sort(key=lambda item: (item.kind == "descriptive", item.priority, item.code))
    return CoachLanguageV1(conclusions=candidates[:3])
