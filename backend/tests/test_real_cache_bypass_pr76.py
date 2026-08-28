"""PR76 — REAL-PATH verification of the resume-guard cache bypass.

Unlike test_resume_guard_pr76.py (which simulates the fallback and hard-codes
44 km), this test drives the REAL coach_service.generate_dynamic_training_plan
function and its REAL in-memory _plan_cache:

  1. First call: athlete active (km_7 = 40, chronic = 40) → target 44 km.
     A ~44 km plan is generated and stored in _plan_cache.
  2. Second call: athlete resuming (km_7 = 15, chronic = 40) → resume guard
     caps target_km_protected at 42 km. The cache_key is identical (same
     week/phase/goal/vma), so the stale 44 km plan is in the cache.
  3. The cache MUST be bypassed and the returned plan MUST be <= 42 km.
"""

import asyncio
from datetime import datetime, timezone, timedelta

import coach_service
from coach_service import generate_dynamic_training_plan


def _mk_workouts(recent7_total_km: float, older_total_km: float):
    """Build running workouts: `recent7_total_km` inside last 7 days,
    `older_total_km` between day 8 and day 28. All at pace 6:00/km so the
    computed VMA (and therefore the cache_key) is identical across calls."""
    now = datetime.now(timezone.utc)
    workouts = []

    def add(distance_km, days_ago):
        workouts.append({
            "type": "running",
            "distance_km": distance_km,
            "moving_time": int(distance_km * 6 * 60),  # 6:00/km
            "date": (now - timedelta(days=days_ago)).isoformat(),
        })

    # 4 runs inside last 7 days
    per = recent7_total_km / 4
    for d in (1, 2, 4, 6):
        add(per, d)
    # 4 runs between day 8 and 28
    per_old = older_total_km / 4
    for d in (9, 14, 20, 26):
        add(per_old, d)
    return workouts


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return self._docs[:n]


class _FakeCollection:
    def __init__(self, workouts=None, single=None):
        self._workouts = workouts or []
        self._single = single

    def find(self, query, projection=None):
        gte = query.get("date", {}).get("$gte") or query.get("start_time", {}).get("$gte")
        if gte is None:
            return _FakeCursor(list(self._workouts))
        return _FakeCursor([
            w for w in self._workouts
            if (w.get("date") or w.get("start_time")) >= gte
        ])

    async def find_one(self, query):
        return self._single

    async def insert_one(self, doc):
        return None

    async def update_one(self, *a, **k):
        return None


class _FakeDB:
    def __init__(self, workouts):
        self.workouts = _FakeCollection(workouts=workouts)
        self.garmin_activities = _FakeCollection(workouts=[
            {
                "user_id": "u1",
                "activity_type": w.get("activity_type") or w.get("type") or "running",
                "start_time": w.get("start_time") or w.get("date"),
                "distance_m": (w.get("distance_km") or 0) * 1000.0 if w.get("distance_km") else w.get("distance_m"),
                "duration_s": w.get("moving_time") or w.get("elapsed_time") or w.get("duration_s"),
                "source": "garmin",
                "source_activity_id": w.get("id"),
            }
            for w in workouts
        ])
        self.training_prefs = _FakeCollection(single={"user_id": "u1", "sessions_per_week": 4})
        self.training_cycles = _FakeCollection(single={"user_id": "u1", "goal": "MARATHON"})
        self.user_goals = _FakeCollection(single=None)  # no event_date -> active week 1


def test_real_cache_bypass_44_to_42():
    coach_service.clear_cache()

    async def _run():
        # 1) Active athlete: km_7 = 40, chronic = 40 -> target 44, no guard.
        db1 = _FakeDB(_mk_workouts(recent7_total_km=40, older_total_km=120))
        r1 = await generate_dynamic_training_plan(db1, "u1")
        v1 = r1["plan"]["weekly_km"]
        t1 = r1["debug_volume"]["target_km"]
        print(f"[call1] target_km={t1}  plan.weekly_km={v1}")
        assert t1 == 44, f"call1 target must be 44, got {t1}"
        # Plan should be cached now.
        assert len(coach_service._plan_cache) == 1, "call1 must populate the cache"

        # 2) Resuming athlete: km_7 = 15, chronic = 40 -> guard caps at 42.
        db2 = _FakeDB(_mk_workouts(recent7_total_km=15, older_total_km=145))
        r2 = await generate_dynamic_training_plan(db2, "u1")
        v2 = r2["plan"]["weekly_km"]
        t2 = r2["debug_volume"]["target_km"]
        print(f"[call2] target_km={t2}  plan.weekly_km={v2}")

        # target_km_protected recomputed server-side must be 42.
        assert t2 == 42, f"call2 target_km_protected must be 42, got {t2}"
        # THE REAL PATH: cache must be bypassed -> regenerated plan capped at 42.
        # The generator normalizes rounding drift so the total matches exactly.
        assert v2 <= 42, (
            f"REAL cache bypass FAILED: returned plan weekly_km={v2} > 42 "
            f"(stale cached plan of {v1} km was served instead of regenerating)"
        )
        assert v2 < v1, f"Regenerated plan ({v2}) must be smaller than the stale cache ({v1})."

    asyncio.run(_run())


def test_real_reprise_zero_km_is_conservative_and_coherent():
    """Athlete resuming after 4 weeks of rest (0 km over 28 days).

    - The chronic base must NOT default to 20 km/week: a conservative reprise
      base is used so the weekly target stays low (~12.6 km).
    - The long run must NOT dominate the week: it is capped at 40 % of target.
    """
    async def _run():
        for goal in ("5K", "10K", "SEMI", "MARATHON"):
            coach_service.clear_cache()
            db = _FakeDB([])  # zero workouts anywhere
            db.training_cycles = _FakeCollection(single={"user_id": "u1", "goal": goal})
            r = await generate_dynamic_training_plan(db, "u1")
            plan = r["plan"]
            weekly = plan["weekly_km"]
            longest = max((s.get("distance_km", 0) for s in plan["sessions"]), default=0)
            print(f"[{goal}] target={r['debug_volume']['target_km']} weekly={weekly} longest={longest}")
            # Conservative reprise: far below the old 21 km default output.
            assert weekly <= 15, f"{goal}: reprise weekly ({weekly}) must be conservative (<=15)."
            # Long run must never dominate: <= 45 % of the weekly volume.
            assert longest <= weekly * 0.45 + 0.1, (
                f"{goal}: long run ({longest}) must not dominate the week ({weekly})."
            )

    asyncio.run(_run())


def test_real_week2_comeback_progresses_not_regresses():
    """Week 2 of a comeback must PROGRESS, not collapse.

    After completing week 1 (~12.6 km in the last 7 days) with no data before,
    the fixed /4 divisor of compute_current_weekly_km would dilute the base to
    ~3 km and prescribe a 3 km week. The active-weeks base must instead keep the
    base near the real recent volume so week 2 progresses by ~+10 %.
    """
    from datetime import datetime, timezone, timedelta

    def _week1_runs():
        now = datetime.now(timezone.utc)
        return [
            {"type": "running", "distance_km": 3.15, "moving_time": int(3.15 * 6 * 60),
             "date": (now - timedelta(days=d)).isoformat()}
            for d in (1, 3, 5, 6)  # 4 x 3.15 = 12.6 km, all within last 7 days
        ]

    async def _run():
        coach_service.clear_cache()
        db = _FakeDB(_week1_runs())
        db.training_cycles = _FakeCollection(single={"user_id": "u1", "goal": "SEMI"})
        r = await generate_dynamic_training_plan(db, "u1")
        target = r["debug_volume"]["target_km"]
        weekly = r["plan"]["weekly_km"]
        print(f"[week2] target={target} weekly={weekly}")
        # Must not regress below what was just done (12.6 km) and must progress.
        assert target >= 12.6, f"Week 2 must not regress below week 1 (12.6). Got {target}."
        assert target <= 12.6 * 1.10 + 0.5, f"Week 2 progression must stay ~+10%. Got {target}."

    asyncio.run(_run())


if __name__ == "__main__":
    test_real_cache_bypass_44_to_42()
    print("PASSED")
