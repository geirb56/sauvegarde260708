"""Scoped transport of the existing V2 judgment; no scientific computation."""

from dataclasses import dataclass
import math

from narrative_coach_v3 import _approved_repetition_judgment
from workout_analysis_v2 import WorkoutAnalysisV2Response


def _finite_positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _finite_nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


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


def approved_v2_pace_direction(
    evidence: ScopedV2Evidence | None, *, user_id: str, workout_id: str, effort_count,
) -> dict | None:
    """Admit only V2's explicit, scoped faster/slower repetition conclusion."""
    regularity = approved_v2_regularity(
        evidence, user_id=user_id, workout_id=workout_id, effort_count=effort_count,
    )
    if regularity is None:
        return None
    try:
        analysis = evidence.analysis
        phases = analysis.phase_analysis
        conclusions = analysis.coach_language.conclusions
        eligible = [
            index for index, candidate in enumerate(conclusions)
            if candidate.code in {"coach.repetitions.pacing", "coach.repetitions.pace_hr"}
            and candidate.category == "repetitions" and candidate.kind == "conclusion"
        ]
        if eligible != [regularity["index"]]:
            return None
        item = conclusions[regularity["index"]]
        metadata, proof = item.metadata, item.evidence
        direction = metadata.get("direction")
        scope = metadata.get("trend_scope")
        if (direction not in {"faster", "slower"}
                or not _finite_nonnegative(proof.get("pace_uncertainty_sec_per_km"))
                or proof.get("atypical_candidate_count") != 0):
            return None
        orders = [phase.order for phase in phases.phases]
        if (any(type(order) is not int or order < 0 for order in orders)
                or any(right <= left for left, right in zip(orders, orders[1:]))
                or "incoherent_pace" in phases.limitations
                or [phase for phase in phases.phases if phase.phase_type == "effort"] != phases.efforts
                or any(phase.phase_type == "unknown" for phase in phases.phases
                       if phases.efforts[0].order < phase.order < phases.efforts[-1].order)
                or any(
                    not _finite_positive(value)
                    for phase in phases.efforts
                    for value in (phase.duration_s, phase.distance_m, phase.pace_sec_per_km)
                )
                or any(
                    phase.average_speed_mps is not None
                    and not _finite_positive(phase.average_speed_mps)
                    for phase in phases.efforts
                )):
            return None

        if scope == "equal_count_endpoint_groups_middle_excluded":
            count = regularity["count"]
            group_size = proof.get("group_size")
            change = proof.get("group_pace_change_sec_per_km")
            start = proof.get("start_group_pace_sec_per_km")
            end = proof.get("end_group_pace_sec_per_km")
            limit = proof.get("trend_limit_sec_per_km")
            uncertainty = proof.get("pace_uncertainty_sec_per_km")
            if (count < 4 or metadata.get("group_direction") != direction
                    or not _finite_number(group_size) or int(group_size) != group_size
                    or group_size != count // 2
                    or not all(_finite_positive(value) for value in (start, end, limit))
                    or not _finite_number(change)
                    or not math.isclose(change, end - start, rel_tol=0, abs_tol=1e-8)
                    or abs(change) <= limit + 2 * uncertainty
                    or (direction == "faster" and change >= 0)
                    or (direction == "slower" and change <= 0)):
                return None
            return {
                **regularity, "direction": direction, "scope": scope,
                "pace_change_sec_per_km": change, "group_size": int(group_size),
            }

        if scope == "first_last_of_three_efforts":
            change = proof.get("first_to_last_pace_change_sec_per_km")
            first = proof.get("first_pace_sec_per_km")
            last = proof.get("last_pace_sec_per_km")
            limit = proof.get("trend_limit_sec_per_km")
            if (regularity["count"] != 3 or "group_direction" in metadata
                    or not all(_finite_positive(value) for value in (first, last))
                    or not _finite_positive(limit)
                    or not _finite_number(change)
                    or not math.isclose(change, last - first, rel_tol=0, abs_tol=1e-8)
                    or abs(change) <= limit + 2 * proof["pace_uncertainty_sec_per_km"]
                    or (direction == "faster" and change >= 0)
                    or (direction == "slower" and change <= 0)):
                return None
            return {
                **regularity, "direction": direction, "scope": scope,
                "pace_change_sec_per_km": change,
            }
        return None
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return None
