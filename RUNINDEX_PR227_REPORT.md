# RUNINDEX — PR #227 Report

## Scope
- Target: make `target_time` a real Training V2 engine input (not decorative).
- Base branch: `copilot/dev`.
- Rule kept: never synthesize/invent `target_time`.
- Rule kept: `MAINTENANCE => target_time=None`.
- Rule kept: no `target_time` => V2 behavior unchanged.

## Audit (requested components)

### `_resolve_goal_v2` (backend/server.py)
- Reads canonical `user_goals.target_time_minutes`.
- Converts only valid positive numeric values to `target_time_sec = int(minutes * 60)`.
- Invalid/missing values remain `None` (no synthetic fallback).
- `MAINTENANCE` path always returns `target_time_sec=None`.

### `PlanGoal` (backend/training_v2/plan_goal.py)
- Already supports `target_time_seconds`.
- Validation already forbids `target_time_seconds` for maintenance.

### `Periodization`
- Target-time agnostic by design (calendar layer only). No prescription logic here.

### `WeeklyTarget`
- Still target-time agnostic by design (weekly load guardrails/reprise logic).
- No target-time synthesis introduced.

### `WorkoutGenerator`
- **Changed**: target-time now influences session composition (when physiologically relevant).
- Modulation applies only when:
  - `target_basis == "distance"`,
  - intensity is allowed,
  - valid `PlanGoal.target_time_seconds` and `PlanGoal.target_distance_km` exist.
- Profiles:
  - aggressive chrono target → promote one easy/recovery slot to steady;
  - conservative chrono target → downgrade quality slot to steady.
- No effect when target-time is absent/invalid.

### `week_plan_bridge`
- **Changed**: `target_time_seconds` propagated into `build_plan_goal(...)` in canonical weekly pipeline.
- Added optional `target_time_seconds` argument to:
  - `_build_weekly_context_from_workouts`
  - `build_weekly_target_from_workouts`
  - `build_weekly_plan_from_workouts`

### `/training/v2/week`
- **Changed**: passes resolved `target_time_sec` into bridge (`target_time_seconds=...`).
- Response `goal.target_time_seconds` unchanged and still exposed.

### `/training/v2/cycle`
- **Changed**: `PlanGoal` now receives `target_time_seconds` as input as well.
- Response passthrough of `target_time_seconds` unchanged.

### Dashboard / Training frontend
- Existing UI consumes week/cycle responses as before.
- No frontend code change required for this PR’s engine-level objective.

## Files changed
- `backend/server.py`
- `backend/training_v2/week_plan_bridge.py`
- `backend/training_v2/workout_generator.py`
- `backend/tests/test_target_time_propagation_pr227.py` (new)

## Mandatory tests and results

### 10K sans target_time => baseline inchangée
- Covered by: `test_10k_without_target_time_keeps_baseline`
- Result: ✅ PASS

### 10K avec objectif réaliste => propagation complète
- Covered by: `test_bridge_propagates_target_time_seconds_to_workout_generator`
- Result: ✅ PASS (`target_time_seconds=3000` reaches engine PlanGoal)

### 10K avec deux chronos différents => effet mesurable sur prescription
- Covered by: `test_10k_two_target_times_change_prescription`
- Result: ✅ PASS (different running signature + profile reason codes)

### Semi idem
- Covered by: `test_semi_two_target_times_change_prescription`
- Result: ✅ PASS

### MAINTENANCE => aucun target_time
- Covered by: `test_maintenance_never_uses_target_time`
- Result: ✅ PASS

### Aucun fallback chrono synthétique
- Covered by: `test_bridge_without_target_time_does_not_synthesize_seconds`
- Result: ✅ PASS (`None` remains `None`)

### Aucune régression volume/reprise/long-run/intensity caps
- Command:
  - `python -m pytest tests/test_target_time_propagation_pr227.py tests/test_workout_generator_v2.py tests/test_weekly_target_v2.py -q`
- Result: ✅ PASS (`176 passed`)

## Runtime gate
- **Runtime: DEFERRED TO FINAL RUNTIME GATE.**
