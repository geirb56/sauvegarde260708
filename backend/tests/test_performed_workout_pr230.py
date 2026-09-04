"""PR230 — Tests: PRESCRIBED vs PERFORMED (Garmin actual).

All tests are pure and deterministic: an explicit ``reference_date`` is always
supplied and no clock is consulted.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest
from pydantic import ValidationError

from garmin.domain_adapter import (
    garmin_local_start_time,
    mongo_garmin_to_observed_activity,
    mongo_garmin_to_observed_activities,
)
from training_v2.domain_activity import DomainActivity
from training_v2.performed_workout import (
    ADHERENCE_TOLERANCE_RATIO,
    MATCH_MAX_DEVIATION_RATIO,
    AdherenceStatus,
    MatchingStatus,
    ObservedActivity,
    PerformedWorkoutLedger,
    PrescribedWorkout,
    RC_AMBIGUOUS_MULTIPLE_CANDIDATES,
    RC_CANDIDATE_REJECTED_DEVIATION,
    RC_FUTURE_SESSION,
    RC_MATCHED_NO_COMPARABLE_DIMENSION,
    RC_NO_CANDIDATE,
    RC_RESOLVED_BY_PLANNED_START_TIME,
    RC_NO_PRESCRIPTION,
    RC_REST_NOT_MATCHABLE,
    RC_WINDOW_CLOSED,
    RC_WINDOW_OPEN,
    build_performed_workouts,
    to_observed_activity,
)

USER = "user-1"
OTHER_USER = "user-2"
REF = date(2026, 6, 10)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _prescription(
    *,
    prescription_id: str = "p1",
    user_id: str = USER,
    planned_date: date = REF,
    workout_type: str = "easy",
    distance_km=10.0,
    duration_min=None,
    pace=None,
    intensity_class="low",
    planned_start_time=None,
) -> PrescribedWorkout:
    return PrescribedWorkout(
        prescription_id=prescription_id,
        user_id=user_id,
        planned_date=planned_date,
        workout_type=workout_type,
        intensity_class=intensity_class,
        planned_distance_km=distance_km,
        planned_duration_min=duration_min,
        planned_pace_min_per_km=pace,
        planned_start_time=planned_start_time,
    )


def _activity(
    *,
    activity_id: str = "a1",
    user_id: str = USER,
    local_date: date = REF,
    start_time=datetime(2026, 6, 10, 7, 0, 0),
    activity_type: str = "running",
    distance_km=10.0,
    duration_min=55.0,
    source: str = "garmin",
) -> ObservedActivity:
    pace = None
    if distance_km and duration_min:
        pace = round(duration_min / distance_km, 2)
    return ObservedActivity(
        activity_id=activity_id,
        user_id=user_id,
        local_date=local_date,
        start_time=start_time,
        source=source,
        activity_type=activity_type,
        distance_km=distance_km,
        duration_min=duration_min,
        pace_min_per_km=pace,
    )


def _build(prescriptions, activities, reference_date=REF, user_id=USER):
    return build_performed_workouts(
        user_id=user_id,
        reference_date=reference_date,
        prescriptions=prescriptions,
        activities=activities,
    )


def _by_prescription(ledger: PerformedWorkoutLedger, prescription_id: str):
    return [e for e in ledger.entries if e.prescription_id == prescription_id][0]


# ---------------------------------------------------------------------------
# 1. Prescribed session + compatible Garmin run → matched
# ---------------------------------------------------------------------------


def test_planned_session_with_compatible_run_is_matched():
    ledger = _build([_prescription()], [_activity()])

    row = _by_prescription(ledger, "p1")
    assert row.matching_status is MatchingStatus.MATCHED
    assert row.adherence_status is AdherenceStatus.COMPLETED_AS_PLANNED
    assert row.activity_id == "a1"
    assert row.actual_distance_km == 10.0
    assert row.comparison_dimensions == ("distance",)
    assert ledger.matched_count == 1
    assert ledger.unmatched_actual_count == 0


def test_matched_row_keeps_raw_deltas():
    prescription = _prescription(distance_km=10.0, duration_min=60.0, pace=6.0)
    activity = _activity(distance_km=10.5, duration_min=63.0)

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert row.distance_delta_km == pytest.approx(0.5)
    assert row.duration_delta_min == pytest.approx(3.0)
    assert row.pace_delta_min_per_km == pytest.approx(0.0)
    assert row.planned_pace_min_per_km == 6.0
    assert row.actual_pace_min_per_km == 6.0


# ---------------------------------------------------------------------------
# 2. Prescribed session with no activity after window end → missed
# ---------------------------------------------------------------------------


def test_no_activity_after_window_end_is_missed():
    prescription = _prescription(planned_date=date(2026, 6, 5))

    ledger = _build([prescription], [], reference_date=REF)
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.MISSED
    assert row.adherence_status is AdherenceStatus.MISSED
    assert RC_WINDOW_CLOSED in row.reason_codes
    assert RC_NO_CANDIDATE in row.reason_codes


def test_no_activity_on_planned_day_itself_is_still_planned():
    """The window is not closed yet on the planned day → never missed."""
    ledger = _build([_prescription(planned_date=REF)], [], reference_date=REF)
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.PLANNED
    assert row.adherence_status is AdherenceStatus.PENDING
    assert RC_WINDOW_OPEN in row.reason_codes


# ---------------------------------------------------------------------------
# 3. Future session without activity → planned
# ---------------------------------------------------------------------------


def test_future_session_is_planned_never_missed_never_completed():
    prescription = _prescription(planned_date=date(2026, 6, 20))

    row = _by_prescription(_build([prescription], []), "p1")

    assert row.matching_status is MatchingStatus.PLANNED
    assert row.adherence_status is AdherenceStatus.PENDING
    assert RC_FUTURE_SESSION in row.reason_codes
    assert row.matching_status is not MatchingStatus.MISSED


def test_rest_day_is_never_missed():
    prescription = _prescription(
        planned_date=date(2026, 6, 1), workout_type="rest", distance_km=None
    )

    row = _by_prescription(_build([prescription], []), "p1")

    assert row.matching_status is MatchingStatus.PLANNED
    assert row.adherence_status is AdherenceStatus.NOT_APPLICABLE
    assert row.reason_codes == (RC_REST_NOT_MATCHABLE,)


# ---------------------------------------------------------------------------
# 4. Extra activity without prescription → unmatched_actual
# ---------------------------------------------------------------------------


def test_extra_activity_without_prescription_is_unmatched_actual():
    ledger = _build([], [_activity(activity_id="a9")])

    assert ledger.unmatched_actual_count == 1
    row = ledger.entries[0]
    assert row.matching_status is MatchingStatus.UNMATCHED_ACTUAL
    assert row.adherence_status is AdherenceStatus.UNMATCHED_ACTUAL
    assert row.prescription_id is None
    assert row.activity_id == "a9"
    assert row.reason_codes == (RC_NO_PRESCRIPTION,)


def test_second_run_same_day_stays_visible_as_unmatched_actual():
    ledger = _build(
        [_prescription()],
        [
            _activity(activity_id="a1", distance_km=10.0, duration_min=55.0),
            _activity(
                activity_id="a2",
                distance_km=5.0,
                duration_min=30.0,
                start_time=datetime(2026, 6, 10, 18, 0, 0),
            ),
        ],
    )

    assert ledger.matched_count == 1
    assert ledger.unmatched_actual_count == 1
    assert _by_prescription(ledger, "p1").activity_id == "a1"


# ---------------------------------------------------------------------------
# 5. Non-running activity is never matched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("activity_type", ["cycling", "swimming", "strength_training", None])
def test_non_running_activity_is_never_matched(activity_type):
    ledger = _build([_prescription()], [_activity(activity_type=activity_type)])

    row = _by_prescription(ledger, "p1")
    assert row.matching_status is MatchingStatus.PLANNED
    assert row.activity_id is None
    assert ledger.matched_count == 0
    # Out of scope for the running plan: not reported as unmatched_actual either.
    assert ledger.unmatched_actual_count == 0


@pytest.mark.parametrize("activity_type", ["running", "trail_running", "treadmill_running"])
def test_all_running_types_are_matchable(activity_type):
    ledger = _build([_prescription()], [_activity(activity_type=activity_type)])
    assert _by_prescription(ledger, "p1").matching_status is MatchingStatus.MATCHED


# ---------------------------------------------------------------------------
# 6. Two runs the same day → deterministic choice, or ambiguous / no match
# ---------------------------------------------------------------------------


def test_two_runs_same_day_deterministic_best_match():
    prescription = _prescription(distance_km=10.0)
    far = _activity(activity_id="a_far", distance_km=13.0, duration_min=70.0)
    close = _activity(
        activity_id="a_close",
        distance_km=10.2,
        duration_min=56.0,
        start_time=datetime(2026, 6, 10, 19, 0, 0),
    )

    first = _build([prescription], [far, close])
    second = _build([prescription], [close, far])

    assert _by_prescription(first, "p1").activity_id == "a_close"
    assert _by_prescription(second, "p1").activity_id == "a_close"


def test_two_strictly_equivalent_runs_are_ambiguous_and_not_matched():
    prescription = _prescription(distance_km=10.0)
    a = _activity(activity_id="a1", start_time=None)
    b = _activity(activity_id="a2", start_time=None)

    ledger = _build([prescription], [a, b])
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.AMBIGUOUS
    assert row.adherence_status is AdherenceStatus.AMBIGUOUS
    assert row.candidate_activity_ids == ("a1", "a2")
    assert RC_AMBIGUOUS_MULTIPLE_CANDIDATES in row.reason_codes
    assert row.activity_id is None
    assert ledger.matched_count == 0
    assert ledger.unmatched_actual_count == 2


def test_one_activity_is_attributed_to_at_most_one_prescription():
    p1 = _prescription(prescription_id="p1", distance_km=10.0)
    p2 = _prescription(prescription_id="p2", distance_km=10.0)

    ledger = _build([p1, p2], [_activity(activity_id="a1")], reference_date=REF)

    assert _by_prescription(ledger, "p1").activity_id == "a1"
    assert _by_prescription(ledger, "p2").activity_id is None
    assert ledger.matched_count == 1


# ---------------------------------------------------------------------------
# 7. Wrong date / timezone → no false match
# ---------------------------------------------------------------------------


def test_activity_on_another_day_does_not_match():
    prescription = _prescription(planned_date=date(2026, 6, 5))
    activity = _activity(
        local_date=date(2026, 6, 6), start_time=datetime(2026, 6, 6, 7, 0, 0)
    )

    ledger = _build([prescription], [activity], reference_date=REF)
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.MISSED
    assert ledger.unmatched_actual_count == 1


def test_local_date_drives_matching_not_utc_string():
    """A late-evening local run stays on its local calendar day."""
    domain = DomainActivity(
        activity_type="running",
        start_time="2026-06-10 23:30:00",
        distance_m=10000.0,
        duration_s=3300.0,
        source="garmin",
        source_activity_id="a-late",
    )
    observed = to_observed_activity(
        domain, user_id=USER, local_start_time="2026-06-10 23:30:00"
    )

    assert observed is not None
    assert observed.local_date == date(2026, 6, 10)

    ledger = _build([_prescription(planned_date=date(2026, 6, 10))], [observed])
    assert _by_prescription(ledger, "p1").matching_status is MatchingStatus.MATCHED


# ---------------------------------------------------------------------------
# 8. / 9. Distance and duration deviations
# ---------------------------------------------------------------------------


def test_moderate_distance_deviation_is_completed_modified():
    prescription = _prescription(distance_km=10.0)
    activity = _activity(distance_km=13.0, duration_min=70.0)  # +30 %

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert row.matching_status is MatchingStatus.MATCHED
    assert row.adherence_status is AdherenceStatus.COMPLETED_MODIFIED
    assert row.deviation_ratio == pytest.approx(0.30)
    assert row.distance_delta_km == pytest.approx(3.0)


def test_extreme_distance_deviation_is_not_matched():
    prescription = _prescription(planned_date=date(2026, 6, 5), distance_km=20.0)
    activity = _activity(
        local_date=date(2026, 6, 5),
        start_time=datetime(2026, 6, 5, 7, 0, 0),
        distance_km=3.0,  # −85 % → beyond MATCH_MAX_DEVIATION_RATIO
        duration_min=18.0,
    )

    ledger = _build([prescription], [activity], reference_date=REF)
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.MISSED
    assert RC_CANDIDATE_REJECTED_DEVIATION in row.reason_codes
    assert ledger.unmatched_actual_count == 1


def test_duration_basis_used_when_no_planned_distance():
    prescription = _prescription(distance_km=None, duration_min=60.0)
    activity = _activity(distance_km=None, duration_min=63.0)

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert row.comparison_dimensions == ("duration",)
    assert row.adherence_status is AdherenceStatus.COMPLETED_AS_PLANNED
    assert row.duration_delta_min == pytest.approx(3.0)


def test_extreme_duration_deviation_is_not_matched():
    prescription = _prescription(
        planned_date=date(2026, 6, 5), distance_km=None, duration_min=90.0
    )
    activity = _activity(
        local_date=date(2026, 6, 5),
        start_time=datetime(2026, 6, 5, 7, 0, 0),
        distance_km=None,
        duration_min=15.0,
    )

    ledger = _build([prescription], [activity], reference_date=REF)
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.MISSED
    assert RC_CANDIDATE_REJECTED_DEVIATION in row.reason_codes


def test_no_comparable_dimension_matches_as_unverified():
    prescription = _prescription(distance_km=None, duration_min=None)
    activity = _activity(distance_km=None, duration_min=None)

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert row.matching_status is MatchingStatus.MATCHED
    assert row.adherence_status is AdherenceStatus.COMPLETED_UNVERIFIED
    assert row.comparison_dimensions == ()
    assert row.deviation_ratio is None
    assert RC_MATCHED_NO_COMPARABLE_DIMENSION in row.reason_codes


def test_tolerance_and_guard_boundaries_are_explicit():
    assert ADHERENCE_TOLERANCE_RATIO == 0.10
    assert MATCH_MAX_DEVIATION_RATIO == 0.50


# ---------------------------------------------------------------------------
# 10. The original prescription is never mutated
# ---------------------------------------------------------------------------


def test_prescription_is_never_mutated():
    prescription = _prescription(distance_km=10.0)
    snapshot = prescription.model_dump()

    _build([prescription], [_activity(distance_km=13.0, duration_min=70.0)])

    assert prescription.model_dump() == snapshot


def test_prescription_model_is_frozen():
    prescription = _prescription()
    with pytest.raises(Exception):
        prescription.planned_distance_km = 42.0  # type: ignore[misc]


def test_performed_workout_keeps_planned_values_untouched():
    prescription = _prescription(distance_km=10.0, duration_min=60.0)
    row = _by_prescription(
        _build([prescription], [_activity(distance_km=12.0, duration_min=72.0)]), "p1"
    )

    assert row.planned_distance_km == 10.0
    assert row.planned_duration_min == 60.0
    assert row.actual_distance_km == 12.0
    assert row.actual_duration_min == 72.0


# ---------------------------------------------------------------------------
# 11. No None → 0 substitution
# ---------------------------------------------------------------------------


def test_missing_values_stay_none_never_zero():
    prescription = _prescription(planned_date=date(2026, 6, 5), distance_km=10.0)

    row = _by_prescription(_build([prescription], [], reference_date=REF), "p1")

    assert row.actual_distance_km is None
    assert row.actual_duration_min is None
    assert row.actual_pace_min_per_km is None
    assert row.actual_start_time is None
    assert row.distance_delta_km is None
    assert row.duration_delta_min is None
    assert row.pace_delta_min_per_km is None


def test_unmatched_actual_row_has_no_fabricated_planned_values():
    row = _build([], [_activity()]).entries[0]

    assert row.planned_distance_km is None
    assert row.planned_duration_min is None
    assert row.planned_date is None
    assert row.planned_workout_type is None
    assert row.distance_delta_km is None


def test_zero_distance_activity_is_not_turned_into_zero_value():
    domain = DomainActivity(
        activity_type="running",
        start_time="2026-06-10T07:00:00",
        distance_m=0,
        duration_s=1800,
        source="garmin",
        source_activity_id="a-zero",
    )
    observed = to_observed_activity(
        domain, user_id=USER, local_start_time="2026-06-10T07:00:00"
    )

    assert observed is not None
    assert observed.distance_km is None
    assert observed.duration_min == pytest.approx(30.0)
    assert observed.pace_min_per_km is None


# ---------------------------------------------------------------------------
# 12. Multi-user isolation
# ---------------------------------------------------------------------------


def test_other_user_activity_never_matches():
    ledger = _build([_prescription()], [_activity(user_id=OTHER_USER)])

    assert _by_prescription(ledger, "p1").matching_status is MatchingStatus.PLANNED
    assert ledger.unmatched_actual_count == 0


def test_other_user_prescription_is_ignored():
    ledger = _build(
        [_prescription(prescription_id="p_other", user_id=OTHER_USER)],
        [_activity()],
    )

    assert all(e.prescription_id != "p_other" for e in ledger.entries)
    assert all(e.user_id == USER for e in ledger.entries)


# ---------------------------------------------------------------------------
# 13. No-lookahead
# ---------------------------------------------------------------------------


def test_future_activity_cannot_change_a_historical_prescription():
    prescription = _prescription(planned_date=date(2026, 6, 12), distance_km=10.0)
    activity = _activity(
        local_date=date(2026, 6, 12), start_time=datetime(2026, 6, 12, 7, 0, 0)
    )

    # As of 2026-06-10, the 2026-06-12 run is not known yet.
    ledger = _build([prescription], [activity], reference_date=REF)
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.PLANNED
    assert row.activity_id is None
    assert ledger.unmatched_actual_count == 0

    # As of 2026-06-12 it is known and matches.
    later = _build([prescription], [activity], reference_date=date(2026, 6, 12))
    assert _by_prescription(later, "p1").matching_status is MatchingStatus.MATCHED


def test_historical_state_is_stable_when_replayed():
    """Replaying an old reference_date with newer data yields the old state."""
    prescription = _prescription(planned_date=date(2026, 6, 3), distance_km=10.0)
    later_activity = _activity(
        activity_id="a-late",
        local_date=date(2026, 6, 9),
        start_time=datetime(2026, 6, 9, 7, 0, 0),
    )

    replay = _build([prescription], [later_activity], reference_date=date(2026, 6, 4))
    assert _by_prescription(replay, "p1").matching_status is MatchingStatus.MISSED
    assert replay.unmatched_actual_count == 0


# ---------------------------------------------------------------------------
# 14. Determinism
# ---------------------------------------------------------------------------


def test_result_is_deterministic_across_runs_and_input_order():
    prescriptions = [
        _prescription(prescription_id="p2", planned_date=date(2026, 6, 9), distance_km=8.0),
        _prescription(prescription_id="p1", planned_date=date(2026, 6, 8), distance_km=12.0),
    ]
    activities = [
        _activity(
            activity_id="a2",
            local_date=date(2026, 6, 9),
            start_time=datetime(2026, 6, 9, 7, 0, 0),
            distance_km=8.1,
            duration_min=45.0,
        ),
        _activity(
            activity_id="a1",
            local_date=date(2026, 6, 8),
            start_time=datetime(2026, 6, 8, 7, 0, 0),
            distance_km=12.2,
            duration_min=68.0,
        ),
    ]

    first = _build(prescriptions, activities)
    second = _build(list(reversed(prescriptions)), list(reversed(activities)))
    third = _build(prescriptions, activities)

    assert first.model_dump() == second.model_dump() == third.model_dump()
    assert [e.prescription_id for e in first.entries] == ["p1", "p2"]


# ---------------------------------------------------------------------------
# 15. No legacy consumer can auto-mark a session completed
# ---------------------------------------------------------------------------


def test_engine_never_emits_a_completed_matching_status():
    assert {s.value for s in MatchingStatus} == {
        "planned",
        "matched",
        "missed",
        "ambiguous",
        "unmatched_actual",
        # C231 — item 3: emitted only for historical days that were never
        # frozen/served; still never "completed".
        "prescription_unavailable",
    }
    assert "completed" not in {s.value for s in MatchingStatus}


def test_past_session_without_evidence_is_never_completed():
    past = [
        _prescription(prescription_id=f"p{i}", planned_date=date(2026, 6, i), distance_km=10.0)
        for i in range(1, 6)
    ]

    ledger = _build(past, [], reference_date=REF)

    assert ledger.matched_count == 0
    assert ledger.missed_count == 5
    for row in ledger.entries:
        assert row.adherence_status is not AdherenceStatus.COMPLETED_AS_PLANNED
        assert row.adherence_status is not AdherenceStatus.COMPLETED_MODIFIED
        assert row.activity_id is None


def test_engine_module_has_no_io_dependencies():
    import training_v2.performed_workout as module

    source = module.__doc__ or ""
    assert "db.workouts" in source  # documented as NOT a source of truth

    import inspect

    code = inspect.getsource(module)
    if module.__doc__:
        code = code.replace(module.__doc__, "")
    for forbidden in (
        "datetime.now(",
        "date.today(",
        "pymongo",
        "motor",
        "requests.",
        "random.",
    ):
        assert forbidden not in code, forbidden


# ---------------------------------------------------------------------------
# Garmin → ObservedActivity conversion boundary
# ---------------------------------------------------------------------------


def test_to_observed_activity_from_domain_activity():
    domain = DomainActivity(
        activity_type="running",
        start_time="2026-06-10T05:15:00",  # GMT-first value — NOT used for the day
        distance_m=10500.0,
        duration_s=3300.0,
        source="garmin",
        source_activity_id="123456",
    )

    observed = to_observed_activity(
        domain, user_id=USER, local_start_time="2026-06-10T07:15:00"
    )

    assert observed is not None
    assert observed.activity_id == "123456"
    assert observed.user_id == USER
    assert observed.source == "garmin"
    assert observed.local_date == date(2026, 6, 10)
    assert observed.start_time == datetime(2026, 6, 10, 7, 15, 0)
    assert observed.distance_km == pytest.approx(10.5)
    assert observed.duration_min == pytest.approx(55.0)
    assert observed.pace_min_per_km == pytest.approx(5.24, abs=0.01)
    assert observed.is_running is True


def test_to_observed_activity_rejects_activities_without_local_time_or_id():
    no_local = DomainActivity(
        activity_type="running", source="garmin", source_activity_id="1"
    )
    no_id = DomainActivity(
        activity_type="running", source="garmin", start_time="2026-06-10T07:00:00"
    )

    assert to_observed_activity(no_local, user_id=USER, local_start_time=None) is None
    assert (
        to_observed_activity(no_id, user_id=USER, local_start_time="2026-06-10T07:00:00")
        is None
    )


# ===========================================================================
# C230 CORRECTIONS
# ===========================================================================

# ---------------------------------------------------------------------------
# C230 #1 — real Garmin local date (startTimeLocal), full Mongo chain
# ---------------------------------------------------------------------------


def _mongo_doc(
    *,
    activity_id="9001",
    start_time_local="2026-06-10 00:30:00",
    start_time_gmt="2026-06-09 22:30:00",
    distance_m=10000.0,
    duration_s=3300.0,
    activity_type="running",
    source="garmin",
    user_id=USER,
):
    """A realistic ``garmin_activities`` document.

    Reproduces the real asymmetry: the ``garmin_activity`` sub-document is
    GMT-first while the top-level ``start_time`` is local-first.
    """
    doc = {
        "activity_id": activity_id,
        "user_id": user_id,
        "source": source,
        "activity_type": activity_type,
        "start_time": start_time_local,  # ingestion contract: local first
        "distance": distance_m,
        "duration": duration_s,
        "garmin_activity": {
            "activity_id": activity_id,
            "activity_type": activity_type,
            "start_time": start_time_gmt,  # model convention: GMT first
            "start_time_local": start_time_local,
            "distance_m": distance_m,
            "duration_s": duration_s,
        },
    }
    return doc


def test_mongo_chain_matches_on_real_local_day_not_gmt_day():
    """startTimeLocal 2026-06-10 00:30 / GMT 2026-06-09 22:30 → matched on 06-10."""
    doc = _mongo_doc()

    observed = mongo_garmin_to_observed_activity(doc, user_id=USER)

    assert observed is not None
    assert observed.local_date == date(2026, 6, 10)
    assert observed.start_time == datetime(2026, 6, 10, 0, 30, 0)

    prescription = _prescription(planned_date=date(2026, 6, 10), distance_km=10.0)
    ledger = _build([prescription], [observed], reference_date=date(2026, 6, 11))

    row = _by_prescription(ledger, "p1")
    assert row.matching_status is MatchingStatus.MATCHED
    assert row.activity_id == "9001"
    assert ledger.unmatched_actual_count == 0


def test_mongo_chain_does_not_match_the_gmt_day():
    """The GMT day (06-09) must NOT receive the activity."""
    doc = _mongo_doc()
    observed = mongo_garmin_to_observed_activity(doc, user_id=USER)

    prescription = _prescription(planned_date=date(2026, 6, 9), distance_km=10.0)
    ledger = _build([prescription], [observed], reference_date=date(2026, 6, 11))

    row = _by_prescription(ledger, "p1")
    assert row.matching_status is MatchingStatus.MISSED
    assert ledger.unmatched_actual_count == 1


def test_domain_start_time_alone_would_have_picked_the_wrong_day():
    """Regression guard: the GMT sub-document value is a different calendar day."""
    from garmin.domain_adapter import mongo_garmin_to_domain

    doc = _mongo_doc()
    domain = mongo_garmin_to_domain(doc)

    # DomainActivity.start_time is the GMT-first value → previous day.
    assert str(domain.start_time).startswith("2026-06-09")
    # The dedicated adapter resolves the REAL local day.
    assert garmin_local_start_time(doc) == "2026-06-10 00:30:00"


def test_garmin_local_start_time_prefers_explicit_local_field():
    doc = _mongo_doc()
    doc["start_time"] = "2026-06-09 22:30:00"  # degraded top-level
    assert garmin_local_start_time(doc) == "2026-06-10 00:30:00"


def test_garmin_local_start_time_refuses_gmt_only_document():
    """No local evidence at all → no fabricated local day."""
    doc = _mongo_doc()
    doc["garmin_activity"].pop("start_time_local")
    doc["start_time"] = doc["garmin_activity"]["start_time"]  # GMT fallback

    assert garmin_local_start_time(doc) is None
    assert mongo_garmin_to_observed_activity(doc, user_id=USER) is None


def test_garmin_local_start_time_accepts_raw_start_time_local_key():
    doc = _mongo_doc()
    doc["garmin_activity"].pop("start_time_local")
    doc["startTimeLocal"] = "2026-06-10 00:30:00"
    doc["start_time"] = "2026-06-09 22:30:00"

    assert garmin_local_start_time(doc) == "2026-06-10 00:30:00"


def test_garmin_activity_model_exposes_start_time_local():
    """The Garmin normalisation layer really carries startTimeLocal."""
    from garmin.data_layer import GarminActivity

    normalized = GarminActivity.from_summary(
        {
            "activityId": 42,
            "activityType": {"typeKey": "running"},
            "summaryDTO": {
                "startTimeGMT": "2026-06-09 22:30:00",
                "startTimeLocal": "2026-06-10 00:30:00",
                "distance": 10000.0,
                "duration": 3300.0,
            },
        }
    )

    assert normalized.start_time == "2026-06-09 22:30:00"  # GMT-first convention
    assert normalized.start_time_local == "2026-06-10 00:30:00"


def test_mongo_garmin_to_observed_activities_skips_unusable_documents():
    good = _mongo_doc(activity_id="ok")
    bad_source = _mongo_doc(activity_id="bad", source="workout")
    bad_source.pop("garmin_activity")

    result = mongo_garmin_to_observed_activities([good, bad_source, None], user_id=USER)

    assert [a.activity_id for a in result] == ["ok"]


# ---------------------------------------------------------------------------
# C230 #2 — ambiguity is never missed, no arbitrary clock tiebreak
# ---------------------------------------------------------------------------


def test_two_identical_runs_morning_and_evening_are_ambiguous():
    """10 km at 07:00 and 10 km at 18:00, prescription 10 km without a time."""
    prescription = _prescription(distance_km=10.0)
    morning = _activity(
        activity_id="a_morning",
        distance_km=10.0,
        duration_min=55.0,
        start_time=datetime(2026, 6, 10, 7, 0, 0),
    )
    evening = _activity(
        activity_id="a_evening",
        distance_km=10.0,
        duration_min=55.0,
        start_time=datetime(2026, 6, 10, 18, 0, 0),
    )

    ledger = _build([prescription], [morning, evening])
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.AMBIGUOUS
    assert row.activity_id is None
    assert row.candidate_activity_ids == ("a_evening", "a_morning")
    assert ledger.ambiguous_count == 1
    assert ledger.unmatched_actual_count == 2


def test_ambiguity_stays_ambiguous_after_window_closes():
    prescription = _prescription(planned_date=date(2026, 6, 3), distance_km=10.0)
    common = dict(
        local_date=date(2026, 6, 3), distance_km=10.0, duration_min=55.0
    )
    morning = _activity(
        activity_id="a_morning", start_time=datetime(2026, 6, 3, 7, 0, 0), **common
    )
    evening = _activity(
        activity_id="a_evening", start_time=datetime(2026, 6, 3, 18, 0, 0), **common
    )

    ledger = _build([prescription], [morning, evening], reference_date=REF)
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.AMBIGUOUS
    assert row.matching_status is not MatchingStatus.MISSED
    assert row.adherence_status is AdherenceStatus.AMBIGUOUS
    assert ledger.missed_count == 0
    assert RC_WINDOW_CLOSED in row.reason_codes


def test_ambiguous_prescription_is_never_matched_missed_or_completed():
    prescription = _prescription(planned_date=date(2026, 6, 3), distance_km=10.0)
    a = _activity(
        activity_id="a1",
        local_date=date(2026, 6, 3),
        start_time=datetime(2026, 6, 3, 7, 0, 0),
    )
    b = _activity(
        activity_id="a2",
        local_date=date(2026, 6, 3),
        start_time=datetime(2026, 6, 3, 20, 0, 0),
    )

    row = _by_prescription(_build([prescription], [a, b], reference_date=REF), "p1")

    assert row.matching_status not in (MatchingStatus.MATCHED, MatchingStatus.MISSED)
    assert row.adherence_status not in (
        AdherenceStatus.COMPLETED_AS_PLANNED,
        AdherenceStatus.COMPLETED_MODIFIED,
        AdherenceStatus.COMPLETED_UNVERIFIED,
        AdherenceStatus.MISSED,
    )


def test_clearly_better_candidate_on_prescribed_dimensions_is_matched():
    prescription = _prescription(distance_km=10.0, duration_min=55.0)
    good = _activity(
        activity_id="a_good",
        distance_km=10.1,
        duration_min=56.0,
        start_time=datetime(2026, 6, 10, 18, 0, 0),
    )
    poor = _activity(
        activity_id="a_poor",
        distance_km=7.0,
        duration_min=40.0,
        start_time=datetime(2026, 6, 10, 7, 0, 0),
    )

    ledger = _build([prescription], [poor, good])
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.MATCHED
    assert row.activity_id == "a_good"  # later run, but better evidence


def test_prescribed_start_time_is_a_legitimate_tiebreaker():
    prescription = _prescription(
        distance_km=10.0, planned_start_time=time(18, 0)
    )
    morning = _activity(
        activity_id="a_morning", start_time=datetime(2026, 6, 10, 7, 0, 0)
    )
    evening = _activity(
        activity_id="a_evening", start_time=datetime(2026, 6, 10, 18, 5, 0)
    )

    row = _by_prescription(_build([prescription], [morning, evening]), "p1")

    assert row.matching_status is MatchingStatus.MATCHED
    assert row.activity_id == "a_evening"
    assert RC_RESOLVED_BY_PLANNED_START_TIME in row.reason_codes


def test_without_prescribed_start_time_earlier_run_is_not_preferred():
    """The old (deviation, start_time) ranking would have picked the morning run."""
    prescription = _prescription(distance_km=10.0)
    morning = _activity(
        activity_id="a_morning", start_time=datetime(2026, 6, 10, 6, 0, 0)
    )
    evening = _activity(
        activity_id="a_evening", start_time=datetime(2026, 6, 10, 19, 0, 0)
    )

    row = _by_prescription(_build([prescription], [morning, evening]), "p1")

    assert row.activity_id is None
    assert row.matching_status is MatchingStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# C230 #3 — multi-dimension adherence
# ---------------------------------------------------------------------------


def test_case_A_all_dimensions_within_tolerance_is_as_planned():
    prescription = _prescription(distance_km=10.0, duration_min=60.0)
    activity = _activity(distance_km=10.0, duration_min=60.0)

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert row.matching_status is MatchingStatus.MATCHED
    assert row.adherence_status is AdherenceStatus.COMPLETED_AS_PLANNED
    assert row.comparison_dimensions == ("distance", "duration")
    assert row.distance_deviation_ratio == pytest.approx(0.0)
    assert row.duration_deviation_ratio == pytest.approx(0.0)


def test_case_B_perfect_distance_but_long_duration_is_modified_not_as_planned():
    prescription = _prescription(distance_km=10.0, duration_min=60.0)
    activity = _activity(distance_km=10.0, duration_min=75.0)  # +25 %

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert row.matching_status is MatchingStatus.MATCHED
    assert row.adherence_status is AdherenceStatus.COMPLETED_MODIFIED
    assert row.distance_deviation_ratio == pytest.approx(0.0)
    assert row.duration_deviation_ratio == pytest.approx(0.25)
    assert row.deviation_ratio == pytest.approx(0.25)
    assert row.duration_delta_min == pytest.approx(15.0)


def test_case_C_perfect_distance_but_double_duration_is_never_as_planned():
    """10 km / 60 min prescribed, 10 km / 120 min performed → incompatible."""
    prescription = _prescription(
        planned_date=date(2026, 6, 3), distance_km=10.0, duration_min=60.0
    )
    activity = _activity(
        local_date=date(2026, 6, 3),
        start_time=datetime(2026, 6, 3, 7, 0, 0),
        distance_km=10.0,
        duration_min=120.0,  # +100 % → above MATCH_MAX_DEVIATION_RATIO
    )

    ledger = _build([prescription], [activity], reference_date=REF)
    row = _by_prescription(ledger, "p1")

    assert row.adherence_status is not AdherenceStatus.COMPLETED_AS_PLANNED
    assert row.matching_status is MatchingStatus.MISSED
    assert RC_CANDIDATE_REJECTED_DEVIATION in row.reason_codes
    assert ledger.unmatched_actual_count == 1


def test_case_D_duration_used_when_distance_absent_on_one_side():
    prescription = _prescription(distance_km=None, duration_min=60.0)
    activity = _activity(distance_km=10.0, duration_min=62.0)

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert row.comparison_dimensions == ("duration",)
    assert row.distance_deviation_ratio is None
    assert row.adherence_status is AdherenceStatus.COMPLETED_AS_PLANNED
    assert row.actual_distance_km == 10.0  # kept as raw evidence
    assert row.planned_distance_km is None  # never fabricated


def test_case_E_prescribed_pace_divergence_is_not_ignored():
    prescription = _prescription(distance_km=10.0, pace=5.0)
    activity = _activity(distance_km=10.0, duration_min=65.0)  # pace 6.5 → +30 %

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert "pace" in row.comparison_dimensions
    assert row.pace_deviation_ratio == pytest.approx(0.30)
    assert row.adherence_status is AdherenceStatus.COMPLETED_MODIFIED
    assert row.pace_delta_min_per_km == pytest.approx(1.5)


def test_extreme_prescribed_pace_divergence_rejects_the_candidate():
    prescription = _prescription(
        planned_date=date(2026, 6, 3), distance_km=10.0, pace=4.0
    )
    activity = _activity(
        local_date=date(2026, 6, 3),
        start_time=datetime(2026, 6, 3, 7, 0, 0),
        distance_km=10.0,
        duration_min=90.0,  # pace 9.0 → +125 %
    )

    row = _by_prescription(_build([prescription], [activity], reference_date=REF), "p1")

    assert row.matching_status is MatchingStatus.MISSED
    assert RC_CANDIDATE_REJECTED_DEVIATION in row.reason_codes


def test_pace_is_never_compared_when_not_really_prescribed():
    prescription = _prescription(distance_km=10.0, pace=None)
    activity = _activity(distance_km=10.0, duration_min=55.0)

    row = _by_prescription(_build([prescription], [activity]), "p1")

    assert "pace" not in row.comparison_dimensions
    assert row.pace_deviation_ratio is None
    assert row.planned_pace_min_per_km is None
    assert row.actual_pace_min_per_km == pytest.approx(5.5)


# ---------------------------------------------------------------------------
# C230 #4 — explicit Garmin provenance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["legacy", "workout", "manual", "strava", None])
def test_non_garmin_source_is_refused_as_evidence(source):
    domain = DomainActivity(
        activity_type="running",
        start_time="2026-06-10T07:00:00",
        distance_m=10000.0,
        duration_s=3300.0,
        source=source,
        source_activity_id="x1",
    )

    assert (
        to_observed_activity(
            domain, user_id=USER, local_start_time="2026-06-10T07:00:00"
        )
        is None
    )


def test_garmin_source_is_accepted_as_evidence():
    domain = DomainActivity(
        activity_type="running",
        start_time="2026-06-10T07:00:00",
        distance_m=10000.0,
        duration_s=3300.0,
        source="garmin",
        source_activity_id="x1",
    )

    observed = to_observed_activity(
        domain, user_id=USER, local_start_time="2026-06-10T07:00:00"
    )

    assert observed is not None
    assert observed.source == "garmin"


def test_no_fallback_relabels_an_activity_as_garmin():
    """A non-Garmin Mongo document never becomes Garmin evidence."""
    doc = _mongo_doc(source="workout")
    doc.pop("garmin_activity")

    assert mongo_garmin_to_observed_activity(doc, user_id=USER) is None


def test_engine_drops_activities_whose_source_is_not_garmin():
    """Even a hand-built ObservedActivity cannot smuggle in non-Garmin data."""
    fake = _activity(activity_id="fake").model_copy(update={"source": "workout"})

    ledger = _build([_prescription()], [fake])

    assert _by_prescription(ledger, "p1").matching_status is MatchingStatus.PLANNED
    assert ledger.matched_count == 0
    assert ledger.unmatched_actual_count == 0


# ---------------------------------------------------------------------------
# Full logical integration: Mongo → domain → ObservedActivity → ledger
# ---------------------------------------------------------------------------


def test_full_mongo_to_ledger_integration_is_deterministic():
    docs = [
        _mongo_doc(
            activity_id="d1",
            start_time_local="2026-06-08 07:00:00",
            start_time_gmt="2026-06-08 05:00:00",
            distance_m=10000.0,
            duration_s=3300.0,
        ),
        _mongo_doc(
            activity_id="d2",
            start_time_local="2026-06-10 00:30:00",
            start_time_gmt="2026-06-09 22:30:00",
            distance_m=8000.0,
            duration_s=2700.0,
        ),
        _mongo_doc(
            activity_id="d3",
            start_time_local="2026-06-10 18:00:00",
            start_time_gmt="2026-06-10 16:00:00",
            distance_m=4000.0,
            duration_s=1500.0,
        ),
    ]

    observed = mongo_garmin_to_observed_activities(docs, user_id=USER)
    prescriptions = [
        _prescription(
            prescription_id="p1", planned_date=date(2026, 6, 8), distance_km=10.0
        ),
        _prescription(
            prescription_id="p2", planned_date=date(2026, 6, 10), distance_km=8.0
        ),
        _prescription(
            prescription_id="p3", planned_date=date(2026, 6, 9), distance_km=12.0
        ),
    ]

    ledger = _build(prescriptions, observed, reference_date=date(2026, 6, 11))

    assert _by_prescription(ledger, "p1").activity_id == "d1"
    assert _by_prescription(ledger, "p2").activity_id == "d2"
    assert _by_prescription(ledger, "p3").matching_status is MatchingStatus.MISSED
    assert ledger.unmatched_actual_count == 1  # d3 stays visible

    again = _build(prescriptions, list(reversed(observed)), reference_date=date(2026, 6, 11))
    assert ledger.model_dump() == again.model_dump()


# ---------------------------------------------------------------------------
# C230 FINAL — user_id authority, mandatory source, precise start-time code
# ---------------------------------------------------------------------------


def test_mongo_doc_of_another_user_is_refused():
    doc = _mongo_doc(user_id="user-B")

    assert mongo_garmin_to_observed_activity(doc, user_id="user-A") is None


def test_mongo_doc_without_user_id_is_refused():
    doc = _mongo_doc()
    doc.pop("user_id")

    assert mongo_garmin_to_observed_activity(doc, user_id=USER) is None

    doc["user_id"] = ""
    assert mongo_garmin_to_observed_activity(doc, user_id=USER) is None

    doc["user_id"] = None
    assert mongo_garmin_to_observed_activity(doc, user_id=USER) is None


def test_mongo_batch_keeps_only_the_caller_own_documents():
    docs = [
        _mongo_doc(activity_id="own-1", user_id="user-A"),
        _mongo_doc(activity_id="other-1", user_id="user-B"),
        _mongo_doc(activity_id="own-2", user_id="user-A"),
    ]

    observed = mongo_garmin_to_observed_activities(docs, user_id="user-A")

    assert [a.activity_id for a in observed] == ["own-1", "own-2"]
    assert {a.user_id for a in observed} == {"user-A"}


def test_mongo_doc_of_the_right_owner_is_accepted():
    doc = _mongo_doc(user_id=USER)

    observed = mongo_garmin_to_observed_activity(doc, user_id=USER)

    assert observed is not None
    assert observed.user_id == USER
    assert observed.source == "garmin"
    assert observed.local_date == date(2026, 6, 10)


def test_observed_activity_requires_an_explicit_source():
    with pytest.raises(ValidationError):
        ObservedActivity(
            activity_id="a1",
            user_id=USER,
            local_date=REF,
            activity_type="running",
        )


@pytest.mark.parametrize("bad_source", ["legacy", "manual", "workout", "strava", ""])
def test_non_garmin_observed_activity_is_never_used_as_evidence(bad_source):
    prescription = _prescription(distance_km=10.0)
    activity = _activity(source=bad_source)

    ledger = _build([prescription], [activity], reference_date=date(2026, 6, 12))
    row = _by_prescription(ledger, "p1")

    assert row.matching_status is MatchingStatus.MISSED
    assert ledger.matched_count == 0
    assert ledger.unmatched_actual_count == 0


def test_start_time_reason_code_absent_when_only_one_candidate():
    prescription = _prescription(distance_km=10.0, planned_start_time=time(18, 0))
    only = _activity(activity_id="a_only", start_time=datetime(2026, 6, 10, 18, 5, 0))

    row = _by_prescription(_build([prescription], [only]), "p1")

    assert row.matching_status is MatchingStatus.MATCHED
    assert RC_RESOLVED_BY_PLANNED_START_TIME not in row.reason_codes


def test_start_time_reason_code_absent_when_deviation_decided_the_match():
    prescription = _prescription(distance_km=10.0, planned_start_time=time(18, 0))
    best_distance = _activity(
        activity_id="a_best",
        distance_km=10.0,
        duration_min=55.0,
        start_time=datetime(2026, 6, 10, 7, 0, 0),
    )
    worse_distance = _activity(
        activity_id="a_worse",
        distance_km=8.0,
        duration_min=44.0,
        start_time=datetime(2026, 6, 10, 18, 0, 0),
    )

    row = _by_prescription(_build([prescription], [best_distance, worse_distance]), "p1")

    assert row.activity_id == "a_best"
    assert RC_RESOLVED_BY_PLANNED_START_TIME not in row.reason_codes


def test_start_time_reason_code_absent_when_gaps_are_equal():
    """Same deviation, same gap → ambiguous, so the code is never emitted."""
    prescription = _prescription(distance_km=10.0, planned_start_time=time(12, 0))
    before = _activity(
        activity_id="a_before", start_time=datetime(2026, 6, 10, 11, 0, 0)
    )
    after = _activity(activity_id="a_after", start_time=datetime(2026, 6, 10, 13, 0, 0))

    row = _by_prescription(_build([prescription], [before, after]), "p1")

    assert row.matching_status is MatchingStatus.AMBIGUOUS
    assert RC_RESOLVED_BY_PLANNED_START_TIME not in row.reason_codes
