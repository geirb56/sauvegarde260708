"""Closed editorial language: the provider supplies no displayable assertions."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Literal, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from hybrid_coach_c359 import AdmissibleFact


class EditorialClause(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    fact_id: str = Field(min_length=1, max_length=64)
    form: Literal["direct", "explain", "rounded", "threshold_label", "count_words", "scope"]


class EditorialSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    primary: EditorialClause
    supporting: list[EditorialClause] = Field(max_length=2)
    editorial_intent: Literal[
        "describe_session", "compare_history", "qualify_data", "review_prescription",
    ]


def format_evidence_number(value: float | int, language: str, *, signed: bool = False) -> str:
    """Keep admitted precision; only the explicitly approximate form may round."""
    magnitude = str(abs(value)).removesuffix(".0")
    sign = ("−" if value < 0 else "+") if value != 0 and (value < 0 or signed) else ""
    if language in {"fr", "es"}:
        magnitude = magnitude.replace(".", ",")
    return sign + magnitude


def format_recorded_seconds(value: float | int, language: str, *, pace: bool = False) -> str:
    """Decompose decimal seconds exactly, including exponent and subsecond inputs."""
    whole, _, fraction = format(Decimal(str(value)), "f").partition(".")
    minutes, seconds = divmod(int(whole), 60)
    fraction = fraction.rstrip("0")
    decimal = ("," if language in {"fr", "es"} else ".") + fraction if fraction else ""
    if pace:
        separator = "'" if language == "fr" else ":"
        return f"{minutes}{separator}{seconds:02d}{decimal}/km"
    if minutes and not seconds and not fraction:
        return f"{minutes} min"
    return f"{minutes} min {seconds:02d}{decimal} s" if minutes else f"{seconds}{decimal} s"


def fact_category(fact: AdmissibleFact) -> str:
    if fact.id.startswith("comparison.") or fact.id == "session.long":
        return "comparison"
    if fact.id == "session.kind":
        return "classification"
    if fact.id.startswith("trend.") or fact.id == "prescription.review":
        return "conclusion"
    return "observation"


def editorial_intent(fact: AdmissibleFact) -> str:
    if fact.id.startswith(("comparison.", "trend.")):
        return "compare_history"
    if fact.id in {"session.unknown", "intensity.hr"}:
        return "qualify_data"
    if fact.id == "prescription.review":
        return "review_prescription"
    return "describe_session"


def allowed_forms(fact: AdmissibleFact, language: str) -> list[str]:
    forms = ["direct", "explain"]
    if fact.id == "intensity.position":
        forms += ["threshold_label", "scope"]
    if fact.id == "interval.count" and language == "fr":
        values = dict(fact.values)
        if all(0 <= values[key] <= 10 for key in ("efforts", "recoveries")):
            forms.append("count_words")
    if fact.id.startswith("comparison."):
        key = "pace_difference" if fact.id == "comparison.pace" else "hr_difference"
        if abs(dict(fact.values)[key]) >= 1:
            forms.append("rounded")
    return forms


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def validate_editorial_selection(
    response: str, facts: tuple[AdmissibleFact, ...], language: str,
) -> EditorialSelection:
    """Validate syntax, admission, forms, intent and nonredundancy, not prose."""
    selection = EditorialSelection.model_validate(
        json.loads(response, object_pairs_hook=_unique_object),
    )
    index = {fact.id: fact for fact in facts}
    clauses = [selection.primary, *selection.supporting]
    ids = [clause.fact_id for clause in clauses]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_fact")
    for clause in clauses:
        if clause.fact_id not in index:
            raise ValueError("unknown_or_unauthorized_fact")
        if clause.form not in allowed_forms(index[clause.fact_id], language):
            raise ValueError("unsupported_form")
    if selection.editorial_intent != editorial_intent(index[ids[0]]):
        raise ValueError("contradictory_intent")
    selected = set(ids)
    if ("session.unknown" in selected and selected & {"intensity.hr", "intensity.position"}
            or {"session.kind", "intensity.position"} <= selected
            or {"interval.count", "effort.coverage"} <= selected
            or sum(id.startswith(("comparison.", "trend.")) for id in ids) > 1):
        raise ValueError("redundant_selection")
    return selection


def realize_clause(fact: AdmissibleFact, form: str, language: str) -> str:
    """All values, units, scope and relations come from the admitted backend fact."""
    if form not in allowed_forms(fact, language):
        raise ValueError("unsupported_form")
    if form == "explain":
        return fact.assertion
    values = dict(fact.values)

    def tr(fr, en, es):
        return {"fr": fr, "en": en, "es": es}[language]

    def num(key):
        return format_evidence_number(values[key], language)

    if fact.id in {"effort.first", "effort.last"}:
        label = tr("premier", "first", "primer") if fact.id == "effort.first" else tr(
            "dernier", "last", "último",
        )
        number = num("effort_number")
        duration = (
            format_recorded_seconds(values["recorded_duration"], language)
            if "recorded_duration" in values else None
        )
        pace = (
            format_recorded_seconds(values["recorded_pace"], language, pace=True)
            if "recorded_pace" in values else None
        )
        if duration is not None:
            detail = tr(f"a duré {duration}", f"lasted {duration}", f"duró {duration}")
            if pace is not None:
                detail += tr(f", à {pace}", f" at {pace}", f", a {pace}")
        else:
            detail = tr(f"présente une allure de {pace}", f"has a recorded pace of {pace}",
                        f"tiene un ritmo de {pace}")
        only = tr(" (seule mesure disponible)", " (only available metric)",
                  " (única medida disponible)") if duration is None or pace is None else ""
        return tr(
            f"Dans l'ordre enregistré par Garmin, le {label} effort (n° {number}) {detail}{only}.",
            f"In Garmin's recorded order, the {label} effort (no. {number}) {detail}{only}.",
            f"En el orden registrado por Garmin, el {label} esfuerzo (n.º {number}) {detail}{only}.",
        )
    if fact.id == "effort.coverage":
        metrics = []
        plural = "" if values["recorded_total"] == 1 else "s"
        for key, labels in (
            ("pace_count", ("avec allure", "with pace", "con ritmo")),
            ("duration_count", ("avec durée", "with duration", "con duración")),
            ("both_count", ("avec les deux", "with both", "con ambos")),
        ):
            if key in values:
                metrics.append(f"{num(key)} {tr(*labels)}")
        return tr(
            f"Sur {num('recorded_total')} effort{plural} enregistré{plural} par Garmin : {', '.join(metrics)}.",
            f"Of {num('recorded_total')} Garmin-recorded effort{plural}: {', '.join(metrics)}.",
            f"De {num('recorded_total')} esfuerzo{plural} registrado{plural} por Garmin: {', '.join(metrics)}.",
        )
    if fact.id == "interval.count":
        e, r = num("efforts"), num("recoveries")
        if form == "count_words":
            words = ("zéro", "un", "deux", "trois", "quatre", "cinq",
                     "six", "sept", "huit", "neuf", "dix")
            e, r = words[values["efforts"]], words[values["recoveries"]]
        return tr(
            f"Garmin a enregistré {e} phases d'effort et {r} phases de récupération.",
            f"Garmin recorded {e} effort phases and {r} recovery phases.",
            f"Garmin registró {e} fases de esfuerzo y {r} fases de recuperación.",
        )
    if fact.id == "intensity.position":
        lt1 = tr("LT1", "LT1", "LT1")
        lt2 = "LT2"
        if form == "threshold_label":
            lt1 = tr("seuil lactique 1", "lactate threshold 1", "umbral de lactato 1")
            lt2 = tr("seuil lactique 2", "lactate threshold 2", "umbral de lactato 2")
        position = values["position"]
        relation = {
            "below_LT1": tr(f"sous ton {lt1} de {num('lt1')} bpm",
                           f"below your {lt1} of {num('lt1')} bpm",
                           f"por debajo de tu {lt1} de {num('lt1')} lpm"),
            "between_LT1_LT2": tr(
                f"entre ton {lt1} de {num('lt1')} bpm et ton {lt2} de {num('lt2')} bpm",
                f"between your {lt1} of {num('lt1')} bpm and your {lt2} of {num('lt2')} bpm",
                f"entre tu {lt1} de {num('lt1')} lpm y tu {lt2} de {num('lt2')} lpm"),
            "above_LT2": tr(f"au-dessus de ton {lt2} de {num('lt2')} bpm",
                           f"above your {lt2} of {num('lt2')} bpm",
                           f"por encima de tu {lt2} de {num('lt2')} lpm"),
        }[position]
        text = tr(
            f"Ta FC moyenne est de {num('average_hr')} bpm, {relation}.",
            f"Your average HR is {num('average_hr')} bpm, {relation}.",
            f"Tu FC media es de {num('average_hr')} lpm, {relation}.",
        )
        if form == "scope":
            text += tr(
                " Cette moyenne ne permet pas de conclure à une progression.",
                " This average does not establish progress.",
                " Esta media no permite concluir que haya progreso.",
            )
        return text
    if fact.id.startswith("comparison."):
        pace = fact.id == "comparison.pace"
        key = "pace_difference" if pace else "hr_difference"
        delta = values[key]
        approximate = form == "rounded"
        shown = format_evidence_number(round(delta) if approximate else delta, language, signed=True)
        qualifier = tr("environ ", "approximately ", "aproximadamente ") if approximate else ""
        n = num("references")
        if pace:
            return tr(
                f"À FC comparable, l'écart d'allure est de {qualifier}{shown} s/km par rapport à la moyenne de {n} séances de référence (séance actuelle moins références).",
                f"At comparable HR, the pace difference is {qualifier}{shown} s/km against the mean of {n} reference sessions (current minus references).",
                f"A FC comparable, la diferencia de ritmo es de {qualifier}{shown} s/km respecto a la media de {n} sesiones de referencia (actual menos referencias).",
            )
        return tr(
            f"À allure comparable, l'écart de FC moyenne est de {qualifier}{shown} bpm par rapport à la moyenne de {n} séances de référence (séance actuelle moins références).",
            f"At comparable pace, the average HR difference is {qualifier}{shown} bpm against the mean of {n} reference sessions (current minus references).",
            f"A ritmo comparable, la diferencia de FC media es de {qualifier}{shown} lpm respecto a la media de {n} sesiones de referencia (actual menos referencias).",
        )
    # These facts already carry their mandatory uncertainty/interpretation limits.
    return fact.assertion
