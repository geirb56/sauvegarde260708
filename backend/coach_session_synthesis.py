"""Presentation-only selection of canonical Workout Analysis V2 observations."""

import math
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class SessionSynthesisItem(BaseModel):
    code: str
    text: str
    evidence: Dict[str, float]
    source_paths: List[str] = Field(min_length=1)
    replaces_factual_codes: List[str] = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def _finite_evidence(cls, value):
        if not isinstance(value, dict) or not value or not all(
            isinstance(number, (int, float)) and not isinstance(number, bool)
            and math.isfinite(number) for number in value.values()
        ):
            raise ValueError("Synthesis requires finite measured evidence")
        return value


class SessionSynthesisLimit(BaseModel):
    code: str
    text: str
    source_paths: List[str] = Field(min_length=1)


class CoachSessionSynthesisV2(BaseModel):
    version: Literal["v2"] = "v2"
    status: Literal["available", "insufficient"]
    primary: Optional[SessionSynthesisItem] = None
    supporting: List[SessionSynthesisItem] = Field(default_factory=list, max_length=2)
    limitations: List[SessionSynthesisLimit] = Field(default_factory=list, max_length=2)
    abstention: Optional[str] = None


def _text(language, fr, en, es):
    return {"fr": fr, "en": en, "es": es}.get(language, en)


def _pace(minutes):
    seconds = round(minutes * 60)
    return f"{seconds // 60}:{seconds % 60:02d}/km"


def build_session_synthesis(coach_language, facts, contextual_facts, history_environment, language):
    """Select, never recalculate, scientific conclusions or comparability.

    Contextual facts are built by V2 from its measured totals/phase statistics.
    Legacy history facts are intentionally excluded: only the guarded Coach
    conclusion can authorize their use, including the precise environment gate.
    """
    candidates = []
    for index, conclusion in enumerate(coach_language.conclusions):
        if not conclusion.available:
            continue
        if conclusion.category == "history":
            metric = "pace" if conclusion.code == "coach.history.pace" else "hr"
            if history_environment.get(metric) != "same_known":
                continue
        text = conclusion.text
        if conclusion.code == "coach.history.pace":
            current = _pace(conclusion.evidence["current_pace_min_km"])
            baseline = _pace(conclusion.evidence["baseline_pace_min_km"])
            text += " " + _text(
                language,
                f"Allure moyenne enregistrée : {current}, contre {baseline} pour ces références.",
                f"Recorded average pace: {current}, versus {baseline} for these references.",
                f"Ritmo medio registrado: {current}, frente a {baseline} en esas referencias.",
            )
        candidates.append((conclusion.priority, conclusion.category, SessionSynthesisItem(
            code=conclusion.code, text=text, evidence=conclusion.evidence,
            source_paths=[f"coach_language.conclusions[{index}]"],
            replaces_factual_codes=conclusion.replaces_factual_codes,
        )))

    replaced = {code for _, _, item in candidates for code in item.replaces_factual_codes}
    crossed_hr = any("heart_rate_change_bpm" in item.evidence for _, _, item in candidates)
    # Display priorities only; no physiological threshold or new interpretation.
    fact_policy = {
        "fact.pace_change": (25, "pacing"),
        "fact.negative_split": (26, "pacing"),
        "fact.effort_extremes": (35, "repetitions"),
        "fact.effort_dispersion": (36, "repetitions"),
        "fact.effort_hr_evolution": (38, "cardio"),
    }
    for index, fact in enumerate(facts):
        if fact.code not in fact_policy or fact.code in replaced:
            continue
        if fact.code == "fact.effort_hr_evolution" and crossed_hr:
            continue
        priority, category = fact_policy[fact.code]
        candidates.append((priority, category, SessionSynthesisItem(
            code=fact.code, text=fact.text, evidence=fact.evidence,
            source_paths=[f"meaning.factual_observations[{index}]"],
            replaces_factual_codes=[fact.code],
        )))

    for priority, category, item in contextual_facts:
        candidates.append((priority, category, item))
    candidates.sort(key=lambda candidate: (candidate[0], candidate[2].code))
    selected = []
    categories, codes, texts = set(), set(), set()
    for _, category, item in candidates:
        if category in categories or item.code in codes or item.text in texts:
            continue
        # Recorded totals are a useful last resort, not padding after an analysis.
        if category == "totals" and selected:
            continue
        selected.append(item)
        categories.add(category)
        codes.add(item.code)
        texts.add(item.text)
        if len(selected) == 3:
            break

    limits = []
    historical = [item for item in selected if item.code.startswith("coach.history.")]
    if historical:
        limits.append(SessionSynthesisLimit(
            code="synthesis.history_descriptive",
            text=_text(
                language,
                "Cet écart décrit ces séances ; il ne suffit pas à conclure à un changement de forme ni à juger l’exécution.",
                "This difference describes these sessions; it cannot alone establish a change in fitness or judge execution.",
                "Esta diferencia describe esas sesiones; por sí sola no permite establecer un cambio de forma ni juzgar la ejecución.",
            ),
            source_paths=historical[0].source_paths,
        ))
    hr_items = [item for item in selected if "heart_rate_change_bpm" in item.evidence
                or "heart_rate_difference_bpm" in item.evidence
                or item.code == "fact.effort_hr_evolution"]
    if hr_items:
        limits.append(SessionSynthesisLimit(
            code="synthesis.hr_observation",
            text=_text(
                language,
                "Ces observations de FC ne suffisent pas à établir une dérive physiologique ni une efficacité cardiaque.",
                "These heart-rate observations cannot establish physiological drift or cardiac efficiency.",
                "Estas observaciones de FC no permiten establecer deriva fisiológica ni eficiencia cardíaca.",
            ),
            source_paths=hr_items[0].source_paths,
        ))
    return CoachSessionSynthesisV2(
        status="available" if selected else "insufficient",
        primary=selected[0] if selected else None,
        supporting=selected[1:], limitations=limits,
        abstention=None if selected else _text(
            language,
            "Les données disponibles ne permettent pas de dégager une observation fiable de cette séance.",
            "The available data do not support a reliable observation about this session.",
            "Los datos disponibles no permiten extraer una observación fiable de esta sesión.",
        ),
    )
