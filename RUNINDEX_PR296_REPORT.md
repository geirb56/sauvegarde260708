# RUNINDEX PR296 — Remove inert deep_analysis from Coach contract

- Base branch: `copilot/dev`
- Base SHA used: `f971a696eef302d36f1fad6d32c4fd7ae14b76aa`
- Head SHA: `PENDING_FINAL_COMMIT`

## Files modified

- `backend/server.py`
- `backend/tests/test_coach_contract_unified.py`
- `backend_test_hidden_insight.py`
- `frontend/src/pages/Coach.jsx`
- `frontend/src/__tests__/coach-page.test.jsx`
- `RUNINDEX_PR296_REPORT.md`

## Consumer audit

### 1. Active runtime consumers

- `frontend/src/pages/Coach.jsx` sent `deep_analysis: true` in `triggerWorkoutAnalysis()` to `POST /api/coach/analyze`.
- `backend/server.py` declared `deep_analysis` on `CoachRequest`.
- No runtime backend behavior used `request.deep_analysis`.
- No other runtime consumers were found for `deep_analysis`, `deepAnalysis`, `deep-analysis`, or `request.deep_analysis`.

### 2. Tests and scripts adapted

- `frontend/src/__tests__/coach-page.test.jsx` now asserts the auto-analysis payload excludes `deep_analysis`.
- `backend/tests/test_coach_contract_unified.py` now asserts `CoachRequest` no longer exposes `deep_analysis`, preserves `CoachResponse`, and keeps workout context persistence intact without the removed field.
- `backend_test_hidden_insight.py` no longer sends `deep_analysis` in its sample `POST /api/coach/analyze` payloads.

### 3. Historical documentation references

- `test_reports/iteration_3.json`
- `test_reports/iteration_4.json`
- `test_reports/iteration_10.json`
- `test_reports/iteration_11.json`

These remaining references are historical evidence snapshots only and were intentionally left unchanged.

## Remaining `deep_analysis` references

- `frontend/src/__tests__/coach-page.test.jsx`: assertion that the payload does **not** contain `deep_analysis`.
- `backend/tests/test_coach_contract_unified.py`: regression assertions that `CoachRequest` no longer exposes `deep_analysis`.
- `test_reports/iteration_3.json`, `test_reports/iteration_4.json`, `test_reports/iteration_10.json`, `test_reports/iteration_11.json`: historical reports kept as archived snapshots.

## Tests executed

### Executed

1. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_coach_contract_unified.py tests/test_coach_context_v2.py tests/test_rag_endpoints.py tests/test_workout_analysis_v2.py`
2. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/frontend && npx craco test --watchAll=false --forceExit --runTestsByPath src/__tests__/coach-page.test.jsx`

### Results

- Passed: `82`
- Failed: `0`
- Not executed: `16`

### Not executed

- `backend/tests/test_coach_conversational.py` (`16` tests) was not executed in this sandbox because it depends on an external `REACT_APP_BACKEND_URL` integration target rather than the in-process ASGI test client used by the repository unit suites.

## Validation limits

- The conversational integration suite in `backend/tests/test_coach_conversational.py` was not runnable without an external backend target.
- Backend test runs emitted existing unrelated deprecation warnings from FastAPI/Pydantic multipart startup code paths; they did not block execution.

## PR publication

- PR number: `PENDING_PR_NUMBER`
- PR URL: `PENDING_PR_URL`

