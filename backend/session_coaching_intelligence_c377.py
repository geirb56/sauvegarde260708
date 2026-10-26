"""C377: deterministic, evidence-bound coaching decisions; no prose or I/O."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

import hybrid_coach_c359 as admissible
from access_control import UserAccess
from hybrid_coach_c359 import AdmissibleFact, HybridPermissions
from hybrid_coach_editorial_c365 import primary_fact_candidates
from hybrid_coach_v2_c372 import ScopedV2Evidence
from workout_intelligence_v3_models import WorkoutIntelligenceV3


VERSION = "c377-session-coaching-intelligence-1"
Confidence = Literal["high", "medium", "low", "none"]
EvidenceValue = str | int | float
FactCode = Literal[
    "interval.pace_direction",
    "interval.regularity",
    "effort.first",
    "effort.last",
    "effort.coverage",
    "interval.count",
    "intensity.position",
    "intensity.hr",
    "session.kind",
    "session.long",
    "session.unknown",
    "comparison.pace",
    "comparison.hr",
]


class _DecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CoachingObservation(_DecisionModel):
    code: FactCode
    category: Literal["pacing", "structure", "intensity", "history", "classification"]
    fact_ids: list[FactCode] = Field(min_length=1, max_length=1)
    source_paths: list[str] = Field(min_length=1)
    evidence: dict[str, EvidenceValue]
    confidence: Confidence
    scope: Literal[
        "recorded_comparable_efforts",
        "recorded_effort_endpoints",
        "recorded_session",
        "recorded_session_classification",
        "personal_thresholds",
        "owner_scoped_history",
    ]
    limitations: list[str]

    @field_validator("evidence")
    @classmethod
    def _finite_evidence(cls, value):
        if not value or any(
            type(item) not in (str, int, float)
            or (type(item) in (int, float) and not math.isfinite(item))
            for item in value.values()
        ):
            raise ValueError("Coaching observations require finite, typed evidence")
        return value


class CoachingInterpretation(_DecisionModel):
    code: Literal[
        "PACE_CONSISTENCY_OBSERVED",
        "PACE_VARIABILITY_OBSERVED",
        "PROGRESSIVE_EFFORT_OBSERVED",
        "LATE_PACE_REDUCTION_OBSERVED",
        "INTENSITY_POSITION_SUPPORTED",
        "HISTORICAL_COMPARISON_OBSERVED",
        "INSUFFICIENT_EVIDENCE",
    ]
    observation_codes: list[FactCode] = Field(min_length=1, max_length=3)
    meaning: Literal[
        "PACE_CONSISTENCY_OBSERVED",
        "PACE_VARIABILITY_OBSERVED",
        "PROGRESSIVE_EFFORT_OBSERVED",
        "LATE_PACE_REDUCTION_OBSERVED",
        "INTENSITY_POSITION_SUPPORTED",
        "HISTORICAL_COMPARISON_OBSERVED",
        "INSUFFICIENT_EVIDENCE",
    ]
    confidence: Confidence
    conditions: list[str]
    limitations: list[str]


class CoachingAdvice(_DecisionModel):
    code: Literal["SEEK_STEADIER_PACE", "PRESERVE_PACE_CONSISTENCY"]
    linked_observation_codes: list[FactCode] = Field(min_length=1, max_length=1)
    linked_interpretation_codes: list[str] = Field(min_length=1, max_length=1)
    advice_intent: Literal["SEEK_STEADIER_PACE", "PRESERVE_PACE_CONSISTENCY"]
    conditions: list[str] = Field(min_length=1)
    contraindications: list[str] = Field(min_length=1)
    confidence: Confidence
    source_paths: list[str] = Field(min_length=1)


class SessionCoachingDecision(_DecisionModel):
    version: Literal["c377-session-coaching-intelligence-1"] = VERSION
    workout_id: str | None
    primary_observation: CoachingObservation | None
    supporting_observations: list[CoachingObservation] = Field(max_length=2)
    interpretation: CoachingInterpretation | None
    advice: CoachingAdvice | None
    abstention_reason: Literal[
        "permission_not_granted",
        "no_admissible_observation",
        "insufficient_evidence",
        "no_safe_specific_advice",
    ] | None = None
    limitations: list[str]
    provenance: list[str]


_FACTS = {
    "interval.pace_direction": (
        "pacing", "recorded_comparable_efforts", "v2_repetition_pace_direction",
        ("workout_analysis_v2.",),
    ),
    "interval.regularity": (
        "pacing", "recorded_comparable_efforts", "v2_repetition_pacing_band",
        ("workout_analysis_v2.",),
    ),
    "effort.first": (
        "pacing", "recorded_effort_endpoints", "recorded_effort_description_only",
        ("effort_pace_observations.", "effort_duration_observations."),
    ),
    "effort.last": (
        "pacing", "recorded_effort_endpoints", "recorded_effort_description_only",
        ("effort_pace_observations.", "effort_duration_observations."),
    ),
    "effort.coverage": (
        "structure", "recorded_session", "recorded_effort_description_only",
        ("effort_pace_observations", "effort_duration_observations"),
    ),
    "interval.count": (
        "structure", "recorded_session", "recorded_intervals_without_regularity",
        ("session_classification.",),
    ),
    "intensity.position": (
        "intensity", "personal_thresholds", "average_hr_threshold_position",
        ("intensity_assessment.",),
    ),
    "intensity.hr": (
        "intensity", "recorded_session", "descriptive_average_hr_only",
        ("intensity_assessment.",),
    ),
    "session.kind": (
        "classification", "recorded_session_classification", "probable_session_type",
        ("session_classification.",),
    ),
    "session.long": (
        "history", "owner_scoped_history", "probable_long_duration_comparison",
        ("session_classification.",),
    ),
    "session.unknown": (
        "classification", "recorded_session_classification", "session_type_unproven",
        ("session_classification.", "intensity_assessment."),
    ),
    "comparison.pace": (
        "history", "owner_scoped_history", "observed_pace_difference_at_comparable_hr",
        ("historical_comparison.",),
    ),
    "comparison.hr": (
        "history", "owner_scoped_history", "observed_hr_difference_at_comparable_pace",
        ("historical_comparison.",),
    ),
}


def _admitted_fact(fact: AdmissibleFact, *, history: bool) -> bool:
    if (
        type(fact) is not AdmissibleFact
        or type(fact.id) is not str
        or type(fact.source_paths) is not tuple
        or type(fact.values) is not tuple
        or type(fact.important_limits) is not tuple
        or fact.confidence not in {"high", "medium", "low", "none"}
    ):
        return False
    spec = _FACTS.get(fact.id)
    if spec is None:
        return False
    _, _, conclusion, prefixes = spec
    if fact.allowed_conclusion != conclusion or not fact.source_paths:
        return False
    if any(
        not isinstance(path, str) or not path or not path.startswith(prefixes)
        or "prescription" in path.lower()
        for path in fact.source_paths
    ):
        return False
    if fact.id.startswith("comparison.") or fact.id == "session.long":
        if not history:
            return False
    try:
        values = dict(fact.values)
        if len(values) != len(fact.values) or any(
            type(value) not in (str, int, float)
            or (type(value) in (int, float) and not math.isfinite(value))
            for value in values.values()
        ):
            return False
        if fact.id == "interval.regularity" and (
            values.get("source") != "workout_analysis_v2"
            or values.get("regularity_band") not in {"homogeneous", "noticeable", "variable"}
            or values.get("status") != "available"
        ):
            return False
        if fact.id == "interval.pace_direction" and (
            values.get("source") != "workout_analysis_v2"
            or values.get("direction") not in {"faster", "slower"}
            or values.get("scope") not in {
                "equal_count_endpoint_groups_middle_excluded",
                "first_last_of_three_efforts",
            }
        ):
            return False
    except (TypeError, ValueError):
        return False
    return True


def _observation(fact: AdmissibleFact) -> CoachingObservation:
    category, scope, _, _ = _FACTS[fact.id]
    return CoachingObservation(
        code=fact.id,
        category=category,
        fact_ids=[fact.id],
        source_paths=list(fact.source_paths),
        evidence=dict(fact.values),
        confidence=fact.confidence,
        scope=scope,
        limitations=list(fact.important_limits),
    )


def _interpretation(
    observation: CoachingObservation, fact: AdmissibleFact,
) -> CoachingInterpretation:
    values = dict(fact.values)
    meaning = "INSUFFICIENT_EVIDENCE"
    conditions: list[str] = []
    if fact.id == "interval.pace_direction":
        meaning = (
            "PROGRESSIVE_EFFORT_OBSERVED"
            if values["direction"] == "faster"
            else "LATE_PACE_REDUCTION_OBSERVED"
        )
        conditions = ["validated_v2_pace_direction", values["scope"]]
    elif fact.id == "interval.regularity":
        meaning = (
            "PACE_CONSISTENCY_OBSERVED"
            if values["regularity_band"] == "homogeneous"
            else "PACE_VARIABILITY_OBSERVED"
        )
        conditions = [
            "validated_v2_regularity_judgment",
            "all_comparable_recorded_efforts",
            values["comparability_basis"],
        ]
    elif fact.id == "intensity.position":
        meaning = "INTENSITY_POSITION_SUPPORTED"
        conditions = ["validated_v3_personal_thresholds", "session_average_only"]
    elif fact.id.startswith("comparison."):
        meaning = "HISTORICAL_COMPARISON_OBSERVED"
        conditions = ["owner_scoped_history_permission", "v3_strong_comparability"]
    return CoachingInterpretation(
        code=meaning,
        meaning=meaning,
        observation_codes=[observation.code],
        confidence=fact.confidence,
        conditions=conditions or ["available_observation_is_descriptive_only"],
        limitations=list(fact.important_limits),
    )


def _advice(
    fact: AdmissibleFact,
    observation: CoachingObservation,
    interpretation: CoachingInterpretation,
    *,
    has_direction: bool,
) -> CoachingAdvice | None:
    if fact.id != "interval.regularity" or has_direction:
        return None
    band = dict(fact.values).get("regularity_band")
    if band == "variable":
        code = "SEEK_STEADIER_PACE"
        conditions = [
            "v2_validated_variable_regularity",
            "same_comparable_effort_structure",
            "next_similar_session_only",
        ]
        contraindications = [
            "intentionally_variable_efforts",
            "session_objective_unknown",
        ]
    elif band == "homogeneous":
        code = "PRESERVE_PACE_CONSISTENCY"
        conditions = [
            "v2_validated_homogeneous_regularity",
            "same_comparable_effort_structure",
            "next_similar_session_only",
        ]
        contraindications = [
            "intentionally_progressive_efforts",
            "session_objective_unknown",
        ]
    else:
        return None
    return CoachingAdvice(
        code=code,
        linked_observation_codes=[observation.code],
        linked_interpretation_codes=[interpretation.code],
        advice_intent=code,
        conditions=conditions,
        contraindications=contraindications,
        confidence=fact.confidence,
        source_paths=list(fact.source_paths),
    )


def build_session_coaching_decision(
    intelligence: WorkoutIntelligenceV3,
    *,
    access: UserAccess,
    permissions: HybridPermissions = HybridPermissions(),
    v2_evidence: ScopedV2Evidence | None = None,
) -> SessionCoachingDecision:
    """Build an offline decision from admitted evidence; prescription is excluded."""
    workout_id = (
        intelligence.workout_id
        if type(intelligence) is WorkoutIntelligenceV3 else None
    )
    common = {
        "workout_id": workout_id,
        "primary_observation": None,
        "supporting_observations": [],
        "interpretation": None,
        "advice": None,
        "limitations": [
            "no_free_text_or_causal_inference",
            "no_prescription_or_plan_comparison",
            "missing_data_is_not_negative_performance",
        ],
        "provenance": [],
    }
    if not admissible._authorized(access):
        return SessionCoachingDecision(
            **common, abstention_reason="permission_not_granted",
        )
    if (
        type(intelligence) is not WorkoutIntelligenceV3
        or intelligence.version != "v3"
    ):
        return SessionCoachingDecision(
            **common, abstention_reason="no_admissible_observation",
        )

    history_authorized = (
        type(permissions) is HybridPermissions and permissions.history is True
    )
    facts = admissible.build_admissible_facts(
        intelligence,
        access=access,
        permissions=HybridPermissions(history=history_authorized),
        v2_evidence=v2_evidence,
    )
    admitted = tuple(
        fact for fact in facts
        if _admitted_fact(fact, history=history_authorized)
    )
    if not admitted:
        return SessionCoachingDecision(
            **common, abstention_reason="no_admissible_observation",
        )

    by_id = {fact.id: fact for fact in admitted}
    candidates = [
        fact_id for fact_id in primary_fact_candidates(admitted)
        if fact_id in by_id
    ]
    if "interval.pace_direction" in by_id:
        candidates = [
            "interval.pace_direction",
            *(["interval.regularity"] if "interval.regularity" in by_id else []),
        ]
    elif "interval.regularity" in by_id:
        candidates = ["interval.regularity"]
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return SessionCoachingDecision(
            **common, abstention_reason="no_admissible_observation",
        )

    primary_fact = by_id[candidates[0]]
    primary = _observation(primary_fact)
    supporting = [_observation(by_id[item]) for item in candidates[1:3]]
    interpretation = _interpretation(primary, primary_fact)
    if interpretation.meaning == "INSUFFICIENT_EVIDENCE":
        interpretation = None
        reason = "insufficient_evidence"
    else:
        reason = None

    regularity_fact = by_id.get("interval.regularity")
    regularity_observation = next(
        (item for item in [primary, *supporting] if item.code == "interval.regularity"),
        None,
    )
    advice = None
    if (
        regularity_fact is not None
        and regularity_observation is not None
        and interpretation is not None
        and interpretation.observation_codes == [regularity_observation.code]
    ):
        advice = _advice(
            regularity_fact, regularity_observation, interpretation,
            has_direction="interval.pace_direction" in by_id,
        )
    if advice is None and reason is None:
        reason = "no_safe_specific_advice"

    observations = [primary, *supporting]
    provenance = list(dict.fromkeys(
        path for observation in observations for path in observation.source_paths
    ))
    return SessionCoachingDecision(
        **{
            **common,
            "primary_observation": primary,
            "supporting_observations": supporting,
            "interpretation": interpretation,
            "advice": advice,
            "abstention_reason": reason,
            "provenance": provenance,
        },
    )
