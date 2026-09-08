"""#235 — PRESCRIPTION SNAPSHOT V2 — GARMIN-EXPORT-READY.

Pure (no MongoDB, no HTTP) test suite for the extended
``training_v2.prescription_snapshot`` contract: the PARENT snapshot now
freezes its STRUCTURED (#234) view in the SAME document, at the SAME
instant, so that for an already-served day:

    HISTORICAL TRUTH = SNAPSHOT, never a live recompute.

Complements (does not replace) the end-to-end wiring tests in
``test_pr232a_c231_week_endpoint.py`` (Today/Week convergence, idempotence,
historical_frozen wiring) — this file focuses on the pure contract itself:
serialization, immutability against every possible "rule change" axis, the
None != 0 / recovery / mixed-basis invariants, and the Garmin-export-ready
claim (a snapshot alone is enough to reconstruct an executable session).

Run from the backend directory:
    python -m pytest tests/test_prescription_snapshot_v2_pr235.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2.periodization import (  # noqa: E402
    PeriodizationMode,
    PeriodizationPhase,
    PeriodizationSnapshot,
)
from training_v2.plan_goal import GoalType, build_plan_goal  # noqa: E402
from training_v2.prescription_snapshot import (  # noqa: E402
    PrescriptionSnapshot,
    STRUCTURED_STATUS_FUTURE_LIVE,
    STRUCTURED_STATUS_HISTORICAL_FROZEN,
    STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE,
    STRUCTURED_STATUS_TODAY_SERVED,
    resolve_structured_status,
    snapshot_from_prescription,
)
from training_v2.structured_workout import (  # noqa: E402
    StructuredStepType,
    StructuredWorkoutRecovery,
    StructuredWorkoutStep,
    build_structured_workout_prescription,
)
from training_v2.training_paces import TrainingPaces, daniels_paces  # noqa: E402
from training_v2.workout_generator import WorkoutPrescription  # noqa: E402

REF = date(2026, 8, 17)


# ---------------------------------------------------------------------------
# Fixtures / builders — mirror test_structured_workout_pr234.py
# ---------------------------------------------------------------------------


def _goal(goal_type: GoalType, **kwargs) -> "PlanGoal":
    return build_plan_goal(goal_type=goal_type, created_from="user", **kwargs)


def _phase(phase: PeriodizationPhase) -> PeriodizationSnapshot:
    return PeriodizationSnapshot(
        reference_date=REF,
        phase=phase,
        mode=PeriodizationMode.race_calendar,
        weeks_to_race=10.0,
        phase_start_date=REF,
        phase_end_date=REF,
        cycle_week=1,
        cycle_length_weeks=4,
        reason_codes=(),
    )


def _workout(
    workout_type: str,
    *,
    distance_km: float | None = None,
    duration_minutes: int | None = None,
    reason_codes: tuple = ("ORIGINAL_PLAN",),
) -> WorkoutPrescription:
    intensity = {
        "rest": "rest",
        "recovery": "low",
        "easy": "low",
        "steady": "moderate",
        "quality": "high",
        "long_easy": "low",
    }[workout_type]
    return WorkoutPrescription(
        day="wednesday",
        workout_type=workout_type,
        intensity_class=intensity,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=reason_codes,
    )


def _paces(vdot: float = 50.0) -> TrainingPaces:
    return daniels_paces(vdot, REF)


def _snapshot_for(
    *,
    session: WorkoutPrescription,
    plan_goal,
    periodization,
    training_paces: TrainingPaces | None,
    planned_date: date = REF,
    prescription_id: str = "u1:2026-08-17:wednesday",
) -> PrescriptionSnapshot:
    structured = build_structured_workout_prescription(
        workout=session,
        plan_goal=plan_goal,
        periodization=periodization,
        training_paces=training_paces,
    )
    return snapshot_from_prescription(
        user_id="u1",
        prescription_id=prescription_id,
        planned_date=planned_date,
        session=session,
        modified_from_planned=False,
        structured=structured,
        served_at=datetime(2026, 8, 17, 8, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# 1. Serialization / Mongo round-trip
# ---------------------------------------------------------------------------


def test_structured_snapshot_serialization_round_trip():
    """model -> Mongo dict -> model -> same content (test #18)."""
    snap = _snapshot_for(
        session=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    mongo_dict = snap.model_dump(mode="json")
    # JSON-safe: dumping to a real JSON string must never raise (no
    # datetime/Enum/tuple leaking through unconverted).
    json.dumps(mongo_dict)

    rebuilt = PrescriptionSnapshot(**mongo_dict)
    assert rebuilt == snap
    assert rebuilt.structured == snap.structured
    assert rebuilt.reason_codes == snap.reason_codes
    assert rebuilt.served_at == snap.served_at


def test_legacy_structured_snapshot_without_quality_kind_defaults_to_none():
    snap = _snapshot_for(
        session=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    legacy_doc = snap.model_dump(mode="json")
    legacy_doc["structured"].pop("quality_kind")

    rebuilt = PrescriptionSnapshot(**legacy_doc)

    assert rebuilt.structured is not None
    assert rebuilt.structured.quality_kind is None


def test_structured_snapshot_serialization_is_deterministic():
    snap = _snapshot_for(
        session=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    d1 = snap.model_dump(mode="json")
    d2 = snap.model_dump(mode="json")
    assert d1 == d2


def test_legacy_parent_only_document_round_trips_with_structured_none():
    """#235 §12 — a legacy (pre-#235) Mongo document with no `structured`
    key at all must deserialize cleanly with structured=None, never crash
    and never be backfilled."""
    legacy_doc = {
        "user_id": "u1",
        "prescription_id": "u1:2026-08-10:monday",
        "planned_date": "2026-08-10",
        "day": "monday",
        "workout_type": "easy",
        "intensity_class": "low",
        "distance_km": 8.0,
        "duration_minutes": None,
    }
    snap = PrescriptionSnapshot(**legacy_doc)
    assert snap.structured is None
    assert snap.reason_codes == ()
    assert snap.served_at is None


def test_prescription_snapshot_v2_is_frozen():
    snap = _snapshot_for(
        session=_workout("easy", distance_km=8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
        training_paces=_paces(),
    )
    with pytest.raises(Exception):
        snap.structured = None  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. resolve_structured_status — the full state matrix
# ---------------------------------------------------------------------------


def test_status_future_live_no_snapshot():
    status = resolve_structured_status(
        planned_date=REF + timedelta(days=1),
        reference_date=REF,
        frozen_snapshot=None,
    )
    assert status == STRUCTURED_STATUS_FUTURE_LIVE == "future_live"


def test_status_today_served():
    status = resolve_structured_status(
        planned_date=REF, reference_date=REF, frozen_snapshot=None
    )
    assert status == STRUCTURED_STATUS_TODAY_SERVED == "today_served"


def test_status_historical_frozen_with_v2_snapshot():
    snap = _snapshot_for(
        session=_workout("easy", distance_km=8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
        training_paces=_paces(),
        planned_date=REF,
    )
    status = resolve_structured_status(
        planned_date=REF,
        reference_date=REF + timedelta(days=2),
        frozen_snapshot=snap,
    )
    assert status == STRUCTURED_STATUS_HISTORICAL_FROZEN == "historical_frozen"


def test_status_historical_unavailable_no_snapshot():
    status = resolve_structured_status(
        planned_date=REF,
        reference_date=REF + timedelta(days=2),
        frozen_snapshot=None,
    )
    assert status == STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE == "historical_unavailable"


def test_status_historical_unavailable_legacy_snapshot_without_structured():
    legacy = PrescriptionSnapshot(
        user_id="u1",
        prescription_id="u1:2026-08-10:monday",
        planned_date=date(2026, 8, 10),
        day="monday",
        workout_type="easy",
        intensity_class="low",
        distance_km=8.0,
        duration_minutes=None,
        # structured omitted -> None (legacy)
    )
    status = resolve_structured_status(
        planned_date=date(2026, 8, 10),
        reference_date=REF,
        frozen_snapshot=legacy,
    )
    assert status == STRUCTURED_STATUS_HISTORICAL_UNAVAILABLE
    assert legacy.structured is None
    assert status != "historical_frozen", "never backfilled — machine-readable, no new wording invented"


# ---------------------------------------------------------------------------
# 3. Immutability — tests A/B/C/D (§10)
# ---------------------------------------------------------------------------


def test_immutability_a_training_paces_change_never_alters_frozen_structured():
    """A. Training Paces change: snapshot -> paces change -> reread ->
    structured paces identical to the frozen ones."""
    session = _workout("quality", distance_km=9.0)
    goal = _goal(GoalType.ten_k)
    phase = _phase(PeriodizationPhase.build)

    snap = _snapshot_for(
        session=session, plan_goal=goal, periodization=phase, training_paces=_paces(vdot=50.0)
    )
    frozen_structured = snap.structured

    # Training Paces changes drastically (VDOT 50 -> 65) after the freeze.
    new_paces = _paces(vdot=65.0)
    live_structured_with_new_paces = build_structured_workout_prescription(
        workout=session, plan_goal=goal, periodization=phase, training_paces=new_paces
    )
    # Sanity: the new live paces really would differ from what's frozen —
    # otherwise this test would prove nothing.
    assert live_structured_with_new_paces != frozen_structured

    # The snapshot itself — the ONLY thing a historical read is allowed to
    # consult — must be completely unaffected by the change.
    assert snap.structured == frozen_structured


def test_immutability_b_goal_change_never_alters_frozen_structured():
    session = _workout("quality", distance_km=9.0)
    phase = _phase(PeriodizationPhase.build)
    snap = _snapshot_for(
        session=session, plan_goal=_goal(GoalType.five_k), periodization=phase, training_paces=_paces()
    )
    frozen_structured = snap.structured

    live_with_new_goal = build_structured_workout_prescription(
        workout=session, plan_goal=_goal(GoalType.marathon), periodization=phase, training_paces=_paces()
    )
    assert live_with_new_goal != frozen_structured
    assert snap.structured == frozen_structured


def test_immutability_c_phase_change_never_alters_frozen_structured():
    session = _workout("quality", distance_km=9.0)
    goal = _goal(GoalType.ten_k)
    snap = _snapshot_for(
        session=session,
        plan_goal=goal,
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    frozen_structured = snap.structured

    live_with_new_phase = build_structured_workout_prescription(
        workout=session,
        plan_goal=goal,
        periodization=_phase(PeriodizationPhase.taper),
        training_paces=_paces(),
    )
    assert live_with_new_phase != frozen_structured
    assert snap.structured == frozen_structured


def test_immutability_d_engine_output_change_never_rewrites_snapshot(monkeypatch):
    """D. Simulate the #234 engine changing its output entirely after the
    snapshot was frozen (e.g. a rule patch/bugfix release). The historical
    read (the already-frozen ``snap.structured``) must stay exactly what it
    was at freeze time — reading the snapshot never calls the engine again."""
    session = _workout("quality", distance_km=9.0)
    goal = _goal(GoalType.ten_k)
    phase = _phase(PeriodizationPhase.build)
    snap = _snapshot_for(
        session=session, plan_goal=goal, periodization=phase, training_paces=_paces()
    )
    frozen_structured = snap.structured

    import training_v2.structured_workout as structured_workout_module

    def _patched_engine(**kwargs):
        raise AssertionError(
            "The Structured Workout engine must NEVER be invoked again to "
            "read an already-frozen historical snapshot."
        )

    monkeypatch.setattr(
        structured_workout_module, "build_structured_workout_prescription", _patched_engine
    )

    # A historical read is simply attribute access on the frozen snapshot —
    # it must never need to call (the now-patched) engine.
    assert snap.structured == frozen_structured


# ---------------------------------------------------------------------------
# 4. Numeric paces frozen (§14)
# ---------------------------------------------------------------------------


def test_numeric_pace_frozen_single_value_for_threshold_zone():
    """T zone -> single numeric pace (pace_min_per_km), no min/max range."""
    snap = _snapshot_for(
        session=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    work_step = next(
        s for s in snap.structured.steps if s.step_type == StructuredStepType.work
    )
    assert work_step.pace_zone == "T"
    assert work_step.pace_min_per_km is not None
    assert work_step.pace_min_per_km_min is None
    assert work_step.pace_min_per_km_max is None


def test_numeric_pace_frozen_range_for_easy_zone():
    """E zone -> min/max range, no single value."""
    snap = _snapshot_for(
        session=_workout("easy", distance_km=8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
        training_paces=_paces(),
    )
    step = snap.structured.steps[0]
    assert step.pace_zone == "E"
    assert step.pace_min_per_km is None
    assert step.pace_min_per_km_min is not None
    assert step.pace_min_per_km_max is not None


def test_missing_training_pace_remains_none_never_recomputed():
    """K — no Training Paces available at serve time -> numeric pace fields
    stay None forever (never invented later, never recomputed on a
    historical read)."""
    snap = _snapshot_for(
        session=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=None,
    )
    for step in snap.structured.steps:
        assert step.pace_min_per_km is None
        assert step.pace_min_per_km_min is None
        assert step.pace_min_per_km_max is None

    # Even after Mongo round-trip, still None (never fabricated on read).
    rebuilt = PrescriptionSnapshot(**snap.model_dump(mode="json"))
    for step in rebuilt.structured.steps:
        assert step.pace_min_per_km is None


# ---------------------------------------------------------------------------
# 5. Recovery / total semantics preserved exactly (§15)
# ---------------------------------------------------------------------------


def test_recovery_n_minus_1_and_mixed_basis_preserved_through_snapshot():
    """Recovery N-1 + mixed-basis (distance session, time-only recovery) —
    frozen exactly as the #234 engine decided, never corrected."""
    snap = _snapshot_for(
        session=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    work_step = next(
        s for s in snap.structured.steps if s.step_type == StructuredStepType.work
    )
    assert work_step.repetitions > 1
    assert work_step.recovery is not None
    assert work_step.recovery.duration_seconds is not None
    # None != 0 — recovery distance genuinely unknown (time-only recovery),
    # never fabricated as 0.
    assert work_step.recovery.distance_m is None
    # Mixed-basis invariant preserved: cannot claim exact distance closure —
    # never a vacuous/misleading True (C234 blocker 2, DISTANCE_TOTAL_MIXED_BASIS).
    assert not snap.structured.distance_invariant_applicable
    assert not snap.structured.distance_closes_total
    assert "DISTANCE_TOTAL_MIXED_BASIS" in snap.structured.reason_codes

    # Round-trip through Mongo — every one of the above must survive intact.
    rebuilt = PrescriptionSnapshot(**snap.model_dump(mode="json"))
    rebuilt_work = next(
        s for s in rebuilt.structured.steps if s.step_type == StructuredStepType.work
    )
    assert rebuilt_work.recovery.distance_m is None
    assert rebuilt_work.recovery.duration_seconds == work_step.recovery.duration_seconds
    assert not rebuilt.structured.distance_closes_total


def test_known_zero_recovery_distance_distinct_from_unknown_after_round_trip():
    """None != 0 — a recovery step with a genuinely-known zero distance
    (e.g. a stationary/standing recovery) must never collapse into (or be
    confused with) an unknown (None) recovery distance, including after a
    full Mongo round-trip."""
    known_zero_recovery = StructuredWorkoutRecovery(
        kind="standing", duration_seconds=60, distance_m=0.0, count=3
    )
    unknown_recovery = StructuredWorkoutRecovery(
        kind="jog", duration_seconds=90, distance_m=None, count=3
    )
    step_known_zero = StructuredWorkoutStep(
        step_type=StructuredStepType.work,
        repetitions=4,
        distance_m=1000.0,
        recovery=known_zero_recovery,
        pace_zone="I",
    )
    step_unknown = StructuredWorkoutStep(
        step_type=StructuredStepType.work,
        repetitions=4,
        distance_m=1000.0,
        recovery=unknown_recovery,
        pace_zone="I",
    )
    assert step_known_zero.recovery.distance_m == 0.0
    assert step_unknown.recovery.distance_m is None
    assert step_known_zero.recovery.distance_m != step_unknown.recovery.distance_m

    # Round-trip both independently through plain JSON (mirrors Mongo dict
    # storage) and verify the distinction survives.
    known_json = json.loads(json.dumps(step_known_zero.model_dump(mode="json")))
    unknown_json = json.loads(json.dumps(step_unknown.model_dump(mode="json")))
    assert known_json["recovery"]["distance_m"] == 0.0
    assert unknown_json["recovery"]["distance_m"] is None


# ---------------------------------------------------------------------------
# 6. Garmin-export-ready contract (§17 / test 19)
# ---------------------------------------------------------------------------


def test_garmin_export_ready_contract_reconstructs_executable_session_from_snapshot_alone():
    """A quality 9km session (warmup -> repeated work -> recovery ->
    cooldown) must be fully reconstructable — sequence, duration basis,
    target values, reps, recovery count, pace values — by reading ONLY the
    frozen snapshot, calling NOTHING else (no Training Paces, PlanGoal,
    Periodization, or the Structured Workout engine)."""
    snap = _snapshot_for(
        session=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    # Persist/reload through Mongo exactly like a real historical read would.
    frozen = PrescriptionSnapshot(**snap.model_dump(mode="json"))
    structured = frozen.structured
    assert structured is not None

    # A future GarminWorkoutCompiler(snapshot) would need at least this,
    # and nothing else, to translate the session:
    exported_steps = []
    for step in structured.steps:
        # 1. duration basis: distance / time / open.
        if step.distance_m is not None:
            duration_basis = "distance"
            duration_value = step.distance_m
        elif step.duration_seconds is not None:
            duration_basis = "time"
            duration_value = step.duration_seconds
        else:
            duration_basis = "open"
            duration_value = None

        # 2. target type: pace / open (HR not modeled yet — vendor-neutral,
        # #234 doesn't produce HR targets, which is fine: the compiler only
        # translates what's really there).
        if step.pace_min_per_km is not None:
            target_type = "pace_single"
            target_range = (step.pace_min_per_km, step.pace_min_per_km)
        elif step.pace_min_per_km_min is not None or step.pace_min_per_km_max is not None:
            target_type = "pace_range"
            target_range = (step.pace_min_per_km_min, step.pace_min_per_km_max)
        else:
            target_type = "open"
            target_range = (None, None)

        # 3. repetitions + recovery — no external call needed, it's all on
        # the step already.
        exported_steps.append(
            {
                "step_type": step.step_type.value,
                "duration_basis": duration_basis,
                "duration_value": duration_value,
                "target_type": target_type,
                "target_range": target_range,
                "repetitions": step.repetitions,
                "recovery_kind": step.recovery.kind if step.recovery else None,
                "recovery_duration_seconds": step.recovery.duration_seconds if step.recovery else None,
                "recovery_distance_m": step.recovery.distance_m if step.recovery else None,
                "recovery_count": step.recovery.count if step.recovery else None,
            }
        )

    # The exported sequence must contain warmup -> work -> cooldown, in
    # order, with the work block actually repeated and recovered.
    step_types = [s["step_type"] for s in exported_steps]
    assert "warmup" in step_types
    assert "work" in step_types
    assert "cooldown" in step_types
    assert step_types.index("warmup") < step_types.index("work") < step_types.index("cooldown")

    work_export = next(s for s in exported_steps if s["step_type"] == "work")
    assert work_export["repetitions"] > 1
    assert work_export["recovery_kind"] is not None
    assert work_export["recovery_duration_seconds"] is not None
    assert work_export["target_type"] in ("pace_single", "pace_range")

    # No Garmin-specific vocabulary leaked into the snapshot's own contract.
    dumped = json.dumps(structured.model_dump(mode="json"))
    for forbidden in ("garmin", "fit_file", "connectiq", "ConnectIQ"):
        assert forbidden not in dumped.lower() if forbidden.islower() else forbidden not in dumped


# ---------------------------------------------------------------------------
# 7. PARENT reason_codes frozen (§4)
# ---------------------------------------------------------------------------


def test_parent_reason_codes_are_frozen_in_snapshot():
    session = _workout("easy", distance_km=8.0, reason_codes=("WEEKLY_TARGET_EASY",))
    snap = snapshot_from_prescription(
        user_id="u1",
        prescription_id="u1:2026-08-17:wednesday",
        planned_date=REF,
        session=session,
    )
    assert snap.reason_codes == ("WEEKLY_TARGET_EASY",)

    from training_v2.prescription_snapshot import resolve_effective_session

    # A later, differently-reasoned live session must never leak its own
    # reason_codes into the effective (frozen) view.
    live_now = _workout("easy", distance_km=8.0, reason_codes=("SOME_OTHER_REASON",))
    effective = resolve_effective_session(live_session=live_now, frozen_snapshot=snap)
    assert effective.reason_codes == ("WEEKLY_TARGET_EASY",)
