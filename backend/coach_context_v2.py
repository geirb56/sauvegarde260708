from __future__ import annotations

import copy
import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from training_v2.performance_model import (
    CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO,
    PerformanceEstimate,
)
from training_v2.periodization import build_periodization
from training_v2.plan_goal import PlanGoal, build_plan_goal
from training_v2.readiness_decision import ReadinessDecision
from training_v2.training_cycle_response import build_cycle_calendar_response
from training_v2.training_history import build_training_history
from training_v2.prescription_snapshot import (
    PrescriptionSnapshot,
    is_snapshot_authoritative,
)
from training_v2.training_load import TrainingLoadSnapshot
from training_v2.training_paces import TrainingPaces, training_paces_to_api_dict
from workout_analysis_v2 import WorkoutAnalysisV2Response
from workout_analysis_v2 import SIMILAR_HISTORY_WINDOW_DAYS
from workout_intelligence_v3 import DURATION_MATCH_TOLERANCE_PCT, LONG_RUN_MIN_HISTORY

COACH_RECENT_WORKOUTS_WINDOW_DAYS = 30
COACH_RECENT_WORKOUTS_MAX_COUNT = 30


class CoachRecentWorkout(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    date: str
    type: str
    name: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    avg_pace_min_km: Optional[float] = None
    avg_speed_kmh: Optional[float] = None
    avg_heart_rate: Optional[float] = None
    max_heart_rate: Optional[float] = None
    elevation_gain_m: Optional[float] = None


class CoachRecentWorkoutsCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    window_days: int
    start_date_inclusive: str
    end_date_inclusive: str
    available_count: int
    included_count: int
    max_count: int
    truncated: bool
    # Sessions proven earlier than the analysed one by the same rule as the Coach history
    # selection (strict, de-duplicated); None when there is no analysed session.
    strictly_prior_available_count: Optional[int] = None


class CoachWorkoutDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: Optional[str] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    type: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_heart_rate: Optional[float] = None
    max_heart_rate: Optional[float] = None
    avg_pace_min_km: Optional[float] = None
    avg_pace_display: Optional[str] = None
    avg_speed_kmh: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    zones: Optional[dict[str, Any]] = None
    km_splits: list[Any] = Field(default_factory=list)
    analysis: Optional[WorkoutAnalysisV2Response] = None


class CoachActivityStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    km: float
    sessions: int


class CoachGoalContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    objective: str
    goal_type: str
    race_date: Optional[str] = None
    target_time_seconds: Optional[int] = None
    target_distance_km: Optional[float] = None


class CoachTrainingStateContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    phase: Optional[str] = None
    current_week: Optional[int] = None
    total_weeks: int
    continuity_state: Optional[str] = None
    allow_intensity: Optional[bool] = None


class CoachWeeklyTargetContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_basis: str
    target_km: Optional[float] = None
    target_duration_minutes: Optional[int] = None
    session_count: int
    confidence: str


class CoachWeeklyReconciliationContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)


class CoachWeekSessionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical: dict[str, Any]
    prescription_source: str


class CoachTodayContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical: dict[str, Any]
    prescription_source: str


class CoachReadinessContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    band: str
    score: Optional[float] = None
    confidence: str
    sufficiency_level: str
    reason_codes: list[str] = Field(default_factory=list)
    data_source: str


class CoachTrainingLoadContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    acute_load_7d: float
    load_28d: float
    chronic_weekly_load: float
    acwr: Optional[float] = None
    status: str
    confidence: str
    is_available: bool
    has_sufficient_history: bool
    load_change_percent: Optional[float] = None


class CoachTrainingPacesContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_available: bool
    confidence: str
    data: dict[str, Any]


class CoachPerformancePredictionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    distance: str
    predicted_time: Optional[str] = None
    predicted_pace: Optional[str] = None
    confidence: str
    extrapolation_ratio: Optional[float] = None
    is_strong_extrapolation: Optional[bool] = None


class CoachPerformanceContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    has_data: bool
    predictions: list[CoachPerformancePredictionContext] = Field(default_factory=list)


class CoachContextV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "coach_context_v2"
    language: str
    reference_date: str
    goal: CoachGoalContext
    training_state: CoachTrainingStateContext
    stats_7d: CoachActivityStats
    stats_30d: CoachActivityStats
    weekly_target: CoachWeeklyTargetContext
    weekly_reconciliation: CoachWeeklyReconciliationContext
    current_week_sessions: list[CoachWeekSessionContext] = Field(default_factory=list)
    recent_workouts: list[CoachRecentWorkout] = Field(default_factory=list)
    recent_workouts_coverage: CoachRecentWorkoutsCoverage
    today: CoachTodayContext
    readiness: CoachReadinessContext
    training_load: CoachTrainingLoadContext
    training_paces: CoachTrainingPacesContext
    performance: CoachPerformanceContext
    workout_detail: Optional[CoachWorkoutDetail] = None


def _parse_iso_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


def _parse_exact_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and ("T" in value or " " in value):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_datetime_with_zone(value: Any) -> tuple[Optional[datetime], bool]:
    """(datetime, has_explicit_zone). Naive values keep their wall-clock time and are NOT labelled UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and ("T" in value or " " in value):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None, False
    else:
        return None, False
    if parsed.tzinfo is None:
        return parsed, False
    return parsed.astimezone(timezone.utc), True


_MIN_UTC_OFFSET = timedelta(hours=-12)
_MAX_UTC_OFFSET = timedelta(hours=14)


def _provable_order(candidate: Any, reference: Any) -> str:
    """"before" | "after" | "unknown": is `candidate` provably earlier than `reference`?

    Aware vs aware compares absolute instants. Naive vs naive compares wall-clock times (both
    come from the same local-time source; no zone is assumed). Naive vs aware only decides when
    the order holds for every real UTC offset (-12h..+14h). A bare date only proves order across
    different calendar days; same-day order is unknown.
    """
    a, a_aware = _parse_datetime_with_zone(candidate)
    b, b_aware = _parse_datetime_with_zone(reference)
    if a is not None and b is not None:
        # Naive values only get a UTC label for the arithmetic below; they are never read as UTC.
        a = a if a_aware else a.replace(tzinfo=timezone.utc)
        b = b if b_aware else b.replace(tzinfo=timezone.utc)
        if a_aware == b_aware:
            return "before" if a < b else "after" if a > b else "unknown"
        if a_aware:  # b is a local wall-clock time of unknown zone: its instant lies in [b-14h, b+12h]
            if a < b - _MAX_UTC_OFFSET:
                return "before"
            return "after" if a > b - _MIN_UTC_OFFSET else "unknown"
        if a - _MIN_UTC_OFFSET < b:  # a naive, b aware: a's instant lies in [a-14h, a+12h]
            return "before"
        return "after" if a - _MAX_UTC_OFFSET > b else "unknown"
    day_a, day_b = _parse_iso_date(candidate), _parse_iso_date(reference)
    if day_a is None or day_b is None or day_a == day_b:
        return "unknown"
    return "before" if day_a < day_b else "after"


def _format_pace_min_km(value: Any) -> Optional[str]:
    try:
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite() or decimal_value < 0:
            return None
        total_seconds = int((decimal_value * 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return None
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}/km"


def _format_pace_delta_min_km(value: Any) -> Optional[str]:
    try:
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite():
            return None
        total_seconds = int((decimal_value * 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return None
    sign = "+" if total_seconds > 0 else "-" if total_seconds < 0 else ""
    minutes, seconds = divmod(abs(total_seconds), 60)
    return f"{sign}{minutes}:{seconds:02d}/km"


def _project_paces_for_llm(value: Any) -> Any:
    if isinstance(value, list):
        return [_project_paces_for_llm(item) for item in value]
    if not isinstance(value, dict):
        return value

    projected = {}
    for key, item in value.items():
        if key == "min_per_km":
            if value.get("pace_str"):
                continue
            display = _format_pace_min_km(item)
            if display is not None:
                projected["pace_display"] = display
            continue
        if key in {
            "avg_pace_min_km",
            "average_pace_min_km",
            "fastest_split_min_km",
            "slowest_split_min_km",
            "pace_min_km",
            "split_pace_min_km",
            "pace_min_per_km",
            "pace_min_per_km_min",
            "pace_min_per_km_max",
            "planned_pace_min_per_km",
            "actual_pace_min_per_km",
        }:
            if isinstance(item, dict):
                continue
            if key == "avg_pace_min_km" and value.get("avg_pace_display"):
                continue
            display = _format_pace_min_km(item)
            if display is not None:
                projected[key.removesuffix("_min_km").replace("_min_per_km", "") + "_display"] = display
            continue
        if key in {"pace_seconds_per_km", "avg_pace_seconds_per_km"}:
            try:
                pace_min_km = Decimal(str(item)) / Decimal("60")
            except (InvalidOperation, TypeError, ValueError):
                continue
            display = _format_pace_min_km(pace_min_km)
            if display is not None:
                projected[key.removesuffix("_seconds_per_km") + "_display"] = display
            continue
        if key in {"pace_difference_min_km", "pace_drop_min_km", "pace_delta_min_per_km"}:
            display = _format_pace_delta_min_km(item)
            if display is not None:
                projected[key.removesuffix("_min_km").removesuffix("_min_per_km") + "_display"] = display
            continue
        projected[key] = _project_paces_for_llm(item)
    return projected


def build_llm_coach_context(
    context: CoachContextV2 | dict[str, Any],
    *,
    workout_analysis_allowed: bool = True,
) -> dict[str, Any]:
    """Build a compact LLM projection with display-ready paces and explicit permissions."""
    canonical = (
        context.model_dump(mode="json")
        if isinstance(context, CoachContextV2)
        else context
    )
    projected = _project_paces_for_llm(canonical)
    projected["coach_workout_analysis_allowed"] = workout_analysis_allowed
    if not workout_analysis_allowed:
        projected.pop("workout_detail", None)
        projected.pop("selected_workout_permissions", None)
        return projected
    workout_detail = canonical.get("workout_detail")
    if workout_detail:
        analysis = workout_detail.get("analysis") or {}
        signals = analysis.get("signals") or {}
        intensity_available = bool((signals.get("intensity") or {}).get("available"))
        similar = ((analysis.get("comparison") or {}).get("similar") or {})
        selected_date = workout_detail.get("date")
        raw_selected_date = (
            (workout_detail.get("start_time"))
            or selected_date
        )
        exact_cutoff, cutoff_has_zone = _parse_datetime_with_zone(raw_selected_date)
        projected["selected_workout_permissions"] = {
            "intensity_interpretation_allowed": intensity_available,
            "raw_hr_is_descriptive_only": True,
            "raw_pace_is_descriptive_only": True,
            "progress_regression_allowed": False,
            "physiological_efficiency_allowed": False,
            "causal_explanation_allowed": False,
            "similar_comparison_available": bool(similar.get("available")),
            "similar_comparable": bool(similar.get("comparable")),
            "similar_differences_descriptive_only": not bool(similar.get("comparable")),
        }
        projected["selected_workout_history_cutoff"] = (
            exact_cutoff.isoformat() if exact_cutoff else selected_date
        )
        projected["selected_workout_history_cutoff_precision"] = (
            "strict_timestamp_exclusive" if exact_cutoff else "date_inclusive"
        )
        if exact_cutoff:
            # A naive Garmin local time is kept as written: it is not an instant in UTC.
            projected["selected_workout_history_cutoff_zone"] = (
                "explicit" if cutoff_has_zone else "unknown_local_time")
        selected_workout_date = _parse_iso_date(raw_selected_date)
        reference_date = canonical.get("reference_date")
        projected["current_training_context"] = {
            "reference_date": reference_date,
            "stats_7d": projected.pop("stats_7d", None),
            "stats_30d": projected.pop("stats_30d", None),
            "temporal_scope": "current_only",
            "may_include_activity_after_selected_workout": bool(
                selected_workout_date
                and _parse_iso_date(reference_date)
                and _parse_iso_date(reference_date) > selected_workout_date
            ),
            "historical_selected_workout_evidence": False,
            "description": (
                "These current aggregates and the Training V2, readiness, load, and performance "
                "context are calculated as of reference_date, not as of the selected workout date. "
                "When reference_date is later, these aggregates may include activity after the selected workout; "
                "never use them as historical evidence about the selected workout."
            ),
        }
    return projected


def _text_items(items: Any, limit: int) -> list[dict[str, Any]]:
    compact = []
    for item in (items or [])[:limit]:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            compact.append({
                "code": item.get("code"),
                "text": item["text"].strip(),
                "source_paths": list(item.get("source_paths") or []),
            })
    return compact


def _compact_v3_assessment(intel: dict[str, Any]) -> dict[str, Any]:
    """Compact copy of the already-computed V3 results; nothing is recalculated here.

    Not transmitted on purpose: performance_trend (a progress question, not an execution
    judgment; progress_regression_allowed stays false) and coach_assessment.advice
    (an engine recommendation, never relayed as a prescription).
    """
    source = "workout_intelligence_v3"
    classification = intel.get("session_classification") or {}
    relative = classification.get("relative_effort") or {}
    intensity = intel.get("intensity_assessment") or {}
    comparison = intel.get("historical_comparison") or {}
    coach = intel.get("coach_assessment") or {}

    relative_effort: dict[str, Any] = {"status": relative.get("status", "not_evaluated")}
    if relative.get("status") == "used":
        relative_effort.update({
            key: relative.get(key) for key in (
                "relative_position", "current_hr_bpm", "reference_count", "hr_q1_bpm",
                "hr_median_bpm", "hr_q3_bpm", "period_start", "period_end",
            )
        })
        relative_effort["meaning"] = "position of average HR among the athlete's own comparable earlier sessions; not a physiological zone"
        relative_effort["provenance"] = _relative_effort_provenance(relative, classification, source)

    compact: dict[str, Any] = {
        "source": source,
        "classification": {
            "source_path": f"{source}.session_classification",
            "probable_type": classification.get("type", "unknown"),
            "decision_tier": classification.get("decision_tier", "insufficient_data"),
            "confidence": classification.get("confidence", "none"),
            "limitations": list(classification.get("limitations") or []),
            "relative_effort": relative_effort,
        },
        "intensity": {
            "source_path": f"{source}.intensity_assessment",
            "position_vs_declared_thresholds": intensity.get("position", "unknown"),
            "thresholds_available": intensity.get("lt1") is not None or intensity.get("lt2") is not None,
            "declared_fcmax_available": intensity.get("fcmax_bpm") is not None,
            "session_max_hr_bpm": intensity.get("session_max_hr_bpm"),
            "session_max_hr_meaning": "maximum observed during this activity; not the athlete's physiological max HR",
            "confidence": intensity.get("confidence", "none"),
            "limitations": list(intensity.get("limitations") or []),
        },
        "historical_comparison": {
            "source_path": f"{source}.historical_comparison",
            "status": comparison.get("status", "insufficient"),
            "comparability": comparison.get("comparability", "insufficient"),
            "reference_count": comparison.get("reference_count", 0),
            "window_days": comparison.get("window_days"),
        },
        "coach_assessment": {
            "source_path": f"{source}.coach_assessment",
            "diagnosis": _text_items([coach.get("diagnosis")], 1),
            "evidence": _text_items(coach.get("evidence"), 3),
            "limitations": _text_items(coach.get("limitations"), 4),
        },
    }
    duration_ratio = _duration_vs_habitual(classification, source)
    if duration_ratio:
        compact["classification"]["duration_vs_habitual"] = duration_ratio
    if comparison.get("status") == "available":
        compact["historical_comparison"]["provenance"] = _comparison_provenance(comparison, source)
    if comparison.get("status") == "available" and comparison.get("comparability") in {"strong", "moderate"}:
        pace = comparison.get("pace_at_comparable_hr") or {}
        hr = comparison.get("hr_at_comparable_pace") or {}
        compact["historical_comparison"]["pace_difference_sec_per_km_at_comparable_hr"] = pace.get(
            "pace_difference_sec_per_km")
        compact["historical_comparison"]["hr_difference_bpm_at_comparable_pace"] = hr.get("hr_difference_bpm")
        compact["historical_comparison"]["difference_units"] = {
            "pace_difference_sec_per_km_at_comparable_hr": "s/km",
            "hr_difference_bpm_at_comparable_pace": "bpm",
        }
    return compact


def _duration_vs_habitual(classification: dict[str, Any], source: str) -> Optional[dict[str, Any]]:
    """Session duration over the athlete's habitual duration, copied from V3's long-run evidence.

    V3 computes it only for a long_run_probable classification: habitual = median duration of the
    athlete's strictly earlier same-sport sessions (V3 history window, no other filter), with at
    least LONG_RUN_MIN_HISTORY of them. Nothing is recomputed; no ratio exists for any other case.
    """
    evidence = classification.get("evidence") or {}
    values = {key: _finite_number(evidence.get(key)) for key in (
        "duration_ratio", "duration_minutes", "habitual_duration_minutes", "history_count")}
    if classification.get("type") != "long_run_probable" or any(v is None or v <= 0 for v in values.values()):
        return None
    if values["history_count"] < LONG_RUN_MIN_HISTORY or values["history_count"] != int(values["history_count"]):
        return None
    return {
        "source_path": f"{source}.session_classification.evidence.duration_ratio",
        "metric": "session_duration_vs_habitual_median_duration",
        "ratio": values["duration_ratio"],
        "session_duration_minutes": values["duration_minutes"],
        "habitual_duration_minutes": values["habitual_duration_minutes"],
        "reference_count": int(values["history_count"]),
        "reference_population": "athlete's strictly earlier sessions of the same sport within the V3 history "
                                f"window ({SIMILAR_HISTORY_WINDOW_DAYS} days), any distance, environment or structure",
        "habitual_definition": "median duration of the reference population",
        "ratio_precision": "rounded to 2 decimals by V3",
        "meaning": "a duration ratio only: not a pace or heart-rate comparison, not a physiological statement",
    }


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _relative_effort_provenance(relative: dict[str, Any], classification: dict[str, Any], source: str) -> dict[str, Any]:
    """Where the relative HR position comes from, copied from the V3 result (nothing recomputed).

    The population is defined by V3's own admissibility rules, which do not include distance:
    it is neither "sessions of the same distance" nor the sessions listed in the history block.
    """
    criteria = relative.get("criteria") or {}
    return {
        "source_path": f"{source}.session_classification.relative_effort",
        "metric_type": "average_hr_relative_position",
        "reference_population": "athlete's own earlier sessions admitted by the V3 relative-effort rules",
        "activity_count": relative.get("reference_count"),
        "period_start": relative.get("period_start"),
        "period_end": relative.get("period_end"),
        "selection_criteria": {
            "same_athlete_same_sport_same_environment": True,
            "strictly_prior_to_analysed_session": True,
            "window_days": criteria.get("window_days"),
            "excludes": ["competitions", "interval_or_structured_sessions", "missing_or_aberrant_hr_or_pace"],
            "duration_ratio_to_analysed_session": [criteria.get("duration_ratio_min"), criteria.get("duration_ratio_max")],
            "distance_is_a_selection_criterion": False,
            "is_the_history_block_listing": False,
        },
        "observed_value": {"avg_hr_bpm": relative.get("current_hr_bpm")},
        "reference_value": {
            "hr_q1_bpm": relative.get("hr_q1_bpm"),
            "hr_median_bpm": relative.get("hr_median_bpm"),
            "hr_q3_bpm": relative.get("hr_q3_bpm"),
        },
        "comparison_method": "position of the session average HR against the quartiles of the reference sessions' average HR",
        "confidence": classification.get("confidence", "none"),
        "known_limits": list(relative.get("limitations") or []),
    }


def _comparison_provenance(comparison: dict[str, Any], source: str) -> dict[str, Any]:
    pace = comparison.get("pace_at_comparable_hr") or {}
    hr = comparison.get("hr_at_comparable_pace") or {}
    return {
        "source_path": f"{source}.historical_comparison",
        "metric_type": "pace_at_comparable_hr / hr_at_comparable_pace",
        "reference_population": "earlier sessions admitted by the V3 comparison rules (comparable duration, environment, structure)",
        "activity_count": comparison.get("reference_count"),
        "period_start": comparison.get("period_start"),
        "period_end": comparison.get("period_end"),
        "sub_populations": {
            "pace_at_comparable_hr": {
                "activity_count": pace.get("reference_count"),
                "hr_tolerance_bpm": pace.get("hr_tolerance_bpm"),
            },
            "hr_at_comparable_pace": {
                "activity_count": hr.get("reference_count"),
                "pace_tolerance_sec_per_km": hr.get("pace_tolerance_sec_per_km"),
            },
        },
        "selection_criteria": {
            "window_days": comparison.get("window_days"),
            "duration_within_pct_of_analysed_session": DURATION_MATCH_TOLERANCE_PCT,
            "distance_is_a_selection_criterion": False,
            "is_the_history_block_listing": False,
        },
        "comparison_method": "mean pace of earlier sessions at comparable HR; mean HR at comparable pace",
        "confidence": comparison.get("comparability"),
        "known_limits": list(comparison.get("limitations") or []),
    }


def _prescription_timing(served_at: Any, session_start: Any) -> str:
    """Was the recorded prescription stored before the session started?

    Compares the snapshot's first-served instant with the session start; never infers an
    intention. A session start without a zone (Garmin local time) is not assumed to be UTC:
    the order is decided only when it holds for every possible UTC offset, else the timing
    is unknown. A bare session date only proves ordering across different days.
    """
    order = _provable_order(served_at, session_start)
    if _parse_datetime_with_zone(served_at)[0] is None and _parse_iso_date(served_at) is None:
        return "recording_time_unknown"
    return {"before": "recorded_before_session", "after": "recorded_after_session"}.get(
        order, "recording_time_unknown")


_TIMING_RULES = {
    "recorded_before_session": "recorded before the session started: it may be called a prescription "
                               "recorded beforehand; whether the athlete saw or followed it is not known",
    "recorded_after_session": "recorded after the session started: never present it as an intention known "
                              "before the start; at most say a prescription for that day was recorded afterwards",
    "recording_time_unknown": "the recording time is unknown: do not assert it was known before the start",
}


def _recorded_prescription(intel: Optional[dict[str, Any]], session_start: Any = None) -> Any:
    """Historical prescription actually recorded for the session date, else why not."""
    assessment = (intel or {}).get("prescription_assessment") or {}
    if assessment.get("prescription_id"):
        timing = _prescription_timing(assessment.get("served_at"), session_start)
        return {
            "source": "training_prescription_snapshots (workout_intelligence_v3.prescription_assessment)",
            "assessment_status": assessment.get("status"),
            "planned_date": assessment.get("planned_date"),
            "recorded_at": assessment.get("served_at"),
            "recording_timing": timing,
            "recording_timing_rule": _TIMING_RULES[timing],
            "prescribed_workout_type": assessment.get("prescribed_workout_type"),
            "prescribed_intensity_class": assessment.get("prescribed_intensity_class"),
            "prescribed_distance_km": assessment.get("prescribed_distance_km"),
            "prescribed_duration_minutes": assessment.get("prescribed_duration_minutes"),
            "observed_classification": assessment.get("observed_classification"),
            "reasons": list(assessment.get("reasons") or []),
            "status_meaning": (
                "no conformity verdict can be given (not a deviation); the recorded prescription "
                "remains a historical fact" if assessment.get("status") == "indeterminate"
                else "engine verdict on observed type versus the recorded prescription"
            ),
        }
    status = assessment.get("status")
    reasons = set(assessment.get("reasons") or [])
    if status == "unavailable":
        return "none_recorded_for_session_date"
    if "ambiguous_session_prescription_association" in reasons:
        return "ambiguous_do_not_assert"
    if status == "indeterminate":
        return "unknown_session_date_cannot_look_up"
    return "not_available_in_this_context"


def _effort_list(intel: Optional[dict[str, Any]], key: str, field: str, formatter) -> list[dict[str, Any]]:
    block = (intel or {}).get(key) or {}
    out = []
    for effort in block.get("efforts") or []:
        if isinstance(effort, dict) and effort.get("available") and effort.get(field) is not None:
            shown = formatter(effort[field])
            if shown is not None:
                out.append({"effort_number": effort.get("effort_number"), "value": shown})
    return out


def _effort_structure(intel: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """"N x D" of the recorded efforts, only when every recorded effort has a valid, near-identical duration."""
    block = (intel or {}).get("effort_duration_observations") or {}
    efforts = [e for e in block.get("efforts") or [] if isinstance(e, dict)]
    if len(efforts) < 2:
        return None
    durations = []
    for effort in efforts:
        value = effort.get("duration_s")
        if (not effort.get("available") or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            return None
        durations.append(float(value))
    typical = sorted(durations)[len(durations) // 2]
    if max(durations) - min(durations) > max(5.0, 0.03 * typical):
        return None
    return {"effort_count": len(durations), "effort_duration_s": int(round(typical)),
            "scope": "recorded efforts only; not proof of the whole session structure"}


def build_evidence_contract(
    detail: dict[str, Any],
    analysis: dict[str, Any],
    v3: Optional[dict[str, Any]],
    recorded: Any,
    intelligence: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """C408-C: compact, deterministic split between what is measured, validated, allowed and unproven.

    Built only from the V2/V3 results already present; nothing is recomputed. Interpretations
    are referenced by code and source path (their wording stays in v3_assessment), so the
    contract adds structure, not a second copy of the text.
    """
    pace = detail.get("avg_pace_display") or _format_pace_min_km(detail.get("avg_pace_min_km"))
    measured: dict[str, Any] = {
        key: value for key, value in {
            "distance_km": detail.get("distance_km"),
            "duration_minutes": detail.get("duration_minutes"),
            "avg_hr_bpm": detail.get("avg_hr"),
            "avg_pace": pace,
            "elevation_gain_m": detail.get("elevation_gain_m"),
        }.items() if value is not None
    }
    effort_paces = _effort_list(intelligence, "effort_pace_observations", "pace_sec_per_km",
                                lambda v: _format_pace_min_km(Decimal(str(v)) / 60))
    effort_durations = _effort_list(intelligence, "effort_duration_observations", "duration_s",
                                    lambda v: f"{int(round(float(v)))} s")
    if effort_paces:
        measured["recorded_effort_paces"] = effort_paces
    if effort_durations:
        measured["recorded_effort_durations"] = effort_durations
    structure = _effort_structure(intelligence)
    if structure:
        measured["recorded_effort_structure"] = structure

    comparisons: list[dict[str, Any]] = []
    classification = (v3 or {}).get("classification") or {}
    relative = classification.get("relative_effort") or {}
    if relative.get("status") == "used":
        comparisons.append({
            "metric": "average_hr_relative_position",
            "source_path": "session_coaching_frame.v3_assessment.classification.relative_effort",
            "provenance": "relative_effort.provenance",
        })
    historical = (v3 or {}).get("historical_comparison") or {}
    if historical.get("provenance") and historical.get("comparability") in {"strong", "moderate"}:
        comparisons.append({
            "metric": "pace_and_hr_at_comparable_effort",
            "source_path": "session_coaching_frame.v3_assessment.historical_comparison",
            "provenance": "historical_comparison.provenance",
            "values": {
                name: {"value": historical.get(key), "unit": unit}
                for name, key, unit in (
                    ("pace_difference_at_comparable_hr", "pace_difference_sec_per_km_at_comparable_hr", "s/km"),
                    ("hr_difference_at_comparable_pace", "hr_difference_bpm_at_comparable_pace", "bpm"),
                ) if historical.get(key) is not None
            },
        })
    duration_ratio = classification.get("duration_vs_habitual")
    if isinstance(duration_ratio, dict):
        comparisons.append(dict(duration_ratio))
    similar = ((analysis.get("comparison") or {}).get("similar") or {})
    if similar.get("available") and similar.get("sample_count"):
        comparisons.append({
            "metric": "pace_and_hr_vs_similar_distance_sessions",
            "source_path": "workout_detail.analysis.comparison.similar",
            "reference_population": "most recent earlier sessions of the same sport with a distance within "
                                    f"{similar.get('distance_tolerance_pct')}% of this one",
            "activity_count": similar.get("sample_count"),
            # The pace delta rests on the sessions with a usable pace only; never on activity_count.
            "pace_sample_count": similar.get("pace_sample_count"),
            "pace_difference_display": similar.get("pace_difference_display"),
            "window_days": similar.get("period_days"),
            "limits": list(similar.get("limitations") or []),
        })

    coach = (v3 or {}).get("coach_assessment") or {}
    allowed = [
        {"code": item.get("code"), "source_path": "session_coaching_frame.v3_assessment.coach_assessment"}
        for item in (coach.get("diagnosis") or []) + (coach.get("evidence") or [])
        if isinstance(item, dict) and item.get("code")
    ]

    not_shown = {
        "pace_is_not_performance": "a faster or slower pace does not show a better or worse performance",
        "recovery_not_measured": "recovery state or need is not measured; a long, hard-looking or relatively "
                                 "intense session does not by itself establish that recovery is needed",
        "progress_not_demonstrated": "no progress or regression is established",
        "sensations_unknown": "no feeling, fatigue or perceived effort is recorded",
    }
    if not ((v3 or {}).get("intensity") or {}).get("thresholds_available"):
        not_shown["physiological_intensity_undetermined"] = (
            "no personal LT1/LT2 threshold: the physiological intensity cannot be determined")
    if relative.get("status") == "used":
        not_shown["relative_hr_is_not_easy_effort"] = (
            "a relatively low or high average HR is a position among the athlete's own sessions, "
            "not proof of an easy or hard physiological effort")
    if len(effort_paces) >= 2 or len(effort_durations) >= 2:
        not_shown["hr_rise_is_not_external_intensity"] = (
            "HR rising across repetitions does not show that the external intensity (pace) rose")
    assessment_status = ((intelligence or {}).get("prescription_assessment") or {}).get("status")
    if assessment_status not in {"consistent", "deviation"}:
        not_shown["prescription_compliance_undetermined"] = (
            "compliance with the prescription is not determined: an indeterminate or missing status "
            "never shows that the prescription was not followed")
    return {
        "measured_facts": measured,
        "validated_comparisons": comparisons,
        "allowed_interpretations": allowed,
        "not_demonstrated": not_shown,
        "usage": "Cite measured_facts exactly. Describe a comparison only with its provenance population. "
                 "State a not_demonstrated item as a limit, once, only when it helps the answer.",
    }


def build_observed_lap_pattern_context(intelligence: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """C420: the lap pattern detected by V3 (cached Garmin laps), relayed unchanged for the LLM.

    A detected pattern outranks the global averages as a description of what was done, but it
    stays an inference: never a recorded phase, a prescription or a certain classification.
    Undetected structure is relayed only as a status so the Coach does not invent one.
    """
    pattern = (intelligence or {}).get("observed_lap_pattern")
    if not isinstance(pattern, dict) or pattern.get("schema") != "garmin_lap_pattern_v1":
        return None
    out = copy.deepcopy(pattern)
    if out.get("status") == "pattern_observed":
        out["priority"] = "describes what was done; prefer it over whole-session average pace and HR"
        out["rule"] = (
            "State the alternation as an observation inferred from Garmin laps, with its confidence. "
            "Do not call slow laps programmed recoveries, do not claim a prescribed workout, "
            "and do not add durations, paces or heart rates that are not listed here."
        )
    else:
        out["rule"] = "No alternation was established from the laps; the structure is unknown, do not invent one."
    return out


def build_session_coaching_frame(
    llm_context: dict[str, Any],
    *,
    goal_declared: bool = True,
    intelligence: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """C408: compact, traceable frame for judging the selected workout.

    Derived only from fields already present in the LLM context and from the already-computed
    Workout Intelligence V3 result (no new calculation, no I/O). It keeps four things apart:
    a recorded historical prescription, the observed classification (a hypothesis about the
    intent), what is current context and what is unknown.
    """
    detail = llm_context.get("workout_detail")
    if not isinstance(detail, dict) or not detail.get("id"):
        return None
    analysis = detail.get("analysis") if isinstance(detail.get("analysis"), dict) else {}
    phase_analysis = analysis.get("phase_analysis") if isinstance(analysis.get("phase_analysis"), dict) else {}
    available = {
        "pace": detail.get("avg_pace_min_km") is not None or bool(detail.get("avg_pace_display")),
        "avg_hr": detail.get("avg_hr") is not None,
        "km_splits": bool(detail.get("km_splits")),
        "structured_phases": bool(phase_analysis.get("efforts") or phase_analysis.get("phases")),
        "elevation": detail.get("elevation_gain_m") is not None,
        "intensity_classification": bool(
            ((analysis.get("signals") or {}).get("intensity") or {}).get("available")
        ),
    }
    v3 = _compact_v3_assessment(intelligence) if isinstance(intelligence, dict) else None
    recorded = _recorded_prescription(intelligence, detail.get("start_time") or detail.get("date"))
    probable_type = ((v3 or {}).get("classification") or {}).get("probable_type", "unknown")
    if isinstance(recorded, dict):
        intent_status = (
            "prescription_recorded_after_session_not_a_known_intent"
            if recorded.get("recording_timing") == "recorded_after_session"
            else "recorded_historical_prescription"
        )
    elif probable_type != "unknown":
        intent_status = "probable_type_from_observed_classification_not_a_prescription"
    else:
        intent_status = "unknown"
    frame: dict[str, Any] = {
        "workout_id": detail["id"],
        "workout_date": detail.get("date"),
        "activity_type": detail.get("type"),
        "data_available": available,
        "missing_data": sorted(key for key, value in available.items() if not value),
        "session_intent": {
            "recorded_historical_prescription": recorded,
            "current_training_v2_evaluation": "current_training_context_only_not_historical",
            "intent_status": intent_status,
            "rule": (
                "State the intended purpose as fact only when recorded_historical_prescription is a "
                "recorded prescription whose recording_timing is recorded_before_session. A probable type from the observed classification is a "
                "hypothesis and must be worded as one; otherwise the intent is unknown."
            ),
        },
        "athlete_goal_declared": bool(goal_declared and llm_context.get("goal")),
    }
    if v3 is not None:
        frame["v3_assessment"] = v3
    else:
        frame["v3_assessment"] = "unavailable"
    frame["evidence_contract"] = build_evidence_contract(detail, analysis, v3, recorded, intelligence)
    return frame


# ------------------------------------------------- C421: conversational projection (chat only)
# Read-only projections of results already computed by V2/V3 for the chat LLM. They never change the
# V2/V3/frame outputs (still used by C400, the guards and the tests); they only choose what the
# conversational context repeats, and merge the same uncertainty expressed by several engines.

_PHYSIOLOGY_LIMITS = {
    "limitations.intensity", "limit.no_thresholds", "limit.average_hr", "limit.relative_not_physiological",
    "personal_thresholds_not_persisted", "average_hr_is_not_time_in_zone", "no_reliable_personal_threshold",
    "missing_threshold_for_this_hr_range", "fcmax_declaration_date_unknown", "hr_above_reference_fcmax",
    "variation_is_not_physiological_proof", "unavailable.intensity", "meaning.intensity_unavailable",
}
# Already carried by scientific_permissions or by the athlete_context prescription status.
_COVERED_ELSEWHERE = _PHYSIOLOGY_LIMITS | {
    "isolated_variation_not_confirmed", "status_sensitive_to_criteria", "limit.isolated",
    "intervals_not_identifiable_without_phases", "structured_phases_without_identifiable_type",
    "intensity_unknown_volume_based_only", "synthesis.hr_observation",
}
_LIMIT_TOPIC_BY_CODE = {
    **{code: "hr_unusable" for code in (
        "limitations.heart_rate", "limit.hr_unusable", "hr_missing", "current_hr_unusable", "unavailable.hr")},
    **{code: "no_splits" for code in (
        "limitations.splits", "no_splits_whole_session_averages_only", "limitations.phase_splits")},
    "no_recorded_session_structure": "structure_unknown",
    **{code: "no_validated_comparison" for code in (
        "limit.no_history", "limitations.no_comparable_reference", "limitations.baseline",
        "limitations.baseline_descriptive", "limitations.comparability", "habitual_duration_unavailable",
        "insufficient_comparability", "no_comparable_reference")},
    **{code: "comparison_small_sample" for code in (
        "limitations.sample_too_small", "limitations.pace_sample_too_small", "limitations.hr_sample_too_small")},
    **{code: "comparison_conditions" for code in (
        "terrain_weather_not_controlled", "limit.structure_unknown", "reference_structure_unknown")},
    "limitations.session_nature_unknown": "session_nature_unknown",
    **{code: "recorded_phases_limited" for code in (
        "limitations.phase_classification", "limitations.phase_classification_partial",
        "limitations.phase_missing", "limitations.phase_quality", "limitations.phase_regularity",
        "limitations.phase_hr")},
}
_LIMIT_TOPIC_TEXT = {
    "hr_unusable": "Heart rate is missing or unusable: no heart-rate reading of this session.",
    "no_splits": "No split data: the pace distribution inside the session is unknown.",
    "structure_unknown": "No recorded or inferred session structure: whole-session figures only; do not infer intervals.",
    "no_validated_comparison": "No validated comparison with earlier sessions: say nothing about how this session "
                               "compares or about progress.",
    "comparison_small_sample": "Small reference sample: present the comparison cautiously.",
    "comparison_conditions": "Terrain, weather and reference structure are not controlled: a gap is not proof of change.",
    "session_nature_unknown": "Training-versus-race nature is not recorded.",
    "session_type_unknown": "The session type cannot be determined reliably: do not name one as fact.",
    "recorded_phases_limited": "Recorded phases are partly unclassified or incomplete: describe only what is listed.",
}
_COMPARISON_ONLY_TOPICS = {"comparison_small_sample", "comparison_conditions", "session_nature_unknown"}


def _display_pace_sec(value: Any) -> Optional[str]:
    number = _finite_number(value)
    return _format_pace_min_km(Decimal(str(number)) / 60) if number is not None and number >= 0 else None


def _usable_hr(value: Any) -> Optional[Any]:
    """A heart-rate reading only when it is a finite positive number (0 or garbage is not a measurement)."""
    number = _finite_number(value)
    return value if number is not None and number > 0 else None


def _present(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if value is not None and value != [] and value != {}}


def compact_recorded_structure(phase_analysis: Any) -> dict[str, Any]:
    """Garmin-recorded phases (V2 phase_analysis) as a compact block; ``status`` says what exists.

    ``recorded_by_garmin`` requires at least one classified phase (effort, recovery, warmup, cooldown).
    Phases that are all ``unknown`` are kept as ``recorded_unclassified``: their figures are information,
    but they are not a classified structure and never outrank a lap pattern.
    """
    if not isinstance(phase_analysis, dict) or not phase_analysis.get("available") or not phase_analysis.get("phases"):
        return {"status": "none_recorded"}
    phases = []
    for phase in phase_analysis.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        phases.append(_present({
            "type": phase.get("phase_type"),
            "n": phase.get("effort_number") or phase.get("recovery_number"),
            "duration_s": phase.get("duration_s"),
            "distance_m": phase.get("distance_m"),
            "pace": _display_pace_sec(phase.get("pace_sec_per_km")),
            "avg_hr_bpm": _usable_hr(phase.get("average_hr")),
            "max_hr_bpm": _usable_hr(phase.get("max_hr")),
        }))
    classified = any(p.get("type") not in (None, "unknown") for p in phases)
    if not classified:
        return {"status": "recorded_unclassified", "phases": phases,
                "rule": "Garmin recorded these phases without classifying them: no effort/recovery structure."}
    regularity = phase_analysis.get("effort_regularity") or {}
    out: dict[str, Any] = {"status": "recorded_by_garmin", "phases": phases}
    if regularity.get("available"):
        out["effort_regularity"] = _present({
            "effort_count": regularity.get("effort_count"),
            "comparable_effort_count": regularity.get("comparable_effort_count"),
            "average_pace": _display_pace_sec(regularity.get("average_pace_sec_per_km")),
            "first_to_last_pace_change_sec_per_km": regularity.get("first_to_last_pace_change_sec_per_km"),
        })
    return out


def _compact_segments(block: Any) -> Optional[dict[str, Any]]:
    if not isinstance(block, dict):
        return None
    repetitions = [
        _present({"n": index, "duration_s": seg.get("duration_s"),
                  "pace": _display_pace_sec(seg.get("pace_sec_per_km")), "avg_hr_bpm": _usable_hr(seg.get("avg_hr_bpm"))})
        for index, seg in enumerate((s for s in block.get("segments") or [] if isinstance(s, dict)), start=1)
    ]
    return _present({
        "typical_duration_s": block.get("typical_duration_s"),
        "typical_pace": _display_pace_sec(block.get("typical_pace_sec_per_km")),
        "repetitions": repetitions,
        "avg_hr_first_bpm": _usable_hr(block.get("avg_hr_first_bpm")) if block.get("hr_evolution_available") else None,
        "avg_hr_last_bpm": _usable_hr(block.get("avg_hr_last_bpm")) if block.get("hr_evolution_available") else None,
        "avg_hr_change_first_to_last_bpm":
            block.get("avg_hr_change_first_to_last_bpm")
            if block.get("hr_evolution_available") and _usable_hr(block.get("avg_hr_first_bpm"))
            and _usable_hr(block.get("avg_hr_last_bpm")) else None,
    })


def _compact_edge(block: Any) -> Optional[dict[str, Any]]:
    if not isinstance(block, dict):
        return None
    return _present({"lap_count": block.get("lap_count"), "duration_s": block.get("duration_s"),
                     "distance_m": block.get("length_m"), "pace": _display_pace_sec(block.get("pace_sec_per_km"))})


def compact_inferred_structure(pattern: Any) -> dict[str, Any]:
    """The C420/C420B lap pattern without its repeated rules and lap bookkeeping.

    Figures are copied from the detector, never recomputed: only the detected repetitions are listed.
    """
    if not isinstance(pattern, dict) or pattern.get("schema") != "garmin_lap_pattern_v1":
        return {"status": "not_available"}
    if pattern.get("status") != "pattern_observed" or not isinstance(pattern.get("pattern"), dict):
        return {"status": "no_pattern_established", "rule": "Structure unknown: do not invent one."}
    detail = pattern["pattern"]
    return _present({
        "status": "pattern_observed",
        "source": "inferred_from_garmin_laps",
        "confidence": pattern.get("confidence"),
        "type": detail.get("type"),
        "repetition_count": detail.get("repetition_count"),
        "fast": _compact_segments(detail.get("fast_segments")),
        "slow": _compact_segments(detail.get("slow_segments")),
        "warmup_probable": _compact_edge(pattern.get("probable_warmup")),
        "cooldown_probable": _compact_edge(pattern.get("probable_cooldown")),
        "anomalies": [a.get("code") for a in pattern.get("anomalies") or [] if isinstance(a, dict) and a.get("code")],
        "rule": "Inferred from laps: never a recorded phase or a prescription; slow laps are not proven programmed "
                "recoveries; it describes what was done better than whole-session averages; add no figure absent here.",
    })


def _compact_provenance(provenance: Any) -> dict[str, Any]:
    if not isinstance(provenance, dict):
        return {}
    criteria = provenance.get("selection_criteria") or {}
    return _present({
        "reference_population": provenance.get("reference_population"),
        "activity_count": provenance.get("activity_count"),
        "sub_populations": provenance.get("sub_populations"),
        "period_start": provenance.get("period_start"),
        "period_end": provenance.get("period_end"),
        "window_days": criteria.get("window_days"),
        "excludes": criteria.get("excludes"),
        "known_limits": provenance.get("known_limits"),
        "distance_is_a_selection_criterion": criteria.get("distance_is_a_selection_criterion"),
        "confidence": provenance.get("confidence"),
    })


def compact_validated_comparisons(frame: Any, analysis: Any = None) -> list[dict[str, Any]]:
    """Comparisons the V2/V3 engines validated, each with its provenance, reference population,
    comparability status and the limits that qualify it (``analysis`` is the V2 workout analysis)."""
    similar = ((analysis or {}).get("comparison") or {}).get("similar") if isinstance(analysis, dict) else None
    similar = similar if isinstance(similar, dict) else {}
    if not isinstance(frame, dict) or not isinstance(frame.get("v3_assessment"), dict):
        v3, contract = {}, ((frame or {}).get("evidence_contract") or {}) if isinstance(frame, dict) else {}
    else:
        v3, contract = frame["v3_assessment"], frame.get("evidence_contract") or {}
    relative = (v3.get("classification") or {}).get("relative_effort") or {}
    historical = v3.get("historical_comparison") or {}
    out: list[dict[str, Any]] = []
    for item in contract.get("validated_comparisons") or []:
        if not isinstance(item, dict):
            continue
        metric = item.get("metric")
        if metric == "average_hr_relative_position":
            out.append(_present({
                "metric": metric,
                "relative_position": relative.get("relative_position"),
                "session_avg_hr_bpm": relative.get("current_hr_bpm"),
                "reference_hr_q1_bpm": relative.get("hr_q1_bpm"),
                "reference_hr_median_bpm": relative.get("hr_median_bpm"),
                "reference_hr_q3_bpm": relative.get("hr_q3_bpm"),
                "reference_status": relative.get("status"),
                "provenance": _compact_provenance(relative.get("provenance")),
                "meaning": "a position among the athlete's own comparable sessions, not an effort zone",
            }))
        elif metric == "pace_and_hr_at_comparable_effort":
            out.append(_present({
                "metric": metric, "values": item.get("values"),
                "comparability": historical.get("comparability"),
                "provenance": _compact_provenance(historical.get("provenance")),
            }))
        elif metric == "pace_and_hr_vs_similar_distance_sessions":
            entry = {k: v for k, v in item.items() if k != "source_path"}
            entry.update(_present({
                "comparable": similar.get("comparable"),
                "pace_comparability": similar.get("pace_comparability"),
                "hr_comparability": similar.get("hr_comparability"),
                "pace_structure_status": similar.get("pace_structure_status"),
                "hr_structure_status": similar.get("hr_structure_status"),
                "pace_nature_status": similar.get("pace_nature_status"),
                "hr_nature_status": similar.get("hr_nature_status"),
                "heart_rate_difference_bpm": similar.get("heart_rate_difference_bpm"),
                "hr_sample_count": similar.get("hr_sample_count"),
            }))
            out.append(entry)
        else:
            out.append({k: v for k, v in item.items() if k not in {"source_path", "meaning", "ratio_precision"}})
    return out


def compact_recorded_prescription(frame: Any) -> dict[str, Any]:
    """The historical prescription, only when recorded before the session started."""
    intent = (frame or {}).get("session_intent") if isinstance(frame, dict) else None
    recorded = (intent or {}).get("recorded_historical_prescription")
    if not isinstance(recorded, dict):
        return {"status": "none_usable", "reason": recorded or "not_available"}
    if recorded.get("recording_timing") != "recorded_before_session":
        return {"status": "none_usable", "reason": recorded.get("recording_timing"),
                "rule": "A prescription recorded after the start, or at an unknown time, is not a known intent."}
    return _present({
        "status": "recorded_before_session",
        "planned_date": recorded.get("planned_date"),
        "recorded_at": recorded.get("recorded_at"),
        "prescribed_workout_type": recorded.get("prescribed_workout_type"),
        "prescribed_intensity_class": recorded.get("prescribed_intensity_class"),
        "prescribed_distance_km": recorded.get("prescribed_distance_km"),
        "prescribed_duration_minutes": recorded.get("prescribed_duration_minutes"),
        "conformity": recorded.get("assessment_status"),
        "observed_classification": recorded.get("observed_classification"),
        "rule": "Historical record; whether the athlete saw or followed it is unknown. An indeterminate conformity "
                "is not a deviation.",
    })


def compact_allowed_conclusions(frame: Any, *, prescription_usable: bool = False) -> list[dict[str, Any]]:
    """V3 conclusions the Coach may relay (diagnosis/evidence items and a hypothesised type).

    A prescription-derived conclusion (``evidence.prescription``, ``prescription.*``) is relayed only when
    the prescription was recorded before the session (``prescription_usable``), like recorded_prescription.
    """
    v3 = (frame or {}).get("v3_assessment") if isinstance(frame, dict) else None
    if not isinstance(v3, dict):
        return []
    out: list[dict[str, Any]] = []
    classification = v3.get("classification") or {}
    if classification.get("probable_type") not in (None, "unknown"):
        out.append({
            "code": "session_type_hypothesis", "value": classification.get("probable_type"),
            "confidence": classification.get("confidence"),
            "status": "hypothesis from observed data, not a prescription",
        })
    coach = v3.get("coach_assessment") or {}
    for item in (coach.get("diagnosis") or []) + (coach.get("evidence") or []):
        if isinstance(item, dict) and item.get("code") and item.get("code") != "diagnosis.unknown":
            if not prescription_usable and "prescription" in str(item["code"]):
                continue
            out.append({"code": item["code"], "text": item.get("text")})
    return out


def comparison_limit_topics(comparisons: Any) -> set[str]:
    """Limit topics already attached to a validated comparison (its own ``limits``/``known_limits``)."""
    topics: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"limits", "known_limits"} and isinstance(item, list):
                    for code in item:
                        topic = _LIMIT_TOPIC_BY_CODE.get(str(code)) or _LIMIT_TOPIC_BY_CODE.get(f"limitations.{code}")
                        if topic:
                            topics.add(topic)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(comparisons)
    return topics


def consolidate_limitations(
    items: list[Any], *, structure_present: bool, comparisons_present: bool, session_type_unknown: bool,
    structure_has_hr: bool = False, attached_topics: Optional[set[str]] = None,
) -> list[dict[str, str]]:
    """One entry per material uncertainty, whichever engine expressed it and however it was worded.

    Items are (code or None, text). Limits already carried by scientific_permissions are dropped; limits
    that cannot change a conclusion given the available structure/comparisons are dropped; the rest is
    merged into a single compact wording per topic. Unknown codes are kept once with their own text.
    """
    topics: dict[str, str] = {}
    for code, text in items:
        code = str(code) if code else None
        if code in _COVERED_ELSEWHERE:
            continue
        topic = _LIMIT_TOPIC_BY_CODE.get(code)
        if topic is None:
            if not text:
                continue
            topic = code or " ".join(str(text).lower().split())
            topics.setdefault(topic, str(text))
        else:
            topics.setdefault(topic, _LIMIT_TOPIC_TEXT[topic])
    if session_type_unknown and not structure_present:
        topics.setdefault("session_type_unknown", _LIMIT_TOPIC_TEXT["session_type_unknown"])
    if structure_has_hr:  # heart rates are listed per phase/repetition: the whole-session gap no longer matters
        topics.pop("hr_unusable", None)
    if structure_present:
        topics.pop("structure_unknown", None)
        topics.pop("no_splits", None)
    elif "no_splits" in topics and "structure_unknown" in topics:
        topics.pop("no_splits")  # whole-session figures only already says it
    if comparisons_present:
        topics.pop("no_validated_comparison", None)
    else:
        for topic in _COMPARISON_ONLY_TOPICS:
            topics.pop(topic, None)
    for topic in attached_topics or ():  # carried by the comparison itself: stated once
        if topic in _COMPARISON_ONLY_TOPICS:
            topics.pop(topic, None)
    return [{"code": topic, "text": text} for topic, text in topics.items()]


def _build_plan_goal(resolved_goal: Any) -> PlanGoal:
    return build_plan_goal(
        goal_type=resolved_goal.mapped_goal,
        race_date=resolved_goal.race_date,
        target_distance_km=resolved_goal.target_distance_km,
        target_time_seconds=resolved_goal.target_time_sec,
        created_from="user",
    )


def _build_cycle_response(*, resolved_goal: Any, reference_date: date):
    plan_goal = _build_plan_goal(resolved_goal)
    if plan_goal.race_date is not None:
        return build_cycle_calendar_response(
            plan_goal=plan_goal,
            reference_date=reference_date,
            race_plan_start_date=resolved_goal.cycle_start,
            target_time_seconds=resolved_goal.target_time_sec,
        )
    return build_cycle_calendar_response(
        plan_goal=plan_goal,
        reference_date=reference_date,
        cycle_anchor_date=resolved_goal.cycle_start,
        target_time_seconds=resolved_goal.target_time_sec,
    )


def _build_phase_value(*, resolved_goal: Any, reference_date: date) -> str:
    plan_goal = _build_plan_goal(resolved_goal)
    if plan_goal.race_date is not None:
        return build_periodization(
            plan_goal=plan_goal,
            reference_date=reference_date,
            race_plan_start_date=resolved_goal.cycle_start,
        ).phase.value
    return build_periodization(
        plan_goal=plan_goal,
        reference_date=reference_date,
        cycle_anchor_date=resolved_goal.cycle_start,
    ).phase.value


async def _week_prescription_authorities(
    *,
    db: Any,
    user_id: str,
    week_sessions: list[dict[str, Any]],
    reference_date: date,
) -> dict[str, str]:
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)

    snapshot_docs = await db.training_prescription_snapshots.find(
        {
            "user_id": user_id,
            "planned_date": {"$gte": week_start.isoformat(), "$lte": week_end.isoformat()},
        },
        {"_id": 0},
    ).to_list(1000)
    memory_docs = await db.training_planned_prescription_memory.find(
        {
            "user_id": user_id,
            "planned_date": {"$gte": week_start.isoformat(), "$lte": week_end.isoformat()},
        },
        {"_id": 0},
    ).to_list(1000)

    snapshot_ids: set[str] = set()
    for doc in snapshot_docs:
        if not isinstance(doc.get("prescription_id"), str):
            continue
        try:
            snapshot = PrescriptionSnapshot(**doc)
        except (TypeError, ValueError):
            continue
        if is_snapshot_authoritative(
            snapshot=snapshot, reference_date=reference_date
        ):
            snapshot_ids.add(snapshot.prescription_id)
    memory_ids = {
        doc.get("prescription_id")
        for doc in memory_docs
        if isinstance(doc.get("prescription_id"), str)
    }

    sources: dict[str, str] = {}
    for session in week_sessions:
        prescription_id = session.get("prescription_id")
        if not isinstance(prescription_id, str):
            continue
        planned_date = _parse_iso_date(session.get("planned_date"))
        if prescription_id in snapshot_ids:
            sources[prescription_id] = "served_snapshot"
        elif (
            prescription_id in memory_ids
            and planned_date is not None
            and planned_date < reference_date
        ):
            sources[prescription_id] = "planned_memory"
        elif session.get("execution_status") == "prescription_unavailable":
            sources[prescription_id] = "unavailable"
        elif planned_date is not None and planned_date >= reference_date:
            sources[prescription_id] = "live_planned"
        else:
            sources[prescription_id] = "unavailable"
    return sources


async def _today_snapshot_doc(
    *,
    db: Any,
    user_id: str,
    today_payload: dict[str, Any],
    reference_date: date,
) -> Optional[dict[str, Any]]:
    prescription_id = today_payload.get("prescription_id")
    if not isinstance(prescription_id, str):
        return None
    doc = await db.training_prescription_snapshots.find_one(
        {"user_id": user_id, "prescription_id": prescription_id},
        {"_id": 0},
    )
    if doc is None:
        return None
    try:
        snapshot = PrescriptionSnapshot(**doc)
    except (TypeError, ValueError):
        return None
    if not is_snapshot_authoritative(
        snapshot=snapshot, reference_date=reference_date
    ):
        return None
    return doc


def _safe_distance_km(workout: dict[str, Any]) -> Optional[float]:
    raw_km = workout.get("distance_km")
    if raw_km is not None and not isinstance(raw_km, bool):
        try:
            val = float(raw_km)
            if math.isfinite(val) and val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass
    raw_m = workout.get("distance")
    if raw_m is not None and not isinstance(raw_m, bool):
        try:
            val = float(raw_m)
            if math.isfinite(val) and val > 0:
                return round(val / 1000.0 if val >= 1000 else val, 2)
        except (ValueError, TypeError):
            pass
    return None


def _safe_duration_minutes(workout: dict[str, Any]) -> Optional[float]:
    moving_time = workout.get("moving_time")
    if moving_time is not None and not isinstance(moving_time, bool):
        try:
            val = float(moving_time)
            if math.isfinite(val) and val > 0:
                return round(val / 60.0, 1)
        except (ValueError, TypeError):
            pass
    raw_dur = workout.get("duration_minutes")
    if raw_dur is not None and not isinstance(raw_dur, bool):
        try:
            val = float(raw_dur)
            if math.isfinite(val) and val > 0:
                return round(val, 1)
        except (ValueError, TypeError):
            pass
    return None


def _safe_hr(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        return round(f, 1) if math.isfinite(f) and f > 0 else None
    except (ValueError, TypeError):
        return None


def _safe_pace_min_km(workout: dict[str, Any]) -> Optional[float]:
    raw_pace = workout.get("avg_pace_min_km")
    if raw_pace is not None and not isinstance(raw_pace, bool):
        try:
            val = float(raw_pace)
            if math.isfinite(val) and val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass
    return None


def _pace_display_from_raw(workout: dict[str, Any]) -> Optional[str]:
    """Display only: nearest second from the unrounded source (the 2-decimal context value is never re-used)."""
    seconds = workout.get("pace_seconds_per_km")
    if seconds is not None and not isinstance(seconds, bool):
        return _format_pace_min_km(Decimal(str(seconds)) / Decimal("60")) if _is_positive(seconds) else None
    raw = workout.get("avg_pace_min_km")
    return _format_pace_min_km(raw) if _is_positive(raw) else None


def _is_positive(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _safe_speed_kmh(workout: dict[str, Any]) -> Optional[float]:
    raw_speed = workout.get("avg_speed_kmh")
    if raw_speed is not None and not isinstance(raw_speed, bool):
        try:
            val = float(raw_speed)
            if math.isfinite(val) and val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass
    return None


def _safe_elevation(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        return round(f, 1) if math.isfinite(f) and f >= 0 else None
    except (ValueError, TypeError):
        return None


def _safe_scaled_positive(value: Any, scale: float, digits: int) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        scaled = float(value) * scale
        return round(scaled, digits) if math.isfinite(scaled) and scaled > 0 else None
    except (ValueError, TypeError):
        return None


def _is_valid_recent_workout(
    workout: dict[str, Any],
    reference_date: date,
    window_days: int = COACH_RECENT_WORKOUTS_WINDOW_DAYS,
) -> bool:
    raw_date = workout.get("start_time") or workout.get("date")
    if not raw_date:
        return False
    workout_date = _parse_iso_date(raw_date)
    if workout_date is None:
        return False
    if workout_date >= reference_date + timedelta(days=1):
        return False
    cutoff = reference_date - timedelta(days=window_days - 1)
    if workout_date < cutoff:
        return False
    return True


def _is_before_selected_workout(
    recent_workout: dict[str, Any] | CoachRecentWorkout,
    *,
    selected_workout_id: str,
    selected_date: date,
    selected_datetime: Optional[datetime],
    selected_raw: Any = None,
) -> bool:
    workout_id = recent_workout.id if isinstance(recent_workout, CoachRecentWorkout) else recent_workout.get("id")
    if str(workout_id or "") == selected_workout_id:
        return False
    raw_date = (
        recent_workout.date
        if isinstance(recent_workout, CoachRecentWorkout)
        else recent_workout.get("start_time") or recent_workout.get("date")
    )
    workout_date = _parse_iso_date(raw_date)
    if workout_date is None:
        return False
    if selected_datetime is not None:
        selected_raw = selected_raw if selected_raw is not None else selected_datetime
        if _parse_datetime_with_zone(raw_date)[0] is not None:
            return _provable_order(raw_date, selected_raw) == "before"
        return workout_date < selected_date
    return workout_date <= selected_date


def _strictly_prior_count(items: Any, selected_raw: Any, selected_workout_id: str) -> Optional[int]:
    """Count distinct earlier sessions with the same strict rule as `coach_session_comment`."""
    if selected_raw is None:
        return None
    seen: set = set()
    for item in items:
        if isinstance(item, CoachRecentWorkout):
            raw, wid = item.date, item.id
        else:
            raw, wid = item.get("start_time") or item.get("date"), item.get("id")
        if str(wid or "") == selected_workout_id or _provable_order(raw, selected_raw) != "before":
            continue
        seen.add(str(wid) if wid else str(raw))
    return len(seen)


def _normalize_recent_workout(workout: dict[str, Any]) -> CoachRecentWorkout:
    garmin_activity = workout.get("garmin_activity")
    raw_values = {**(garmin_activity if isinstance(garmin_activity, dict) else {}), **workout}
    raw_avg_hr = raw_values.get("avg_heart_rate")
    if raw_avg_hr is None:
        raw_avg_hr = raw_values.get("average_hr")
    if raw_avg_hr is None:
        raw_avg_hr = raw_values.get("average_heartrate")
    if raw_avg_hr is None:
        raw_avg_hr = raw_values.get("avg_hr")
    avg_hr = _safe_hr(raw_avg_hr)

    raw_max_hr = raw_values.get("max_heart_rate")
    if raw_max_hr is None:
        raw_max_hr = raw_values.get("max_heartrate")
    if raw_max_hr is None:
        raw_max_hr = raw_values.get("max_hr")
    max_hr = _safe_hr(raw_max_hr)

    raw_elevation = raw_values.get("elevation_gain_m")
    if raw_elevation is None:
        raw_elevation = raw_values.get("elevation_gain")

    distance_m = raw_values.get("distance_m")
    if distance_m is None:
        distance_m = raw_values.get("distance")
    duration_seconds = raw_values.get("duration_s")
    if duration_seconds is None:
        duration_seconds = raw_values.get("duration")
    raw_pace = raw_values.get("pace_seconds_per_km")
    raw_speed = raw_values.get("average_speed_mps")
    workout_id = raw_values.get("id")
    if workout_id is None and raw_values.get("external_id") is not None:
        workout_id = f"garmin-{raw_values['external_id']}"
    if workout_id is None:
        workout_id = raw_values.get("activity_id", "")
    workout_date = raw_values.get("start_time") or raw_values.get("date") or ""
    distance_km = _safe_scaled_positive(distance_m, 0.001, 2)
    duration_minutes = _safe_scaled_positive(duration_seconds, 1 / 60, 1)
    avg_pace_min_km = _safe_scaled_positive(raw_pace, 1 / 60, 2)
    avg_speed_kmh = _safe_scaled_positive(raw_speed, 3.6, 2)
    if distance_km is None:
        distance_km = _safe_distance_km(raw_values)
    if duration_minutes is None:
        duration_minutes = _safe_duration_minutes(raw_values)
    if avg_pace_min_km is None:
        avg_pace_min_km = _safe_pace_min_km(raw_values)
    if avg_speed_kmh is None:
        avg_speed_kmh = _safe_speed_kmh(raw_values)

    return CoachRecentWorkout(
        id=str(workout_id),
        date=str(workout_date),
        type=str(raw_values.get("type") or raw_values.get("activity_type") or "workout"),
        name=raw_values.get("name") if raw_values.get("name") is not None else None,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        avg_pace_min_km=avg_pace_min_km,
        avg_speed_kmh=avg_speed_kmh,
        avg_heart_rate=avg_hr,
        max_heart_rate=max_hr,
        elevation_gain_m=_safe_elevation(raw_elevation),
    )


def _normalize_workout_detail(
    workout: Optional[dict[str, Any]],
    analysis: Optional[WorkoutAnalysisV2Response] = None,
) -> Optional[CoachWorkoutDetail]:
    if not workout:
        return None

    garmin_activity = workout.get("garmin_activity")
    raw_values = {**(garmin_activity if isinstance(garmin_activity, dict) else {}), **workout}

    duration_minutes = _safe_duration_minutes(raw_values)
    distance_km = _safe_distance_km(raw_values)
    raw_avg_hr = raw_values.get("avg_heart_rate")
    if raw_avg_hr is None:
        raw_avg_hr = raw_values.get("average_heartrate")
    if raw_avg_hr is None:
        raw_avg_hr = raw_values.get("average_hr")
    if raw_avg_hr is None:
        raw_avg_hr = raw_values.get("avg_hr")
    avg_hr = _safe_hr(raw_avg_hr)

    raw_max_hr = raw_values.get("max_heart_rate")
    if raw_max_hr is None:
        raw_max_hr = raw_values.get("max_heartrate")
    if raw_max_hr is None:
        raw_max_hr = raw_values.get("max_hr")
    max_hr = _safe_hr(raw_max_hr)

    avg_pace = _safe_pace_min_km(raw_values)
    avg_speed = _safe_speed_kmh(raw_values)
    raw_elevation = raw_values.get("elevation_gain_m")
    if raw_elevation is None:
        raw_elevation = raw_values.get("elevation_gain")
    if raw_elevation is None:
        raw_elevation = raw_values.get("total_elevation_gain_m")
    elevation = _safe_elevation(raw_elevation)

    return CoachWorkoutDetail(
        id=str(workout.get("id")),
        name=workout.get("name"),
        date=str(workout.get("date")) if workout.get("date") is not None else None,
        start_time=str(raw_values.get("start_time")) if raw_values.get("start_time") is not None else None,
        type=str(workout.get("type")) if workout.get("type") is not None else None,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        avg_hr=float(avg_hr) if avg_hr is not None else None,
        max_hr=float(max_hr) if max_hr is not None else None,
        avg_heart_rate=avg_hr,
        max_heart_rate=max_hr,
        avg_pace_min_km=avg_pace,
        avg_pace_display=_pace_display_from_raw(raw_values),
        avg_speed_kmh=avg_speed,
        elevation_gain_m=elevation,
        zones=raw_values.get("effort_zone_distribution"),
        km_splits=list(raw_values.get("km_splits") or [])[:5],
        analysis=analysis,
    )


async def build_coach_context_v2(
    *,
    db: Any,
    user_id: str,
    language: str,
    reference_date: date,
    resolved_goal: Any,
    domain_activities_90: list[Any],
    week_payload: dict[str, Any],
    today_payload: dict[str, Any],
    training_load: TrainingLoadSnapshot,
    readiness_decision: ReadinessDecision,
    readiness_data_source: str,
    training_paces: TrainingPaces,
    performance: PerformanceEstimate,
    workout: Optional[dict[str, Any]] = None,
    workout_analysis: Optional[WorkoutAnalysisV2Response] = None,
    recent_workouts: Optional[list[CoachRecentWorkout]] = None,
) -> CoachContextV2:
    cycle_response = _build_cycle_response(
        resolved_goal=resolved_goal,
        reference_date=reference_date,
    )
    training_history = build_training_history(domain_activities_90, reference_date)
    week_sessions = list(((week_payload.get("week") or {}).get("sessions") or []))
    sources_by_id = await _week_prescription_authorities(
        db=db,
        user_id=user_id,
        week_sessions=week_sessions,
        reference_date=reference_date,
    )

    today_snapshot = await _today_snapshot_doc(
        db=db,
        user_id=user_id,
        today_payload=today_payload,
        reference_date=reference_date,
    )
    today_source = (
        "served_snapshot"
        if today_snapshot is not None
        else "live_planned" if str(today_payload.get("status") or "success") == "success"
        else "unavailable"
    )

    current_week_sessions = [
        CoachWeekSessionContext(
            canonical=dict(session),
            prescription_source=source,
        )
        for session in week_sessions
        for source in [sources_by_id.get(session.get("prescription_id"), "live_planned")]
    ]

    training_paces_payload = training_paces_to_api_dict(training_paces)
    predictions = [
        CoachPerformancePredictionContext(
            distance=prediction.distance_label,
            predicted_time=prediction.predicted_time_str,
            predicted_pace=prediction.predicted_pace_str,
            confidence=prediction.confidence,
            extrapolation_ratio=prediction.extrapolation_ratio,
            is_strong_extrapolation=(
                prediction.extrapolation_ratio is not None
                and prediction.extrapolation_ratio > CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO
            ),
        )
        for prediction in performance.predictions
    ]

    selected_workout_id = str(workout.get("id") or "") if workout else ""
    garmin_activity = workout.get("garmin_activity") if workout else None
    workout_values = (
        {**(garmin_activity if isinstance(garmin_activity, dict) else {}), **workout}
        if workout else {}
    )
    selected_workout_date = _parse_iso_date(
        workout_values.get("start_time") or workout_values.get("date")
    )
    history_reference_date = selected_workout_date or reference_date
    selected_raw_value = workout_values.get("start_time") or workout_values.get("date")
    selected_workout_datetime = _parse_exact_datetime(selected_raw_value)

    if recent_workouts is None and db is not None and hasattr(db, "garmin_activities"):
        start_date = history_reference_date - timedelta(days=COACH_RECENT_WORKOUTS_WINDOW_DAYS - 1)
        end_date = history_reference_date
        lower_bound = start_date.isoformat()
        upper_bound = (end_date + timedelta(days=1)).isoformat()
        cursor = db.garmin_activities.find(
            {
                "user_id": user_id,
                "start_time": {"$gte": lower_bound, "$lt": upper_bound},
            },
            {"_id": 0},
        )
        if hasattr(cursor, "sort"):
            cursor = cursor.sort("start_time", -1)
        workout_docs = await cursor.to_list(length=None)
        valid_workout_docs = [
            doc
            for doc in workout_docs
            if doc.get("user_id") == user_id
            and _is_valid_recent_workout(doc, history_reference_date)
            and (
                selected_workout_date is None
                or _is_before_selected_workout(
                    doc,
                    selected_workout_id=selected_workout_id,
                    selected_date=selected_workout_date,
                    selected_datetime=selected_workout_datetime,
                    selected_raw=selected_raw_value,
                )
            )
        ]
        normalized_workouts = [
            _normalize_recent_workout(doc)
            for doc in valid_workout_docs
        ]
        recent_workouts = normalized_workouts[:COACH_RECENT_WORKOUTS_MAX_COUNT]
        recent_workouts_coverage = CoachRecentWorkoutsCoverage(
            window_days=COACH_RECENT_WORKOUTS_WINDOW_DAYS,
            start_date_inclusive=lower_bound,
            end_date_inclusive=end_date.isoformat(),
            available_count=len(normalized_workouts),
            included_count=len(recent_workouts),
            max_count=COACH_RECENT_WORKOUTS_MAX_COUNT,
            truncated=len(normalized_workouts) > COACH_RECENT_WORKOUTS_MAX_COUNT,
            strictly_prior_available_count=_strictly_prior_count(
                normalized_workouts, selected_raw_value, selected_workout_id),
        )
    elif recent_workouts is None:
        recent_workouts = []
        recent_workouts_coverage = CoachRecentWorkoutsCoverage(
            window_days=COACH_RECENT_WORKOUTS_WINDOW_DAYS,
            start_date_inclusive=(history_reference_date - timedelta(days=COACH_RECENT_WORKOUTS_WINDOW_DAYS - 1)).isoformat(),
            end_date_inclusive=history_reference_date.isoformat(),
            available_count=0,
            included_count=0,
            max_count=COACH_RECENT_WORKOUTS_MAX_COUNT,
            truncated=False,
        )
    else:
        if selected_workout_date is not None:
            recent_workouts = [
                item
                for item in recent_workouts
                if _is_before_selected_workout(
                    item,
                    selected_workout_id=selected_workout_id,
                    selected_date=selected_workout_date,
                    selected_datetime=selected_workout_datetime,
                    selected_raw=selected_raw_value,
                )
            ]
        available_count = len(recent_workouts)
        filtered_workouts = list(recent_workouts)
        recent_workouts = list(recent_workouts)[:COACH_RECENT_WORKOUTS_MAX_COUNT]
        recent_workouts_coverage = CoachRecentWorkoutsCoverage(
            window_days=COACH_RECENT_WORKOUTS_WINDOW_DAYS,
            start_date_inclusive=(history_reference_date - timedelta(days=COACH_RECENT_WORKOUTS_WINDOW_DAYS - 1)).isoformat(),
            end_date_inclusive=history_reference_date.isoformat(),
            available_count=available_count,
            included_count=len(recent_workouts),
            max_count=COACH_RECENT_WORKOUTS_MAX_COUNT,
            truncated=available_count > COACH_RECENT_WORKOUTS_MAX_COUNT,
            strictly_prior_available_count=_strictly_prior_count(
                filtered_workouts, selected_raw_value, selected_workout_id),
        )

    return CoachContextV2(
        language=language,
        reference_date=reference_date.isoformat(),
        goal=CoachGoalContext(
            objective=((resolved_goal.user_goal_doc or {}).get("event_name") or resolved_goal.goal_type),
            goal_type=((week_payload.get("goal") or {}).get("goal_type") or resolved_goal.goal_type),
            race_date=(week_payload.get("goal") or {}).get("race_date"),
            target_time_seconds=(week_payload.get("goal") or {}).get("target_time_seconds"),
            target_distance_km=resolved_goal.target_distance_km,
        ),
        training_state=CoachTrainingStateContext(
            phase=_build_phase_value(resolved_goal=resolved_goal, reference_date=reference_date),
            current_week=cycle_response.cycle.current_week,
            total_weeks=cycle_response.cycle.total_weeks,
            continuity_state=(week_payload.get("state") or {}).get("continuity_state"),
            allow_intensity=(week_payload.get("state") or {}).get("allow_intensity"),
        ),
        stats_7d=CoachActivityStats(
            km=training_history.window_7d.distance_km,
            sessions=training_history.window_7d.activity_count,
        ),
        stats_30d=CoachActivityStats(
            km=training_history.window_30d.distance_km,
            sessions=training_history.window_30d.activity_count,
        ),
        weekly_target=CoachWeeklyTargetContext(
            target_basis=((week_payload.get("weekly_target") or {}).get("target_basis") or "distance"),
            target_km=(week_payload.get("weekly_target") or {}).get("target_km"),
            target_duration_minutes=(week_payload.get("weekly_target") or {}).get("target_duration_minutes"),
            session_count=int(((week_payload.get("weekly_target") or {}).get("session_count") or 0)),
            confidence=((week_payload.get("weekly_target") or {}).get("confidence") or "none"),
        ),
        weekly_reconciliation=CoachWeeklyReconciliationContext(
            action=week_payload.get("reconciliation_action"),
            reason_codes=list(week_payload.get("reconciliation_reason_codes") or []),
        ),
        current_week_sessions=current_week_sessions,
        recent_workouts=recent_workouts,
        recent_workouts_coverage=recent_workouts_coverage,
        today=CoachTodayContext(
            canonical=dict(today_payload),
            prescription_source=today_source,
        ),
        readiness=CoachReadinessContext(
            band=readiness_decision.band.value,
            score=readiness_decision.score,
            confidence=readiness_decision.confidence.value,
            sufficiency_level=readiness_decision.sufficiency_level.value,
            reason_codes=list(readiness_decision.reason_codes),
            data_source=readiness_data_source,
        ),
        training_load=CoachTrainingLoadContext(
            acute_load_7d=training_load.acute_load_7d,
            load_28d=training_load.load_28d,
            chronic_weekly_load=training_load.chronic_weekly_load,
            acwr=training_load.acwr,
            status=training_load.status,
            confidence=training_load.confidence,
            is_available=training_load.is_available,
            has_sufficient_history=training_load.has_sufficient_history,
            load_change_percent=training_load.load_change_percent,
        ),
        training_paces=CoachTrainingPacesContext(
            is_available=training_paces.confidence != "INSUFFICIENT",
            confidence=training_paces.confidence,
            data=training_paces_payload,
        ),
        performance=CoachPerformanceContext(
            has_data=performance.has_data,
            predictions=predictions,
        ),
        workout_detail=_normalize_workout_detail(workout, workout_analysis),
    )


__all__ = [
    "COACH_RECENT_WORKOUTS_MAX_COUNT",
    "COACH_RECENT_WORKOUTS_WINDOW_DAYS",
    "CoachContextV2",
    "CoachRecentWorkout",
    "CoachRecentWorkoutsCoverage",
    "CoachWorkoutDetail",
    "build_coach_context_v2",
]
