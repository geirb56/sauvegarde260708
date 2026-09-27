"""PR165 — WeeklyTarget/WeeklyPlan V2 safety invariants.

Legacy `/training/week-plan` and its adapter were removed; this suite keeps
only canonical V2 bridge-level invariants.
"""

from __future__ import annotations

from datetime import date, timedelta

from training_v2.week_plan_bridge import build_weekly_plan_from_workouts

_REF_DATE = date(2024, 6, 10)


def _make_workouts(n: int = 0, km_per_session: float = 8.0) -> list[dict]:
    ref = _REF_DATE
    workouts = []
    for i in range(n):
        d = ref - timedelta(days=i * 7 + 3)
        workouts.append(
            {
                "distance_km": km_per_session,
                "duration_minutes": 50,
                "date": d.isoformat(),
                "activity_type": "running",
            }
        )
    return workouts


def _make_workouts_deep_reprise_trained() -> list[dict]:
    ref = _REF_DATE
    prior_dates = [ref - timedelta(days=d) for d in [41, 38, 35, 32, 29]]
    return [
        {
            "distance_km": 16.0,
            "duration_minutes": 80,
            "date": d.isoformat(),
            "activity_type": "running",
        }
        for d in prior_dates
    ]


def _make_workouts_partial_reprise_distance() -> list[dict]:
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
            "duration_minutes": 25,
            "date": (ref - timedelta(days=3)).isoformat(),
            "activity_type": "running",
        }
    ]
    return bigger + small


def _run_bridge(workouts: list[dict], goal_type: str = "SEMI") -> tuple:
    return build_weekly_plan_from_workouts(
        workouts=workouts,
        goal_type=goal_type,
        race_date=None,
        cycle_start_date=_REF_DATE - timedelta(weeks=4),
        reference_date=_REF_DATE,
    )


def test_bridge_is_deterministic_for_identical_inputs():
    workouts = _make_workouts(8, km_per_session=10.0)
    wt1, wp1 = _run_bridge(workouts)
    wt2, wp2 = _run_bridge(workouts)

    assert wt1 == wt2
    assert wp1 == wp2


def test_deep_reprise_stays_duration_based_without_invented_km():
    wt, wp = _run_bridge(_make_workouts_deep_reprise_trained())

    assert wt.continuity_state == "deep_reprise"
    assert wt.target_basis == "duration"
    assert wt.target_km is None
    assert wt.target_duration_minutes == 135
    assert wp.target_basis == "duration"
    assert wp.planned_km is None
    assert wp.planned_duration_minutes == wt.target_duration_minutes
    active_sessions = [s for s in wp.sessions if s.workout_type != "rest"]
    assert active_sessions
    assert all(s.distance_km is None for s in active_sessions)


def test_partial_reprise_distance_prescription_is_conserved():
    wt, wp = _run_bridge(_make_workouts_partial_reprise_distance())

    assert wt.continuity_state == "partial_reprise"
    assert wt.target_basis == "distance"
    assert wt.target_km is not None
    assert wp.target_basis == "distance"
    assert wp.planned_km is not None
    planned_from_sessions = round(
        sum((s.distance_km or 0.0) for s in wp.sessions if s.workout_type != "rest"),
        1,
    )
    assert abs(planned_from_sessions - (wp.planned_km or 0.0)) <= 0.15
    assert abs(planned_from_sessions - (wt.target_km or 0.0)) <= 0.15
    assert abs((wp.planned_km or 0) - (wt.target_km or 0)) <= 0.15


def test_no_history_remains_duration_based_and_low_intensity():
    wt, wp = _run_bridge([])

    assert wt.continuity_state in ("no_history", "deep_reprise")
    assert wt.target_basis == "duration"
    assert wt.target_km is None
    assert wt.allow_intensity is False
    assert wp.target_basis == "duration"
    assert wp.allow_intensity is False
    active_sessions = [s for s in wp.sessions if s.workout_type != "rest"]
    assert all(s.distance_km is None for s in active_sessions)
