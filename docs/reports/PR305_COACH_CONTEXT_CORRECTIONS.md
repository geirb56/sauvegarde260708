# PR305 Coach context corrections

## Revisions

- Base (`copilot/dev`): `933ab88f7bf5d5092b13e54d2ab1bdf5103fea73`
- Starting HEAD: `e15c7f739c6ef4e5d5a740c32b0d491c4c4479da`
- Corrective code HEAD: `be6f37b6ccf8d7916e93e1bf432e48ee03f38c0f`
- Branch: `copilot/restore-factual-context-coach`
- PR: [#305](https://github.com/geirb56/sauvegarde260708/pull/305)

The corrective code commit was pushed to the existing PR branch. This report is a follow-up documentation change; no merge was performed.

## Files changed

- `backend/coach_context_v2.py`
- `backend/workout_analysis_v2_service.py` (new)
- `backend/server.py`
- `backend/llm_coach.py`
- `backend/tests/test_coach_context_v2.py`
- `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
- `frontend/src/pages/WorkoutDetail.jsx`
- `docs/reports/PR305_COACH_CONTEXT_CORRECTIONS.md` (this report)

## Corrections

1. **Workout ID validation before side effects:** `/coach/analyze` looks up the requested workout using both `id` and the authenticated `user_id` before quota reservation, conversation persistence, or LLM invocation. Missing and foreign workouts receive the same `404 {"detail":"Workout not found"}`. Endpoint tests check both cases and verify no LLM call, persisted messages, or quota change/reservation; valid and absent `workout_id` paths remain covered.
2. **Factual Garmin history and exact date window:** recent sessions are read from the user-scoped `garmin_activities` source. The date window is J−29 inclusive through J inclusive (query interval `[J−29, J+1)`), with the same secondary validation, future-date exclusion, descending order, and 30-session cap. Missing measurements remain `None`, while valid zero elevation is preserved.
3. **Coverage metadata:** typed context reports the window, included start/end dates, eligible count before capping, sent count, maximum count, and truncation status. Prompts warn that bounded or truncated history is not necessarily the complete period history.
4. **Shared canonical analysis:** Coach context and the workout-analysis endpoint use the shared scoped loader/builder in `workout_analysis_v2_service.py`, avoiding separate query windows and orchestration. No parallel analysis calculation was added.
5. **Inference guardrails:** system and enrichment prompts distinguish descriptive metrics from physiological conclusions, disallow unsupported threshold/intensity/progress inferences, require unavailable conclusions to be identified, and preserve Training V2 as the prescription authority.
6. **Frontend route:** the integration test loads WorkoutDetail and the actual Coach component, clicks “Ask Coach,” checks the mocked `/coach/analyze` POST and `workout_id`, and checks the rendered response. Navigation retains `encodeURIComponent(id)`.

## Validation performed

Targeted backend suites passed individually:

- `cd backend && python -m pytest -q tests/test_coach_context_v2.py` — 16 passed.
- `cd backend && python -m pytest -q tests/test_coach_contract_unified.py` — 27 passed.
- `cd backend && python -m pytest -q tests/test_idor_authorization.py` — 15 passed.
- `cd backend && python -m pytest -q tests/test_workout_analysis_v2.py` — 119 passed.

Targeted frontend tests:

- `cd frontend && npm test -- --watchAll=false --runInBand src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/coach-page.test.jsx` — 2 suites passed, 9 tests passed. Console output included existing fallback/network warnings; tests passed.
- `cd frontend && npm run build` — passed.

Additional checks passed: Python `compileall` and `git diff --check`.

**Combined backend run:** running the four backend modules together resulted in 13 failures and 164 passes, concentrated in Coach context tests with cross-module mocks/application-context interactions. Each module passed when rerun individually. The combined run is not reported as passing and should be rechecked in the target Emergent environment.

**Environment/CI notes:** complete backend dependency setup was unavailable because required Emergent-hosted wheels (`customer-assets.emergentagent.com` and `emergentintegrations`) could not be fetched due to DNS/network access. The targeted suites were run individually with the available dependencies. GitHub Actions checks inspected for this task were still in progress on the previous HEAD `e15c7f7`; fetching their job logs returned HTTP 404, so no CI result for the corrective commit is claimed.

Commands to re-run in Emergent:

```sh
cd backend
python -m pytest -q tests/test_coach_context_v2.py
python -m pytest -q tests/test_coach_contract_unified.py
python -m pytest -q tests/test_idor_authorization.py
python -m pytest -q tests/test_workout_analysis_v2.py

cd ../frontend
npm test -- --watchAll=false --runInBand src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/coach-page.test.jsx
npm run build
```

## LLM validation limits

Prompt tests capture the prompts and context passed to the LLM call boundary, including sessions of 21.27 km / 160 bpm and 10.18 km / 127 bpm, with absent analysis and unavailable V2 conclusions. They verify factual context and explicit guardrails only. No real LLM call was made, so these tests do not establish that a model will always follow the instructions.
