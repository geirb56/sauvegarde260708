# RUNINDEX — PATCH PR #227 Report

## Scope
- Same PR #227, no merge.
- Fix 3 blockers: remove universal pace references, enforce absolute protection priority, and hard-validate `target_time_minutes` at POST `/user/goal`.

## Blocker fixes

### 1) Remove universal reference paces
- Removed `_goal_reference_pace_seconds_per_km` from `workout_generator`.
- Target-time classification now compares goal pace only against an observed/canonical capability pace.
- Capability source used: Training Paces V2 (VDOT from qualified observed performances), resolved in `week_plan_bridge`.
- If capability confidence is insufficient (`LOW` / `INSUFFICIENT`) or missing pace signal, target-time modulation is disabled.
- No VMA, no Garmin VO2max, no race-prediction shortcut, no synthetic per-distance reference pace.

### 2) Absolute priority for protections
- Target-time modulation is now bounded and can apply only when all are true:
  - `continuity_state == "normal"`,
  - `allow_intensity == True`,
  - `target_basis == "distance"`,
  - phase in `{base, build, specific}`.
- Therefore no chrono effect in:
  - `no_history`, `deep_reprise`, `partial_reprise`, `reprise_exit`,
  - `taper`, `race`, `consolidation`,
  - any `allow_intensity=False` path.
- Chrono never overrides TrainingState / WeeklyTarget / Periodization protections.

### 3) POST `/user/goal` target_time validation
- Added strict validation (`_validate_target_time_minutes`) before any mutation:
  - `None` accepted.
  - provided value must be numeric and strictly `> 0`.
  - `0`, negative, bool, non-numeric => HTTP 400.
- Invalid target time is rejected before `delete_many` / `insert_one`.
- No invalid value is stored then silently transformed to `None`.

## Files changed
- `backend/training_v2/workout_generator.py`
- `backend/training_v2/week_plan_bridge.py`
- `backend/server.py`
- `backend/tests/test_target_time_propagation_pr227.py`
- `backend/tests/test_goal_truth_pr226.py`

## Mandatory tests (blockers)

### Capacity-relative chrono behavior
- `test_10k_aggressive_when_target_faster_than_observed_capability` ✅
- `test_10k_conservative_when_target_slower_than_observed_capability` ✅
- `test_same_target_time_two_runners_can_be_classified_differently` ✅
- `test_insufficient_capability_does_not_alter_prescription` ✅
- `test_bridge_uses_canonical_paces_for_target_time_modulation` ✅

### Protection priority
- `test_taper_aggressive_target_does_not_reintroduce_steady_or_quality` ✅
- `test_race_aggressive_target_keeps_race_week_unchanged` ✅
- `test_reprise_target_time_keeps_protections_unchanged` ✅
- `test_without_target_time_baseline_is_unchanged` ✅

### POST `/user/goal` validation
- `test_post_user_goal_invalid_target_time_rejected_without_mutation` ✅
- `test_post_user_goal_non_numeric_target_time_rejected_without_mutation` ✅

## Required suite reruns

Command:
- `python -m pytest tests/test_target_time_propagation_pr227.py tests/test_training_paces_pr194.py tests/test_workout_generator_v2.py tests/test_weekly_target_v2.py tests/test_periodization_pr06.py -q`

Result:
- ✅ `282 passed`

Additional validation command:
- `python -m pytest tests/test_goal_truth_pr226.py -k "invalid_target_time or non_numeric_target_time" -q`

Result:
- ✅ `4 passed`

## Runtime gate
- Runtime: **DEFERRED TO FINAL RUNTIME GATE**.
