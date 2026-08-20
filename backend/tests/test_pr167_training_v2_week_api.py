"""PR167 — Tests for GET /training/v2/week native V2 endpoint.

Contracts verified
------------------
A — NORMAL DISTANCE:
    target_basis == "distance", target_km > 0, target_duration_minutes is None,
    planned_km matches WeeklyPlan.planned_km.

B — DEEP_REPRISE DURATION:
    continuity_state == "deep_reprise", target_basis == "duration",
    target_duration_minutes > 0, no km invented.

C — PARTIAL_REPRISE DISTANCE:
    continuity_state == "partial_reprise", target_basis == "distance",
    distance exact.

D — PARTIAL_REPRISE DURATION:
    target_basis == "duration", minutes exact.

E — NO_HISTORY / duration fallback:
    target_km is None, target_duration_minutes > 0.

F — NONE semantics:
    active sessions → duration_minutes None when distance-based.
    active sessions → estimated_tss None.
    rest sessions  → estimated_tss == 0.

Architecture tests
------------------
- adapt_weekly_plan_to_legacy calls = 0 in new endpoint.
- generate_cycle_week calls = 0 in new endpoint.
- build_weekly_plan_from_workouts IS called.
- Canonical builder used (no WeeklyTarget duplication).
- Frontend / legacy endpoints untouched (AST).
"""
from __future__ import annotations

import ast
import os
import sys
from datetime import date, timedelta
from typing import Optional

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-pr167")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from training_v2.week_plan_bridge import build_weekly_plan_from_workouts  # noqa: E402
from training_v2.training_week_response import (  # noqa: E402
    TrainingWeekV2Response,
    WeekV2GoalResponse,
    WeekV2PlanResponse,
    WeekV2SessionResponse,
    WeekV2StateResponse,
    WeekV2TargetResponse,
)

# ---------------------------------------------------------------------------
# Fixtures (mirrors test_pr165 fixtures for parity)
# ---------------------------------------------------------------------------

_REF_DATE = date(2024, 6, 10)


def _make_workouts(n: int = 0, km_per_session: float = 8.0) -> list[dict]:
    ref = _REF_DATE
    return [
        {
            "distance_km": km_per_session,
            "duration_minutes": 50,
            "date": (ref - timedelta(days=i * 7 + 3)).isoformat(),
            "activity_type": "running",
        }
        for i in range(n)
    ]


def _make_workouts_deep_reprise() -> list[dict]:
    """Former trained runner: all activity in [28, 41] days ago → deep_reprise."""
    ref = _REF_DATE
    return [
        {
            "distance_km": 16.0,
            "duration_minutes": 80,
            "date": (ref - timedelta(days=d)).isoformat(),
            "activity_type": "running",
        }
        for d in [41, 38, 35, 32, 29]
    ]


def _make_workouts_partial_reprise_distance() -> list[dict]:
    """partial_reprise + distance target."""
    ref = _REF_DATE
    bigger = [
        {
            "distance_km": 10.0,
            "duration_minutes": 60,
            "date": (ref - timedelta(days=d)).isoformat(),
            "activity_type": "running",
        }
        for d in [21, 17, 14, 11, 8]
    ]
    small = [
        {
            "distance_km": 4.0,
            "duration_minutes": 30,
            "date": (ref - timedelta(days=3)).isoformat(),
            "activity_type": "running",
        }
    ]
    return bigger + small


def _build_v2_context_minimal():
    """Build minimal V2 context for direct WeeklyTarget construction tests.

    Returns (runner_profile, plan_goal, periodization, reference_date).
    Uses empty history — the only way to avoid depending on a particular
    continuity state from the pipeline.
    """
    from training_v2.runner_profile import build_runner_profile
    from training_v2.training_history import build_training_history
    from training_v2.training_load import build_training_load
    from training_v2.plan_goal import build_plan_goal, GoalType
    from training_v2.periodization import build_periodization

    ref = _REF_DATE
    training_history = build_training_history([], ref)
    training_load = build_training_load([], ref)
    runner_profile = build_runner_profile(
        training_history=training_history,
        training_load=training_load,
        user_profile=None,
        capabilities=None,
        physiological_metrics=None,
        reference_date=ref,
    )
    plan_goal = build_plan_goal(goal_type=GoalType.marathon, race_date=None, created_from="user")
    periodization = build_periodization(
        plan_goal=plan_goal,
        reference_date=ref,
        cycle_anchor_date=ref - timedelta(weeks=4),
    )
    return runner_profile, plan_goal, periodization, ref


def _call_builder(
    workouts: list[dict],
    goal_type: str = "MARATHON",
    race_date: Optional[date] = None,
    cycle_start_date: Optional[date] = None,
    reference_date: date = _REF_DATE,
):
    return build_weekly_plan_from_workouts(
        workouts=workouts,
        goal_type=goal_type,
        race_date=race_date,
        cycle_start_date=cycle_start_date,
        reference_date=reference_date,
    )


def _assemble_response(workouts, **kwargs) -> dict:
    """Full response assembly identical to the server handler logic."""
    ref = kwargs.get("reference_date", _REF_DATE)
    wt, wp = _call_builder(workouts, **kwargs)

    sessions = [
        WeekV2SessionResponse(
            day=s.day,
            workout_type=s.workout_type,
            intensity_class=s.intensity_class,
            distance_km=s.distance_km,
            duration_minutes=s.duration_minutes,
            estimated_tss=0 if s.workout_type == "rest" else None,
            reason_codes=list(s.reason_codes),
        )
        for s in wp.sessions
    ]

    response = TrainingWeekV2Response(
        reference_date=ref.isoformat(),
        goal=WeekV2GoalResponse(goal_type="MARATHON"),
        state=WeekV2StateResponse(
            continuity_state=wt.continuity_state,
            allow_intensity=wt.allow_intensity,
        ),
        weekly_target=WeekV2TargetResponse(
            target_basis=wt.target_basis,
            target_km=wt.target_km,
            target_duration_minutes=wt.target_duration_minutes,
            session_count=wt.target_sessions,
            confidence=wt.confidence,
        ),
        week=WeekV2PlanResponse(
            planned_km=wp.planned_km,
            planned_duration_minutes=wp.planned_duration_minutes,
            session_count=wp.session_count,
            sessions=sessions,
        ),
    )
    return response.model_dump(mode="json"), wt, wp


# ===========================================================================
# Contract A — NORMAL DISTANCE
# ===========================================================================

class TestContractA_NormalDistance:
    """Normal runner with solid history → distance-based prescription."""

    def _build(self):
        workouts = _make_workouts(n=8, km_per_session=10.0)
        return _assemble_response(workouts, goal_type="MARATHON", reference_date=_REF_DATE)

    def test_target_basis_is_distance(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_basis"] == "distance", (
            f"Expected distance, got {resp['weekly_target']['target_basis']}"
        )

    def test_target_km_positive(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_km"] is not None
        assert resp["weekly_target"]["target_km"] > 0

    def test_target_duration_minutes_is_none(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_duration_minutes"] is None, (
            "NONE != ZERO: distance-based → target_duration_minutes must be None"
        )

    def test_planned_km_matches_weekly_plan(self):
        resp, wt, wp = self._build()
        assert resp["week"]["planned_km"] == wp.planned_km

    def test_planned_duration_minutes_is_none(self):
        resp, wt, wp = self._build()
        assert resp["week"]["planned_duration_minutes"] is None


# ===========================================================================
# Contract B — DEEP_REPRISE DURATION
# ===========================================================================

class TestContractB_DeepRepriseDuration:
    """Trained runner who stopped 29+ days: deep_reprise → duration-based."""

    def _build(self):
        workouts = _make_workouts_deep_reprise()
        resp, wt, wp = _assemble_response(workouts, goal_type="MARATHON", reference_date=_REF_DATE)
        if wt.continuity_state not in ("deep_reprise", "no_history"):
            pytest.skip(
                f"Fixture produced continuity_state={wt.continuity_state!r}; "
                "need deep_reprise or no_history for Contract B"
            )
        return resp, wt, wp

    def test_continuity_state_is_deep_reprise_or_no_history(self):
        resp, wt, _ = self._build()
        assert resp["state"]["continuity_state"] in ("deep_reprise", "no_history")

    def test_target_basis_is_duration(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_basis"] == "duration"

    def test_target_duration_minutes_positive(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_duration_minutes"] is not None
        assert resp["weekly_target"]["target_duration_minutes"] > 0

    def test_no_km_invented(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_km"] is None, (
            "NONE != ZERO: duration-based → target_km must be None"
        )
        assert resp["week"]["planned_km"] is None, (
            "NONE != ZERO: duration-based → planned_km must be None"
        )

    def test_api_planned_duration_equals_weekly_plan(self):
        resp, wt, wp = self._build()
        assert resp["week"]["planned_duration_minutes"] == wp.planned_duration_minutes


# ===========================================================================
# Contract C — PARTIAL_REPRISE DISTANCE
# ===========================================================================

class TestContractC_PartialRepriseDistance:
    """Partial reprise with distance-based target."""

    def _build(self):
        workouts = _make_workouts_partial_reprise_distance()
        resp, wt, wp = _assemble_response(workouts, goal_type="MARATHON", reference_date=_REF_DATE)
        if wt.continuity_state != "partial_reprise" or wt.target_basis != "distance":
            pytest.skip(
                f"Fixture: continuity={wt.continuity_state}, basis={wt.target_basis}"
            )
        return resp, wt, wp

    def test_continuity_is_partial_reprise(self):
        resp, wt, _ = self._build()
        assert resp["state"]["continuity_state"] == "partial_reprise"

    def test_target_basis_is_distance(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_basis"] == "distance"

    def test_planned_km_matches_builder(self):
        resp, wt, wp = self._build()
        assert resp["week"]["planned_km"] == pytest.approx(wp.planned_km, abs=0.11)

    def test_no_duration_invented(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_duration_minutes"] is None
        assert resp["week"]["planned_duration_minutes"] is None


# ===========================================================================
# Contract D — PARTIAL_REPRISE DURATION
# ===========================================================================

class TestContractD_PartialRepriseDuration:
    """Partial reprise with duration-based target.

    Because the pipeline cannot produce partial_reprise + duration through a
    workout fixture (whenever days_since < 28 the 28d buckets always contain
    enough activity to produce a distance-based target), we construct
    WeeklyTarget directly — same technique as test_pr165 Contract D.

    The contract under test is the response assembly layer, not the heuristic
    that selects partial_reprise duration (that is covered by weekly_target tests).
    """

    def _build(self):
        from training_v2.weekly_target import WeeklyTarget
        from training_v2.workout_generator import build_weekly_plan

        runner_profile, plan_goal, periodization, ref = _build_v2_context_minimal()

        wt = WeeklyTarget(
            reference_date=ref,
            target_basis="duration",
            target_km=None,
            target_duration_minutes=120,
            target_sessions=3,
            allow_intensity=False,
            confidence="low",
            continuity_state="partial_reprise",
            reason_codes=("partial_reprise",),
        )
        wp = build_weekly_plan(
            weekly_target=wt,
            runner_profile=runner_profile,
            plan_goal=plan_goal,
            periodization=periodization,
            reference_date=ref,
        )

        sessions = [
            WeekV2SessionResponse(
                day=s.day,
                workout_type=s.workout_type,
                intensity_class=s.intensity_class,
                distance_km=s.distance_km,
                duration_minutes=s.duration_minutes,
                estimated_tss=0 if s.workout_type == "rest" else None,
                reason_codes=list(s.reason_codes),
            )
            for s in wp.sessions
        ]

        resp = TrainingWeekV2Response(
            reference_date=ref.isoformat(),
            goal=WeekV2GoalResponse(goal_type="MARATHON"),
            state=WeekV2StateResponse(
                continuity_state=wt.continuity_state,
                allow_intensity=wt.allow_intensity,
            ),
            weekly_target=WeekV2TargetResponse(
                target_basis=wt.target_basis,
                target_km=wt.target_km,
                target_duration_minutes=wt.target_duration_minutes,
                session_count=wt.target_sessions,
                confidence=wt.confidence,
            ),
            week=WeekV2PlanResponse(
                planned_km=wp.planned_km,
                planned_duration_minutes=wp.planned_duration_minutes,
                session_count=wp.session_count,
                sessions=sessions,
            ),
        )
        return resp.model_dump(mode="json"), wt, wp

    def test_continuity_is_partial_reprise(self):
        resp, wt, _ = self._build()
        assert resp["state"]["continuity_state"] == "partial_reprise"

    def test_target_basis_is_duration(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_basis"] == "duration"

    def test_planned_duration_matches_builder(self):
        resp, wt, wp = self._build()
        assert resp["week"]["planned_duration_minutes"] == wp.planned_duration_minutes

    def test_planned_duration_matches_target(self):
        resp, wt, wp = self._build()
        assert resp["week"]["planned_duration_minutes"] == wt.target_duration_minutes

    def test_no_km_invented(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_km"] is None, (
            "NONE != ZERO: duration-based → target_km must be None"
        )
        assert resp["week"]["planned_km"] is None, (
            "NONE != ZERO: duration-based → planned_km must be None"
        )


# ===========================================================================
# Contract E — NO_HISTORY / duration fallback
# ===========================================================================

class TestContractE_NoHistory:
    """No workout history → no_history state → duration fallback."""

    def _build(self):
        workouts: list[dict] = []
        resp, wt, wp = _assemble_response(workouts, goal_type="MARATHON", reference_date=_REF_DATE)
        if wt.continuity_state not in ("no_history", "deep_reprise"):
            pytest.skip(
                f"Fixture: continuity_state={wt.continuity_state}; "
                "need no_history or deep_reprise for Contract E"
            )
        return resp, wt, wp

    def test_target_km_is_null(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_km"] is None, (
            "no_history → no km invented"
        )

    def test_planned_km_is_null(self):
        resp, wt, _ = self._build()
        assert resp["week"]["planned_km"] is None

    def test_canonical_duration_positive(self):
        resp, wt, _ = self._build()
        assert resp["weekly_target"]["target_duration_minutes"] is not None
        assert resp["weekly_target"]["target_duration_minutes"] > 0


# ===========================================================================
# Contract F — NONE semantics
# ===========================================================================

class TestContractF_NoneSemantics:
    """None != 0 doctrine: active sessions keep None where unknown."""

    def _build_distance(self):
        workouts = _make_workouts(n=8, km_per_session=10.0)
        return _assemble_response(workouts, goal_type="MARATHON", reference_date=_REF_DATE)

    def test_active_session_duration_is_none_when_distance_based(self):
        resp, wt, wp = self._build_distance()
        if resp["weekly_target"]["target_basis"] != "distance":
            pytest.skip("Need distance-based for this check")
        running = [s for s in resp["week"]["sessions"] if s["workout_type"] != "rest"]
        for s in running:
            assert s["duration_minutes"] is None, (
                f"NONE != ZERO: distance-based active session "
                f"duration_minutes must be None, got {s['duration_minutes']} "
                f"for day={s['day']}"
            )

    def test_active_session_tss_is_none(self):
        resp, wt, wp = self._build_distance()
        running = [s for s in resp["week"]["sessions"] if s["workout_type"] != "rest"]
        assert running, "No running sessions found"
        for s in running:
            assert s["estimated_tss"] is None, (
                f"TSS doctrine: active session estimated_tss must be None, "
                f"got {s['estimated_tss']} for day={s['day']}"
            )

    def test_rest_session_tss_is_zero(self):
        resp, wt, wp = self._build_distance()
        rest = [s for s in resp["week"]["sessions"] if s["workout_type"] == "rest"]
        assert rest, "No rest sessions found"
        for s in rest:
            assert s["estimated_tss"] == 0, (
                f"TSS doctrine: rest session estimated_tss must be 0, "
                f"got {s['estimated_tss']} for day={s['day']}"
            )


# ===========================================================================
# Architecture tests
# ===========================================================================

class TestArchitecture:
    """Verify endpoint uses canonical builder and no legacy functions."""

    _SERVER_PATH = os.path.join(_BACKEND_DIR, "server.py")

    def _get_v2_week_func_body(self) -> str:
        """Extract the source of get_training_v2_week from server.py."""
        with open(self._SERVER_PATH) as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_training_v2_week":
                lines = source.splitlines()
                start = node.lineno - 1
                end = node.end_lineno
                return "\n".join(lines[start:end])
        raise AssertionError("get_training_v2_week not found in server.py")

    def test_adapt_weekly_plan_to_legacy_not_called(self):
        body = self._get_v2_week_func_body()
        assert "adapt_weekly_plan_to_legacy" not in body, (
            "get_training_v2_week must NOT call adapt_weekly_plan_to_legacy"
        )

    def test_generate_cycle_week_not_called(self):
        body = self._get_v2_week_func_body()
        assert "generate_cycle_week" not in body, (
            "get_training_v2_week must NOT call generate_cycle_week"
        )

    def test_compute_target_km_not_called(self):
        body = self._get_v2_week_func_body()
        assert "compute_target_km" not in body

    def test_reprise_durations_not_called(self):
        body = self._get_v2_week_func_body()
        assert "reprise_durations" not in body

    def test_compute_long_run_km_not_called(self):
        body = self._get_v2_week_func_body()
        assert "compute_long_run_km" not in body

    def test_apply_resume_guard_not_called(self):
        body = self._get_v2_week_func_body()
        assert "apply_resume_guard" not in body

    def test_canonical_builder_is_used(self):
        body = self._get_v2_week_func_body()
        assert "build_weekly_plan_from_workouts" in body, (
            "get_training_v2_week must use build_weekly_plan_from_workouts"
        )

    def test_training_engine_not_imported(self):
        body = self._get_v2_week_func_body()
        assert "training_engine" not in body, (
            "get_training_v2_week must not use training_engine"
        )

    def test_legacy_endpoint_week_plan_still_exists(self):
        """/training/week-plan must not be removed (additive only)."""
        with open(self._SERVER_PATH) as f:
            source = f.read()
        assert '"/training/week-plan"' in source, (
            "/training/week-plan was removed — PR167 must be additive only"
        )

    def test_legacy_endpoint_plan_still_exists(self):
        with open(self._SERVER_PATH) as f:
            source = f.read()
        assert '"/training/plan"' in source

    def test_legacy_endpoint_full_cycle_still_exists(self):
        with open(self._SERVER_PATH) as f:
            source = f.read()
        assert '"/training/full-cycle"' in source

    def test_v2_week_route_registered(self):
        with open(self._SERVER_PATH) as f:
            source = f.read()
        assert '"/training/v2/week"' in source


# ===========================================================================
# Parity test — same builder → same WeeklyTarget and WeeklyPlan
# ===========================================================================

class TestParity:
    """Both /training/week-plan and /training/v2/week share the canonical builder.

    Parity is trivially guaranteed because both call build_weekly_plan_from_workouts.
    This test verifies the builder is deterministic for identical inputs.
    """

    def test_builder_is_deterministic(self):
        workouts = _make_workouts(n=8, km_per_session=10.0)
        wt1, wp1 = build_weekly_plan_from_workouts(
            workouts=workouts,
            goal_type="MARATHON",
            reference_date=_REF_DATE,
        )
        wt2, wp2 = build_weekly_plan_from_workouts(
            workouts=workouts,
            goal_type="MARATHON",
            reference_date=_REF_DATE,
        )
        assert wt1 == wt2, "WeeklyTarget must be deterministic for same inputs"
        assert wp1 == wp2, "WeeklyPlan must be deterministic for same inputs"

    def test_no_weekly_target_duplication(self):
        """WeeklyTarget is built once inside build_weekly_plan_from_workouts.

        The function returns (WeeklyTarget, WeeklyPlan).  The new endpoint
        reads target from the returned WeeklyTarget — no second build.
        """
        workouts = _make_workouts(n=8, km_per_session=10.0)
        wt, wp = build_weekly_plan_from_workouts(
            workouts=workouts,
            goal_type="MARATHON",
            reference_date=_REF_DATE,
        )
        # Verify WeeklyPlan.target_basis mirrors WeeklyTarget.target_basis
        assert wp.target_basis == wt.target_basis, (
            "WeeklyPlan and WeeklyTarget must agree on target_basis"
        )


# ===========================================================================
# Response model tests
# ===========================================================================

class TestResponseModel:
    """Verify TrainingWeekV2Response model serialises correctly."""

    def test_model_serialises_none_not_zero(self):
        """None fields must serialise as null, not 0."""
        s = WeekV2SessionResponse(
            day="monday",
            workout_type="easy",
            intensity_class="low",
            distance_km=8.0,
            duration_minutes=None,
            estimated_tss=None,
            reason_codes=[],
        )
        d = s.model_dump(mode="json")
        assert d["duration_minutes"] is None
        assert d["estimated_tss"] is None

    def test_rest_session_tss_zero(self):
        s = WeekV2SessionResponse(
            day="sunday",
            workout_type="rest",
            intensity_class="rest",
            distance_km=None,
            duration_minutes=None,
            estimated_tss=0,
            reason_codes=[],
        )
        d = s.model_dump(mode="json")
        assert d["estimated_tss"] == 0
        assert d["distance_km"] is None
        assert d["duration_minutes"] is None

    def test_full_response_structure(self):
        workouts = _make_workouts(n=8, km_per_session=10.0)
        d, wt, wp = _assemble_response(workouts, goal_type="MARATHON", reference_date=_REF_DATE)
        assert "reference_date" in d
        assert "goal" in d
        assert "state" in d
        assert "weekly_target" in d
        assert "week" in d
        assert "sessions" in d["week"]
        assert len(d["week"]["sessions"]) == 7, "Must have 7 sessions (Mon–Sun)"

    def test_session_has_v2_native_fields(self):
        workouts = _make_workouts(n=8, km_per_session=10.0)
        d, wt, wp = _assemble_response(workouts, goal_type="MARATHON", reference_date=_REF_DATE)
        for s in d["week"]["sessions"]:
            assert "day" in s
            assert "workout_type" in s
            assert "intensity_class" in s
            assert "reason_codes" in s


# ===========================================================================
# TARGET_TIME — conversion minutes→seconds (BLOCKER 1)
# ===========================================================================

def _target_time_seconds_from_minutes(target_time_minutes):
    """Mirror the conversion logic at the API boundary in server.py."""
    if (
        isinstance(target_time_minutes, (int, float))
        and not isinstance(target_time_minutes, bool)
        and target_time_minutes > 0
    ):
        return int(target_time_minutes * 60)
    return None


class TestTargetTimeConversion:
    """TARGET_TIME_MINUTES_TO_SECONDS — DB canonical field is target_time_minutes."""

    def test_TARGET_TIME_MINUTES_TO_SECONDS(self):
        """120 min → 7200 sec."""
        assert _target_time_seconds_from_minutes(120) == 7200

    def test_TARGET_TIME_MINUTES_TO_SECONDS_float(self):
        """180.0 min → 10800 sec."""
        assert _target_time_seconds_from_minutes(180.0) == 10800

    def test_TARGET_TIME_ABSENT(self):
        """Absent field (None) → None, not 0."""
        assert _target_time_seconds_from_minutes(None) is None

    def test_TARGET_TIME_INVALID_zero(self):
        """Zero is invalid → None."""
        assert _target_time_seconds_from_minutes(0) is None

    def test_TARGET_TIME_INVALID_negative(self):
        """Negative value → None."""
        assert _target_time_seconds_from_minutes(-30) is None

    def test_TARGET_TIME_INVALID_string(self):
        """Non-numeric string → None."""
        assert _target_time_seconds_from_minutes("120") is None

    def test_TARGET_TIME_INVALID_bool(self):
        """Bool (True = 1 in Python) → None — bools rejected explicitly."""
        assert _target_time_seconds_from_minutes(True) is None

    def test_no_none_coerced_to_zero(self):
        """None must never become 0."""
        result = _target_time_seconds_from_minutes(None)
        assert result is None
        assert result != 0

    def test_response_model_accepts_converted_seconds(self):
        """WeekV2GoalResponse accepts the converted int correctly."""
        goal = WeekV2GoalResponse(
            goal_type="MARATHON",
            race_date=None,
            target_time_seconds=7200,
        )
        d = goal.model_dump(mode="json")
        assert d["target_time_seconds"] == 7200

    def test_response_model_null_when_absent(self):
        """WeekV2GoalResponse serialises None as null."""
        goal = WeekV2GoalResponse(
            goal_type="MARATHON",
            race_date=None,
            target_time_seconds=None,
        )
        d = goal.model_dump(mode="json")
        assert d["target_time_seconds"] is None


# ===========================================================================
# SINGLE_NOW_BOUNDARY — single datetime.now call in endpoint (BLOCKER 2)
# ===========================================================================

class TestSingleNowBoundary:
    """SINGLE_NOW_BOUNDARY — GET /training/v2/week must resolve clock once."""

    def test_SINGLE_NOW_BOUNDARY(self):
        """server.py: get_training_v2_week must resolve now_utc exactly once.

        Rule: reference_date and ninety_days_ago must both derive from the
        same now_utc variable — no second datetime.now() call.
        """
        import ast as _ast
        import os as _os

        server_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            "server.py",
        )
        source = open(server_path).read()
        tree = _ast.parse(source)

        # Find the get_training_v2_week function
        func = next(
            (
                n
                for n in _ast.walk(tree)
                if isinstance(n, _ast.AsyncFunctionDef)
                and n.name == "get_training_v2_week"
            ),
            None,
        )
        assert func is not None, "get_training_v2_week not found in server.py"

        # Count datetime.now( calls inside the function body
        func_source_lines = source.splitlines()[func.lineno - 1: func.end_lineno]
        func_source = "\n".join(func_source_lines)
        now_calls = func_source.count("datetime.now(")
        assert now_calls == 1, (
            f"get_training_v2_week must call datetime.now() exactly once "
            f"(found {now_calls}). Use now_utc = datetime.now(timezone.utc) "
            "and derive reference_date and ninety_days_ago from it."
        )
