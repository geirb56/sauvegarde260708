"""C352 — Workout Intelligence V3 Core: deterministic diagnosis without splits.

Pipeline (pure, no I/O, no clock):

1. ``extract_workout_intelligence_input`` — data extraction from the workout,
   its strictly-prior history and the Workout Analysis V2 result.
2. ``assess_intensity``          — physiological position vs PERSONAL LT1/LT2.
3. ``classify_session``          — probable session type, with abstention.
4. ``compare_history``           — pace at comparable HR / HR at comparable pace.
5. ``evaluate_trend``            — multi-observation trend, never one session.
6. ``assess_prescription``       — only an authoritative historical snapshot.
7. ``build_coach_assessment``    — FR/EN/ES diagnosis with provenance.

Operational criteria are module constants, documented in
``docs/reports/C352_WORKOUT_INTELLIGENCE_V3_CORE.md``. They are explicit
decision rules, not physiological constants; their sensitivity is exposed
in ``performance_trend.sensitivity``.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from statistics import mean, median, quantiles
from typing import Dict, Iterable, List, Optional, Tuple

from activity_phases import ActivityPhase
from training_v2.prescription_snapshot import PrescriptionSnapshot, is_snapshot_authoritative
from training_v2.performance_model import _resolve_fcmax_robust
from training_v2.runner_profile import _first_valid_number, _parse_hr
from workout_analysis_v2 import (
    SIMILAR_DISTANCE_TOLERANCE_PCT,
    SIMILAR_HISTORY_WINDOW_DAYS,
    SIMILAR_MIN_COMPARABLE_SAMPLE,
    WorkoutAnalysisV2Response,
    _build_phase_analysis,
    _competition_flag,
    _lang,
    _parse_workout_date,
    _session_structure,
    _valid_positive_number,
)
from workout_intelligence_v3_models import (
    Confidence,
    StructureStatus,
    WIV3CoachAssessment,
    WIV3CoachItem,
    WIV3CurrentSession,
    WIV3FcMax,
    WIV3HistoricalComparison,
    WIV3HistoricalSession,
    WIV3HrAtComparablePace,
    WIV3IntensityAssessment,
    WIV3ObservedMaxHr,
    WIV3PaceAtComparableHr,
    WIV3PerformanceTrend,
    WIV3PhysiologicalProfile,
    WIV3PhysiologicalSource,
    WIV3PrescriptionAssessment,
    WIV3PrescriptionContext,
    WIV3RelativeEffortReference,
    WIV3SessionClassification,
    WIV3ThresholdEstimate,
    WIV3ThresholdUsed,
    WIV3TrendSensitivity,
    WIV3V2Reference,
    WorkoutIntelligenceV3,
    WorkoutIntelligenceV3Input,
)

# ── Operational criteria (documented, not physiological constants) ──────────
# Credible HR ceiling reused from training_v2.performance_model (_resolve_fcmax).
HR_CREDIBLE_CEILING_BPM = 230.0
FCMAX_OBSERVED_FLOOR_BPM = 150.0
PERSONAL_THRESHOLD_SOURCES = {"lab_test", "field_test", "device_estimate"}
RELIABLE_THRESHOLD_CONFIDENCE = {"high", "medium"}
# History comparability bands around the CURRENT session.
HR_MATCH_TOLERANCE_BPM = 5.0
PACE_MATCH_TOLERANCE_SEC_PER_KM = 15.0
DURATION_MATCH_TOLERANCE_PCT = SIMILAR_DISTANCE_TOLERANCE_PCT  # reused V2 tolerance
# Trend.
TREND_MIN_OBSERVATIONS = 4
TREND_MIN_PER_HALF = 2
TREND_MIN_SPAN_DAYS = 21
TREND_PACE_MARGIN_SEC_PER_KM = 10.0
TREND_SENSITIVITY_HR_TOLERANCES = (3.0, 5.0, 8.0)
TREND_SENSITIVITY_MARGINS = (5.0, 10.0, 15.0)
# Long run: relative to the athlete's own habitual duration.
LONG_RUN_DURATION_RATIO = 1.5
LONG_RUN_MIN_HISTORY = 5
# Level C — relative effort within the athlete's own history (no LT1/LT2).
# Operational decision rules, not physiological constants (see report §12).
RELATIVE_MIN_REFERENCES = 8          # distinct earlier sessions, enough for quartiles
RELATIVE_MIN_IQR_BPM = 8.0           # below: history too homogeneous to separate effort levels
RELATIVE_RANGE_MARGIN_BPM = 5.0      # current HR outside [min-5, max+5] → outside the reference range
RELATIVE_DURATION_RATIO_RANGE = (0.5, 2.0)  # reference duration vs current duration

_CONFIDENCE_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
_STRUCTURE_FROM_V2 = {"continuous": "continuous_recorded", "intervals": "intervals", "other": "other"}
_EXPECTED_CLASSES = {
    "easy": {"easy_run_probable"},
    "recovery": {"easy_run_probable"},
    "long_easy": {"long_run_probable", "easy_run_probable"},
    "steady": {"steady_run_probable"},
    "quality": {"tempo_probable", "intervals"},
}


def _num(value) -> Optional[float]:
    return float(value) if _valid_positive_number(value) else None


def _min_confidence(*values: str) -> Confidence:
    return min(values, key=lambda value: _CONFIDENCE_ORDER.get(value, 0))  # type: ignore[return-value]


def _safe_date(raw: str) -> Optional[datetime]:
    try:
        return _parse_workout_date(raw)
    except (TypeError, ValueError):
        return None


def _pace(workout: dict) -> Optional[float]:
    pace = _num(workout.get("avg_pace_min_km"))
    if pace is not None:
        return pace
    speed = _num(workout.get("avg_speed_kmh"))
    return 60.0 / speed if speed is not None else None


def _hr(workout: dict, *keys: str) -> Optional[float]:
    for key in keys:
        value = _num(workout.get(key))
        if value is not None:
            return value
    return None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None or not math.isfinite(value) else round(value, digits)


# ── 1. Extraction ────────────────────────────────────────────────────────────


def _structure_of(workout: dict, phases: Optional[List[ActivityPhase]]) -> StructureStatus:
    signal = _session_structure(workout, _build_phase_analysis(phases), "en")
    return _STRUCTURE_FROM_V2.get(signal.code, "unknown") if signal.available else "unknown"  # type: ignore[return-value]


def observed_max_hr(history: Iterable[WIV3HistoricalSession]) -> WIV3ObservedMaxHr:
    """Observed maximum from strictly-prior sessions with the Training V2 rule.

    This is a lower bound of the physiological FCmax, never a certain FCmax.
    """
    observed = [
        session.max_hr for session in history
        if session.max_hr is not None
        and FCMAX_OBSERVED_FLOOR_BPM <= session.max_hr <= HR_CREDIBLE_CEILING_BPM
    ]
    value = _resolve_fcmax_robust(observed)
    if value is None:
        return WIV3ObservedMaxHr()
    return WIV3ObservedMaxHr(
        value_bpm=value, source="garmin_activities_strictly_prior", observation_count=len(observed),
    )


_KIND_BY_THRESHOLD_SOURCE = {
    "lab_test": "personal_measured",
    "field_test": "personal_measured",
    "device_estimate": "personal_device_estimate",
    "user_declared": "personal_declared",
    "generic_formula": "generic",
    "unknown": "unverified",
}


def _threshold_from(raw) -> Optional[WIV3ThresholdEstimate]:
    if isinstance(raw, WIV3ThresholdEstimate):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return WIV3ThresholdEstimate(**raw)
    except Exception:
        return WIV3ThresholdEstimate(source="unknown", confidence="unknown")


def resolve_physiological_profile(
    *,
    physiological_metrics: Optional[dict] = None,
    user_profile: Optional[dict] = None,
) -> WIV3PhysiologicalProfile:
    """Map the canonical RunnerProfile declared inputs to the V3 profile.

    FCmax follows ``training_v2.runner_profile.build_runner_profile``
    priority (``physiological_metrics`` then ``user_profile``; keys
    ``max_hr`` / ``max_heart_rate``). No age formula, no derivation.
    LT1/LT2 are read only from the V3 threshold contract
    (``physiological_metrics["lt1"|"lt2"]`` with source/date/confidence):
    no existing RunIndex module produces them.
    """
    sources: List[WIV3PhysiologicalSource] = []
    fcmax = WIV3FcMax()
    for container_name, container in (("physiological_metrics", physiological_metrics), ("user_profile", user_profile)):
        value = _first_valid_number(container, _parse_hr, "max_hr", "max_heart_rate")
        if value is None:
            continue
        key = "max_hr" if _parse_hr((container or {}).get("max_hr")) is not None else "max_heart_rate"
        declared_on = (container or {}).get("max_hr_declared_on")
        fcmax = WIV3FcMax(
            value_bpm=float(value), source="user_declared",
            declared_on=str(declared_on) if declared_on else None,
            provenance=f"runner_profile.{container_name}.{key}",
        )
        break
    sources.append(WIV3PhysiologicalSource(
        data="fcmax_declared",
        source=fcmax.provenance or "runner_profile.max_hr (physiological_metrics / user_profile)",
        unit="bpm", available=fcmax.value_bpm is not None,
        usable_by_v3=fcmax.value_bpm is not None,
        kind="personal_declared" if fcmax.value_bpm is not None else "unavailable",
        valid_from=fcmax.declared_on,
        reason=("declared_value_consistency_checks_only" if fcmax.value_bpm is not None
                else "no_declared_fcmax_supplied_runtime_passes_none"),
    ))
    thresholds = {}
    for name in ("lt1", "lt2"):
        estimate = _threshold_from((physiological_metrics or {}).get(name))
        thresholds[name] = estimate
        if estimate is None or estimate.value_bpm is None:
            sources.append(WIV3PhysiologicalSource(
                data=name, source="none: no RunIndex module persists or computes LT1/LT2",
                unit="bpm", available=False, usable_by_v3=False, kind="unavailable",
                reason="personal_threshold_not_persisted",
            ))
            continue
        personal = estimate.source in PERSONAL_THRESHOLD_SOURCES
        reliable = personal and estimate.confidence in RELIABLE_THRESHOLD_CONFIDENCE
        sources.append(WIV3PhysiologicalSource(
            data=name, source=f"physiological_metrics.{name}:{estimate.source}",
            unit="bpm", available=True, usable_by_v3=reliable,
            kind=_KIND_BY_THRESHOLD_SOURCE.get(estimate.source, "unverified"),  # type: ignore[arg-type]
            valid_from=estimate.estimated_on,
            reason=("personal_reliable_subject_to_session_date_check" if reliable
                    else "not_personal_measurement" if not personal else "confidence_insufficient"),
        ))
    sources.append(WIV3PhysiologicalSource(
        data="training_v2_zones", source="training_v2.training_paces (Daniels VDOT E/M/T/I/R)",
        unit="min/km", available=False, usable_by_v3=False, kind="pace_based_not_hr",
        reason="pace_zones_are_not_heart_rate_thresholds",
    ))
    provided = any(item is not None and item.value_bpm is not None for item in thresholds.values())
    return WIV3PhysiologicalProfile(
        fcmax=fcmax, lt1=thresholds["lt1"], lt2=thresholds["lt2"],
        lt_source_status="provided" if provided else "not_persisted",
        sources=sources,
    )


def extract_workout_intelligence_input(
    workout: dict,
    historical_workouts: List[dict],
    *,
    v2_analysis: WorkoutAnalysisV2Response,
    activity_types: Optional[Dict[str, str]] = None,
    historical_phases: Optional[Dict[str, List[ActivityPhase]]] = None,
    profile: Optional[WIV3PhysiologicalProfile] = None,
    prescription: Optional[WIV3PrescriptionContext] = None,
) -> WorkoutIntelligenceV3Input:
    types = activity_types or {}
    current_id = str(workout.get("id") or "")
    current_dt = _safe_date(workout.get("date", ""))
    phase_analysis = v2_analysis.phase_analysis
    structure_signal = v2_analysis.signals.session_structure
    session = WIV3CurrentSession(
        id=current_id,
        date=str(workout.get("date") or ""),
        sport=str(workout.get("type") or ""),
        activity_type=types.get(current_id),
        distance_km=_num(workout.get("distance_km")),
        duration_minutes=_num(workout.get("duration_minutes")),
        avg_pace_min_km=_pace(workout),
        avg_hr=_hr(workout, "avg_heart_rate", "avg_hr"),
        max_hr=_hr(workout, "max_heart_rate", "max_hr"),
        elevation_gain_m=_num(workout.get("elevation_gain_m")),
        competition=_competition_flag(workout),
        has_splits=v2_analysis.evidence.has_splits,
        structure=(
            _STRUCTURE_FROM_V2.get(structure_signal.code, "unknown")
            if structure_signal.available else "unknown"
        ),
        effort_count=len(phase_analysis.efforts),
        recovery_count=len(phase_analysis.recoveries),
        effort_regularity_available=phase_analysis.effort_regularity.available,
        effort_avg_hr=_num(phase_analysis.effort_statistics.average_hr),
        has_warmup_or_cooldown=any(
            phase.phase_type in {"warmup", "cooldown"} for phase in phase_analysis.phases
        ),
    )
    history: List[WIV3HistoricalSession] = []
    for item in historical_workouts:
        item_id = str(item.get("id") or "")
        item_dt = _safe_date(item.get("date", ""))
        # Strictly prior only: no future data can leak into an old session.
        if not item_id or item_id == current_id or current_dt is None or item_dt is None or item_dt >= current_dt:
            continue
        history.append(WIV3HistoricalSession(
            id=item_id,
            date=str(item.get("date")),
            sport=str(item.get("type") or ""),
            activity_type=types.get(item_id),
            distance_km=_num(item.get("distance_km")),
            duration_minutes=_num(item.get("duration_minutes")),
            avg_pace_min_km=_pace(item),
            avg_hr=_hr(item, "avg_heart_rate", "avg_hr"),
            max_hr=_hr(item, "max_heart_rate", "max_hr"),
            competition=_competition_flag(item),
            structure=_structure_of(item, (historical_phases or {}).get(item_id)),
        ))
    profile = profile or WIV3PhysiologicalProfile()
    updates: dict = {}
    if profile.observed_max_hr is None:
        updates["observed_max_hr"] = observed_max_hr(history)
    if isinstance(workout.get("effort_zone_distribution"), dict) and workout.get("effort_zone_distribution"):
        # Same rule as Workout Analysis V2 (_has_trusted_zone_provenance → False).
        updates["sources"] = list(profile.sources) + [WIV3PhysiologicalSource(
            data="workout_hr_zone_distribution", source="workouts.effort_zone_distribution",
            unit="percent_of_duration", available=True, usable_by_v3=False, kind="unverified",
            reason="zone_bounds_provenance_unverified_not_personal_thresholds",
        )]
    if updates:
        profile = profile.model_copy(update=updates)
    similar = v2_analysis.comparison.similar
    v2_reference = WIV3V2Reference(
        available=bool(similar and similar.available),
        sample_count=similar.sample_count if similar else 0,
        workout_ids=list(similar.workout_ids) if similar else [],
        pace_comparability=similar.pace_comparability if similar else None,
        hr_comparability=similar.hr_comparability if similar else None,
        limitations=list(similar.limitations) if similar else [],
    )
    return WorkoutIntelligenceV3Input(
        session=session,
        profile=profile,
        history=history,
        v2_reference=v2_reference,
        prescription=prescription or WIV3PrescriptionContext(),
    )


# ── 2. Physiological evaluation ──────────────────────────────────────────────


def _hr_quality(session: WIV3CurrentSession) -> Tuple[Optional[float], List[str]]:
    """Average HR usable for interpretation, else the reasons it is not."""
    avg, peak = session.avg_hr, session.max_hr
    if avg is None:
        return None, ["hr_missing"]
    if avg > HR_CREDIBLE_CEILING_BPM:
        return None, ["hr_aberrant_above_credible_ceiling"]
    if peak is not None and avg > peak:
        return None, ["hr_aberrant_average_above_max"]
    return avg, []


def _usable_threshold(
    name: str, estimate: Optional[WIV3ThresholdEstimate], session_day: Optional[date],
) -> Tuple[Optional[WIV3ThresholdUsed], Optional[str]]:
    if estimate is None or estimate.value_bpm is None:
        return None, None
    if not _valid_positive_number(estimate.value_bpm) or estimate.value_bpm > HR_CREDIBLE_CEILING_BPM:
        return None, "invalid_value"
    if estimate.source not in PERSONAL_THRESHOLD_SOURCES:
        return None, f"source_not_personal_measurement:{estimate.source}"
    if estimate.confidence not in RELIABLE_THRESHOLD_CONFIDENCE:
        return None, f"confidence_insufficient:{estimate.confidence}"
    estimated = _safe_date(estimate.estimated_on or "")
    if estimated is None:
        return None, "estimate_date_unknown"
    if session_day is None or estimated.date() > session_day:
        return None, "estimate_after_session"
    return WIV3ThresholdUsed(
        value_bpm=float(estimate.value_bpm), source=estimate.source,
        estimated_on=estimated.date().isoformat(), confidence=estimate.confidence,
    ), None


def assess_intensity(data: WorkoutIntelligenceV3Input) -> WIV3IntensityAssessment:
    session, profile = data.session, data.profile
    session_dt = _safe_date(session.date)
    session_day = session_dt.date() if session_dt else None
    hr, limitations = _hr_quality(session)
    rejected: Dict[str, str] = {}
    lt1, reason1 = _usable_threshold("lt1", profile.lt1, session_day)
    lt2, reason2 = _usable_threshold("lt2", profile.lt2, session_day)
    if reason1:
        rejected["lt1"] = reason1
    if reason2:
        rejected["lt2"] = reason2
    if profile.lt_source_status == "not_persisted" and lt1 is None and lt2 is None:
        limitations.append("personal_thresholds_not_persisted")
    if lt1 and lt2 and lt1.value_bpm >= lt2.value_bpm:
        rejected["lt1"] = rejected["lt2"] = "inconsistent_lt1_not_below_lt2"
        lt1 = lt2 = None
    # Only a declared FCmax (never an observed maximum, which is a lower
    # bound) is used, and only for consistency checks.
    declared_fcmax = profile.fcmax.value_bpm if profile.fcmax.source == "user_declared" else None
    if declared_fcmax is not None and not (FCMAX_OBSERVED_FLOOR_BPM <= declared_fcmax <= HR_CREDIBLE_CEILING_BPM):
        rejected["fcmax"] = "declared_value_out_of_credible_range"
        declared_fcmax = None
    declared_on = _safe_date(profile.fcmax.declared_on or "")
    if declared_fcmax is not None and profile.fcmax.declared_on:
        if declared_on is None:
            rejected["fcmax"] = "declaration_date_invalid"
            declared_fcmax = None
        elif session_day is None or declared_on.date() > session_day:
            rejected["fcmax"] = "declared_after_session"
            declared_fcmax = None
    elif declared_fcmax is not None:
        limitations.append("fcmax_declaration_date_unknown")
    observed = profile.observed_max_hr or WIV3ObservedMaxHr()
    if declared_fcmax is not None and lt2 is not None and lt2.value_bpm >= declared_fcmax:
        rejected["lt2"] = "inconsistent_lt2_not_below_fcmax"
        lt2 = None
    if hr is not None and declared_fcmax is not None and hr > declared_fcmax:
        limitations.append("hr_above_reference_fcmax")
        hr = None
    limitations.append("average_hr_is_not_time_in_zone")

    position = "unknown"
    if hr is not None:
        if lt1 is not None and hr < lt1.value_bpm:
            position = "below_LT1"
        elif lt2 is not None and hr > lt2.value_bpm:
            position = "above_LT2"
        elif lt1 is not None and lt2 is not None:
            position = "between_LT1_LT2"
        elif lt1 is None and lt2 is None:
            limitations.append("no_reliable_personal_threshold")
        else:
            limitations.append("missing_threshold_for_this_hr_range")
    confidence: Confidence = "none"
    if position != "unknown":
        used = [item.confidence for item in (lt1, lt2) if item is not None]
        # Average HR never proves the dominant zone: cap at medium.
        confidence = _min_confidence("medium", *used)
    return WIV3IntensityAssessment(
        position=position,
        hr_used_bpm=_round(hr, 1),
        session_max_hr_bpm=session.max_hr,
        lt1=lt1, lt2=lt2,
        fcmax_bpm=declared_fcmax,
        fcmax_source="user_declared" if declared_fcmax is not None else "unavailable",
        observed_max_hr_bpm=observed.value_bpm,
        observed_max_hr_observation_count=observed.observation_count,
        physiological_sources=list(profile.sources),
        rejected_thresholds=rejected,
        confidence=confidence,
        limitations=limitations,
        source_paths=["session.avg_hr", "profile.lt1", "profile.lt2", "profile.fcmax", "profile.observed_max_hr"],
    )


# ── 3. Session classification ────────────────────────────────────────────────


def _habitual_duration(data: WorkoutIntelligenceV3Input) -> Tuple[Optional[float], int]:
    durations = [
        item.duration_minutes for item in data.history
        if item.sport == data.session.sport and item.duration_minutes is not None
    ]
    return (median(durations) if len(durations) >= LONG_RUN_MIN_HISTORY else None), len(durations)


# ── 3b. Level C: relative effort within the athlete's own history ───────────


def _relative_exclusions(
    session: WIV3CurrentSession, item: WIV3HistoricalSession, current_dt: Optional[datetime],
) -> List[str]:
    """Admissibility of an earlier session as a relative-effort reference.

    Independent from ``eligible_references`` (comparison/trend eligibility
    is unchanged).
    """
    reasons: List[str] = []
    item_dt = _safe_date(item.date)
    if current_dt is None or item_dt is None or item_dt >= current_dt:
        reasons.append("not_strictly_prior")
    elif (current_dt - item_dt).days > SIMILAR_HISTORY_WINDOW_DAYS:
        reasons.append("outside_window")
    if item.sport != session.sport:
        reasons.append("different_sport")
    if item.activity_type is None:
        reasons.append("environment_unknown")
    elif item.activity_type != session.activity_type:
        reasons.append("different_environment")
    if item.competition is True:
        reasons.append("competition")
    if item.structure in {"intervals", "other"}:
        reasons.append("interval_or_structured_session")
    if item.avg_pace_min_km is None or not _valid_positive_number(item.avg_pace_min_km):
        reasons.append("missing_pace")
    if item.avg_hr is None or not _valid_positive_number(item.avg_hr) or item.avg_hr > HR_CREDIBLE_CEILING_BPM or (
        item.max_hr is not None and item.avg_hr > item.max_hr
    ):
        reasons.append("missing_or_aberrant_hr")
    low, high = RELATIVE_DURATION_RATIO_RANGE
    if item.duration_minutes is None or session.duration_minutes is None:
        reasons.append("duration_unknown")
    elif not (low * session.duration_minutes <= item.duration_minutes <= high * session.duration_minutes):
        reasons.append("duration_not_comparable")
    return reasons


def relative_effort_reference(
    data: WorkoutIntelligenceV3Input, intensity: WIV3IntensityAssessment,
) -> WIV3RelativeEffortReference:
    """Place the session average HR in the athlete's own reference distribution.

    Robust statistics (quartiles, IQR), no absolute HR rule, no %FCmax.
    """
    session = data.session
    criteria = {
        "min_references": float(RELATIVE_MIN_REFERENCES),
        "min_iqr_bpm": RELATIVE_MIN_IQR_BPM,
        "range_margin_bpm": RELATIVE_RANGE_MARGIN_BPM,
        "duration_ratio_min": RELATIVE_DURATION_RATIO_RANGE[0],
        "duration_ratio_max": RELATIVE_DURATION_RATIO_RANGE[1],
        "window_days": float(SIMILAR_HISTORY_WINDOW_DAYS),
    }
    base_limits = ["relative_position_is_not_a_physiological_zone"]
    hr, pace = intensity.hr_used_bpm, session.avg_pace_min_km
    common = dict(current_hr_bpm=hr, current_pace_min_km=pace, criteria=criteria)
    blockers = []
    if hr is None:
        blockers.append("current_hr_unusable")
    if pace is None:
        blockers.append("current_pace_missing")
    if session.activity_type is None:
        blockers.append("current_environment_unknown")
    if session.competition is True:
        blockers.append("current_session_is_competition")
    if session.structure in {"intervals", "other"}:
        blockers.append("current_session_structured")
    if blockers:
        return WIV3RelativeEffortReference(status="not_applicable", limitations=base_limits + blockers, **common)

    current_dt = _safe_date(session.date)
    refs: List[WIV3HistoricalSession] = []
    exclusions: Dict[str, int] = {}
    seen_days = set()
    for item in sorted(data.history, key=lambda h: h.date):
        reasons = _relative_exclusions(session, item, current_dt)
        for reason in reasons:
            exclusions[reason] = exclusions.get(reason, 0) + 1
        if not reasons:
            refs.append(item)
            seen_days.add(item.date[:10])
    exclusions = dict(sorted(exclusions.items()))
    common["exclusions"] = exclusions
    if len(refs) < RELATIVE_MIN_REFERENCES or len(seen_days) < RELATIVE_MIN_REFERENCES:
        return WIV3RelativeEffortReference(
            status="insufficient_references", reference_count=len(refs),
            workout_ids=[r.id for r in refs],
            limitations=base_limits + ["too_few_admissible_references"], **common,
        )
    hrs = sorted(float(r.avg_hr) for r in refs)
    paces = sorted(float(r.avg_pace_min_km) for r in refs)
    q1, med, q3 = quantiles(hrs, n=4, method="inclusive")
    pq1, _, pq3 = quantiles(paces, n=4, method="inclusive")
    stats = dict(
        reference_count=len(refs), workout_ids=[r.id for r in refs],
        period_start=refs[0].date[:10], period_end=refs[-1].date[:10],
        hr_min_bpm=round(hrs[0], 1), hr_q1_bpm=round(q1, 1), hr_median_bpm=round(med, 1),
        hr_q3_bpm=round(q3, 1), hr_max_bpm=round(hrs[-1], 1), hr_iqr_bpm=round(q3 - q1, 1),
        pace_q1_min_km=round(pq1, 3), pace_q3_min_km=round(pq3, 3),
    )
    limits = base_limits + ["low_hr_may_reflect_walking_pauses_sensor_or_terrain"]
    if q3 - q1 < RELATIVE_MIN_IQR_BPM:
        return WIV3RelativeEffortReference(
            status="no_separation", limitations=limits + ["history_too_homogeneous_to_separate_effort_levels"],
            **stats, **common,
        )
    if hr < hrs[0] - RELATIVE_RANGE_MARGIN_BPM or hr > hrs[-1] + RELATIVE_RANGE_MARGIN_BPM:
        return WIV3RelativeEffortReference(
            status="out_of_reference_range", limitations=limits + ["current_hr_outside_reference_range"],
            **stats, **common,
        )
    position = "low" if hr <= q1 else "high" if hr >= q3 else "intermediate"
    # HR/pace coherence: a low HR at a fast pace (or the reverse) is not
    # interpreted (sensor, terrain, pauses, heat… are not controlled).
    if position == "low" and pace < pq1:
        return WIV3RelativeEffortReference(
            status="incoherent_hr_pace", relative_position=position,
            limitations=limits + ["low_hr_with_fast_pace_not_interpreted"], **stats, **common,
        )
    if position == "high" and pace > pq3:
        return WIV3RelativeEffortReference(
            status="incoherent_hr_pace", relative_position=position,
            limitations=limits + ["high_hr_with_slow_pace_not_interpreted"], **stats, **common,
        )
    return WIV3RelativeEffortReference(
        status="used", relative_position=position, limitations=limits, **stats, **common,
    )


def _relative_evidence(rel: WIV3RelativeEffortReference) -> Dict[str, float]:
    return {
        "avg_hr_bpm": rel.current_hr_bpm,
        "reference_hr_q1_bpm": rel.hr_q1_bpm,
        "reference_hr_median_bpm": rel.hr_median_bpm,
        "reference_hr_q3_bpm": rel.hr_q3_bpm,
        "reference_count": float(rel.reference_count),
    }


def classify_session(
    data: WorkoutIntelligenceV3Input, intensity: WIV3IntensityAssessment,
) -> WIV3SessionClassification:
    session = data.session
    limitations: List[str] = []
    if session.structure == "intervals" and session.effort_count >= 2 and session.recovery_count >= 1:
        evidence = {"effort_count": float(session.effort_count), "recovery_count": float(session.recovery_count)}
        return WIV3SessionClassification(
            type="intervals",
            confidence="high" if session.effort_regularity_available else "medium",
            evidence=evidence,
            rules=["garmin_phases_recovery_between_efforts"], decision_tier="garmin_phases",
            limitations=[] if session.effort_regularity_available else ["effort_regularity_unavailable"],
            source_paths=["phase_analysis.efforts", "phase_analysis.recoveries", "signals.session_structure"],
        )
    if session.structure == "unknown":
        limitations.append("no_recorded_session_structure")
    if not session.has_splits:
        limitations.append("no_splits_whole_session_averages_only")

    # Structured continuous block (warm-up/cool-down + one effort) above LT1.
    lt1 = intensity.lt1.value_bpm if intensity.lt1 else None
    if (
        session.structure == "other" and session.effort_count == 1 and session.recovery_count == 0
        and session.has_warmup_or_cooldown and session.effort_avg_hr is not None and lt1 is not None
        and session.effort_avg_hr >= lt1
    ):
        return WIV3SessionClassification(
            type="tempo_probable", confidence="medium",
            evidence={"effort_avg_hr_bpm": session.effort_avg_hr, "lt1_bpm": lt1},
            rules=["single_effort_block_with_warmup_or_cooldown_at_or_above_lt1"], decision_tier="garmin_phases",
            limitations=limitations, source_paths=["phase_analysis.phases", "profile.lt1"],
        )
    if session.structure == "other":
        limitations.append("structured_phases_without_identifiable_type")

    habitual, history_count = _habitual_duration(data)
    is_long = (
        habitual is not None and session.duration_minutes is not None
        and session.duration_minutes >= LONG_RUN_DURATION_RATIO * habitual
    )
    position = intensity.position
    relative = (
        relative_effort_reference(data, intensity) if position == "unknown"
        else WIV3RelativeEffortReference()
    )
    evidence: Dict[str, float] = {}
    if intensity.hr_used_bpm is not None and position != "unknown":
        evidence["avg_hr_bpm"] = intensity.hr_used_bpm
    relatively_high = relative.status == "used" and relative.relative_position == "high"
    if is_long and (position == "below_LT1" or (position == "unknown" and not relatively_high)):
        evidence.update({
            "duration_minutes": float(session.duration_minutes),
            "habitual_duration_minutes": round(habitual, 1),
            "duration_ratio": round(session.duration_minutes / habitual, 2),
            "history_count": float(history_count),
        })
        if position == "unknown":
            limitations.append("intensity_unknown_volume_based_only")
        return WIV3SessionClassification(
            type="long_run_probable",
            confidence="medium" if position == "below_LT1" else "low",
            evidence=evidence, rules=["duration_at_least_1_5x_habitual_median", "not_above_lt1_when_known"],
            decision_tier="personal_thresholds" if position == "below_LT1" else "individual_history",
            limitations=limitations, relative_effort=relative,
            source_paths=["session.duration_minutes", "history.duration_minutes", "intensity_assessment.position"],
        )
    if habitual is None:
        limitations.append("habitual_duration_unavailable")
    if position == "below_LT1":
        return WIV3SessionClassification(
            type="easy_run_probable", confidence=_min_confidence("medium", intensity.confidence),
            evidence=evidence, rules=["average_hr_below_personal_lt1"], decision_tier="personal_thresholds",
            limitations=limitations, source_paths=["intensity_assessment"],
        )
    if position == "between_LT1_LT2":
        return WIV3SessionClassification(
            type="steady_run_probable", confidence="low",
            evidence=evidence, rules=["average_hr_between_personal_lt1_lt2"], decision_tier="personal_thresholds",
            limitations=limitations + ["tempo_not_distinguishable_from_average_hr"],
            source_paths=["intensity_assessment"],
        )
    if position == "above_LT2":
        return WIV3SessionClassification(
            type="tempo_probable", confidence="low",
            evidence=evidence, rules=["average_hr_above_personal_lt2_without_phase_structure"], decision_tier="personal_thresholds",
            limitations=limitations + ["intervals_not_identifiable_without_phases"],
            source_paths=["intensity_assessment"],
        )
    # Level C — relative effort in the athlete's own history (thresholds absent).
    rel_paths = ["session_classification.relative_effort", "history.avg_hr", "intensity_assessment.hr_used_bpm"]
    rel_limits = limitations + ["relative_effort_not_physiological_intensity", "intervals_not_identifiable_without_phases"]
    if relative.status == "used" and relative.relative_position == "low":
        return WIV3SessionClassification(
            type="easy_run_probable", confidence="low", decision_tier="individual_history",
            evidence=_relative_evidence(relative),
            rules=["average_hr_in_lower_quartile_of_personal_reference_distribution", "pace_not_in_fastest_quartile"],
            limitations=rel_limits, relative_effort=relative, source_paths=rel_paths,
        )
    if (
        relative.status == "used" and relative.relative_position == "high"
        and session.structure == "continuous_recorded"
    ):
        return WIV3SessionClassification(
            type="steady_run_probable", confidence="low", decision_tier="individual_history",
            evidence=_relative_evidence(relative),
            rules=["average_hr_in_upper_quartile_of_personal_reference_distribution", "continuous_structure_recorded"],
            limitations=rel_limits + ["tempo_not_distinguishable_from_average_hr"],
            relative_effort=relative, source_paths=rel_paths + ["signals.session_structure"],
        )
    abstain = ["abstention_no_reliable_intensity_or_structure"]
    if relative.status == "used" and relative.relative_position == "intermediate":
        abstain.append("relative_effort_intermediate_type_not_identifiable")
    elif relative.status == "used":
        abstain.append("relative_effort_high_without_confirmed_continuous_structure")
    elif relative.status not in {"not_evaluated"}:
        abstain.append(f"relative_effort_{relative.status}")
    return WIV3SessionClassification(
        type="unknown", confidence="none", evidence={},
        rules=abstain, decision_tier="insufficient_data",
        limitations=limitations + ["intervals_not_identifiable_without_phases"],
        relative_effort=relative,
        source_paths=["intensity_assessment", "signals.session_structure", "session_classification.relative_effort"],
    )


# ── 4. Historical comparison ─────────────────────────────────────────────────


def _exclusion_reasons(
    session: WIV3CurrentSession, item: WIV3HistoricalSession, current_dt: Optional[datetime],
) -> List[str]:
    reasons: List[str] = []
    item_dt = _safe_date(item.date)
    if current_dt is None or item_dt is None or item_dt >= current_dt:
        reasons.append("not_strictly_prior")
    elif (current_dt - item_dt).days > SIMILAR_HISTORY_WINDOW_DAYS:
        reasons.append("outside_window")
    if item.sport != session.sport:
        reasons.append("different_sport")
    if session.activity_type is None:
        reasons.append("current_environment_unknown")
    elif item.activity_type is None:
        reasons.append("environment_unknown")
    elif item.activity_type != session.activity_type:
        reasons.append("different_environment")
    if session.competition is not None and item.competition is not None and session.competition != item.competition:
        reasons.append("different_session_nature")
    if item.structure in {"intervals", "other"}:
        reasons.append("different_structure")
    if item.avg_pace_min_km is None:
        reasons.append("missing_pace")
    if item.avg_hr is None or item.avg_hr > HR_CREDIBLE_CEILING_BPM or (
        item.max_hr is not None and item.avg_hr > item.max_hr
    ):
        reasons.append("missing_or_aberrant_hr")
    if session.duration_minutes is None or item.duration_minutes is None:
        reasons.append("duration_unknown")
    elif abs(item.duration_minutes - session.duration_minutes) > session.duration_minutes * DURATION_MATCH_TOLERANCE_PCT / 100:
        reasons.append("duration_not_comparable")
    return reasons


def eligible_references(data: WorkoutIntelligenceV3Input) -> Tuple[List[WIV3HistoricalSession], Dict[str, int]]:
    current_dt = _safe_date(data.session.date)
    eligible: List[WIV3HistoricalSession] = []
    counts: Dict[str, int] = {}
    for item in data.history:
        reasons = _exclusion_reasons(data.session, item, current_dt)
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
        if not reasons:
            eligible.append(item)
    return eligible, dict(sorted(counts.items()))


def _hr_cohort(refs: List[WIV3HistoricalSession], hr: Optional[float], tolerance: float) -> List[WIV3HistoricalSession]:
    if hr is None:
        return []
    return [ref for ref in refs if abs(ref.avg_hr - hr) <= tolerance]


def compare_history(
    data: WorkoutIntelligenceV3Input, intensity: WIV3IntensityAssessment,
) -> WIV3HistoricalComparison:
    session = data.session
    pace_block = WIV3PaceAtComparableHr(hr_tolerance_bpm=HR_MATCH_TOLERANCE_BPM, current_pace_min_km=session.avg_pace_min_km)
    hr_block = WIV3HrAtComparablePace(
        pace_tolerance_sec_per_km=PACE_MATCH_TOLERANCE_SEC_PER_KM, current_hr_bpm=intensity.hr_used_bpm,
    )
    base = dict(
        window_days=SIMILAR_HISTORY_WINDOW_DAYS, candidate_count=len(data.history),
        v2_similar_reference=data.v2_reference,
        source_paths=["history", "comparison.similar"],
    )
    if session.structure in {"intervals", "other"}:
        return WIV3HistoricalComparison(
            status="not_applicable", pace_at_comparable_hr=pace_block, hr_at_comparable_pace=hr_block,
            limitations=["structured_session_average_not_comparable"], **base,
        )
    refs, exclusions = eligible_references(data)
    limitations = ["terrain_weather_not_controlled"]
    current_hr, current_pace = intensity.hr_used_bpm, session.avg_pace_min_km
    if current_hr is None:
        limitations.append("current_hr_unusable")
    if current_pace is None:
        limitations.append("current_pace_missing")
    hr_matches = _hr_cohort(refs, current_hr, HR_MATCH_TOLERANCE_BPM)
    pace_matches = (
        [ref for ref in refs if abs(ref.avg_pace_min_km - current_pace) * 60 <= PACE_MATCH_TOLERANCE_SEC_PER_KM]
        if current_pace is not None else []
    )
    if hr_matches and current_pace is not None:
        ref_pace = mean(ref.avg_pace_min_km for ref in hr_matches)
        pace_block = pace_block.model_copy(update=dict(
            reference_count=len(hr_matches), workout_ids=[ref.id for ref in hr_matches],
            reference_pace_min_km=_round(ref_pace, 3),
            reference_hr_bpm=_round(mean(ref.avg_hr for ref in hr_matches), 1),
            pace_difference_sec_per_km=_round((current_pace - ref_pace) * 60, 1),
        ))
    if pace_matches and current_hr is not None:
        ref_hr = mean(ref.avg_hr for ref in pace_matches)
        hr_block = hr_block.model_copy(update=dict(
            reference_count=len(pace_matches), workout_ids=[ref.id for ref in pace_matches],
            reference_hr_bpm=_round(ref_hr, 1),
            reference_pace_min_km=_round(mean(ref.avg_pace_min_km for ref in pace_matches), 3),
            hr_difference_bpm=_round(current_hr - ref_hr, 1),
        ))
    used = {ref.id: ref for ref in hr_matches + pace_matches}
    count = max(pace_block.reference_count, hr_block.reference_count)
    structures_known = session.structure == "continuous_recorded" and all(
        ref.structure == "continuous_recorded" for ref in used.values()
    )
    if used and not structures_known:
        limitations.append("reference_structure_unknown")
    if count == 0:
        level = "insufficient"
    elif count < SIMILAR_MIN_COMPARABLE_SAMPLE:
        level = "low"
    else:
        level = "strong" if structures_known else "moderate"
    dates = sorted(day for day in (_safe_date(ref.date) for ref in used.values()) if day is not None)
    return WIV3HistoricalComparison(
        status="available" if count else "insufficient",
        comparability=level,
        reference_count=len(used),
        period_start=dates[0].date().isoformat() if dates else None,
        period_end=dates[-1].date().isoformat() if dates else None,
        pace_at_comparable_hr=pace_block, hr_at_comparable_pace=hr_block,
        exclusion_reasons=exclusions, limitations=limitations, **base,
    )


# ── 5. Trend ─────────────────────────────────────────────────────────────────


def _trend_status(
    data: WorkoutIntelligenceV3Input, hr: Optional[float], hr_tolerance: float, margin: float,
) -> Tuple[str, Dict]:
    refs, _ = eligible_references(data)
    cohort = _hr_cohort(refs, hr, hr_tolerance)
    pace = data.session.avg_pace_min_km
    if pace is None or hr is None or _safe_date(data.session.date) is None:
        return "insufficient_data", {"reason": "current_pace_or_hr_unusable"}
    observations = sorted(
        [(_safe_date(ref.date), ref.avg_pace_min_km) for ref in cohort]
        + [(_safe_date(data.session.date), pace)],
        key=lambda row: row[0],
    )
    distinct_days = {row[0].date() for row in observations}
    if len(observations) < TREND_MIN_OBSERVATIONS or len(distinct_days) < len(observations):
        return "insufficient_data", {"reason": "too_few_independent_observations", "count": len(observations)}
    span = (observations[-1][0] - observations[0][0]).days
    if span < TREND_MIN_SPAN_DAYS:
        return "insufficient_data", {"reason": "observations_not_spread_in_time", "count": len(observations), "span": span}
    half = len(observations) // 2
    earlier = [row[1] for row in observations[:len(observations) - half]]
    later = [row[1] for row in observations[len(observations) - half:]]
    if len(earlier) < TREND_MIN_PER_HALF or len(later) < TREND_MIN_PER_HALF:
        return "insufficient_data", {"reason": "too_few_independent_observations", "count": len(observations)}
    earlier_median, later_median = median(earlier), median(later)
    change = (later_median - earlier_median) * 60
    info = {
        "count": len(observations), "span": span, "earlier": earlier_median,
        "later": later_median, "change": change, "cohort": cohort,
    }
    if abs(change) < margin:
        return "stable", info
    consistent = all(
        ((value - earlier_median) * 60 <= -margin) if change < 0 else ((value - earlier_median) * 60 >= margin)
        for value in later
    )
    info["consistent"] = consistent
    if not consistent:
        return "stable", info
    return ("probable_improvement" if change < 0 else "possible_decline"), info


def evaluate_trend(
    data: WorkoutIntelligenceV3Input,
    intensity: WIV3IntensityAssessment,
    comparison: WIV3HistoricalComparison,
) -> WIV3PerformanceTrend:
    criteria = {
        "hr_tolerance_bpm": HR_MATCH_TOLERANCE_BPM,
        "min_observations": float(TREND_MIN_OBSERVATIONS),
        "min_per_half": float(TREND_MIN_PER_HALF),
        "min_span_days": float(TREND_MIN_SPAN_DAYS),
        "pace_margin_sec_per_km": TREND_PACE_MARGIN_SEC_PER_KM,
        "duration_tolerance_pct": DURATION_MATCH_TOLERANCE_PCT,
    }
    observed = comparison.pace_at_comparable_hr.pace_difference_sec_per_km
    paths = ["historical_comparison.pace_at_comparable_hr", "history"]
    if comparison.status == "not_applicable":
        return WIV3PerformanceTrend(
            criteria=criteria, limitations=["structured_session_average_not_comparable"], source_paths=paths,
        )
    hr = intensity.hr_used_bpm
    status, info = _trend_status(data, hr, HR_MATCH_TOLERANCE_BPM, TREND_PACE_MARGIN_SEC_PER_KM)
    sensitivity = [
        WIV3TrendSensitivity(
            hr_tolerance_bpm=tolerance, margin_sec_per_km=margin,
            status=_trend_status(data, hr, tolerance, margin)[0],
        )
        for tolerance in TREND_SENSITIVITY_HR_TOLERANCES for margin in TREND_SENSITIVITY_MARGINS
    ]
    limitations = ["variation_is_not_physiological_proof", "terrain_weather_not_controlled"]
    if status == "insufficient_data":
        limitations.append(info.get("reason", "insufficient_comparability"))
        return WIV3PerformanceTrend(
            status=status, confidence="none", observation_count=info.get("count", 0),
            span_days=info.get("span"), observed_variation_sec_per_km=observed,
            criteria=criteria, sensitivity=sensitivity, limitations=limitations, source_paths=paths,
        )
    if info.get("consistent") is False:
        limitations.append("isolated_variation_not_confirmed")
    structures_known = data.session.structure == "continuous_recorded" and all(
        ref.structure == "continuous_recorded" for ref in info["cohort"]
    )
    if not structures_known:
        limitations.append("reference_structure_unknown")
    if len({row.status for row in sensitivity}) > 1:
        limitations.append("status_sensitive_to_criteria")
    confidence: Confidence = "medium" if structures_known and len({row.status for row in sensitivity}) == 1 else "low"
    return WIV3PerformanceTrend(
        status=status, confidence=confidence,
        observation_count=info["count"], span_days=info["span"],
        earlier_median_pace_min_km=_round(info["earlier"], 3),
        later_median_pace_min_km=_round(info["later"], 3),
        median_change_sec_per_km=_round(info["change"], 1),
        variation_confirmed=status in {"probable_improvement", "possible_decline"},
        observed_variation_sec_per_km=observed,
        criteria=criteria, sensitivity=sensitivity, limitations=limitations, source_paths=paths,
    )


# ── 6. Prescription ──────────────────────────────────────────────────────────


def assess_prescription(
    data: WorkoutIntelligenceV3Input, classification: WIV3SessionClassification,
) -> WIV3PrescriptionAssessment:
    context = data.prescription
    paths = ["training_prescription_snapshots"]
    if context.local_date is None:
        return WIV3PrescriptionAssessment(
            status="indeterminate", reasons=["session_local_date_unknown"], source_paths=paths,
        )
    try:
        session_day = date.fromisoformat(context.local_date)
    except ValueError:
        return WIV3PrescriptionAssessment(status="indeterminate", reasons=["session_local_date_invalid"], source_paths=paths)
    same_day = [snap for snap in context.snapshots if snap.planned_date == session_day]
    if not same_day:
        return WIV3PrescriptionAssessment(status="unavailable", reasons=["no_historical_prescription"], source_paths=paths)
    authoritative: List[PrescriptionSnapshot] = [
        snap for snap in same_day if is_snapshot_authoritative(snapshot=snap, reference_date=session_day)
    ]
    if not authoritative:
        return WIV3PrescriptionAssessment(
            status="unavailable", reasons=["snapshot_not_authoritative_for_date"], source_paths=paths,
        )
    if len(authoritative) > 1 or context.same_day_session_count != 1:
        return WIV3PrescriptionAssessment(
            status="indeterminate", reasons=["ambiguous_session_prescription_association"], source_paths=paths,
        )
    snap = authoritative[0]
    base = dict(
        prescription_id=snap.prescription_id, planned_date=snap.planned_date.isoformat(),
        prescribed_workout_type=snap.workout_type, prescribed_intensity_class=snap.intensity_class,
        prescribed_distance_km=snap.distance_km, prescribed_duration_minutes=snap.duration_minutes,
        observed_classification=classification.type, source_paths=paths + ["session_classification"],
    )
    expected = _EXPECTED_CLASSES.get(snap.workout_type)
    if expected is None:
        return WIV3PrescriptionAssessment(
            status="indeterminate", reasons=[f"prescription_type_not_assessed:{snap.workout_type}"], **base,
        )
    if classification.type == "unknown":
        return WIV3PrescriptionAssessment(status="indeterminate", reasons=["session_type_unknown"], **base)
    if classification.type in expected:
        return WIV3PrescriptionAssessment(status="consistent", reasons=["observed_type_matches_prescription"], **base)
    if _CONFIDENCE_ORDER[classification.confidence] >= _CONFIDENCE_ORDER["medium"]:
        return WIV3PrescriptionAssessment(status="deviation", reasons=["observed_type_differs_from_prescription"], **base)
    return WIV3PrescriptionAssessment(status="indeterminate", reasons=["observed_type_confidence_too_low"], **base)


# ── 7. Coach assessment (FR / EN / ES) ───────────────────────────────────────

_TEXT = {
    "en": {
        "diagnosis.intervals": "Interval session identified from {efforts} Garmin effort phases separated by recoveries.",
        "diagnosis.tempo_probable": "Probably a sustained hard session: recorded heart rate is at or above a personal threshold.",
        "diagnosis.easy_run_probable": "Probably an easy endurance run: average heart rate stayed below your personal LT1.",
        "diagnosis.steady_run_probable": "Probably a steady run: average heart rate sits between your personal LT1 and LT2.",
        "diagnosis.long_run_probable": "Probably a long run: {ratio}x your usual session duration.",
        "diagnosis.easy_run_relative": "This session looks like a relatively easy run compared with your usual efforts.",
        "diagnosis.steady_run_relative": "This continuous session looks relatively sustained compared with your usual efforts.",
        "evidence.relative_hr_low": "Your average heart rate ({hr} bpm) sits in the lower part of your {count} personal reference sessions (lower quartile {q1} bpm, median {med} bpm).",
        "evidence.relative_hr_high": "Your average heart rate ({hr} bpm) sits in the upper part of your {count} personal reference sessions (median {med} bpm, upper quartile {q3} bpm).",
        "limit.relative_not_physiological": "Without a reliable LT1 threshold, I cannot confirm a physiological intensity zone: this position is relative to your own history only.",
        "diagnosis.unknown": "No reliable session-type diagnosis from the available data.",
        "evidence.intensity": "Average heart rate ({hr} bpm) is {position} for your personal thresholds.",
        "evidence.pace_at_hr": "At comparable heart rate (±{tol} bpm), pace differs by {delta} s/km from {count} comparable sessions.",
        "evidence.hr_at_pace": "At comparable pace (±{tol} s/km), heart rate differs by {delta} bpm from {count} comparable sessions.",
        "evidence.trend": "Multi-session trend at comparable heart rate: {status} ({count} sessions over {span} days).",
        "evidence.prescription": "Prescription check: {status} (prescribed: {ptype}).",
        "position.below_LT1": "below LT1", "position.between_LT1_LT2": "between LT1 and LT2", "position.above_LT2": "above LT2",
        "trend.probable_improvement": "probable improvement", "trend.stable": "stable", "trend.possible_decline": "possible decline",
        "prescription.consistent": "consistent", "prescription.deviation": "deviation",
        "limit.no_thresholds": "Personal LT1/LT2 thresholds are not available: intensity cannot be placed in a personal zone.",
        "limit.average_hr": "Average heart rate is a session mean, not the time spent in each zone.",
        "limit.no_history": "Too few comparable earlier sessions (same environment, comparable heart rate or pace) to judge progress.",
        "limit.isolated": "The difference observed on this session is isolated and does not confirm a trend.",
        "limit.hr_unusable": "Heart rate is missing or inconsistent: no physiological interpretation.",
        "limit.structure_unknown": "The structure of earlier sessions is unknown: no strong conclusion.",
        "advice.thresholds": "A field or lab test would establish your personal thresholds and enable a reliable intensity diagnosis.",
        "advice.deviation": "This session departed from the prescribed type; keep prescribed easy days easy.",
    },
    "fr": {
        "diagnosis.intervals": "Séance fractionnée identifiée à partir de {efforts} phases d'effort Garmin séparées par des récupérations.",
        "diagnosis.tempo_probable": "Probablement une séance soutenue : la FC enregistrée atteint ou dépasse un seuil personnel.",
        "diagnosis.easy_run_probable": "Probablement un footing d'endurance : la FC moyenne est restée sous votre LT1 personnel.",
        "diagnosis.steady_run_probable": "Probablement une sortie à allure soutenue modérée : la FC moyenne se situe entre votre LT1 et votre LT2 personnels.",
        "diagnosis.long_run_probable": "Probablement une sortie longue : {ratio} fois la durée habituelle de vos séances.",
        "diagnosis.easy_run_relative": "Cette séance ressemble à un footing relativement facile par rapport à vos efforts habituels.",
        "diagnosis.steady_run_relative": "Cette séance continue ressemble à un effort relativement soutenu par rapport à vos efforts habituels.",
        "evidence.relative_hr_low": "Votre FC moyenne ({hr} bpm) se situe dans la partie basse de vos {count} séances de référence personnelles (quartile inférieur {q1} bpm, médiane {med} bpm).",
        "evidence.relative_hr_high": "Votre FC moyenne ({hr} bpm) se situe dans la partie haute de vos {count} séances de référence personnelles (médiane {med} bpm, quartile supérieur {q3} bpm).",
        "limit.relative_not_physiological": "Sans seuil LT1 fiable, je ne peux pas confirmer une zone d'intensité physiologique : cette position est relative à votre seul historique.",
        "diagnosis.unknown": "Pas de diagnostic fiable du type de séance avec les données disponibles.",
        "evidence.intensity": "La FC moyenne ({hr} bpm) se situe {position} selon vos seuils personnels.",
        "evidence.pace_at_hr": "À FC comparable (±{tol} bpm), l'allure diffère de {delta} s/km par rapport à {count} séances comparables.",
        "evidence.hr_at_pace": "À allure comparable (±{tol} s/km), la FC diffère de {delta} bpm par rapport à {count} séances comparables.",
        "evidence.trend": "Tendance sur plusieurs séances à FC comparable : {status} ({count} séances sur {span} jours).",
        "evidence.prescription": "Contrôle de la prescription : {status} (prévu : {ptype}).",
        "position.below_LT1": "sous LT1", "position.between_LT1_LT2": "entre LT1 et LT2", "position.above_LT2": "au-dessus de LT2",
        "trend.probable_improvement": "amélioration probable", "trend.stable": "stable", "trend.possible_decline": "baisse possible",
        "prescription.consistent": "conforme", "prescription.deviation": "écart",
        "limit.no_thresholds": "Seuils LT1/LT2 personnels indisponibles : l'intensité ne peut pas être placée dans une zone personnelle.",
        "limit.average_hr": "La FC moyenne est une moyenne de séance, pas le temps passé dans chaque zone.",
        "limit.no_history": "Trop peu de séances antérieures comparables (même environnement, FC ou allure comparable) pour juger une progression.",
        "limit.isolated": "L'écart observé sur cette séance est isolé et ne confirme pas de tendance.",
        "limit.hr_unusable": "FC absente ou incohérente : aucune interprétation physiologique.",
        "limit.structure_unknown": "La structure des séances antérieures est inconnue : pas de conclusion forte.",
        "advice.thresholds": "Un test de terrain ou de laboratoire permettrait d'établir vos seuils personnels et un diagnostic d'intensité fiable.",
        "advice.deviation": "Cette séance s'est écartée du type prescrit ; gardez faciles les journées prévues faciles.",
    },
    "es": {
        "diagnosis.intervals": "Sesión de intervalos identificada a partir de {efforts} fases de esfuerzo Garmin separadas por recuperaciones.",
        "diagnosis.tempo_probable": "Probablemente una sesión exigente sostenida: la FC registrada alcanza o supera un umbral personal.",
        "diagnosis.easy_run_probable": "Probablemente un rodaje suave de resistencia: la FC media se mantuvo por debajo de tu LT1 personal.",
        "diagnosis.steady_run_probable": "Probablemente un rodaje sostenido moderado: la FC media está entre tu LT1 y tu LT2 personales.",
        "diagnosis.long_run_probable": "Probablemente una tirada larga: {ratio} veces la duración habitual de tus sesiones.",
        "diagnosis.easy_run_relative": "Esta sesión parece un rodaje relativamente suave en comparación con tus esfuerzos habituales.",
        "diagnosis.steady_run_relative": "Esta sesión continua parece un esfuerzo relativamente sostenido en comparación con tus esfuerzos habituales.",
        "evidence.relative_hr_low": "Tu FC media ({hr} lpm) se sitúa en la parte baja de tus {count} sesiones de referencia personales (cuartil inferior {q1} lpm, mediana {med} lpm).",
        "evidence.relative_hr_high": "Tu FC media ({hr} lpm) se sitúa en la parte alta de tus {count} sesiones de referencia personales (mediana {med} lpm, cuartil superior {q3} lpm).",
        "limit.relative_not_physiological": "Sin un umbral LT1 fiable, no puedo confirmar una zona de intensidad fisiológica: esta posición es relativa solo a tu propio historial.",
        "diagnosis.unknown": "Sin diagnóstico fiable del tipo de sesión con los datos disponibles.",
        "evidence.intensity": "La FC media ({hr} lpm) está {position} según tus umbrales personales.",
        "evidence.pace_at_hr": "A FC comparable (±{tol} lpm), el ritmo difiere {delta} s/km respecto a {count} sesiones comparables.",
        "evidence.hr_at_pace": "A ritmo comparable (±{tol} s/km), la FC difiere {delta} lpm respecto a {count} sesiones comparables.",
        "evidence.trend": "Tendencia en varias sesiones a FC comparable: {status} ({count} sesiones en {span} días).",
        "evidence.prescription": "Control de la prescripción: {status} (prescrito: {ptype}).",
        "position.below_LT1": "por debajo de LT1", "position.between_LT1_LT2": "entre LT1 y LT2", "position.above_LT2": "por encima de LT2",
        "trend.probable_improvement": "mejora probable", "trend.stable": "estable", "trend.possible_decline": "posible descenso",
        "prescription.consistent": "conforme", "prescription.deviation": "desviación",
        "limit.no_thresholds": "Umbrales LT1/LT2 personales no disponibles: la intensidad no puede situarse en una zona personal.",
        "limit.average_hr": "La FC media es un promedio de la sesión, no el tiempo pasado en cada zona.",
        "limit.no_history": "Muy pocas sesiones anteriores comparables (mismo entorno, FC o ritmo comparable) para juzgar una progresión.",
        "limit.isolated": "La diferencia observada en esta sesión es aislada y no confirma una tendencia.",
        "limit.hr_unusable": "FC ausente o incoherente: ninguna interpretación fisiológica.",
        "limit.structure_unknown": "La estructura de las sesiones anteriores es desconocida: sin conclusión firme.",
        "advice.thresholds": "Una prueba de campo o de laboratorio permitiría establecer tus umbrales personales y un diagnóstico de intensidad fiable.",
        "advice.deviation": "Esta sesión se apartó del tipo prescrito; mantén suaves los días prescritos como suaves.",
    },
}


def _localized(text: str, language: str) -> str:
    return text.replace(".", ",") if language in {"fr", "es"} else text


def _fmt(value: float, language: str = "en") -> str:
    text = f"{value:+.1f}".removesuffix(".0") if value != 0 else "0"
    return _localized(text, language)


def _item(language: str, code: str, evidence: Dict[str, float], paths: List[str], **params) -> WIV3CoachItem:
    return WIV3CoachItem(code=code, text=_TEXT[language][code].format(**params), evidence=evidence, source_paths=paths)


def build_coach_assessment(
    language: str,
    intensity: WIV3IntensityAssessment,
    classification: WIV3SessionClassification,
    comparison: WIV3HistoricalComparison,
    trend: WIV3PerformanceTrend,
    prescription: WIV3PrescriptionAssessment,
) -> WIV3CoachAssessment:
    lang = _lang(language)
    text = _TEXT[lang]
    kind = classification.type
    relative_kind = (
        {"easy_run_probable": "easy_run_relative", "steady_run_probable": "steady_run_relative"}.get(kind)
        if classification.decision_tier == "individual_history" else None
    )
    if kind == "intervals":
        diagnosis = _item(lang, "diagnosis.intervals", dict(classification.evidence),
                          ["session_classification"], efforts=int(classification.evidence["effort_count"]))
    elif kind == "long_run_probable":
        ratio = classification.evidence["duration_ratio"]
        diagnosis = _item(lang, "diagnosis.long_run_probable", {"duration_ratio": ratio},
                          ["session_classification"], ratio=_localized(f"{ratio:g}", lang))
    elif relative_kind:
        diagnosis = _item(lang, f"diagnosis.{relative_kind}", dict(classification.evidence), ["session_classification"])
    else:
        diagnosis = _item(lang, f"diagnosis.{kind}", dict(classification.evidence), ["session_classification"])

    evidence: List[WIV3CoachItem] = []
    if relative_kind:
        rel = classification.relative_effort
        evidence.append(_item(
            lang, "evidence.relative_hr_low" if kind == "easy_run_probable" else "evidence.relative_hr_high",
            _relative_evidence(rel), ["session_classification.relative_effort"],
            hr=_localized(f"{rel.current_hr_bpm:g}", lang), count=rel.reference_count,
            q1=_localized(f"{rel.hr_q1_bpm:g}", lang), med=_localized(f"{rel.hr_median_bpm:g}", lang),
            q3=_localized(f"{rel.hr_q3_bpm:g}", lang),
        ))
    # Intensity-based diagnoses already state the position; only volume-based ones need it.
    if intensity.position != "unknown" and kind == "long_run_probable":
        evidence.append(_item(lang, "evidence.intensity", {"avg_hr_bpm": intensity.hr_used_bpm},
                              ["intensity_assessment"], hr=f"{intensity.hr_used_bpm:g}",
                              position=text[f"position.{intensity.position}"]))
    pace_block, hr_block = comparison.pace_at_comparable_hr, comparison.hr_at_comparable_pace
    strong_enough = comparison.comparability in {"strong", "moderate"}
    if strong_enough and pace_block.pace_difference_sec_per_km is not None and pace_block.reference_count >= SIMILAR_MIN_COMPARABLE_SAMPLE:
        evidence.append(_item(
            lang, "evidence.pace_at_hr",
            {"pace_difference_sec_per_km": pace_block.pace_difference_sec_per_km, "reference_count": float(pace_block.reference_count)},
            ["historical_comparison.pace_at_comparable_hr"],
            tol=f"{pace_block.hr_tolerance_bpm:g}", delta=_fmt(pace_block.pace_difference_sec_per_km, lang), count=pace_block.reference_count,
        ))
    elif strong_enough and hr_block.hr_difference_bpm is not None and hr_block.reference_count >= SIMILAR_MIN_COMPARABLE_SAMPLE:
        evidence.append(_item(
            lang, "evidence.hr_at_pace",
            {"hr_difference_bpm": hr_block.hr_difference_bpm, "reference_count": float(hr_block.reference_count)},
            ["historical_comparison.hr_at_comparable_pace"],
            tol=f"{hr_block.pace_tolerance_sec_per_km:g}", delta=_fmt(hr_block.hr_difference_bpm, lang), count=hr_block.reference_count,
        ))
    if trend.status != "insufficient_data" and trend.confidence == "medium":
        evidence.append(_item(
            lang, "evidence.trend",
            {"median_change_sec_per_km": trend.median_change_sec_per_km, "observation_count": float(trend.observation_count)},
            ["performance_trend"], status=text[f"trend.{trend.status}"], count=trend.observation_count, span=trend.span_days,
        ))
    if prescription.status in {"consistent", "deviation"} and len(evidence) < 3:
        evidence.append(_item(lang, "evidence.prescription", {}, ["prescription_assessment"],
                              status=text[f"prescription.{prescription.status}"], ptype=prescription.prescribed_workout_type))

    limitations: List[WIV3CoachItem] = []
    hr_unusable = any(code.startswith("hr_") for code in intensity.limitations)
    if hr_unusable:
        limitations.append(_item(lang, "limit.hr_unusable", {}, ["intensity_assessment.limitations"]))
    elif intensity.lt1 is None and intensity.lt2 is None:
        limitations.append(_item(lang, "limit.no_thresholds", {}, ["intensity_assessment.limitations"]))
    if relative_kind:
        limitations.append(_item(lang, "limit.relative_not_physiological", {}, ["session_classification.relative_effort"]))
    if intensity.position != "unknown":
        limitations.append(_item(lang, "limit.average_hr", {}, ["intensity_assessment.limitations"]))
    if comparison.status != "not_applicable" and comparison.comparability in {"insufficient", "low"}:
        limitations.append(_item(lang, "limit.no_history", {}, ["historical_comparison"]))
    elif "isolated_variation_not_confirmed" in trend.limitations:
        limitations.append(_item(lang, "limit.isolated", {}, ["performance_trend.limitations"]))
    elif "reference_structure_unknown" in comparison.limitations:
        limitations.append(_item(lang, "limit.structure_unknown", {}, ["historical_comparison.limitations"]))

    advice = None
    if prescription.status == "deviation" and prescription.prescribed_workout_type in {"easy", "recovery", "long_easy"}:
        advice = _item(lang, "advice.deviation", {}, ["prescription_assessment"])
    elif intensity.lt1 is None and intensity.lt2 is None and not hr_unusable and kind != "intervals":
        advice = _item(lang, "advice.thresholds", {}, ["intensity_assessment.rejected_thresholds", "profile"])
    return WIV3CoachAssessment(
        language=lang, diagnosis=diagnosis, evidence=evidence[:3], limitations=limitations, advice=advice,
    )


# ── Orchestration ────────────────────────────────────────────────────────────


def build_workout_intelligence_v3(data: WorkoutIntelligenceV3Input, language: str = "en") -> WorkoutIntelligenceV3:
    intensity = assess_intensity(data)
    classification = classify_session(data, intensity)
    comparison = compare_history(data, intensity)
    trend = evaluate_trend(data, intensity, comparison)
    prescription = assess_prescription(data, classification)
    data_used = [
        name for name, present in (
            ("session.avg_pace_min_km", data.session.avg_pace_min_km is not None),
            ("session.avg_hr", data.session.avg_hr is not None),
            ("session.max_hr", data.session.max_hr is not None),
            ("session.duration_minutes", data.session.duration_minutes is not None),
            ("session.activity_type", data.session.activity_type is not None),
            ("session.recorded_structure", data.session.structure != "unknown"),
            ("session.splits", data.session.has_splits),
            ("profile.fcmax", intensity.fcmax_bpm is not None),
            ("profile.observed_max_hr", intensity.observed_max_hr_bpm is not None),
            ("profile.lt1", intensity.lt1 is not None),
            ("profile.lt2", intensity.lt2 is not None),
            ("history", bool(data.history)),
            ("workout_analysis_v2.comparison.similar", data.v2_reference.available),
            ("prescription_snapshot", prescription.prescription_id is not None),
        ) if present
    ]
    return WorkoutIntelligenceV3(
        workout_id=data.session.id,
        analyzed_date=data.session.date,
        data_used=data_used,
        intensity_assessment=intensity,
        session_classification=classification,
        historical_comparison=comparison,
        performance_trend=trend,
        prescription_assessment=prescription,
        coach_assessment=build_coach_assessment(language, intensity, classification, comparison, trend, prescription),
    )
