"""Scoped transport of the existing V2 judgment; no scientific computation."""

from dataclasses import dataclass

from narrative_coach_v3 import _approved_repetition_judgment
from workout_analysis_v2 import WorkoutAnalysisV2Response


@dataclass(frozen=True)
class ScopedV2Evidence:
    """Internal loader evidence, never a client-supplied or provider contract."""

    user_id: str
    analysis: WorkoutAnalysisV2Response
    source: str = "workout_analysis_v2"


def approved_v2_regularity(
    evidence: ScopedV2Evidence | None, *, user_id: str, workout_id: str, effort_count,
) -> dict | None:
    """Check binding and declared coverage; reuse Narrative's categorical admission."""
    if (type(evidence) is not ScopedV2Evidence or not user_id or not workout_id
            or evidence.user_id != user_id or evidence.source != "workout_analysis_v2"
            or type(evidence.analysis) is not WorkoutAnalysisV2Response):
        return None
    analysis = evidence.analysis
    try:
        phases = analysis.phase_analysis
        regularity = phases.effort_regularity
        if (analysis.version != "v2" or analysis.workout.id != workout_id
                or phases.available is not True or phases.source != "garmin"
                or not phases.phases or not phases.efforts
                or any(phase.source != "garmin" for phase in phases.phases)
                or [phase for phase in phases.phases if phase.phase_type == "effort"] != phases.efforts
                or regularity.available is not True or regularity.partial_comparison is not False
                or type(effort_count) not in (int, float) or effort_count != len(phases.efforts)
                or regularity.effort_count != effort_count
                or regularity.comparable_effort_count != effort_count
                or regularity.pace_sample_count != effort_count):
            return None
        judgment = _approved_repetition_judgment(analysis.coach_language, effort_count)
        if judgment is None:
            return None
        item = analysis.coach_language.conclusions[judgment["index"]]
        basis = item.metadata["comparability_basis"]
        if item.available is not True or regularity.comparability_basis != basis:
            return None
        return {**judgment, "basis": basis}
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return None
