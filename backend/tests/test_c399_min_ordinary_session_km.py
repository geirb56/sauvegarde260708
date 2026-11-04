"""C399 — an adapted ordinary session is >= 4.0 km, otherwise it is removed."""
from datetime import date, timedelta

import pytest

from training_v2.daily_adaptation import DailyAdaptationAction, build_daily_adaptation
from training_v2.domain_activity import DomainActivity
from training_v2.readiness_decision import ReadinessBand, ReadinessDecision
from training_v2.weekly_budget import apply_weekly_budget
from training_v2.workout_generator import (
    MIN_ORDINARY_SESSION_KM,
    WeeklyPlan,
    WorkoutPrescription,
    short_sessions_allowed,
)

MON = date(2026, 11, 2)
TUE = MON + timedelta(days=1)
WED = MON + timedelta(days=2)
THU = MON + timedelta(days=3)
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MIN = MIN_ORDINARY_SESSION_KM


def _run(d, km, aid, vig=None):
    return DomainActivity(
        activity_type="running", start_time=f"{d.isoformat()}T07:00:00", distance_m=km * 1000,
        duration_s=km * 360, source="garmin", source_activity_id=aid,
        vigorous_intensity_minutes=vig,
    )


def _plan(sessions, ref=WED, basis="distance"):
    out = []
    for d in DAYS:
        t, km = sessions.get(d, ("rest", None))
        out.append(WorkoutPrescription(
            day=d, workout_type=t, intensity_class={"rest": "rest", "quality": "high"}.get(t, "low"),
            distance_km=km if basis == "distance" else None,
            duration_minutes=None if basis == "distance" else 40 if t != "rest" else None,
            reason_codes=(),
        ))
    train = [s for s in out if s.workout_type != "rest"]
    return WeeklyPlan(
        reference_date=ref, sessions=tuple(out), target_basis=basis,
        planned_km=round(sum(s.distance_km for s in train), 1) if basis == "distance" else None,
        planned_duration_minutes=None if basis == "distance" else 40 * len(train),
        session_count=len(train), allow_intensity=True, reason_codes=(),
    )


# C398 plan: target 20.6; Wed/Fri/Sun are the sessions the old engine shrank to 2.5/3.6/3.1.
C398 = {"monday": ("easy", 2.0), "wednesday": ("easy", 5.0), "friday": ("easy", 7.3),
        "sunday": ("long_easy", 6.3)}
C398_ACTS = [_run(MON, 4.66, "a"), _run(TUE, 5.79, "b")]


def _future(plan, ref=WED):
    idx = ref.weekday()
    return [s for s in plan.sessions if DAYS.index(s.day) >= idx]


def _running(plan, ref=WED):
    return [s for s in _future(plan, ref) if s.workout_type not in ("rest", "race")]


def _no_short_ordinary(plan, ref=WED):
    for s in _running(plan, ref):
        assert s.distance_km >= MIN - 1e-9, (s.day, s.distance_km)


def test_c398_reproduction_no_session_below_4km():
    plan = _plan(C398)
    new, b = apply_weekly_budget(plan, C398_ACTS, WED)
    assert b.remaining_budget_km == 10.2
    _no_short_ordinary(new)
    run = _running(new)
    assert 1 <= len(run) < 3
    assert sum(s.distance_km for s in run) <= b.remaining_budget_km + 1e-9
    orig = {s.day: s for s in plan.sessions}
    assert all(s.distance_km <= orig[s.day].distance_km + 1e-9 for s in run)
    for s in _future(new):
        if s.workout_type == "rest":
            assert orig[s.day].workout_type != "rest" or s.reason_codes == ()
    dropped = [s for s in _future(new) if s.workout_type == "rest" and orig[s.day].workout_type != "rest"]
    assert dropped and all("ORDINARY_SESSION_MIN_KM_NOT_MET" in s.reason_codes for s in dropped)
    # The long run is kept at its own planned distance (no proportional shrink).
    assert next(s for s in new.sessions if s.day == "sunday").distance_km == pytest.approx(6.2, abs=0.11)


def _budget_case(acts, sessions, ref=WED):
    plan = _plan(sessions, ref)
    return plan, *apply_weekly_budget(plan, acts, ref)


@pytest.mark.parametrize("acts", [
    [_run(MON, 4.0, "a")],                                   # A one off-plan run
    [_run(MON, 4.0, "a"), _run(TUE, 5.0, "b")],              # B two runs
    [_run(MON, 2.0, "a"), _run(MON, 2.0, "b"), _run(TUE, 5.0, "c")],  # C several same day
])
def test_off_plan_runs_never_leave_short_sessions(acts):
    plan, new, b = _budget_case(acts, {"monday": ("easy", 4.0), "wednesday": ("easy", 6.0),
                                       "friday": ("easy", 6.0), "sunday": ("long_easy", 8.0)})
    _no_short_ordinary(new)
    assert sum(s.distance_km for s in _running(new)) <= b.remaining_budget_km + 1e-9


def test_sufficient_budget_changes_nothing():
    plan, new, b = _budget_case([], {"wednesday": ("easy", 5.0), "friday": ("easy", 5.0)})
    assert new == plan and "WEEKLY_BUDGET_APPLIED" not in b.reason_codes


def test_budget_for_two_sessions_only():
    plan, new, b = _budget_case([_run(MON, 6.0, "a")], {"wednesday": ("easy", 5.0), "friday": ("easy", 5.0),
                                                      "sunday": ("long_easy", 6.0)})
    # planned 16, actual 6 -> 10 left: only two 4+ km sessions fit
    assert len(_running(new)) == 2
    assert sum(s.distance_km for s in _running(new)) <= 10.0 + 1e-9
    _no_short_ordinary(new)


def test_budget_for_one_session_only():
    plan, new, b = _budget_case([_run(MON, 9.0, "a")], {"wednesday": ("easy", 5.0), "friday": ("easy", 5.0),
                                                      "sunday": ("long_easy", 6.0)})
    assert [s.workout_type for s in _running(new)] == ["long_easy"]
    assert _running(new)[0].distance_km <= 7.0


def test_budget_below_4km_gives_rest_everywhere():
    plan, new, b = _budget_case([_run(MON, 13.0, "a")], {"wednesday": ("easy", 5.0), "friday": ("easy", 5.0),
                                                       "sunday": ("long_easy", 6.0)})
    assert b.remaining_budget_km == 3.0
    assert _running(new) == []
    assert all(s.workout_type == "rest" for s in _future(new))


def test_exactly_4_km_is_kept_and_3_9_is_dropped():
    sessions = {"wednesday": ("easy", 6.0)}
    _, new, b = _budget_case([_run(MON, 2.0, "a")], sessions)          # planned 6, left 4.0
    assert next(s for s in new.sessions if s.day == "wednesday").distance_km == 4.0
    _, new, b = _budget_case([_run(MON, 2.1, "a")], sessions)          # left 3.9
    assert next(s for s in new.sessions if s.day == "wednesday").workout_type == "rest"


def test_quality_session_with_impossible_structure_is_not_truncated(monkeypatch):
    import training_v2.weekly_budget as wb

    monkeypatch.setattr(wb, "_structure_is_coherent", lambda s, g, p: s.workout_type != "quality")
    plan = _plan({"wednesday": ("quality", 8.0), "friday": ("easy", 6.0)})
    new, b = apply_weekly_budget(plan, [_run(MON, 6.0, "a")], WED, plan_goal=object(), periodization=object())
    wed = next(s for s in new.sessions if s.day == "wednesday")
    assert wed.workout_type in ("easy", "rest")
    _no_short_ordinary(new)
    if wed.workout_type == "easy":
        assert "QUALITY_DOWNGRADED_STRUCTURE_INCOHERENT" in wed.reason_codes


def test_long_run_no_longer_longest_becomes_easy_or_rest():
    plan = _plan({"wednesday": ("easy", 9.0), "sunday": ("long_easy", 6.0)})
    new, b = apply_weekly_budget(plan, [_run(MON, 6.0, "a")], WED)  # 15 - 6 = 9 left
    run = _running(new)
    assert len(run) <= 2 and not any(
        s.workout_type == "long_easy" and s.distance_km < max(o.distance_km for o in run) for s in run
    )
    _no_short_ordinary(new)


def test_recovery_by_name_is_not_exempt():
    plan = _plan({"wednesday": ("recovery", 5.0), "friday": ("easy", 5.0)})
    new, _ = apply_weekly_budget(plan, [_run(MON, 6.0, "a")], WED)  # 10-6 = 4 left
    _no_short_ordinary(new)
    assert len(_running(new)) == 1


@pytest.mark.parametrize("state,exempt", [
    ("deep_reprise", True), ("partial_reprise", True), ("no_history", True),
    ("normal", False), ("reprise_exit", False), (None, False),
])
def test_reprise_exemption_is_structured(state, exempt):
    assert short_sessions_allowed(state) is exempt


def test_reprise_keeps_legacy_short_sessions():
    plan = _plan({"wednesday": ("easy", 5.0), "friday": ("easy", 5.0)})
    new, _ = apply_weekly_budget(plan, [_run(MON, 3.5, "a")], WED, continuity_state="partial_reprise")
    kms = sorted(s.distance_km for s in _running(new))
    assert len(kms) == 2 and kms[0] < MIN
    normal, _ = apply_weekly_budget(plan, [_run(MON, 3.5, "a")], WED)
    _no_short_ordinary(normal)


def test_frozen_session_below_4km_is_untouched_and_reserves_budget():
    plan = _plan({"wednesday": ("easy", 3.0), "friday": ("easy", 6.0), "sunday": ("long_easy", 8.0)})
    wed = plan.sessions[2]
    new, b = apply_weekly_budget(plan, [_run(MON, 8.0, "a")], WED, frozen_sessions={"wednesday": wed})
    assert new.sessions[2] == wed
    for s in _running(new):
        assert s.day == "wednesday" or s.distance_km >= MIN - 1e-9


def test_confirmed_vs_unverified_intensity_still_adapt_without_short_sessions():
    sessions = {"wednesday": ("quality", 7.0), "friday": ("easy", 6.0), "sunday": ("long_easy", 8.0)}
    for kw, evidence in (({"confirmed_intense_days": {MON}}, "confirmed"), ({}, "present_unverified")):
        plan = _plan(sessions)
        new, b = apply_weekly_budget(plan, [_run(MON, 8.0, "a", vig=25.0)], WED, **kw)
        assert b.unplanned_intensity_evidence == evidence
        _no_short_ordinary(new)


def test_date_change_never_regrows_and_consultations_are_deterministic():
    sessions = {"wednesday": ("easy", 5.0), "friday": ("easy", 7.3), "sunday": ("long_easy", 6.3)}
    acts = [_run(MON, 4.66, "a"), _run(TUE, 5.79, "b")]
    plan_w = _plan(sessions, WED)
    first = apply_weekly_budget(plan_w, acts, WED)
    assert apply_weekly_budget(plan_w, acts, WED) == first
    plan_t = _plan(sessions, THU)
    thu, _ = apply_weekly_budget(plan_t, acts, THU)
    wed, _ = first
    for d in ("friday", "sunday"):
        t = next(s for s in thu.sessions if s.day == d)
        w = next(s for s in wed.sessions if s.day == d)
        assert (t.distance_km or 0) <= (w.distance_km or 0) + 1e-9
    _no_short_ordinary(thu, THU)


def test_no_catch_up_on_removed_kilometres():
    plan, new, b = _budget_case(C398_ACTS, C398)
    assert sum(s.distance_km for s in _running(new)) <= b.remaining_budget_km + 1e-9
    assert b.planned_weekly_km == 20.6


def test_reason_codes_have_no_duplicates():
    plan, new, b = _budget_case(C398_ACTS, C398)
    assert len(b.reason_codes) == len(set(b.reason_codes))
    for s in new.sessions:
        assert len(s.reason_codes) == len(set(s.reason_codes))
    thu_plan = _plan({"wednesday": ("easy", 6.0), "friday": ("easy", 8.0), "sunday": ("long_easy", 12.0)}, THU)
    new, b = apply_weekly_budget(thu_plan, [_run(MON, 8.0, "a"), _run(TUE, 4.0, "b")], THU)
    for s in new.sessions:
        assert len(s.reason_codes) == len(set(s.reason_codes))


def test_duration_based_plans_are_not_converted_to_km():
    plan = _plan({"wednesday": ("easy", None), "friday": ("easy", None)}, basis="duration")
    new, b = apply_weekly_budget(plan, [_run(MON, 6.0, "a")], WED)
    assert new == plan and b.reason_codes == ("BUDGET_NOT_DISTANCE_BASED",)
    assert b.with_final_sessions(new.sessions) is b


# ---- daily adaptation (Today and Week share it) ---------------------------

def _decision(band):
    fields = ReadinessDecision.model_fields if hasattr(ReadinessDecision, "model_fields") else {}
    kwargs = {k: None for k in fields}
    kwargs.update(band=band, reason_codes=("TEST",))
    return ReadinessDecision.model_construct(**kwargs)


def _workout(km, wt="easy"):
    return WorkoutPrescription(
        day="wednesday", workout_type=wt, intensity_class="low", distance_km=km,
        duration_minutes=None, reason_codes=(),
    )


def _adapt(km, wt="easy", **kw):
    return build_daily_adaptation(
        workout=_workout(km, wt), readiness_decision=_decision(ReadinessBand.LOW),
        training_load=None, recent_response=None, **kw,
    )


def test_daily_shortening_below_minimum_becomes_rest():
    r = _adapt(5.0)                      # 5.0 * 0.7 = 3.5
    assert r.action == DailyAdaptationAction.REST
    assert "ORDINARY_SESSION_MIN_KM_NOT_MET" in r.reason_codes
    assert r.adapted_workout.workout_type == "rest"
    assert _adapt(8.0, "long_easy").action == DailyAdaptationAction.SHORTEN


def test_daily_shortening_at_exactly_4km_is_kept():
    r = _adapt(5.8)                      # 4.06 -> 4.1
    assert r.action == DailyAdaptationAction.SHORTEN and r.adapted_workout.distance_km >= MIN
    r = _adapt(5.72)                     # 4.004 -> 4.0
    assert r.adapted_workout.distance_km == 4.0


def test_daily_shortening_allowed_in_explicit_reprise_only():
    r = _adapt(5.0, short_sessions_allowed=True)
    assert r.action == DailyAdaptationAction.SHORTEN and r.adapted_workout.distance_km == 3.5


def test_low_readiness_alone_never_authorises_short_ordinary_session():
    r = build_daily_adaptation(
        workout=_workout(4.5), readiness_decision=_decision(ReadinessBand.CAUTION),
        training_load=None, recent_response=None,
    )
    assert r.adapted_workout.workout_type == "rest"


# ---- first-display consistency -------------------------------------------

def test_adapted_remaining_matches_final_sessions_and_theoretical_budget_stays_distinct():
    plan, new, b = _budget_case(C398_ACTS, C398)
    assert b.adapted_remaining_km == pytest.approx(sum(s.distance_km for s in _running(new)))
    final = [s if s.day != "wednesday" else s.model_copy(update={"workout_type": "rest", "distance_km": None})
             for s in new.sessions]
    refreshed = b.with_final_sessions(final)
    assert refreshed.remaining_budget_km == b.remaining_budget_km == 10.2
    assert refreshed.adapted_remaining_km == pytest.approx(sum(s.distance_km for s in _running(new) if s.day != "wednesday"))
    r = refreshed.to_response()
    assert "reference_weekday" not in r and "ran_today" not in r


def test_today_and_week_use_the_same_budgeted_plan_and_adaptation():
    from training_v2.today_prescription import resolve_today_final_prescription

    plan, new, b = _budget_case(C398_ACTS, C398)
    sessions = [s for s in _running(new)]
    for s in sessions:
        a = resolve_today_final_prescription(
            planned_prescription=s, reference_date=WED, domain_activities_90=[],
            garmin_daily_metrics_docs=[], garmin_connected=False,
        )
        b_ = resolve_today_final_prescription(
            planned_prescription=s, reference_date=WED, domain_activities_90=[],
            garmin_daily_metrics_docs=[], garmin_connected=False, continuity_state="normal",
        )
        assert a.adaptation_result == b_.adaptation_result
        assert a.adaptation_result.adapted_workout.distance_km >= MIN
