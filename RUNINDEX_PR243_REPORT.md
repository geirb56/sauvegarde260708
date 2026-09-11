# RUNINDEX PR243 REPORT

- Base branch: `copilot/dev`
- Exact base SHA: `c25c795284157b6fe11a401326696a5307cc7d5d`
- Final head SHA: recorded in the PR head metadata and final task handoff response

## Root cause
`WorkoutGenerator` scheduled abstract weekday training sessions without reserving the real `PlanGoal.race_date` inside the generated calendar week. In taper weeks before a Sunday race, the generator could still assign a normal session such as `long_easy` onto the actual race date.

## Calendar rule
If `plan_goal.race_date` falls inside the generated week (`week_start <= race_date <= week_start + 6 days`), that exact date is reserved for exactly one canonical `race` prescription. Normal training sessions are limited to eligible dates strictly before the race, `_assign_days()` cannot overwrite the reserved race slot, and no training session is created after the race within that week.

## Race-distance authority
The `race` session distance comes from `PlanGoal` truth only:
- `5k` -> `5.0 km`
- `10k` -> `10.0 km`
- `half_marathon` -> `21.0975 km`
- `marathon` -> `42.195 km`
- `ultra` -> explicit `target_distance_km`

No race distance is derived from `WeeklyTarget` or long-run fractions. Standard-goal fallback still resolves from canonical `goal_type` truth if a legacy `PlanGoal` instance arrives without `target_distance_km`. `None` remains `None` only when goal truth is genuinely unavailable.

## Weekly-target / race separation
`race` is modeled as an event, not training load.
- `WeeklyPlan.planned_km` remains a training-only aggregate and excludes race distance.
- training session counts exclude both `rest` and `race`.
- the `race` session still exposes its own event distance.

## Files changed
- `backend/server.py`
- `backend/tests/test_daily_runtime_pr137.py`
- `backend/tests/test_pr235_c235_corrections.py`
- `backend/tests/test_workout_generator_v2.py`
- `backend/training_v2/daily_adaptation.py`
- `backend/training_v2/daily_runtime_helpers.py`
- `backend/training_v2/performed_workout.py`
- `backend/training_v2/runtime_plan_adapter.py`
- `backend/training_v2/training_week_response.py`
- `backend/training_v2/week_plan_adapter.py`
- `backend/training_v2/workout_generator.py`
- `frontend/src/__tests__/training-v2-page.test.jsx`
- `frontend/src/lib/i18n.js`
- `frontend/src/lib/trainingWeekProgress.js`
- `frontend/src/pages/TrainingPlanV2.jsx`
- `RUNINDEX_PR243_REPORT.md`

## Tests / results
Backend targeted race-day regression suites:
- `python -m pytest tests/test_workout_generator_v2.py tests/test_daily_runtime_pr137.py tests/test_pr235_c235_corrections.py` -> `178 passed`

Relevant backend suites run individually:
- `python -m pytest -n 0 tests/test_plan_goal_pr05.py tests/test_periodization_pr06.py tests/test_weekly_target_v2.py tests/test_workout_generator_v2.py tests/test_daily_runtime_pr137.py -q` -> `308 passed`
- `python -m pytest -n 0 tests/test_pr232a_week_execution.py -q` -> `21 passed`
- `python -m pytest -n 0 tests/test_pr232a_c231_week_endpoint.py -q` -> `64 passed`
- `python -m pytest -n 0 tests/test_pr235_c235_corrections.py tests/test_pr167_training_v2_week_api.py -q` -> `14 passed`

Frontend:
- `npx craco test --watchAll=false --forceExit --runInBand --testPathPattern='training-v2-page|dashboard-training-v2'` -> `118 passed`
- `npm run build` -> success
- `git diff --check` -> success

Full backend suite attempt:
- `python -m pytest -n 0 -q` -> blocked by pre-existing collection/environment issues unrelated to PR243 (`tests/test_pr153_fallback_no_unvalidated_tss.py`, `tests/test_sse.py`, `tests/test_subscription_trial.py`)

## Today / Week convergence
Confirmed. On race day, `/training/today` and `/training/v2/week` expose the same canonical `race` prescription identity and type through the shared weekly source path.

## Execution / Garmin
Confirmed. This PR does not fabricate race completion. Before a matching Garmin activity exists, race-day status remains `planned`; completion still depends on the existing factual Garmin matching flow.
