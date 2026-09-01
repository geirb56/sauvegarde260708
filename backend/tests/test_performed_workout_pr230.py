"""PR230 — Tests: PRESCRIBED vs PERFORMED (Garmin actual).

All tests are pure and deterministic: an explicit ``reference_date`` is always
supplied and no clock is consulted.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

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
    RC_NO_PRESCRIPTION,
    RC_REST_NOT_MATCHABLE,
    RC_WINDOW_CLOSED,
    RC_WINDOW_OPEN,
    build_performed_workouts,
    to_observed_activities,
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
) -> ObservedActivity:
    pace = None
    if distance_km and duration_min:
        pace = round(duration_min / distance_km, 2)
    return ObservedActivity(
        activity_id=activity_id,
        user_id=user_id,
        local_date=local_date,
        start_time=start_time,
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
    assert row.comparison_basis == "distance"
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

    assert row.matching_status is MatchingStatus.PLANNED
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
        source_activity_id="a-late",
    )
    observed = to_observed_activity(domain, user_id=USER)

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

    assert row.comparison_basis == "duration"
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
    assert row.comparison_basis is None
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
        source_activity_id="a-zero",
    )
    observed = to_observed_activity(domain, user_id=USER)

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
        "unmatched_actual",
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
        start_time="2026-06-10T07:15:00",
        distance_m=10500.0,
        duration_s=3300.0,
        source="garmin",
        source_activity_id="123456",
    )

    observed = to_observed_activity(domain, user_id=USER)

    assert observed is not None
    assert observed.activity_id == "123456"
    assert observed.user_id == USER
    assert observed.local_date == date(2026, 6, 10)
    assert observed.start_time == datetime(2026, 6, 10, 7, 15, 0)
    assert observed.distance_km == pytest.approx(10.5)
    assert observed.duration_min == pytest.approx(55.0)
    assert observed.pace_min_per_km == pytest.approx(5.24, abs=0.01)
    assert observed.is_running is True


def test_to_observed_activity_rejects_activities_without_date_or_id():
    no_date = DomainActivity(activity_type="running", source_activity_id="1")
    no_id = DomainActivity(activity_type="running", start_time="2026-06-10T07:00:00")

    assert to_observed_activity(no_date, user_id=USER) is None
    assert to_observed_activity(no_id, user_id=USER) is None


def test_to_observed_activities_skips_unusable_inputs():
    usable = DomainActivity(
        activity_type="running",
        start_time="2026-06-10T07:00:00",
        source_activity_id="ok",
    )
    unusable = DomainActivity(activity_type="running")

    result = to_observed_activities([usable, unusable], user_id=USER)

    assert len(result) == 1
    assert result[0].activity_id == "ok"
