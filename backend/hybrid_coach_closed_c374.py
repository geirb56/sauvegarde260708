"""C374-C: bounded backend compositions; the provider selects one opaque ID.

This is an opt-in internal entry point, not a production route or a fallback.
Callers must supply owner-scoped V3/V2 data, as for the existing hybrid coach.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from access_control import UserAccess
import hybrid_coach_c359 as legacy
from hybrid_coach_editorial_c365 import (
    EDITORIAL_EXCLUDED_FACTS, EditorialClause, EditorialSelection, editorial_intent,
    primary_fact_candidates, realize_clause, validate_editorial_selection,
    format_evidence_number, format_recorded_seconds,
)
from hybrid_coach_v2_c372 import ScopedV2Evidence
from narrative_coach_v3 import Transport
from workout_intelligence_v3_models import WorkoutIntelligenceV3


VERSION = "c374-c-closed-choice-1"
MAX_OPTIONS = 6
MAX_RESPONSE_CHARS = 256
MAX_CONTEXT_CHARS = 24000
TIMEOUT_SECONDS = 8.0


class SelectionFailure(ValueError):
    """Only fixed reason codes, never provider content."""


class OptionChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    option_id: str = Field(min_length=1, max_length=32)


class Abstention(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    abstain: Literal[True]


@dataclass(frozen=True)
class EditorialOption:
    option_id: str
    primary: str
    supporting: tuple[str, ...]
    editorial_intent: str
    forms: tuple[str, ...]
    claims: tuple[legacy.HybridClaim, ...]
    # Structured advice is preserved; the complete realization includes it once.
    advice: legacy.HybridClaim | None = None
    advice_reason: str | None = None
    # Internal contextual priority, rebuilt from C365/C374 candidates, never an ID.
    primary_priority: int = 0

    @property
    def text(self) -> str:
        return " ".join(claim.text for claim in (
            *self.claims, *((self.advice,) if self.advice else ()),
        ))

    def provider_option(self, facts: dict[str, legacy.AdmissibleFact]) -> dict:
        return {
            "option_id": self.option_id,
            "primary": self.primary,
            "supporting": list(self.supporting),
            "editorial_intent": self.editorial_intent,
            "advice_id": self.advice.id if self.advice is not None else None,
            "clauses": [
                {**facts[fact_id].provider_fact(), "allowed_forms": [form]}
                for fact_id, form in zip((self.primary, *self.supporting), self.forms)
            ],
        }


class ClosedChoiceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = VERSION
    mode: Literal["disabled", "denied", "failed", "editorial_realization"]
    reason: str
    text: str = ""
    claims: list[legacy.HybridClaim] = Field(default_factory=list)
    option_id: str | None = None
    option_count: int = 0
    verification_scope: Literal["none", "closed_realization"] = "none"
    provider_attempted: bool = False
    transport_kind: Literal["none", "injected"] = "none"
    elapsed_ms: float | None = None
    provider_duration_sec: float | None = None
    cost: float | None = None
    language: str | None = None
    advice: legacy.HybridClaim | None = None
    advice_reason: str | None = None
    blockers: list[str] = Field(default_factory=lambda: [
        "real_llm_editorial_quality_not_evaluated",
    ])


def _candidates(facts):
    candidates = primary_fact_candidates(facts)
    index = {f.id: f for f in facts}
    intensity = index.get("intensity.position")
    if (candidates and candidates[0] == "intensity.position" and intensity
            and dict(intensity.values).get("position") != "above_LT2"):
        history = tuple(f for f in candidates if f.startswith(("trend.", "comparison.")))
        if history:
            # A qualified personal comparison is more distinctive than a routine average.
            candidates = (*history, *(f for f in candidates if f not in history))
    if any(f.id == "session.unknown" for f in facts) and "intensity.hr" in candidates:
        return (*candidates, "session.unknown")
    return candidates


def _validate_composition(primary, supporting, facts, language):
    ids = (primary, *supporting)
    index = {fact.id: fact for fact in facts}
    if (len(index) != len(facts) or len(ids) != len(set(ids)) or len(supporting) > 2
            or any(fact_id not in index for fact_id in ids)
            or primary not in _candidates(facts)
            or set(ids) & EDITORIAL_EXCLUDED_FACTS):
        raise SelectionFailure("option_not_admissible")
    selected = set(ids)
    # Unknown already contains the available HR: adding descriptive HR repeats it.
    if {"session.unknown", "intensity.hr"} <= selected:
        raise SelectionFailure("option_not_admissible")
    # Only these two legacy editorial exclusions are relaxed, not scientific gates:
    # probable type + average HR; global pacing band + scoped endpoint direction.
    relaxed = set()
    if {"session.kind", "intensity.position"} <= selected:
        if index["session.kind"].confidence not in {"medium", "high"}:
            raise SelectionFailure("option_not_admissible")
        relaxed.add("session.kind" if primary != "session.kind" else "intensity.position")
    if {"interval.regularity", "interval.pace_direction"} <= selected:
        relaxed.add("interval.regularity")
    # Recorded endpoints illustrate a scoped group comparison, never replace it.
    # Keep the old exclusion when a global regularity verdict is also present.
    if "interval.pace_direction" in selected and "interval.regularity" not in selected:
        relaxed.update(selected & {"effort.first", "effort.last"})
    if ("interval.regularity" in selected and "interval.pace_direction" not in selected
            and len(selected & {"effort.first", "effort.last"}) == 1):
        relaxed.update(selected & {"effort.first", "effort.last"})
    if primary == "session.unknown" and primary not in primary_fact_candidates(facts):
        # No support is needed: the unknown fact already includes descriptive HR.
        if supporting:
            raise SelectionFailure("option_not_admissible")
        return
    selection = EditorialSelection(
        primary=EditorialClause(fact_id=primary, form="direct"),
        supporting=[
            EditorialClause(fact_id=fact_id, form="direct")
            for fact_id in supporting if fact_id not in relaxed
        ],
        editorial_intent=editorial_intent(index[primary]),
    )
    try:
        validate_editorial_selection(selection.model_dump_json(), facts, language)
    except (ValueError, TypeError) as exc:
        raise SelectionFailure("option_not_admissible") from exc
    # A relaxed pair must not hide an exclusion against a third fact.
    if "interval.regularity" in selected and (
        selected & {"interval.count", "effort.coverage"}
        or len(selected & {"effort.first", "effort.last"}) > 1
        or "interval.pace_direction" in selected and selected & {"effort.first", "effort.last"}
    ):
        raise SelectionFailure("option_not_admissible")


def _realize(fact, form, language, *, pace_only=False, paired=False):
    """C378: show a caveat only where the clause alone could mislead.

    Strictly descriptive clauses (counts, recorded endpoints, scoped pace
    comparisons, probable type, duration) no longer repeat physiological
    disclaimers: their limits stay in ``HybridClaim.limits`` and in the admitted
    fact, and every option is still rebuilt and compared before/after selection.
    A threshold position (average read as whole-session intensity) and a
    historical comparison (read as a fitness change) keep one short caveat.
    """
    if form != "direct":
        raise SelectionFailure("option_not_admissible")
    text = realize_clause(fact, form, language)

    def tr(fr, en, es):
        return {"fr": fr, "en": en, "es": es}[language]

    values = dict(fact.values)

    def num(key):
        return format_evidence_number(values[key], language)

    if fact.id == "interval.regularity":
        band = values["regularity_band"]
        description = {
            "homogeneous": tr("des allures proches", "similar paces", "ritmos similares"),
            "noticeable": tr("des variations d'allure perceptibles",
                             "noticeable pace variations", "variaciones de ritmo perceptibles"),
            "variable": tr("des variations d'allure importantes",
                           "large pace variations", "variaciones de ritmo importantes"),
        }[band]
        text = tr(
            f"Sur tes {num('efforts')} répétitions comparables, tu as couru à {description}."
            if band == "homogeneous" else
            f"Tes {num('efforts')} répétitions comparables présentent {description}.",
            f"Your {num('efforts')} comparable repetitions show {description}.",
            f"Tus {num('efforts')} repeticiones comparables muestran {description}.",
        )
    elif fact.id == "interval.pace_direction":
        # V2 group deltas are averages, not differences between individual endpoints.
        if values["scope"] == "equal_count_endpoint_groups_middle_excluded":
            count = num("group_size")
            change = format_evidence_number(abs(values["pace_change_sec_per_km"]), language)
            faster = values["direction"] == "faster"
            text = tr(
                f"Tes {count} dernières répétitions comparables sont en moyenne {change} s/km "
                f"plus {'rapides' if faster else 'lentes'} que les {count} premières",
                f"Your last {count} comparable repetitions averaged {change} s/km "
                f"{'faster' if faster else 'slower'} than the first {count}",
                f"Tus {count} últimas repeticiones comparables fueron de media {change} s/km "
                f"más {'rápidas' if faster else 'lentas'} que las {count} primeras",
            )
            if values["efforts"] % 2:
                text += tr(" (répétition centrale exclue)", " (middle repetition excluded)",
                           " (se excluye la repetición central)")
            text += "."
    elif fact.id in {"effort.first", "effort.last"}:
        label = tr("premier", "first", "primer") if fact.id == "effort.first" else tr(
            "dernier", "last", "último",
        )
        pace = format_recorded_seconds(values["recorded_pace"], language, pace=True) \
            if "recorded_pace" in values else None
        duration = format_recorded_seconds(values["recorded_duration"], language) \
            if "recorded_duration" in values else None
        if pace_only and pace:
            duration = None
        detail = tr(f"a duré {duration}", f"lasted {duration}", f"duró {duration}") \
            if duration else tr(f"est à {pace}", f"was at {pace}", f"fue a {pace}")
        if duration and pace:
            detail += tr(f", à {pace}", f" at {pace}", f", a {pace}")
        if paired:
            if pace_only and pace:
                detail = tr(f"était à {pace}", f"was at {pace}", f"fue a {pace}")
            if fact.id == "effort.first":
                text = tr(
                    f"Parmi les efforts enregistrés, le premier {detail}",
                    f"Among the recorded efforts, the first {detail}",
                    f"Entre los esfuerzos registrados, el primero {detail}",
                )
            else:
                text = tr(f"et le dernier à {pace}.", f"and the last at {pace}.",
                          f"y el último a {pace}.") if pace_only and pace else tr(
                    f"et le dernier {detail}.", f"and the last {detail}.",
                    f"y el último {detail}.",
                )
        else:
            text = tr(
                f"Ton {label} effort enregistré {detail}.",
                f"Your {label} recorded effort {detail}.",
                f"Tu {label} esfuerzo registrado {detail}.",
            )
    elif fact.id == "intensity.hr":
        text = tr(
            f"Ta fréquence cardiaque moyenne est de {num('average_hr')} bpm, sans repère personnel validé pour interpréter cette valeur.",
            f"Your average heart rate is {num('average_hr')} bpm, without a validated personal reference to interpret it.",
            f"Tu frecuencia cardíaca media es de {num('average_hr')} lpm, sin una referencia personal validada para interpretarla.",
        )
    elif fact.id.startswith("comparison."):
        pace = fact.id == "comparison.pace"
        key = "pace_difference" if pace else "hr_difference"
        delta = values[key]
        change = format_evidence_number(abs(delta), language)
        n = num("references")
        if delta == 0:
            text = tr(
                "Ta fréquence cardiaque moyenne est la même que sur les séances de référence à allure comparable."
                if not pace else "Ton allure est la même que sur les séances de référence à FC comparable.",
                "Your average heart rate matches the reference sessions at comparable pace."
                if not pace else "Your pace matches the reference sessions at comparable heart rate.",
                "Tu frecuencia cardíaca media coincide con las sesiones de referencia a ritmo comparable."
                if not pace else "Tu ritmo coincide con las sesiones de referencia a FC comparable.",
            )
        elif pace:
            text = tr(
                f"À FC comparable, ton allure est {change} s/km plus {'rapide' if delta < 0 else 'lente'} que la moyenne de tes {n} séances de référence.",
                f"At comparable heart rate, your pace is {change} s/km {'faster' if delta < 0 else 'slower'} than the average of your {n} reference sessions.",
                f"A FC comparable, tu ritmo es {change} s/km más {'rápido' if delta < 0 else 'lento'} que la media de tus {n} sesiones de referencia.",
            )
        else:
            text = tr(
                f"À allure comparable, ta fréquence cardiaque moyenne est {change} bpm plus {'basse' if delta < 0 else 'élevée'} que la moyenne de tes {n} séances de référence.",
                f"At comparable pace, your average heart rate is {change} bpm {'lower' if delta < 0 else 'higher'} than the average of your {n} reference sessions.",
                f"A ritmo comparable, tu frecuencia cardíaca media es {change} lpm más {'baja' if delta < 0 else 'alta'} que la media de tus {n} sesiones de referencia.",
            )
    elif fact.id.startswith("trend."):
        delta = values["median_change"]
        change = format_evidence_number(abs(delta), language)
        detail = tr(
            f"ton allure médiane récente est {change} s/km plus {'rapide' if delta < 0 else 'lente'} qu'auparavant",
            f"your recent median pace is {change} s/km {'faster' if delta < 0 else 'slower'} than before",
            f"tu ritmo mediano reciente es {change} s/km más {'rápido' if delta < 0 else 'lento'} que antes",
        ) if delta else tr("ton allure médiane est inchangée", "your median pace is unchanged",
                          "tu ritmo mediano no ha cambiado")
        text = tr(
            f"Sur les {num('observations')} observations de ton historique, {detail}.",
            f"Across the {num('observations')} observations in your history, {detail}.",
            f"En las {num('observations')} observaciones de tu historial, {detail}.",
        )
        if "span" in values:
            text = text[:-1] + tr(
                f" sur {num('span')} jours.", f" over {num('span')} days.",
                f" durante {num('span')} días.",
            )
        # Keep V3's qualified status: a pace observation is not proof of fitness.
        qualification = {
            "probable_improvement": tr("amélioration probable", "probable improvement",
                                       "mejora probable"),
            "possible_decline": tr("baisse possible", "possible decline", "descenso posible"),
            "stable": tr("tendance stable", "stable trend", "tendencia estable"),
        }[values["status"]]
        text += tr(
            f" Cela suggère une {qualification}, sans prouver un changement de forme.",
            f" This suggests a {qualification}, not proof of a fitness change.",
            f" Esto sugiere una {qualification}, sin demostrar un cambio de forma.",
        )
    if fact.id == "intensity.position":
        for technical, plain in {
            "fr": (("ton LT1", "ton premier seuil"), ("ton LT2", "ton second seuil")),
            "en": (("your LT1", "your first threshold"), ("your LT2", "your second threshold")),
            "es": (("tu LT1", "tu primer umbral"), ("tu LT2", "tu segundo umbral")),
        }[language]:
            text = text.replace(technical, plain)
        text += tr(
            " Cette moyenne ne décrit ni chaque phase ni le temps en zones.",
            " This average describes neither each phase nor time in zones.",
            " Esta media no describe cada fase ni el tiempo en zonas.",
        )
    if fact.id.startswith("comparison."):
        text += tr(
            " Les effets du terrain et de la météo ne sont pas isolés ; ce n'est pas une preuve de changement de forme.",
            " Effects of terrain and weather are not isolated; this is not proof of a fitness change.",
            " No se aíslan los efectos del terreno y del clima; no es una prueba de cambio de forma.",
        )
    if fact.id.startswith("trend."):
        text = text.replace(
            tr("sans prouver un changement de forme.", "not proof of a fitness change.",
               "sin demostrar un cambio de forma."),
            tr("sans prouver un changement de forme ; les effets du terrain et de la météo restent mêlés.",
               "not proof of a fitness change; effects of terrain and weather remain mixed.",
               "sin demostrar un cambio de forma; los efectos del terreno y del clima siguen mezclados."),
        )
    return legacy._claim(fact).model_copy(update={"text": text})


def _make_option(option_id, primary, supporting, facts, language):
    _validate_composition(primary, supporting, facts, language)
    index = {fact.id: fact for fact in facts}
    forms = ("direct",) * (1 + len(supporting))
    paired = primary in {"interval.pace_direction", "effort.first"} and (
        {"effort.first", "effort.last"} <= {primary, *supporting}
    )
    claims = tuple(_realize(
        index[fact_id], form, language,
        paired=paired and fact_id in {"effort.first", "effort.last"},
        pace_only=(primary == "interval.pace_direction"
                   and fact_id in {"effort.first", "effort.last"}
                   and {"effort.first", "effort.last"} <= set(supporting)
                   and "recorded_pace" in dict(index["effort.first"].values)
                   and "recorded_pace" in dict(index["effort.last"].values)
                   and dict(index["effort.first"].values).get("recorded_duration") ==
                   dict(index["effort.last"].values).get("recorded_duration")),
    )
                   for fact_id, form in zip((primary, *supporting), forms))
    advice, advice_reason = legacy.admissible_advice(list(claims), facts, language)
    text = " ".join(c.text for c in (*claims, *((advice,) if advice else ())))
    if len(text) > legacy.MAX_COACH_TEXT_CHARS:
        raise SelectionFailure("size_limit")
    return EditorialOption(
        option_id, primary, supporting, editorial_intent(index[primary]), forms, claims,
        advice, advice_reason, _candidates(facts).index(primary),
    )


def validate_option(option, facts, language):
    """Rebuild from admitted authority, including all caveats, before and after LLM."""
    if option.forms != ("direct",) * (1 + len(option.supporting)):
        raise SelectionFailure("option_not_admissible")
    expected = _make_option(
        option.option_id, option.primary, option.supporting, facts, language,
    )
    if option != expected:
        raise SelectionFailure("scientific_violation")


def build_editorial_options(
    facts: tuple[legacy.AdmissibleFact, ...], language: str = "fr",
) -> tuple[EditorialOption, ...]:
    """At most two information sets per primary, never lexical permutations."""
    language = legacy._language(language)
    # Zero deltas remain admitted, but are not an editorial result in themselves.
    displayable = tuple(f for f in facts if not (
        f.id.startswith("comparison.")
        and dict(f.values).get("pace_difference" if f.id == "comparison.pace" else "hr_difference") == 0
    ))
    index = {fact.id: fact for fact in displayable}
    enriched, bare = [], []
    history = tuple(f.id for f in displayable if f.id.startswith("trend."))
    history += tuple(f.id for f in displayable if f.id.startswith("comparison."))
    endpoints = []
    # Do not promote a formerly ineligible primary when hiding a zero delta.
    # Validation must see the same authority snapshot as candidate generation.
    for primary in (candidate for candidate in _candidates(facts) if candidate in index):
        base = _make_option("", primary, (), facts, language)
        support = []
        preferred = []
        if primary == "interval.pace_direction":
            preferred.append("interval.regularity")
        elif primary == "interval.regularity" and "interval.pace_direction" not in index:
            preferred.append("effort.first")
        if primary == "intensity.position":
            preferred.extend((*history[:1],) if history else ("session.kind",))
        elif primary == "continuous.pace_halves":
            preferred.extend(("intensity.position", *history[:1]))
        elif primary == "session.long":
            preferred.extend(("continuous.pace_halves", *history[:1], "intensity.position"))
        elif primary == "session.kind":
            preferred.append("intensity.position")
        elif primary == "interval.count":
            preferred.extend(("intensity.position", "intensity.hr"))
        elif primary in {"effort.first", "effort.last"}:
            preferred.extend(("effort.last", "effort.coverage"))
        intensity = index.get("intensity.position")
        if intensity and dict(intensity.values).get("position") == "above_LT2":
            preferred = ["intensity.position"] if primary in {
                "interval.pace_direction", "interval.regularity", "effort.first", "effort.last",
            } else ["intensity.position", *preferred]
        for fact_id in preferred:
            if fact_id not in index or fact_id in (primary, *support) or len(support) == 2:
                continue
            try:
                _validate_composition(primary, (*support, fact_id), facts, language)
            except SelectionFailure:
                continue
            support.append(fact_id)
        enriched.append(_make_option("", primary, tuple(support), facts, language))
        if primary == "interval.pace_direction":
            endpoint_ids = tuple(f for f in ("effort.first", "effort.last") if f in index)
            # One first/last comparison already describes these endpoints; do not repeat it.
            if (dict(index[primary].values)["scope"] ==
                    "equal_count_endpoint_groups_middle_excluded" and endpoint_ids):
                endpoints.append(_make_option("", primary, endpoint_ids, facts, language))
        if support:
            bare.append(base)
    options = tuple(
        EditorialOption(f"option_{i}", o.primary, o.supporting, o.editorial_intent,
                        o.forms, o.claims, o.advice, o.advice_reason, o.primary_priority)
        for i, o in enumerate((enriched + endpoints + bare)[:MAX_OPTIONS], 1)
    )
    for option in options:
        validate_option(option, facts, language)
    return options


def select_deterministic_option(options: tuple[EditorialOption, ...]) -> EditorialOption:
    """Use validated contextual priority and useful supports, never IDs or display order."""
    if not options:
        raise SelectionFailure("option_not_admissible")

    def content_key(option):
        return (len(option.text), option.primary, option.supporting, option.forms, option.text)

    first = min(options, key=lambda o: (o.primary_priority, o.primary))
    same_primary = [o for o in options if o.primary == first.primary]
    threshold = [o for o in same_primary if "intensity.position" in o.supporting]
    if threshold:
        return min(threshold, key=content_key)
    if first.primary == "interval.pace_direction":
        endpoints = [o for o in same_primary if "effort.first" in o.supporting
                     and "effort.last" in o.supporting]
        if endpoints:
            return min(endpoints, key=content_key)
        # A global variation band complements a first/last comparison.
        regularity = [o for o in same_primary if "interval.regularity" in o.supporting]
        return min(regularity or same_primary, key=content_key)
    if first.primary == "session.long":
        halves = [o for o in same_primary if "continuous.pace_halves" in o.supporting]
        return min(halves or same_primary, key=content_key)
    # Keep history or a measured threshold as useful complementary information.
    useful = [o for o in same_primary if any(
        f.startswith(("trend.", "comparison.")) or f == "intensity.position"
        for f in o.supporting
    )]
    return min(useful or same_primary, key=content_key)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SelectionFailure("multiple_response" if key == "option_id" else "invalid_json")
        result[key] = value
    return result


def _reject_constant(value):
    raise SelectionFailure("invalid_json")


def validate_choice(response: str, options: tuple[EditorialOption, ...]) -> EditorialOption:
    if len(response) > MAX_RESPONSE_CHARS:
        raise SelectionFailure("size_limit")
    try:
        data = json.loads(
            response, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, SelectionFailure):
            raise
        if isinstance(exc, json.JSONDecodeError) and exc.msg == "Extra data":
            raise SelectionFailure("multiple_response") from exc
        raise SelectionFailure("invalid_json") from exc
    if (isinstance(data, list) or isinstance(data, dict) and (
        "option_ids" in data or isinstance(data.get("option_id"), list)
    )):
        raise SelectionFailure("multiple_response")
    if isinstance(data, dict) and "abstain" in data:
        try:
            Abstention.model_validate(data)
            if data["abstain"] is not True:
                raise ValueError("strict_boolean")
        except ValueError as exc:
            raise SelectionFailure("invalid_response") from exc
        raise SelectionFailure("abstention")
    try:
        choice = OptionChoice.model_validate(data)
    except ValueError as exc:
        raise SelectionFailure("invalid_response") from exc
    matches = [option for option in options if option.option_id == choice.option_id]
    if len(matches) != 1:
        raise SelectionFailure("unknown_option_id")
    return matches[0]


async def generate_closed_choice_coach(
    intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: legacy.HybridPermissions = legacy.HybridPermissions(),
    language: str = "fr", transport: Transport | None = None,
    v2_evidence: ScopedV2Evidence | None = None,
) -> ClosedChoiceResult:
    """No failure text and no fallback. Production routing remains the caller's job."""
    start = perf_counter()
    if not legacy._authorized(access):
        return ClosedChoiceResult(mode="denied", reason="workout_analysis_not_authorized")
    if os.getenv(legacy.FEATURE_FLAG, "").lower() not in {"1", "true", "yes"}:
        return ClosedChoiceResult(mode="disabled", reason="flag_off")
    if not access.can("llm_access"):
        return ClosedChoiceResult(mode="denied", reason="llm_access_not_authorized")
    language = legacy._language(language)
    result = ClosedChoiceResult(mode="failed", reason="provider_unavailable", language=language)
    try:
        facts = legacy.build_admissible_facts(
            intelligence, access=access, permissions=permissions,
            language=language, v2_evidence=v2_evidence,
        )
        options = build_editorial_options(facts, language)
        if not options or len(options) > MAX_OPTIONS:
            raise SelectionFailure("option_not_admissible")
        if len({o.option_id for o in options}) != len(options):
            raise SelectionFailure("option_not_admissible")
        for option in options:
            validate_option(option, facts, language)
        result.option_count = len(options)
        index = {fact.id: fact for fact in facts}
        prompt = json.dumps({
            "language": language,
            "options": [option.provider_option(index) for option in options],
            "selection_schema": {
                "oneOf": [
                    {**OptionChoice.model_json_schema(), "properties": {
                        "option_id": {"type": "string", "enum": [o.option_id for o in options]},
                    }},
                    Abstention.model_json_schema(),
                ],
            },
        }, ensure_ascii=False, allow_nan=False)
        if len(prompt) > MAX_CONTEXT_CHARS:
            raise SelectionFailure("size_limit")
        # Explicit injection is required: no implicit production provider activation.
        if transport is None:
            return result
        result.provider_attempted = True
        result.transport_kind = "injected"
        response, success, metadata = await asyncio.wait_for(
            transport(
                "Select exactly one complete editorial option for the runner. "
                'Return only {"option_id":"option_N"} or {"abstain":true}. '
                "Prefer distinctive useful information without redundant complements. "
                "Never write user-facing text, combine options, alter facts, values or units, "
                "infer physiology, causality, fitness, fatigue or prescriptions.",
                prompt, "anonymous", "c374_closed_choice",
            ),
            timeout=TIMEOUT_SECONDS,
        )
        if success is not True:
            raise SelectionFailure("provider_unavailable")
        if not isinstance(response, str):
            raise SelectionFailure("invalid_response")
        if isinstance(metadata, dict):
            if metadata.get("response_truncated") is True:
                raise SelectionFailure("size_limit")
            duration = metadata.get("duration_sec")
            if legacy._finite(duration) and duration >= 0:
                result.provider_duration_sec = duration
        selected = validate_choice(response, options)
        validate_option(selected, facts, language)
        result.mode = "editorial_realization"
        result.reason = "option_validated"
        result.option_id = selected.option_id
        result.text = selected.text
        result.claims = list(selected.claims)
        result.advice, result.advice_reason = selected.advice, selected.advice_reason
        result.verification_scope = "closed_realization"
    except asyncio.TimeoutError:
        result.reason = "timeout"
    except SelectionFailure as exc:
        result.reason = str(exc)
    except Exception:
        # Neither untrusted content nor provider exception details reach diagnostics.
        result.reason = "provider_unavailable" if result.provider_attempted else "option_not_admissible"
    finally:
        result.elapsed_ms = (perf_counter() - start) * 1000
    return result
