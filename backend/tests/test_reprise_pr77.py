"""PR77 — Reprise after a break (comeback) — permanent regression tests.

Covers the mandatory scenarios:
  1. 0 km over 28 days after 4 weeks off (deep reprise).
  2. S1 -> S2 -> S3 comeback progression without plan collapse.
  3. Long run never disproportionate vs the prescribed weekly volume.
  4. Partial reprise after a break.
  5. Abrupt overload after a comeback.
  6. Normal trained athlete: no regression.
  7. Volume and intensity never increase simultaneously during reprise.

These drive the REAL engine (coach_service.generate_dynamic_training_plan) via a
fake async DB, so the whole path (classification -> target -> week structure) is
exercised end to end.
"""

import asyncio
from datetime import datetime, timezone, timedelta

import coach_service
from coach_service import generate_dynamic_training_plan
from tests.test_real_cache_bypass_pr76 import _FakeDB, _FakeCollection

HARD_TYPES = {"threshold", "tempo", "fartlek", "intervals"}


def _runs(items):
    """items: list of (total_km, [days_ago]) -> running workouts at 6:00/km."""
    now = datetime.now(timezone.utc)
    out = []
    for total, days in items:
        per = total / len(days)
        for d in days:
            out.append({
                "type": "running",
                "distance_km": per,
                "moving_time": int(per * 6 * 60),
                "date": (now - timedelta(days=d)).isoformat(),
            })
    return out


async def _plan(workouts, goal="SEMI"):
    coach_service.clear_cache()
    db = _FakeDB(workouts)
    db.training_cycles = _FakeCollection(single={"user_id": "u1", "goal": goal})
    r = await generate_dynamic_training_plan(db, "u1")
    p = r["plan"]
    return {
        "state": r["context"].get("training_state"),
        "weekly": p["weekly_km"],
        "longest": max((s.get("distance_km", 0) for s in p["sessions"]), default=0),
        "types": [s["type"] for s in p["sessions"] if s["type"] != "rest"],
        "sessions": p["sessions"],
    }


def _has_hard(types):
    return any(t in HARD_TYPES for t in types)


# 1. Deep reprise: 0 km over 28 days.
def test_deep_reprise_zero_km_is_easy_and_duration_based():
    async def _run():
        for goal in ("5K", "10K", "SEMI", "MARATHON"):
            res = await _plan(_runs([]), goal)
            assert res["state"] == "deep_reprise", f"{goal}: expected deep_reprise, got {res['state']}"
            assert not _has_hard(res["types"]), f"{goal}: deep reprise must have NO hard sessions."
            assert res["weekly"] <= 15, f"{goal}: deep reprise weekly ({res['weekly']}) must stay conservative."
            # Duration-based: session details expressed in minutes with run/walk.
            run_sessions = [s for s in res["sessions"] if s["type"] != "rest"]
            assert all("min" in s["duration"] for s in run_sessions)
            assert any("marche" in s["details"].lower() for s in run_sessions), "run/walk option expected"
    asyncio.run(_run())


# 2. S1 -> S2 -> S3 progression must not collapse.
def test_reprise_progression_s1_s2_s3():
    async def _run():
        s1 = await _plan(_runs([]))                                  # week 1: nothing yet
        s2 = await _plan(_runs([(12.6, [1, 3, 5, 6])]))              # week 2: did ~12.6 last 7d
        s3 = await _plan(_runs([(12.6, [8, 10, 12, 13]), (14, [1, 3, 5, 6])]))  # week 3
        assert s2["weekly"] >= s1["weekly"], "S2 must not collapse below S1."
        assert s3["weekly"] >= s2["weekly"] - 0.5, "S3 must keep progressing (no regression)."
        assert s2["state"] == "partial_reprise" and s3["state"] == "partial_reprise"
    asyncio.run(_run())


# 3. Long run never disproportionate.
def test_long_run_never_disproportionate():
    async def _run():
        scenarios = [
            _runs([]),                                   # deep reprise
            _runs([(12.6, [1, 3, 5, 6])]),               # partial reprise
            _runs([(30, [24, 26]), (30, [17, 19]), (30, [10, 12]), (30, [2, 4])]),  # normal
        ]
        for w in scenarios:
            for goal in ("5K", "SEMI", "MARATHON"):
                res = await _plan(w, goal)
                assert res["longest"] <= res["weekly"] * 0.50 + 0.2, (
                    f"{goal}: long run {res['longest']} disproportionate vs weekly {res['weekly']}."
                )
    asyncio.run(_run())


# 4. Partial reprise (recent km but big drop) -> resume guard + easy.
def test_partial_reprise_after_break():
    async def _run():
        # chronic ~40 (weeks 2-4) but last week dropped to 15.
        w = _runs([(40, [24, 26]), (40, [17, 19]), (40, [10, 12]), (15, [2, 4])])
        res = await _plan(w, "SEMI")
        assert res["state"] in ("partial_reprise", "reprise_exit"), res["state"]
        assert not _has_hard(res["types"]) if res["state"] == "partial_reprise" else True
    asyncio.run(_run())


# 5. Abrupt overload after a comeback must be dampened, not validated.
def test_abrupt_overload_is_dampened():
    async def _run():
        # week 1 done (12.6), athlete suddenly runs 40 km the next week.
        w = _runs([(12.6, [8, 10, 12, 13]), (40, [1, 2, 4, 6])])
        res = await _plan(w, "SEMI")
        # Active-week average dampens the spike: target must stay well below 40.
        assert res["weekly"] <= 32, f"Overload must be dampened, got weekly={res['weekly']}."
    asyncio.run(_run())


# 6. Normal trained athlete: no regression.
def test_normal_athlete_no_regression():
    async def _run():
        cases = {"SEMI": (50, 55), "MARATHON": (80, 88), "10K": (40, 44)}
        for goal, (chronic, expected) in cases.items():
            w = _runs([(chronic, [24, 26]), (chronic, [17, 19]), (chronic, [10, 12]), (chronic, [2, 4])])
            res = await _plan(w, goal)
            assert res["state"] == "normal", f"{goal}: expected normal, got {res['state']}"
            assert abs(res["weekly"] - expected) <= 1.5, f"{goal}: weekly {res['weekly']} != ~{expected}"
            assert _has_hard(res["types"]), f"{goal}: normal plan must keep intensity."
    asyncio.run(_run())


# 7. Volume and intensity never increase simultaneously.
def test_volume_and_intensity_not_simultaneous():
    async def _run():
        # During reprise: intensity frozen (easy only) while volume grows.
        s2 = await _plan(_runs([(12.6, [1, 3, 5, 6])]))
        assert not _has_hard(s2["types"]), "Reprise weeks must stay easy (no intensity)."
        # Exit week: intensity is (re)introduced but volume is HELD (not grown).
        exit_w = _runs([(12, [15, 17, 19]), (13, [8, 10, 12]), (14, [1, 3, 5])])
        ex = await _plan(exit_w)
        assert ex["state"] == "reprise_exit", f"expected reprise_exit, got {ex['state']}"
        assert _has_hard(ex["types"]), "Exit week must (re)introduce intensity."
        # Volume held: exit weekly must not exceed the last reprise week's volume.
        assert ex["weekly"] <= 15.5, f"Exit week must hold volume, got {ex['weekly']}."
    asyncio.run(_run())


if __name__ == "__main__":
    for fn in [
        test_deep_reprise_zero_km_is_easy_and_duration_based,
        test_reprise_progression_s1_s2_s3,
        test_long_run_never_disproportionate,
        test_partial_reprise_after_break,
        test_abrupt_overload_is_dampened,
        test_normal_athlete_no_regression,
        test_volume_and_intensity_not_simultaneous,
    ]:
        fn()
        print(f"PASSED {fn.__name__}")
