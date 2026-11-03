"""P384 final — snapshot selection (Today/Week) and unplanned-intensity protection."""
import asyncio
from datetime import date, datetime, timedelta

from training_v2.domain_activity import DomainActivity
from training_v2.snapshot_selection import (
    frozen_sessions_from_snapshots,
    load_authoritative_week_snapshots,
    select_authoritative_week_snapshots,
    week_prescription_ids,
)
from training_v2.week_execution import prescription_id_for
from training_v2.weekly_budget import apply_weekly_budget
from training_v2.workout_generator import WeeklyPlan, WorkoutPrescription

WED = date(2026, 3, 11)
MON = date(2026, 3, 9)
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _doc(user, d, *, wt="easy", km=6.0, served_ref="same", served_at=None):
    day = DAYS[d.weekday()]
    return {
        "user_id": user,
        "prescription_id": prescription_id_for(user, d, day),
        "planned_date": d.isoformat(),
        "served_reference_date": d.isoformat() if served_ref == "same" else served_ref,
        "day": day, "workout_type": wt, "intensity_class": "low",
        "distance_km": km, "duration_minutes": None,
        "reason_codes": ["X"], "served_at": served_at,
    }


class _Cursor:
    def __init__(self, docs): self.docs = docs
    async def to_list(self, n): return self.docs[:n]


class _Col:
    def __init__(self, docs): self.docs = docs; self.queries = []
    def find(self, q, proj=None):
        self.queries.append(q)
        out = []
        for d in self.docs:
            if d["user_id"] != q["user_id"]:
                continue
            if d["prescription_id"] not in q["prescription_id"]["$in"]:
                continue
            if not (q["planned_date"]["$gte"] <= d["planned_date"] <= q["planned_date"]["$lte"]):
                continue
            out.append(dict(d))
        return _Cursor(out)


class _Db:
    def __init__(self, docs): self.training_prescription_snapshots = _Col(docs)


def _load(docs, user="u1", ref=WED):
    db = _Db(docs)
    return asyncio.run(load_authoritative_week_snapshots(db, user_id=user, reference_date=ref)), db


def test_no_snapshot_and_past_snapshot():
    snaps, _ = _load([])
    assert snaps == {}
    snaps, _ = _load([_doc("u1", MON)])
    assert list(snaps) == [prescription_id_for("u1", MON, "monday")]


def test_future_served_snapshot_is_not_authoritative():
    snaps, _ = _load([_doc("u1", WED + timedelta(days=2))])
    assert snaps == {}


def test_incoherent_provenance_is_not_authoritative():
    snaps, _ = _load([_doc("u1", MON, served_ref=WED.isoformat())])
    assert snaps == {}


def test_more_than_1000_historical_snapshots_do_not_hide_the_week():
    hist = [_doc("u1", date(2022, 1, 1) + timedelta(days=i)) for i in range(1200)]
    snaps, db = _load(hist + [_doc("u1", MON, km=9.0)])
    assert snaps[prescription_id_for("u1", MON, "monday")].distance_km == 9.0
    q = db.training_prescription_snapshots.queries[0]
    assert q["user_id"] == "u1" and len(q["prescription_id"]["$in"]) == 7


def test_two_users_never_mix():
    docs = [_doc("u1", MON, km=5.0), _doc("u2", MON, km=11.0)]
    s1, _ = _load(docs, "u1")
    s2, _ = _load(docs, "u2")
    assert next(iter(s1.values())).distance_km == 5.0
    assert next(iter(s2.values())).distance_km == 11.0


def test_duplicates_deterministic_and_authoritative_never_replaced():
    early = _doc("u1", MON, km=5.0, served_at="2026-03-09T06:00:00")
    late = _doc("u1", MON, km=8.0, served_at="2026-03-09T18:00:00")
    bad = _doc("u1", MON, km=99.0, served_ref="2026-03-12", served_at="2026-03-10T00:00:00")
    for order in ([early, late, bad], [bad, late, early], [late, bad, early]):
        out = select_authoritative_week_snapshots(order, user_id="u1", week_start=MON, reference_date=WED)
        assert next(iter(out.values())).distance_km == 5.0


def test_repeated_selection_is_identical_for_today_and_week():
    docs = [_doc("u1", MON, km=5.0), _doc("u1", MON + timedelta(days=1), km=7.0)]
    a, _ = _load(docs)
    b, _ = _load(docs)
    assert a == b
    assert frozen_sessions_from_snapshots(a) == frozen_sessions_from_snapshots(b)
    assert len(week_prescription_ids("u1", MON)) == 7


def test_frozen_sessions_copy_snapshot_as_served():
    snaps, _ = _load([_doc("u1", MON, wt="quality", km=7.5)])
    fs = frozen_sessions_from_snapshots(snaps)
    assert fs["monday"].workout_type == "quality" and fs["monday"].distance_km == 7.5
    assert fs["monday"].reason_codes == ("X",)


# ---- intensity ------------------------------------------------------------

def _run(d, km, aid, vig=None):
    return DomainActivity(
        activity_type="running", start_time=f"{d.isoformat()}T07:00:00", distance_m=km * 1000,
        duration_s=km * 360, source="garmin", source_activity_id=aid,
        vigorous_intensity_minutes=vig,
    )


def _plan(sessions):
    out = []
    for d in DAYS:
        t, km = sessions.get(d, ("rest", None))
        out.append(WorkoutPrescription(
            day=d, workout_type=t, intensity_class={"rest": "rest", "quality": "high"}.get(t, "low"),
            distance_km=km, duration_minutes=None, reason_codes=(),
        ))
    train = [s for s in out if s.workout_type != "rest"]
    return WeeklyPlan(
        reference_date=WED, sessions=tuple(out), target_basis="distance",
        planned_km=sum(s.distance_km for s in train), planned_duration_minutes=None,
        session_count=len(train), allow_intensity=True, reason_codes=(),
    )


# Mon easy (off-plan intense run happens here), Tue quality, Thu quality(future)
P = {"monday": ("easy", 6.0), "tuesday": ("quality", 7.0), "thursday": ("quality", 7.0),
     "saturday": ("easy", 6.0), "sunday": ("long_easy", 10.0)}


def _types(plan):
    return {s.day: s.workout_type for s in plan.sessions}


def test_easy_off_plan_run_changes_nothing():
    plan = _plan(P)
    new2, b2 = apply_weekly_budget(plan, [_run(MON, 4.0, "a", vig=0.0)], WED)
    assert _types(new2) == _types(plan) and b2.unplanned_intensity_evidence == "none_known"


def test_vigorous_minutes_alone_do_not_adapt_and_are_flagged_unconfirmed():
    plan = _plan(P)
    new, b = apply_weekly_budget(plan, [_run(MON, 8.0, "a", vig=25.0)], WED)
    assert _types(new)["thursday"] == "quality"
    assert b.unplanned_intensity_evidence == "present_unverified"
    assert "INTENSITY_CONFIRMATION_UNAVAILABLE" in b.reason_codes


def test_confirmed_intense_run_prevents_duplication_planned_quality_missed_not_counted():
    plan = _plan(P)
    # Tuesday quality planned but NOT run; Monday confirmed off-plan intense run.
    new, b = apply_weekly_budget(plan, [_run(MON, 8.0, "a", vig=25.0)], WED, confirmed_intense_days={MON})
    assert b.unplanned_intensity_evidence == "confirmed"
    # planned_total=2, done=0 (Tuesday missed), off-plan=1 -> 1 quality allowed, pending=1 (Thu)
    assert _types(new)["thursday"] == "quality"
    new, _ = apply_weekly_budget(plan, [_run(MON, 8.0, "a", vig=25.0), _run(MON + timedelta(days=1), 7.0, "b", vig=20.0)],
                                 WED, confirmed_intense_days={MON})
    # Tuesday quality done + Monday confirmed = 2 done -> Thursday quality downgraded, never added
    assert _types(new)["thursday"] == "easy"
    assert "QUALITY_NOT_DUPLICATED_AFTER_CONFIRMED_INTENSE_RUN" in _.reason_codes
    assert sum(1 for s in new.sessions if s.workout_type == "quality") <= 2


def test_planned_quality_already_done_without_off_plan_run_is_untouched():
    plan = _plan(P)
    new, _ = apply_weekly_budget(plan, [_run(MON + timedelta(days=1), 7.0, "b", vig=20.0)], WED)
    assert _types(new)["thursday"] == "quality"


def test_frozen_future_quality_is_never_modified_and_reason_given():
    plan = _plan(P)
    thu = next(s for s in plan.sessions if s.day == "thursday")
    acts = [_run(MON, 8.0, "a", vig=25.0), _run(MON + timedelta(days=1), 7.0, "b", vig=20.0)]
    new, b = apply_weekly_budget(plan, acts, WED, confirmed_intense_days={MON}, frozen_sessions={"thursday": thu})
    assert next(s for s in new.sessions if s.day == "thursday") == thu
    assert "QUALITY_DUPLICATION_NOT_ADAPTABLE" in b.reason_codes


def test_two_activities_same_day_and_absent_intensity_data():
    plan = _plan(P)
    acts = [_run(MON, 5.0, "a"), _run(MON, 4.0, "b")]
    new, b = apply_weekly_budget(plan, acts, WED)
    assert b.actual_weekly_km == 9.0 and b.unplanned_intensity_evidence == "unknown"
    assert _types(new) == _types(plan)


def test_weekly_target_stable_across_the_week_and_with_current_week_activity():
    from test_weekly_volume_trajectory import _canonical, _history
    hist = _history([30] * 6)
    race = WED + timedelta(weeks=12)
    mid = _canonical(hist, race=race, ref=WED).original_target.target_km
    extra = hist + [_run(MON, 12.0, "cur1"), _run(MON + timedelta(days=1), 5.0, "cur2")]
    assert _canonical(extra, race=race, ref=WED).original_target.target_km == mid
    # Later in the week (continuity kept alive by a Friday run) the target does not drift.
    later = extra + [_run(MON + timedelta(days=4), 6.0, "cur3")]
    assert _canonical(later, race=race, ref=WED + timedelta(days=3)).original_target.target_km == mid
