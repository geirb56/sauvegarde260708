# RUNINDEX — PR #239 — Dashboard ↔ Training Truth Convergence

- Integration target: `copilot/dev`
- Base SHA: `58fe4ca860181b4e14b5341c23c9e85b0acf8ef3`
- PR final head: `e0c70412afb24d76973564c7ec44700d4f5cf611`
- Merge commit: `5b694ea669e5812e90fed138e350dd98712e5404`
- Status: `MERGED — 2026-09-09`

## Scope

This PR converged Dashboard weekly target progress with Training V2 authority and removed prescriptive readiness wording from Dashboard UX.

## Files changed

- `frontend/src/lib/trainingWeekProgress.js`
- `frontend/src/pages/TrainingPlanV2.jsx`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/lib/i18n.js`
- `frontend/src/__tests__/dashboard-training-v2.test.jsx`
- `frontend/src/__tests__/dashboard-run-readiness-v2.test.jsx`
- `RUNINDEX_PR239_REPORT.md`

## Canonical changes

### Shared weekly progress authority

Dashboard and Training now share:
- `computeTrainingWeekProgress(trainingWeekV2)`

Authority inputs:
- `weekly_target`
- `week.sessions`
- `week.unmatched_actuals`

### Progress semantics

- target authority comes from `/training/v2/week`
- completed-in-plan = matched Garmin activity only
- unmatched actuals remain separate and never inflate plan completion
- progress = `completed_planned / target`

### `None != 0`

Current semantics preserved:
- `empty` = true zero
- `complete` = known value
- `partial` = incomplete / unknown
- `partial` and `unavailable` never become fake `0%`

### Readiness wording

Dashboard no longer presents readiness as a workout directive.
Readiness is displayed as freshness state, separate from training prescription.

## Tests executed during PR work

### Frontend targeted
- `npm test -- --watchAll=false --runInBand --testPathPattern='dashboard-training-v2.test.jsx|training-v2-page.test.jsx'`
- Result: 2 suites passed / 116 tests passed

### Frontend full
- `npm test -- --watchAll=false --runInBand`
- Result: 18 suites passed / 317 tests passed

### Build
- `npm run build`
- Result: success

## CI note correction

Workflow run `34372600720` must not be treated as validating the final PR head `e0c70412afb24d76973564c7ec44700d4f5cf611`.
It was an in-progress branch run observed during the audit, not canonical final-head CI evidence.

## Boundaries

No backend training science changed.
No changes were made to:
- WeeklyTarget
- WorkoutGenerator
- WeeklyReconciliation
- Training Paces
- StructuredWorkout
- PrescriptionSnapshot
- Garmin matching rules
- DailyAdaptation
- RunIndex or Performance Curve
