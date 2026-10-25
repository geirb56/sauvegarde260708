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
    EditorialClause, EditorialSelection, editorial_intent, primary_fact_candidates,
    realize_clause, validate_editorial_selection,
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

    @property
    def text(self) -> str:
        return " ".join(claim.text for claim in self.claims)

    def provider_option(self, facts: dict[str, legacy.AdmissibleFact]) -> dict:
        return {
            "option_id": self.option_id,
            "primary": self.primary,
            "supporting": list(self.supporting),
            "editorial_intent": self.editorial_intent,
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
    blockers: list[str] = Field(default_factory=lambda: [
        "real_llm_editorial_quality_not_evaluated",
    ])


def _candidates(facts):
    candidates = primary_fact_candidates(facts)
    if any(f.id == "session.unknown" for f in facts) and "intensity.hr" in candidates:
        return (*candidates, "session.unknown")
    return candidates


def _validate_composition(primary, supporting, facts, language):
    ids = (primary, *supporting)
    index = {fact.id: fact for fact in facts}
    if (len(index) != len(facts) or len(ids) != len(set(ids)) or len(supporting) > 2
            or any(fact_id not in index for fact_id in ids)
            or primary not in _candidates(facts)):
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
    if "interval.regularity" in selected and selected & {
        "interval.count", "effort.first", "effort.last", "effort.coverage",
    }:
        raise SelectionFailure("option_not_admissible")


def _realize(fact, form, language):
    if form != "direct":
        raise SelectionFailure("option_not_admissible")
    text = realize_clause(fact, form, language)

    def tr(fr, en, es):
        return {"fr": fr, "en": en, "es": es}[language]

    if fact.id in {"intensity.hr", "intensity.position", "session.unknown"}:
        text += tr(
            " Une FC moyenne ne décrit pas chaque phase ni le temps en zones et ne démontre ni progression ni cause physiologique.",
            " An average HR describes neither each phase nor time in zones and establishes neither progress nor a physiological cause.",
            " Una FC media no describe cada fase ni el tiempo en zonas y no demuestra progreso ni una causa fisiológica.",
        )
    if fact.id in {"interval.regularity", "interval.pace_direction"}:
        text += tr(
            " Cette observation des allures des répétitions comparables enregistrées ne démontre ni fatigue, ni récupération, ni progression physiologique, ni causalité.",
            " This observation of recorded comparable repetition paces establishes neither fatigue, recovery, physiological progress nor causality.",
            " Esta observación de los ritmos de repeticiones comparables registradas no demuestra fatiga, recuperación, progreso fisiológico ni causalidad.",
        )
    if fact.id == "interval.regularity":
        text += tr(
            " Ce constat décrit les allures, pas une stabilité physiologique ni une évaluation bonne ou mauvaise.",
            " This describes paces, not physiological stability or a good-or-bad assessment.",
            " Esto describe ritmos, no estabilidad fisiológica ni una valoración buena o mala.",
        )
    if fact.id == "interval.count":
        text += tr(
            " Ce décompte ne donne pas les durées des répétitions et ne permet pas de juger leur régularité.",
            " This count supplies no repetition durations and does not establish regularity.",
            " Este recuento no aporta duraciones de repeticiones ni permite juzgar su regularidad.",
        )
    if fact.id == "session.kind":
        text += tr(
            " Ce type probable ne détermine pas l'intensité physiologique de chaque phase.",
            " This probable type does not establish each phase's physiological intensity.",
            " Este tipo probable no determina la intensidad fisiológica de cada fase.",
        )
    if fact.id.startswith("effort."):
        text += tr(
            " Ces observations enregistrées ne garantissent pas la couverture de toute la séance et ne démontrent ni fatigue ni récupération.",
            " These recorded observations do not guarantee whole-session coverage and establish neither fatigue nor recovery.",
            " Estas observaciones registradas no garantizan la cobertura de toda la sesión ni demuestran fatiga o recuperación.",
        )
    if fact.id.startswith(("comparison.", "trend.")):
        text += tr(
            " Ce n'est pas une preuve de changement de forme ni de causalité ; les effets du terrain et de la météo ne sont pas isolés.",
            " This is not proof of a fitness change or causality; terrain and weather effects are not isolated.",
            " No es una prueba de cambio de forma ni de causalidad; no se aíslan los efectos del terreno y del clima.",
        )
    if fact.id == "session.long":
        text += tr(
            " La durée ne détermine pas l'intensité physiologique.",
            " Duration does not establish physiological intensity.",
            " La duración no determina la intensidad fisiológica.",
        )
    if fact.id == "prescription.review":
        text += tr(
            " Cette lecture porte uniquement sur le type probable, pas sur la conformité complète ; elle n'infère aucune cause et ne crée aucune prescription ni allure cible.",
            " This reviews probable type only, not full compliance; it infers no cause and creates no prescription or target pace.",
            " Esta lectura trata solo del tipo probable, no del cumplimiento completo; no infiere causas ni crea prescripciones o ritmos objetivo.",
        )
    return legacy._claim(fact).model_copy(update={"text": text})


def _make_option(option_id, primary, supporting, facts, language):
    _validate_composition(primary, supporting, facts, language)
    index = {fact.id: fact for fact in facts}
    forms = ("direct",) * (1 + len(supporting))
    claims = tuple(_realize(index[fact_id], form, language)
                   for fact_id, form in zip((primary, *supporting), forms))
    option = EditorialOption(
        option_id, primary, supporting, editorial_intent(index[primary]), forms, claims,
    )
    if len(option.text) > legacy.MAX_COACH_TEXT_CHARS:
        raise SelectionFailure("size_limit")
    return option


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
    index = {fact.id: fact for fact in facts}
    enriched, bare = [], []
    deviation = ("prescription.review" in index
                 and dict(index["prescription.review"].values).get("status") == "deviation")
    for primary in _candidates(facts):
        base = _make_option("", primary, (), facts, language)
        support = []
        preferred = []
        if primary == "interval.pace_direction":
            preferred.append("interval.regularity")
        if deviation:
            preferred.append("prescription.review")
        if primary == "intensity.position":
            preferred.append("session.kind")
        elif primary == "session.kind":
            preferred.append("intensity.position")
        elif primary == "interval.count":
            preferred.extend(("intensity.position", "intensity.hr"))
        elif primary in {"effort.first", "effort.last"}:
            preferred.extend(("effort.last", "effort.coverage"))
        intensity = index.get("intensity.position")
        if intensity and dict(intensity.values).get("position") == "above_LT2":
            preferred.append("intensity.position")
        for fact_id in preferred:
            if fact_id not in index or fact_id in (primary, *support) or len(support) == 2:
                continue
            try:
                _validate_composition(primary, (*support, fact_id), facts, language)
            except SelectionFailure:
                continue
            support.append(fact_id)
        enriched.append(_make_option("", primary, tuple(support), facts, language))
        if support:
            bare.append(base)
    options = tuple(
        EditorialOption(f"option_{i}", o.primary, o.supporting, o.editorial_intent,
                        o.forms, o.claims)
        for i, o in enumerate((enriched + bare)[:MAX_OPTIONS], 1)
    )
    for option in options:
        validate_option(option, facts, language)
    return options


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
    result = ClosedChoiceResult(mode="failed", reason="provider_unavailable")
    language = legacy._language(language)
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
