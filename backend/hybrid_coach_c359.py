"""C359 offline prototype. Not imported by any route, loader or UI.

Only trusted, owner-scoped V3 output and server-resolved UserAccess belong here.
Permissions are additional server-side restrictions, never request-body grants.
No historical KB tip has adequate scientific provenance: none is loaded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import os
import re
from time import perf_counter
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from access_control import UserAccess
from narrative_coach_v3 import (
    Transport,
    build_narrative_context,
    format_narrative_number,
)
from workout_intelligence_v3_models import WorkoutIntelligenceV3

FEATURE_FLAG = "C359_HYBRID_COACH_ENABLED"
TIMEOUT_SECONDS = 8.0
MAX_RESPONSE_CHARS = 700
VERSION = "c359-bounded-paraphrase-1"

# Exact substitutions, not fuzzy similarity or a bag-of-numbers check. Every
# unmatched character (including units, qualifiers and negation) stays literal.
REPHRASINGS = {
    "fr": (
        ("Ta fréquence cardiaque moyenne sur cette séance était de",
         "Sur cette séance, ta FC moyenne était de"),
        ("Ta fréquence cardiaque moyenne", "Ta FC moyenne"),
        ("selon tes seuils personnels", "d'après tes seuils personnels"),
        ("Garmin a enregistré", "L'enregistrement Garmin montre"),
        ("phases d'effort", "phases d'effort enregistrées"),
        ("Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable.",
         "Avec les données disponibles, le type de séance reste incertain."),
        ("Par rapport à tes", "En regard de tes"),
        ("cet effort paraît", "cet effort semble"),
        ("Ton historique comparable ne permet pas encore de savoir avec confiance",
         "Les séances comparables disponibles ne permettent pas encore de savoir avec confiance"),
    ),
    "en": (
        ("Your average heart rate for this session was", "Your session's average heart rate was"),
        ("Garmin recorded", "The Garmin recording shows"),
        ("using your personal thresholds", "based on your personal thresholds"),
        ("this effort looks", "this effort appears"),
    ),
    "es": (
        ("Tu FC media en esta sesión fue de", "En esta sesión, tu FC media fue de"),
        ("Garmin registró", "El registro de Garmin muestra"),
        ("según tus umbrales personales", "con tus umbrales personales como referencia"),
        ("este esfuerzo parece", "este esfuerzo se presenta como"),
    ),
}

# A closed allowlist is intentional: future V3 claims do not silently acquire
# authorization here. Dependencies also include indirect classification facts.
_CLAIMS = {
    "session.kind": "classification",
    "session.unknown": "classification",
    "interval.count": "session",
    "interval.execution": "session",
    "intensity.hr": "session",
    "intensity.position": "session",
    "intensity.relative": "history",
    "trend.improvement": "history",
    "trend.stable": "history",
    "trend.decline": "history",
    "trend.insufficient": "history",
    "limit.scope": "session",
    "prescription.status": "prescription",
    "prescription.review": "prescription",
}


@dataclass(frozen=True)
class HybridPermissions:
    history: bool = False
    prescription: bool = False


class HybridClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    section: str
    text: str
    evidence_refs: list[str]


class HybridResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = VERSION
    mode: Literal["disabled", "denied", "deterministic_fallback", "llm_validated"]
    reason: str
    text: str = ""
    claims: list[HybridClaim] = Field(default_factory=list)
    provider_attempted: bool = False
    transport_kind: Literal["none", "runindex", "injected"] = "none"
    elapsed_ms: float = 0
    provider_duration_sec: Optional[float] = None
    cost: Optional[float] = None
    """No tariff or token usage is provided by the existing transport."""


def _authorized(access: Optional[UserAccess]) -> bool:
    return isinstance(access, UserAccess) and access.can("coach_workout_analysis")


def build_hybrid_context(
    intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(), language: str = "fr",
) -> dict:
    """Build only permitted claims; raw IDs, dates, prose and goals never cross."""
    if not _authorized(access):
        return {"language": "fr", "claims": []}
    context = build_narrative_context(intelligence, language)
    history = permissions.history is True
    prescription = permissions.prescription is True
    classification = intelligence.session_classification
    history_classification = (
        classification.decision_tier == "individual_history"
        or classification.type == "long_run_probable"
        or any(path == "history" or path.startswith("history.") for path in classification.source_paths)
    )
    claims = []
    for claim in context["claims"]:
        dependency = _CLAIMS.get(claim["id"])
        if dependency is None:
            continue
        if dependency == "history" and not history:
            continue
        if dependency == "classification" and history_classification and not history:
            continue
        if dependency == "prescription" and (
            not prescription or (history_classification and not history)
        ):
            continue
        # No phase-analysis input is accepted by this V3-only prototype.
        if any(ref.startswith(("phase_analysis.", "coach_language.")) for ref in claim["evidence_refs"]):
            continue
        claims.append(HybridClaim(
            id=claim["id"], section=claim["section"], text=claim["variants"][0],
            evidence_refs=claim["evidence_refs"],
        ))
    # A history-derived headline/primary reading must not leak via an indirect
    # classification dependency. Descriptive HR remains usable without history.
    if history_classification and not history:
        hr = format_narrative_number(intelligence.intensity_assessment.hr_used_bpm, context["language"])
        if hr is not None:
            text = {
                "fr": f"Ta fréquence cardiaque moyenne sur cette séance était de {hr} bpm.",
                "en": f"Your average heart rate for this session was {hr} bpm.",
                "es": f"Tu FC media en esta sesión fue de {hr} lpm.",
            }[context["language"]]
            claims.insert(0, HybridClaim(
                id="intensity.hr", section="analysis", text=text,
                evidence_refs=["intensity_assessment.hr_used_bpm"],
            ))
    if intelligence.session_classification.confidence in {"low", "none"} and any(
        c.id == "session.kind" for c in claims
    ):
        claims.append(HybridClaim(
            id="confidence.limit", section="limitations", text={
                "fr": "Le type de séance reste incertain.",
                "en": "The session type remains uncertain.",
                "es": "El tipo de sesión sigue siendo incierto.",
            }[context["language"]],
            evidence_refs=["session_classification.confidence"],
        ))
    return {"language": context["language"], "claims": [c.model_dump() for c in claims]}


def _equivalent(candidate: str, original: str, language: str) -> bool:
    """Recognize a finite compositional grammar; never judge arbitrary meaning."""
    rules = sorted(REPHRASINGS[language], key=lambda pair: len(pair[0]), reverse=True)
    parts = []
    position = 0
    while position < len(original):
        match = next(((a, b) for a, b in rules if original.startswith(a, position)), None)
        if match is None:
            parts.append(re.escape(original[position]))
            position += 1
        else:
            a, b = match
            parts.append(f"(?:{re.escape(a)}|{re.escape(b)})")
            position += len(a)
    return re.fullmatch("".join(parts), candidate) is not None


def validate_hybrid_lead(payload: object, context: dict) -> Optional[list[HybridClaim]]:
    """Internal validator over freshly rebuilt authorized context, not client refs."""
    if type(payload) is not dict or set(payload) != {"lead"}:
        return None
    lead = payload["lead"]
    if type(lead) is not list or len(lead) != 2:
        return None
    index, text = lead
    if type(index) is not int or not 0 <= index < len(context["claims"]):
        return None
    if type(text) is not str or len(text) > 500:
        return None
    claims = [HybridClaim(**claim) for claim in context["claims"]]
    claim = claims[index]
    if claim.section not in {"analysis", "interpretation"}:
        return None
    if not _equivalent(text, claim.text, context["language"]):
        return None
    claims[index] = claim.model_copy(update={"text": text})
    return claims


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _render(claims: list[HybridClaim]) -> str:
    # Mandatory caveats stay attached, not hidden in UI metadata. Only the
    # canonical prescription review can be advice; no new next-session target.
    order = ("headline", "analysis", "interpretation", "limitations", "recommendation")
    return " ".join(
        c.text + ("." if section == "headline" and not c.text.endswith((".", "!", "?")) else "")
        for section in order for c in claims if c.section == section
    )


async def _transport(system, prompt, user, context_type):
    from llm_coach import _call_gpt

    return await _call_gpt(system, prompt, user, context_type)


async def generate_hybrid_coach(
    intelligence: WorkoutIntelligenceV3, *, access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(), language: str = "fr",
    transport: Optional[Transport] = None,
) -> HybridResult:
    """One bounded call, no retry/cache/persistence; cancellation propagates.

    Only a single lead sentence is rewritten, keeping JSON comfortably below
    the existing provider's 700-character prose-cleaning boundary. Remaining
    claims, including all required caveats, are rendered locally unchanged.
    """
    start = perf_counter()
    if not _authorized(access):
        return HybridResult(mode="denied", reason="workout_analysis_not_authorized")
    if os.getenv(FEATURE_FLAG, "").lower() not in {"1", "true", "yes"}:
        return HybridResult(mode="disabled", reason="flag_off")
    context = build_hybrid_context(
        intelligence, access=access, permissions=permissions, language=language,
    )
    claims = [HybridClaim(**claim) for claim in context["claims"]]
    result = HybridResult(
        mode="deterministic_fallback", reason="provider_unavailable",
        text=_render(claims), claims=claims,
    )
    eligible = [i for i, c in enumerate(claims) if c.section in {"analysis", "interpretation"}]
    if not eligible or not access.can("llm_access"):
        result.reason = "no_authorized_lead"
        result.elapsed_ms = (perf_counter() - start) * 1000
        return result
    # Evidence paths and identifiers stay local. Provider receives only
    # authorized literal observations plus audited presentation substitutions.
    prompt = json.dumps({
        "version": VERSION, "language": context["language"],
        "sentences": [[i, claims[i].text] for i in eligible],
        "equivalent_phrases": REPHRASINGS[context["language"]],
    }, ensure_ascii=False, allow_nan=False)
    system = (
        "Be a concise, natural running coach. Explain facts, never prescribe. "
        "Rewrite ONE supplied sentence using only the supplied equivalent phrase "
        "substitutions. All other characters, numbers, units, uncertainty, "
        "negations and caveats must remain unchanged. Do not add a fact, cause, "
        "threshold, history comparison or advice. Return only compact JSON "
        '{"lead":[sentence_index,"rewritten sentence"]}, under 700 characters. '
        "Unverifiable paraphrases will be rejected."
    )
    result.provider_attempted = True
    result.transport_kind = "injected" if transport is not None else "runindex"
    try:
        text, success, metadata = await asyncio.wait_for(
            (transport or _transport)(system, prompt, "anonymous", "c359_hybrid"),
            timeout=TIMEOUT_SECONDS,
        )
        duration = metadata.get("duration_sec") if isinstance(metadata, dict) else None
        if type(duration) in (float, int) and math.isfinite(duration) and duration >= 0:
            result.provider_duration_sec = duration
        if success and isinstance(text, str) and len(text) <= MAX_RESPONSE_CHARS:
            payload = json.loads(text, object_pairs_hook=_unique_object)
            validated = validate_hybrid_lead(payload, context)
            if validated is not None:
                result.claims = validated
                result.text = _render(validated)
                result.mode, result.reason = "llm_validated", "bounded_equivalence"
            else:
                result.reason = "nonconforming_response"
    except asyncio.TimeoutError:
        result.reason = "timeout"
    except Exception:
        # Never retain/log raw provider text, errors or private input data.
        result.reason = "invalid_response_or_provider_error"
    result.elapsed_ms = (perf_counter() - start) * 1000
    return result
