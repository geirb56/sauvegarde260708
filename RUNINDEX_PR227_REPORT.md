# RUNINDEX — PATCH FINAL PR #227 Report

## Scope
- Same PR #227, no merge.
- Final patch for 2 remaining blockers:
  1) capability on exact target distance from canonical VDOT;
  2) target_time independent of race_date.

## Final blocker fixes

### 1) Capability on exact target distance
- `target_time` comparison now uses **equivalent capability time on exact `PlanGoal.target_distance_km`** from canonical VDOT (`Training Paces V2`).
- Confidence gate enforced: modulation only when `TrainingPaces.confidence in {MEDIUM, HIGH}`.
- Added robust Daniels inversion bounds in `week_plan_bridge._equivalent_time_seconds_from_vdot`.
- ULTRA: explicit modulation disablement (no easy-pace proxy, no synthetic capability).
- No Race Predictions V2, no VMA, no Garmin VO2max.

### 2) target_time independent from race_date
- Backend API accepts `target_time_minutes` with `event_name=None` and `event_date=None`.
- `user_goals` storage keeps null race metadata when omitted.
- `_resolve_goal_v2` supports `PlanGoal(target_time_seconds=X, race_date=None)`.
- Without race_date: continuous periodization, no invented taper/race.
- With race_date later added: race-calendar behavior remains unchanged.
- Frontend Settings save flow posts null race metadata for target-time-only goal.

## Files changed (final patch)
- `backend/server.py`
- `backend/training_v2/workout_generator.py`
- `backend/training_v2/week_plan_bridge.py`
- `backend/tests/test_target_time_propagation_pr227.py`
- `backend/tests/test_goal_truth_pr226.py`
- `frontend/src/pages/Settings.jsx`
- `frontend/src/__tests__/settings-page.test.jsx`
- `RUNINDEX_PR227_REPORT.md`

## Mandatory test coverage added/updated

- 5K Daniels capability vs target_time ✅
- 10K Daniels capability vs target_time ✅
- Semi Daniels capability vs target_time ✅
- Marathon Daniels capability vs target_time ✅
- Same target_time + different VDOT => different classification ✅
- LOW/INSUFFICIENT confidence => no modulation ✅
- ULTRA => explicit no target_time modulation ✅
- 10K + target_time + race_date=None => save OK ✅
- `/training/v2/week` with target_time and race_date=None => OK ✅
- `/training/v2/cycle` idem => OK ✅
- No taper/race phases without race_date ✅
- Add race_date later => race-calendar periodization works ✅
- Without target_time => baseline unchanged ✅

## Exact commands and results

### Backend required rerun set
```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && \
python -m pytest \
  tests/test_target_time_propagation_pr227.py \
  tests/test_training_paces_pr194.py \
  tests/test_plan_goal_pr05.py \
  tests/test_periodization_pr06.py \
  tests/test_weekly_target_v2.py \
  tests/test_workout_generator_v2.py \
  tests/test_goal_truth_pr226.py
```
Result: ✅ **379 passed**

### Frontend settings regression (target_time without race metadata)
```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/frontend && \
npx craco test --watchAll=false --forceExit src/__tests__/settings-page.test.jsx
```
Result: ✅ **11 passed**

## Runtime gate
- Runtime: **DEFERRED TO FINAL RUNTIME GATE**.
