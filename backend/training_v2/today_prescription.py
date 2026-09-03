"""C231 — Shared "today's FINAL prescription" resolver.

Problem
-------
``/training/today`` runs WeeklyPlan -> DailyAdaptation and presents the
*adapted* prescription to the athlete (e.g. a SHORTEN action turning a
planned 18 km long run into 12.6 km). Before this module, the prescription
snapshot frozen for adherence matching (see ``prescription_snapshot.py``)
only ever captured the RAW ``WeeklyPlan`` session — never the adapted one —
so an activity of 12.6 km would be compared against 18 km and wrongly
reported as "modified"/"missed" instead of ``completed_as_planned``.

Fix
---
This module is the SINGLE place where the post-DailyAdaptation prescription
for a given day is computed. Both ``/training/today`` and
``/training/v2/week`` MUST call it (never re-implement the readiness ->
DailyAdaptation pipeline independently) so that whichever endpoint is hit
first computes and freezes the exact same snapshot, and the other endpoint
never overwrites it with a different value.

Design rules
------------
- PURE with respect to persistence: the caller supplies already-fetched
  Garmin data (``domain_activities_90``, ``garmin_daily_metrics_docs``,
  ``garmin_connected``); no MongoDB/HTTP access happens here.
- DailyAdaptation itself is only ever computed for ONE specific day (the day
  whose ``planned_date == reference_date``) — this does NOT change the
  "DailyAdaptation is Today-only" rule; it only allows a second call site
  (the week endpoint) to obtain today's already-adapted result before a
  snapshot is frozen, instead of freezing the un-adapted one.
- None != 0: absence of Garmin connection/data yields ``readiness_decision``
  with an UNAVAILABLE band, which ``build_daily_adaptation`` maps to KEEP
  (never a fabricated reduction).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from .readiness_decision import ReadinessDecision, build_readiness_decision
from .daily_adaptation import DailyAdaptationResult, build_daily_adaptation
from .training_load import build_training_load
from .training_response import build_recent_training_response
from .workout_generator import WorkoutPrescription
from garmin.readiness_adapter import build_readiness_v2_from_garmin_data


@dataclass(frozen=True)
class TodayFinalPrescription:
    """Result of running WeeklyPlan -> DailyAdaptation for ONE day."""

    planned_prescription: WorkoutPrescription
    """The RAW (pre-adaptation) prescription from the reconciled WeeklyPlan."""

    adaptation_result: DailyAdaptationResult
    """Includes ``.adapted_workout`` — the FINAL prescription actually served."""

    readiness_decision: ReadinessDecision
    readiness_data_source: str
    """"garmin" when a live Garmin connection provided readiness data,
    "unavailable" otherwise."""


def resolve_today_final_prescription(
    *,
    planned_prescription: WorkoutPrescription,
    reference_date: date,
    domain_activities_90: List,
    garmin_daily_metrics_docs: List[dict],
    garmin_connected: bool,
) -> TodayFinalPrescription:
    """Run readiness + DailyAdaptation for ONE prescription and return the
    FINAL (post-adaptation) prescription actually served to the athlete.

    This is the SINGLE source of truth for "today's served prescription" —
    both ``/training/today`` and ``/training/v2/week`` (for the one session
    whose ``planned_date == reference_date``) must call this instead of
    freezing the raw ``WeeklyPlan`` session.
    """
    training_load = None
    readiness_result = None
    recent_response_for_readiness = None
    readiness_data_source = "unavailable"

    if garmin_connected:
        try:
            training_load = build_training_load(domain_activities_90, reference_date)
            readiness_result = build_readiness_v2_from_garmin_data(
                garmin_daily_metrics_docs,
                domain_activities_90,
                reference_date,
                load_snapshot=training_load,
                hrv_supported=None,
            )
            recent_response_for_readiness = build_recent_training_response(
                domain_activities_90, reference_date
            )
            readiness_data_source = "garmin"
        except Exception:
            # Fail-open on readiness only: an UNAVAILABLE band still yields a
            # deterministic (KEEP) DailyAdaptation result below — never a
            # fabricated reduction, never a crash of the whole endpoint.
            training_load = None
            readiness_result = None
            recent_response_for_readiness = None
            readiness_data_source = "unavailable"

    readiness_decision = build_readiness_decision(readiness_result)
    adaptation_result = build_daily_adaptation(
        workout=planned_prescription,
        readiness_decision=readiness_decision,
        training_load=training_load,
        recent_response=recent_response_for_readiness,
    )

    return TodayFinalPrescription(
        planned_prescription=planned_prescription,
        adaptation_result=adaptation_result,
        readiness_decision=readiness_decision,
        readiness_data_source=readiness_data_source,
    )


__all__ = ["TodayFinalPrescription", "resolve_today_final_prescription"]
