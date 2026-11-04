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


# ---- review corrections (retention replay, post-race, priority, rounding) --

import random
from types import SimpleNamespace

import training_v2.weekly_budget as wb


def _replay_with(monkeypatch, wed_km):
    """Earlier-day views (the C385/C386 replay) report Wednesday at ``wed_km``."""
    real = wb._budget_view

    def patched(plan, acts, ref, *a, **k):
        view = real(plan, acts, ref, *a, **k)
        if ref < WED:
            sessions = list(view.sessions)
            i = next(n for n, s in enumerate(sessions) if s.day == "wednesday")
            sessions[i] = sessions[i].model_copy(update={"distance_km": wed_km})
            return wb._View(sessions, view.codes, view.evidence, view.actual_km, view.remaining,
                            view.ran_today, view.today_idx)
        return view

    monkeypatch.setattr(wb, "_budget_view", patched)


def _wed(plan):
    return next(s for s in plan.sessions if s.day == "wednesday")


def test_retained_reduction_below_4km_becomes_rest(monkeypatch):
    plan = _plan({"wednesday": ("easy", 6.0), "friday": ("easy", 5.0)})
    _replay_with(monkeypatch, 3.5)
    new, b = apply_weekly_budget(plan, [], WED)
    assert _wed(new).workout_type == "rest" and _wed(new).distance_km is None
    assert "ORDINARY_SESSION_MIN_KM_NOT_MET" in _wed(new).reason_codes
    assert "WEEKLY_BUDGET_REDUCTION_RETAINED" in b.reason_codes


def test_retained_reduction_at_exactly_4km_is_kept_never_raised(monkeypatch):
    plan = _plan({"wednesday": ("easy", 6.0)})
    _replay_with(monkeypatch, 4.0)
    new, _ = apply_weekly_budget(plan, [], WED)
    assert _wed(new).distance_km == 4.0
    _replay_with(monkeypatch, 3.9)
    assert _wed(apply_weekly_budget(plan, [], WED)[0]).workout_type == "rest"


def test_retained_reduction_exempt_in_reprise(monkeypatch):
    plan = _plan({"wednesday": ("easy", 6.0)})
    _replay_with(monkeypatch, 3.5)
    new, _ = apply_weekly_budget(plan, [], WED, continuity_state="partial_reprise")
    assert _wed(new).distance_km == 3.5


def test_retained_reduction_never_touches_frozen(monkeypatch):
    plan = _plan({"wednesday": ("easy", 3.0), "friday": ("easy", 6.0)})
    _replay_with(monkeypatch, 2.0)
    new, _ = apply_weekly_budget(plan, [], WED, frozen_sessions={"wednesday": plan.sessions[2]})
    assert _wed(new) == plan.sessions[2]


# post-race: only explicit structured evidence exempts
RACE_PASSED = SimpleNamespace(reason_codes=("RACE_DATE_PASSED", "CONTINUOUS_CYCLE", "PHASE_CONSOLIDATION"))
NO_RACE = SimpleNamespace(reason_codes=("CONTINUOUS_CYCLE", "PHASE_CONSOLIDATION"))


def _post_race_plan(recovery_codes, wt="recovery", km=3.5):
    plan = _plan({"wednesday": (wt, km), "friday": ("easy", 6.0), "sunday": ("long_easy", 8.0)})
    sessions = list(plan.sessions)
    sessions[2] = sessions[2].model_copy(update={"reason_codes": recovery_codes})
    return plan.model_copy(update={"sessions": tuple(sessions)})


def test_explicit_post_race_recovery_may_stay_under_4km():
    plan = _post_race_plan(("POST_RACE_RECOVERY",))
    new, b = apply_weekly_budget(plan, [_run(MON, 8.0, "a")], WED, periodization=RACE_PASSED)
    assert _wed(new).distance_km == 3.5 and _wed(new).workout_type == "recovery"
    assert sum(s.distance_km for s in _running(new)) <= b.remaining_budget_km + 1e-9
    for s in _running(new):
        assert s.day == "wednesday" or s.distance_km >= MIN - 1e-9


def test_post_race_recovery_is_reduce_only_and_budget_bound():
    plan = _post_race_plan(("POST_RACE_RECOVERY",), km=3.5)
    new, b = apply_weekly_budget(plan, [_run(MON, 15.0, "a")], WED, periodization=RACE_PASSED)  # 17.5-15=2.5
    assert _wed(new).distance_km == 2.5
    assert all(s.workout_type == "rest" for s in _future(new) if s.day != "wednesday")


@pytest.mark.parametrize("codes,perio,wt", [
    ((), RACE_PASSED, "recovery"),                         # recovery name alone
    (("POST_RACE_RECOVERY",), NO_RACE, "recovery"),        # code without a passed race
    (("POST_RACE_RECOVERY",), RACE_PASSED, "easy"),        # ordinary run after a race
    (("POST_RACE_RECOVERY",), None, "recovery"),
])
def test_post_race_exemption_needs_all_explicit_signals(codes, perio, wt):
    plan = _post_race_plan(codes, wt=wt)
    new, b = apply_weekly_budget(plan, [_run(MON, 8.0, "a")], WED, periodization=perio)
    _no_short_ordinary(new)


def test_daily_adaptation_post_race_exemption_is_explicit():
    from training_v2.today_prescription import resolve_today_final_prescription

    def final(session, perio):
        return resolve_today_final_prescription(
            planned_prescription=session, reference_date=WED, domain_activities_90=[],
            garmin_daily_metrics_docs=[], garmin_connected=False, periodization=perio,
        ).adaptation_result

    rec = _workout(5.0, "recovery").model_copy(update={"reason_codes": ("POST_RACE_RECOVERY",)})
    # Unavailable readiness keeps the plan: exemption only matters when shortening happens.
    assert final(rec, RACE_PASSED).adapted_workout.distance_km == 5.0
    r = build_daily_adaptation(
        workout=rec, readiness_decision=_decision(ReadinessBand.LOW), training_load=None,
        recent_response=None,
        short_sessions_allowed=__import__("training_v2.workout_generator", fromlist=["x"]).is_post_race_recovery(rec, RACE_PASSED),
    )
    assert r.action == DailyAdaptationAction.SHORTEN and r.adapted_workout.distance_km == 3.5
    r = build_daily_adaptation(
        workout=rec, readiness_decision=_decision(ReadinessBand.LOW), training_load=None, recent_response=None,
    )
    assert r.adapted_workout.workout_type == "rest"


def test_intensity_not_allowed_never_keeps_quality_by_priority():
    plan = _plan({"wednesday": ("quality", 7.0), "friday": ("easy", 6.0), "sunday": ("easy", 6.0)})
    plan = plan.model_copy(update={"allow_intensity": False})
    new, b = apply_weekly_budget(plan, [_run(MON, 9.0, "a")], WED)   # 19-9 = 10 left
    assert not any(s.workout_type == "quality" for s in new.sessions)
    _no_short_ordinary(new)


def test_confirmed_offplan_intensity_does_not_duplicate_quality():
    plan = _plan({"wednesday": ("easy", 6.0), "friday": ("quality", 7.0), "sunday": ("long_easy", 8.0)})
    new, b = apply_weekly_budget(plan, [_run(MON, 8.0, "a", vig=25.0)], WED, confirmed_intense_days={MON})
    assert b.unplanned_intensity_evidence == "confirmed"
    assert not any(s.workout_type == "quality" for s in new.sessions)
    _no_short_ordinary(new)


def test_quality_loses_to_easy_when_intensity_was_confirmed_and_budget_short(monkeypatch):
    monkeypatch.setattr(wb, "_limit_quality_duplication", lambda *a, **k: None)  # isolate the ranking
    plan = _plan({"wednesday": ("quality", 7.0), "friday": ("easy", 7.0)})
    new, _ = apply_weekly_budget(plan, [_run(MON, 8.0, "a", vig=25.0)], WED, confirmed_intense_days={MON})  # 6 left
    kept = _running(new)
    assert [s.day for s in kept] == ["friday"]


def test_long_run_shorter_than_an_easy_run_is_requalified():
    plan = _plan({"wednesday": ("easy", 7.0), "sunday": ("long_easy", 5.0)})
    new, b = apply_weekly_budget(plan, [_run(MON, 4.0, "a")], WED)   # 12-4 = 8 left
    run = _running(new)
    assert sum(s.distance_km for s in run) <= 8.0
    longest = max(s.distance_km for s in run)
    assert not any(s.workout_type == "long_easy" and s.distance_km < longest - 1e-9 for s in run)


def test_rounding_never_exceeds_exact_remainder():
    # planned 20.6, actual 10.44 -> exact 10.16, published (rounded) 10.2
    plan = _plan({"wednesday": ("easy", 5.0), "friday": ("easy", 7.3), "sunday": ("long_easy", 6.3),
                  "monday": ("easy", 2.0)})
    acts = [_run(MON, 4.66, "a"), _run(TUE, 5.78, "b")]
    new, b = apply_weekly_budget(plan, acts, WED)
    assert b.remaining_budget_km == 10.2
    assert sum(s.distance_km for s in _running(new)) <= 10.16 + 1e-9


def _random_case(rng):
    ref = MON + timedelta(days=rng.randint(0, 5))
    sess = {d: (rng.choice(["easy", "easy", "quality", "long_easy", "recovery"]), round(rng.uniform(3, 12), 1))
            for d in DAYS if rng.random() < 0.55}
    acts = [_run(MON + timedelta(days=i), round(rng.uniform(2, 8), 1), f"a{i}{j}")
            for i in range(ref.weekday() + 1) for j in range(2) if rng.random() < 0.3]
    return ref, sess, acts


def test_property_min_budget_no_regrowth_codes_and_determinism():
    rng = random.Random(399)
    for _ in range(600):
        ref, sess, acts = _random_case(rng)
        if not sess:
            continue
        plan = _plan(sess, ref)
        orig = {s.day: s for s in plan.sessions}
        new, b = apply_weekly_budget(plan, acts, ref)
        assert apply_weekly_budget(plan, acts, ref)[0] == new
        exact = max(0.0, plan.planned_km - round(sum(a.distance_m for a in acts) / 1000, 2))
        ran_today = any(a.start_time[:10] == ref.isoformat() for a in acts)
        prescribable = [s for s in _running(new, ref) if DAYS.index(s.day) > ref.weekday() or not ran_today]
        assert sum(s.distance_km for s in prescribable) <= exact + 1e-9
        assert len(b.reason_codes) == len(set(b.reason_codes))
        for s in new.sessions:
            assert len(s.reason_codes) == len(set(s.reason_codes))
        for s in _running(new, ref):
            o = orig[s.day]
            assert s.distance_km <= o.distance_km + 1e-9
            if s.distance_km < o.distance_km - 1e-9:
                assert s.distance_km >= MIN - 1e-9
        # moving the reference date later never re-grows a session
        later = ref + timedelta(days=1)
        if later.weekday() <= 6 and later <= MON + timedelta(days=6):
            nxt, _ = apply_weekly_budget(_plan(sess, later), acts, later)
            for s in nxt.sessions:
                if DAYS.index(s.day) >= later.weekday():
                    prev = next(p for p in new.sessions if p.day == s.day)
                    assert (s.distance_km or 0.0) <= (prev.distance_km or 0.0) + 1e-9


def test_today_then_week_and_week_then_today_share_the_same_plan():
    sessions = {"wednesday": ("easy", 5.0), "friday": ("easy", 7.3), "sunday": ("long_easy", 6.3)}
    acts = [_run(MON, 4.66, "a"), _run(TUE, 5.79, "b")]
    week_first = apply_weekly_budget(_plan(sessions), acts, WED)
    today_after = apply_weekly_budget(_plan(sessions), acts, WED)
    assert week_first == today_after


# ---- C399 final fix: intensity forbidden is enforced regardless of the budget --

def _no_intensity(plan):
    return plan.model_copy(update={"allow_intensity": False})


def _quality_plan(**extra):
    sessions = {"wednesday": ("quality", 6.0), "friday": ("easy", 5.0), "sunday": ("long_easy", 8.0)}
    sessions.update(extra)
    return _no_intensity(_plan(sessions))


def _types_and_classes(plan):
    return {s.day: (s.workout_type, s.intensity_class) for s in plan.sessions}


def test_forbidden_intensity_with_sufficient_budget_requalifies_quality():
    plan = _quality_plan()
    new, b = apply_weekly_budget(plan, [], WED)            # budget fully sufficient
    wed = _wed(new)
    assert (wed.workout_type, wed.intensity_class) == ("easy", "low")
    assert wed.distance_km == 6.0                          # never increased nor reduced here
    assert wed.reason_codes.count("QUALITY_NOT_KEPT_INTENSITY_NOT_ALLOWED") == 1
    assert "QUALITY_NOT_KEPT_INTENSITY_NOT_ALLOWED" in b.reason_codes


def test_forbidden_intensity_with_insufficient_budget_leaves_no_quality():
    plan = _quality_plan()
    new, b = apply_weekly_budget(plan, [_run(MON, 8.0, "a")], WED)     # 19 - 8 = 11 left
    assert not any(s.workout_type == "quality" or s.intensity_class == "high" for s in new.sessions)
    assert sum(s.distance_km for s in _running(new)) <= 11.0 + 1e-9
    _no_short_ordinary(new)


def test_requalification_that_makes_budget_fit_is_kept_in_the_returned_plan():
    # 6 + 5 = 11 total; budget exactly 11 only once quality is requalified (distance unchanged).
    plan = _no_intensity(_plan({"wednesday": ("quality", 6.0), "friday": ("easy", 5.0)}))
    new, b = apply_weekly_budget(plan, [_run(MON, 2.0, "a")], WED)
    assert _wed(new).workout_type == "easy"
    assert new != plan


def test_forbidden_intensity_never_touches_frozen_and_reports_contradiction():
    plan = _quality_plan()
    frozen_wed = plan.sessions[2]
    new, b = apply_weekly_budget(plan, [], WED, frozen_sessions={"wednesday": frozen_wed})
    assert _wed(new) == frozen_wed and _wed(new).workout_type == "quality"
    assert "QUALITY_FROZEN_CONTRADICTS_INTENSITY_POLICY" in b.reason_codes
    frozen_fri = _plan({"friday": ("quality", 6.0)}).sessions[4]
    new, b = apply_weekly_budget(_no_intensity(_plan({"friday": ("quality", 6.0)})), [], WED,
                                 frozen_sessions={"friday": frozen_fri})
    assert new.sessions[4] == frozen_fri


def test_forbidden_intensity_past_and_already_run_today_are_not_modified():
    plan = _no_intensity(_plan({"monday": ("quality", 6.0), "wednesday": ("quality", 6.0)}))
    new, _ = apply_weekly_budget(plan, [_run(WED, 6.0, "a")], WED)
    assert next(s for s in new.sessions if s.day == "monday").workout_type == "quality"
    assert _wed(new).workout_type == "quality"


def test_allowed_intensity_and_sufficient_budget_keeps_quality():
    plan = _plan({"wednesday": ("quality", 6.0), "friday": ("easy", 5.0)})
    new, b = apply_weekly_budget(plan, [], WED)
    assert new == plan and _wed(new).workout_type == "quality"


def test_incoherent_requalification_falls_back_to_rest(monkeypatch):
    monkeypatch.setattr(wb, "_structure_is_coherent", lambda s, g, p: s.workout_type != "easy")
    new, b = apply_weekly_budget(_quality_plan(), [], WED, plan_goal=object(), periodization=object())
    assert _wed(new).workout_type == "rest" and _wed(new).distance_km is None


def test_forbidden_intensity_final_structure_has_no_interval_blocks():
    from test_weekly_volume_trajectory import _canonical, _history
    from training_v2.structured_workout import StructuredStepType, build_structured_workout_prescription

    c = _canonical(_history([30] * 6), race=WED + timedelta(weeks=12), ref=WED)
    quality = WorkoutPrescription(day="friday", workout_type="quality", intensity_class="high",
                                  distance_km=9.0, duration_minutes=None, reason_codes=())
    sessions = {s.day: s.model_copy(update={"distance_km": 5.0, "duration_minutes": None})
                if s.workout_type != "rest" else s for s in c.weekly_plan.sessions}
    sessions["friday"] = quality
    plan = c.weekly_plan.model_copy(update={"allow_intensity": False, "target_basis": "distance", "planned_km": 40.0,
                                            "sessions": tuple(sessions[d] for d in DAYS)})
    ref = date.fromisoformat(plan.reference_date.isoformat())
    new, _ = apply_weekly_budget(plan, [], ref, plan_goal=c.plan_goal, periodization=c.periodization)
    fri = next(s for s in new.sessions if s.day == "friday")
    assert fri.workout_type != "quality" and fri.intensity_class != "high"
    if fri.workout_type != "rest":
        structured = build_structured_workout_prescription(
            workout=fri, plan_goal=c.plan_goal, periodization=c.periodization)
        assert structured.quality_kind is None
        assert all(step.repetitions == 1 and step.recovery is None for step in structured.steps)
        assert structured.workout_type == fri.workout_type


def test_post_race_exemption_requires_every_structured_signal():
    from training_v2.workout_generator import is_post_race_recovery
    rec = _workout(3.5, "recovery").model_copy(update={"reason_codes": ("POST_RACE_RECOVERY",)})
    assert is_post_race_recovery(rec, RACE_PASSED)
    assert not is_post_race_recovery(rec.model_copy(update={"reason_codes": ()}), RACE_PASSED)
    assert not is_post_race_recovery(rec, NO_RACE) and not is_post_race_recovery(rec, None)
    assert not is_post_race_recovery(rec.model_copy(update={"workout_type": "easy"}), RACE_PASSED)
    # The generator never emits the code today: the exception stays inactive.
    import inspect, training_v2.workout_generator as g
    src = inspect.getsource(g)
    assert src.count('"POST_RACE_RECOVERY"') == 1 and "POST_RACE_RECOVERY_CODE" in src


def test_property_forbidden_intensity_leaves_no_modifiable_quality():
    rng = random.Random(7)
    for _ in range(300):
        ref, sess, acts = _random_case(rng)
        if not sess:
            continue
        plan = _no_intensity(_plan(sess, ref))
        new, b = apply_weekly_budget(plan, acts, ref)
        ran_today = any(a.start_time[:10] == ref.isoformat() for a in acts)
        for s in new.sessions:
            i = DAYS.index(s.day)
            if i > ref.weekday() or (i == ref.weekday() and not ran_today):
                assert s.workout_type != "quality"
        for s in new.sessions:
            assert len(s.reason_codes) == len(set(s.reason_codes))
        assert len(b.reason_codes) == len(set(b.reason_codes))
