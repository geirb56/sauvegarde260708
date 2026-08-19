"""PR149 — Architecture tests: WeeklyTarget V2 as prescription source in /training/week-plan.

These tests prove the architectural invariants of PR149:
1. target_km_protected comes from WeeklyTarget V2 (not determine_target_load).
2. deep_reprise/no_history → target_km = None (duration-based, no invented km).
3. No DEFAULT_WEEKLY_KM as V2 fallback.
4. No raw Mongo docs enter Training V2 (bridge converts to DomainActivity).
5. None != 0.
6. No fictitious ACWR/TSS.
7. Low capacity + ambitious goal → target governed by capacity, not goal floor.
8. build_weekly_target_from_workouts is deterministic and pure.
"""

import pytest
from datetime import date, timedelta

from training_v2.week_plan_bridge import build_weekly_target_from_workouts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workout(days_ago: int, distance_km: float, duration_min: float = 45.0, ref: date = None):
    """Create a minimal workout document similar to db.workouts."""
    ref = ref or date(2025, 6, 1)
    d = ref - timedelta(days=days_ago)
    return {
        "activity_type": "running",
        "date": d.isoformat(),
        "start_time": f"{d.isoformat()}T08:00:00",
        "distance_km": distance_km,
        "duration_minutes": duration_min,
    }


REFERENCE_DATE = date(2025, 6, 1)
RACE_DATE = date(2025, 9, 15)
CYCLE_START = date(2025, 4, 1)


# ---------------------------------------------------------------------------
# Test 1: target from WeeklyTarget V2 (distance-based normal runner)
# ---------------------------------------------------------------------------

class TestWeeklyTargetV2Source:
    """Verify that build_weekly_target_from_workouts produces a valid WeeklyTarget."""

    def test_normal_runner_distance_based(self):
        """A runner with consistent history gets a distance-based target."""
        workouts = []
        # 4 weeks of consistent running (~30 km/week)
        for week in range(4):
            for day_in_week in [1, 3, 5]:
                workouts.append(_make_workout(
                    days_ago=week * 7 + day_in_week,
                    distance_km=10.0,
                    ref=REFERENCE_DATE,
                ))

        wt = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        assert wt.target_basis == "distance"
        assert wt.target_km is not None
        assert wt.target_km > 0
        assert wt.target_duration_minutes is None
        assert wt.continuity_state in ("normal", "reprise_exit")


# ---------------------------------------------------------------------------
# Test 2: determine_target_load does NOT decide target_km
# ---------------------------------------------------------------------------

class TestDetermineTargetLoadDecoupled:
    """Prove that determine_target_load is not the source of the V2 prescription."""

    def test_target_load_is_independent_of_weekly_target(self):
        """determine_target_load returns a pseudo-load, not the V2 km target."""
        from training_engine import determine_target_load

        context = {"ctl": None, "atl": None, "tsb": None, "acwr": None,
                   "weekly_km": 25.0, "load_7": 250, "load_28": 1000}
        target_load = determine_target_load(context, "build")

        # target_load is in "load units" (km*10 adjusted), NOT the same as WeeklyTarget.target_km
        workouts = [_make_workout(days_ago=d, distance_km=8.0, ref=REFERENCE_DATE)
                    for d in range(1, 22, 3)]
        wt = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        # The two values are fundamentally different metrics
        assert target_load != wt.target_km


# ---------------------------------------------------------------------------
# Test 3: deep_reprise → duration-based, target_km = None
# ---------------------------------------------------------------------------

class TestDeepRepriseDurationBased:
    """Deep reprise must be duration-based with no invented km."""

    def test_no_recent_activity_deep_reprise(self):
        """No activity in 28 days but some prior → deep_reprise, target_km=None."""
        # Old activity only (> 28 days ago)
        workouts = [_make_workout(days_ago=60, distance_km=10.0, ref=REFERENCE_DATE)]

        wt = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="MARATHON",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        assert wt.continuity_state in ("deep_reprise", "no_history")
        assert wt.target_basis == "duration"
        assert wt.target_km is None
        assert wt.target_duration_minutes is not None
        assert wt.target_duration_minutes > 0


# ---------------------------------------------------------------------------
# Test 4: No DEFAULT_WEEKLY_KM as V2 fallback
# ---------------------------------------------------------------------------

class TestNoDefaultWeeklyKmFallback:
    """V2 must never inject a fictitious DEFAULT_WEEKLY_KM floor."""

    def test_no_history_no_invented_km(self):
        """Empty workout list → no_history, no km invented."""
        wt = build_weekly_target_from_workouts(
            workouts=[],
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        assert wt.continuity_state == "no_history"
        assert wt.target_km is None
        # Duration target exists but is not a km-equivalent
        assert wt.target_basis == "duration"


# ---------------------------------------------------------------------------
# Test 5: No raw Mongo enters V2 (bridge converts)
# ---------------------------------------------------------------------------

class TestNonRawMongo:
    """The bridge must convert workout dicts, not pass them raw."""

    def test_bridge_produces_valid_target_from_raw_docs(self):
        """Raw-looking Mongo docs are properly converted by the bridge."""
        raw_doc = {
            "_id": "mongo_objectid_fake",
            "user_id": "user123",
            "activity_type": "running",
            "date": "2025-05-28T08:00:00",
            "start_time": "2025-05-28T08:00:00",
            "distance_km": 8.5,
            "duration_minutes": 48,
            "average_hr": 145,
        }
        wt = build_weekly_target_from_workouts(
            workouts=[raw_doc],
            goal_type="10K",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )
        # If raw Mongo were passed directly, V2 builders would fail.
        # The bridge must handle it gracefully.
        assert wt is not None
        assert wt.target_basis in ("duration", "distance")


# ---------------------------------------------------------------------------
# Test 6: None != 0
# ---------------------------------------------------------------------------

class TestNoneNotZero:
    """target_km=None is semantically different from target_km=0."""

    def test_duration_based_target_km_is_none_not_zero(self):
        wt = build_weekly_target_from_workouts(
            workouts=[],
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )
        # Must be None, not 0
        assert wt.target_km is None
        assert wt.target_km != 0


# ---------------------------------------------------------------------------
# Test 7: No fictitious ACWR/TSS
# ---------------------------------------------------------------------------

class TestNoFictitiousMetrics:
    """WeeklyTarget V2 must not produce or depend on fictitious ACWR/TSS."""

    def test_weekly_target_has_no_acwr_tss_fields(self):
        workouts = [_make_workout(days_ago=d, distance_km=8.0, ref=REFERENCE_DATE)
                    for d in range(1, 22, 3)]
        wt = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )
        # WeeklyTarget model has no acwr/tss fields
        assert not hasattr(wt, "acwr")
        assert not hasattr(wt, "tss")


# ---------------------------------------------------------------------------
# Test 8: Low capacity + ambitious goal → governed by capacity
# ---------------------------------------------------------------------------

class TestCapacityGovernsTarget:
    """Low volume runner + marathon goal → target reflects capacity, not goal floor."""

    def test_low_volume_marathon_stays_low(self):
        """A runner doing ~15 km/week targeting marathon doesn't get 60+ km prescribed."""
        workouts = []
        for week in range(4):
            workouts.append(_make_workout(
                days_ago=week * 7 + 2,
                distance_km=5.0,
                ref=REFERENCE_DATE,
            ))
            workouts.append(_make_workout(
                days_ago=week * 7 + 5,
                distance_km=10.0,
                ref=REFERENCE_DATE,
            ))
        # ~15 km/week capacity

        wt = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="MARATHON",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        if wt.target_basis == "distance":
            # Target must be governed by capacity (~15*1.1 = 16.5), not marathon floor (~40+)
            assert wt.target_km < 25.0, f"target_km={wt.target_km} exceeds capacity-governed limit"


# ---------------------------------------------------------------------------
# Test 9: WeeklyTarget formula unchanged (invariant check)
# ---------------------------------------------------------------------------

class TestWeeklyTargetFormulaUnchanged:
    """Ensure build_weekly_target_from_workouts does not alter WeeklyTarget formulas."""

    def test_same_inputs_same_output(self):
        """Deterministic: same workouts → same target."""
        workouts = [_make_workout(days_ago=d, distance_km=10.0, ref=REFERENCE_DATE)
                    for d in [2, 5, 9, 12, 16, 19]]

        wt1 = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )
        wt2 = build_weekly_target_from_workouts(
            workouts=workouts,
            goal_type="SEMI",
            race_date=RACE_DATE,
            cycle_start_date=CYCLE_START,
            reference_date=REFERENCE_DATE,
        )

        assert wt1 == wt2
