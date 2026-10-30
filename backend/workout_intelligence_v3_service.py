"""C352 — read-only loader for Workout Intelligence V3.

Reads only: ``workouts``, ``garmin_activities`` (cached phases / precise type /
local start time / historical observed maxima) and
``training_prescription_snapshots``. No write, no Garmin or GCCLI call, no clock.
Workout Analysis V2 is reused unchanged as the
source of session structure, phases and the existing similar comparison.

Physiological wiring (C352 correction): the profile is resolved by
``resolve_physiological_profile`` from the same declared inputs as
``training_v2.runner_profile.build_runner_profile`` (``physiological_metrics``
/ ``user_profile``). The Training V2 runtime supplies neither a declared
FCmax nor physiological metrics (``week_plan_bridge`` passes
``physiological_metrics=None`` and only training preferences as
``user_profile``; ``performance_model`` runs with ``user_max_hr=None``), and
no RunIndex collection persists FCmax, LT1 or LT2. The endpoint therefore
passes nothing and V3 abstains; the observed Garmin maximum is computed from
strictly-prior activities and reported as a lower bound only.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from garmin.domain_adapter import garmin_local_start_time
from narrative_coach_v3_models import NarrativeCoachV3
from hybrid_coach_v2_c372 import ScopedV2Evidence
from training_v2.prescription_snapshot import PrescriptionSnapshot
from workout_analysis_v2 import (
    SIMILAR_HISTORY_WINDOW_DAYS,
    WorkoutAnalysisV2Response,
    build_workout_analysis_v2,
    workout_analysis_candidate_date_bounds,
)
from workout_analysis_v2_service import (
    _cached_activity_phases,
    _extract_garmin_external_id,
    _fetch_garmin_activity,
    _historical_garmin_sources,
    _is_garmin_workout,
    _reliable_activity_type,
    enrich_workout_from_garmin_activity,
)
from workout_intelligence_v3 import (
    build_workout_intelligence_v3,
    extract_workout_intelligence_input,
    resolve_physiological_profile,
)
from workout_intelligence_v3_models import (
    WIV3PrescriptionContext,
    WorkoutIntelligenceV3,
)

logger = logging.getLogger(__name__)

HISTORY_FETCH_LIMIT = 200  # same bound as the Workout Analysis V2 loader


async def _historical_snapshots(db: Any, user_id: str, local_date: Optional[str]) -> list[PrescriptionSnapshot]:
    if local_date is None or not hasattr(db, "training_prescription_snapshots"):
        return []
    try:
        docs = await db.training_prescription_snapshots.find(
            {"user_id": user_id, "planned_date": local_date}, {"_id": 0},
        ).to_list(length=10)
    except Exception:
        logger.warning("Prescription snapshots unavailable for user_id=%s", user_id)
        return []
    snapshots = []
    for doc in docs or []:
        try:
            snapshots.append(PrescriptionSnapshot(**doc))
        except Exception:
            continue
    return snapshots


async def load_scoped_workout_intelligence_v3(
    *, db: Any, user_id: str, workout_id: str, language: str,
    physiological_metrics: Optional[dict] = None,
    user_profile: Optional[dict] = None,
) -> Optional[tuple[dict[str, Any], Optional[WorkoutIntelligenceV3]]]:
    result = await _load_scoped_workout_intelligence_v3(
        db=db, user_id=user_id, workout_id=workout_id, language=language,
        physiological_metrics=physiological_metrics, user_profile=user_profile,
    )
    return result[:2] if result is not None else None


async def load_scoped_workout_intelligence_v3_with_narrative(
    *, db: Any, user_id: str, workout_id: str, language: str,
) -> Optional[tuple[dict[str, Any], Optional[WorkoutIntelligenceV3], NarrativeCoachV3]]:
    """Reuse the same scoped evidence load; narrative failures cannot hide facts."""
    result = await _load_scoped_workout_intelligence_v3(
        db=db, user_id=user_id, workout_id=workout_id, language=language,
        include_narrative=True,
    )
    return result[:3] if result is not None else None


async def load_scoped_workout_intelligence_v3_with_v2(
    *, db: Any, user_id: str, workout_id: str, language: str,
) -> Optional[tuple[dict[str, Any], Optional[WorkoutIntelligenceV3], Optional[ScopedV2Evidence]]]:
    """Internal hybrid context from the same scoped pass; no route or extra read."""
    result = await _load_scoped_workout_intelligence_v3(
        db=db, user_id=user_id, workout_id=workout_id, language=language,
    )
    if result is None:
        return None
    workout, intelligence, _, analysis = result
    evidence = ScopedV2Evidence(user_id, analysis) if analysis is not None else None
    return workout, intelligence, evidence


async def _load_scoped_workout_intelligence_v3(
    *, db: Any, user_id: str, workout_id: str, language: str,
    physiological_metrics: Optional[dict] = None,
    user_profile: Optional[dict] = None,
    include_narrative: bool = False,
) -> Optional[tuple[
    dict[str, Any], Optional[WorkoutIntelligenceV3], NarrativeCoachV3,
    Optional[WorkoutAnalysisV2Response],
]]:
    workout = await db.workouts.find_one({"id": workout_id, "user_id": user_id}, {"_id": 0})
    if workout is None:
        return None

    phases = None
    current_type = None
    local_date = None
    if _is_garmin_workout(workout):
        ext_id = _extract_garmin_external_id(workout)
        if ext_id:
            activity_doc = await _fetch_garmin_activity(db, user_id, ext_id)
            if activity_doc:
                workout = enrich_workout_from_garmin_activity(workout, activity_doc)
                phases = _cached_activity_phases(activity_doc)
                current_type = _reliable_activity_type(activity_doc)
                local_start = garmin_local_start_time(activity_doc)
                local_date = local_start[:10] if local_start and len(local_start) >= 10 else None

    v2_analysis = None
    try:
        lower_bound, upper_bound = workout_analysis_candidate_date_bounds(
            workout.get("date", ""), days=SIMILAR_HISTORY_WINDOW_DAYS,
        )
        historical_workouts = await (
            db.workouts.find(
                {
                    "user_id": user_id,
                    "type": workout.get("type"),
                    "date": {"$gte": lower_bound, "$lt": upper_bound},
                },
                {"_id": 0},
            )
            .sort("date", -1)
            .to_list(length=HISTORY_FETCH_LIMIT)
        )
        # Superset of the V2 similar selection: V2 only reads its own ids.
        historical_maxima: dict[str, int] = {}
        historical_phases, activity_types = await _historical_garmin_sources(
            db, user_id, historical_workouts, max_heart_rates=historical_maxima,
        )
        if current_type:
            activity_types[str(workout.get("id") or "")] = current_type
        v2_analysis = build_workout_analysis_v2(
            workout=workout,
            historical_workouts=historical_workouts,
            language=language,
            phases=phases,
            historical_phases=historical_phases,
            activity_types=activity_types,
        )
        same_day = sum(
            1 for item in historical_workouts
            if local_date is not None and str(item.get("date") or "")[:10] == local_date
            and str(item.get("id") or "") != str(workout.get("id") or "")
        )
        prescription = WIV3PrescriptionContext(
            local_date=local_date,
            snapshots=await _historical_snapshots(db, user_id, local_date),
            same_day_session_count=1 + same_day,
        )
        # V3-only copies: preserve both existing aliases and the V2 input unchanged.
        v3_history = [
            {**item, "max_heart_rate": historical_maxima[str(item.get("id"))]}
            if item.get("max_heart_rate") is None and item.get("max_hr") is None
            and str(item.get("id")) in historical_maxima else item
            for item in historical_workouts
        ]
        data = extract_workout_intelligence_input(
            workout,
            v3_history,
            v2_analysis=v2_analysis,
            activity_types=activity_types,
            historical_phases=historical_phases,
            profile=resolve_physiological_profile(
                physiological_metrics=physiological_metrics, user_profile=user_profile,
            ),
            prescription=prescription,
        )
        intelligence = build_workout_intelligence_v3(data, language)
    except Exception:
        logger.exception("Workout Intelligence V3 unavailable for workout_id=%s", workout_id)
        intelligence = None
    narrative = NarrativeCoachV3(language=language if language in {"fr", "en", "es"} else "en")
    if include_narrative and intelligence is not None:
        try:
            from narrative_coach_v3 import generate_narrative_coach_v3

            narrative = await generate_narrative_coach_v3(
                intelligence, language,
                phase_analysis=v2_analysis.phase_analysis if v2_analysis is not None else None,
                coach_language=v2_analysis.coach_language if v2_analysis is not None else None,
                v2_analysis=v2_analysis,
            )
        except Exception:
            logger.exception("Narrative coach unavailable; factual V3 preserved")
            try:
                from narrative_coach_v3 import deterministic_fallback

                narrative = deterministic_fallback(
                    intelligence, language,
                    phase_analysis=v2_analysis.phase_analysis if v2_analysis is not None else None,
                    coach_language=v2_analysis.coach_language if v2_analysis is not None else None,
                    v2_analysis=v2_analysis,
                )
            except Exception:
                logger.exception("Narrative fallback unavailable; factual V3 preserved")
    return workout, intelligence, narrative, v2_analysis
