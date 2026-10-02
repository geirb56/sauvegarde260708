# PR305 Coach context corrections

## Revisions

- Base (`copilot/dev`): `933ab88f7bf5d5092b13e54d2ab1bdf5103fea73`
- Audited starting HEAD: `86baa8a181e5e83b256e2a4bfe0034dd47744339` (previous audited HEADs: `e15c7f739c6ef4e5d5a740c32b0d491c4c4479da`, `be6f37b6ccf8d7916e93e1bf432e48ee03f38c0f`)
- Branch: `copilot/restore-factual-context-coach`
- PR: [#305](https://github.com/geirb56/sauvegarde260708/pull/305)

All corrective commits are applied directly to the existing PR branch without creating a new PR and without merging.

## Files changed

- `backend/coach_context_v2.py`
- `backend/workout_analysis_v2_service.py`
- `backend/server.py`
- `backend/llm_coach.py`
- `backend/tests/test_coach_context_v2.py`
- `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
- `frontend/src/pages/WorkoutDetail.jsx`
- `docs/reports/PR305_COACH_CONTEXT_CORRECTIONS.md` (this report)

## Corrections

1. **Workout ID validation before side effects (P1):** `/coach/analyze` looks up the requested workout using both `id` and the authenticated `user_id` before quota reservation, conversation persistence, or LLM invocation. Missing and foreign workouts receive the exact same `404 {"detail":"Workout not found"}`. Endpoint tests check both cases and verify no LLM call, no persisted user or assistant messages, and no quota change/reservation. Valid and absent `workout_id` paths remain covered.
2. **Factual Garmin history and exact date window (P2):** recent sessions are read from the user-scoped `garmin_activities` source. The date window is exactly J−29 inclusive through J inclusive (query interval `[J−29, J+1)`), with the same secondary validation, future-date exclusion, descending order, and 30-session cap. Missing measurements remain `None`, while valid zero elevation (`elevation_gain_m = 0.0`) is strictly preserved (`None != 0`).
3. **Coverage metadata (P2):** typed context reports the window in days (30), included start and end dates, eligible count before capping, sent count, maximum count (30), and truncation status boolean. Prompts instruct the Coach that bounded or truncated history is a partial selection and not necessarily the complete period history.
4. **Shared canonical analysis (P1):** Coach context and the workout-analysis endpoint use the shared scoped loader/builder in `workout_analysis_v2_service.py`, avoiding separate query windows and orchestration. No parallel analysis calculation was added. Training V2 remains the sole prescription authority; Workout Analysis V2 remains the sole deterministic analysis authority.
5. **Garmin factual enrichment for Workout Analysis V2 (P1):** `db.workouts` is preserved as the identity authority and `id + user_id` access check. However, in `load_scoped_workout_analysis_v2()`, when a workout originates from Garmin (`workout_id.startswith("garmin-")` or `data_source == "garmin"`), the loader deterministically fetches the corresponding user-scoped record from `db.garmin_activities` (`user_id + external_id`). Before invoking `build_workout_analysis_v2()`, it factually enriches the workout document with available native Garmin observations (e.g. `max_heart_rate`, `avg_speed_kmh` converted from m/s, `elevation_gain_m` preserving true zeros, `avg_cadence_spm`, `km_splits`, `zone_distribution`, `heart_rate_zones`) without fabricating missing data or overwriting product IDs.
6. **Inference guardrails (P1):** system and enrichment prompts distinguish descriptive metrics from physiological conclusions, disallow unsupported threshold/intensity/progress inferences from raw heart rate/pace/splits/names, require unavailable conclusions to be clearly stated, and preserve Training V2 as the prescription authority.
7. **Frontend route integration (P1):** the integration test loads WorkoutDetail and the actual Coach component, clicks “Ask Coach,” checks the mocked `/coach/analyze` POST and `workout_id`, and checks the rendered response. Navigation retains `encodeURIComponent(id)`.

## Validation performed

Targeted backend suites passed:

- `cd backend && python3 -m pytest tests/test_coach_context_v2.py` — 19 passed (including 3 new tests validating Garmin factual enrichment from `garmin_activities`, strict user isolation preventing cross-user contamination, and end-to-end coach analyze pipeline integration).
- `cd backend && python3 -m pytest tests/test_workout_analysis_v2.py` — 119 passed.
- `cd backend && python3 -m pytest tests/test_idor_authorization.py` — 15 passed.
- Combined run of `test_coach_context_v2.py`, `test_workout_analysis_v2.py`, and `test_idor_authorization.py` — 153 passed in 2.19s.
- `cd backend && python3 -m pytest -n 0 tests/test_coach_contract_unified.py` — 27 passed.

Targeted frontend tests and build:

- `cd frontend && npx craco test src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/coach-page.test.jsx --watchAll=false --forceExit` — 2 suites passed, 9 tests passed.
- `cd frontend && npm run build` — compiled successfully.

Additional checks passed: Python syntax check and `git diff --check`.

**Combined backend run note:** running `test_coach_contract_unified.py` concurrently with other modules under xdist `-n 2 --dist loadscope` causes test interference due to global state patching on the `server` module in `test_coach_contract_unified.py`. Running `test_coach_contract_unified.py` with `-n 0` passes all 27 tests without issue.

**Environment/CI notes:** backend dependencies in the sandbox were installed using standard wheels. Full runtime dependencies requiring Emergent-hosted wheels (`customer-assets.emergentagent.com` and `emergentintegrations`) are not accessible directly in the sandbox due to network restrictions.

Commands to re-run in Emergent:

```sh
cd backend
python -m pytest tests/test_coach_context_v2.py
python -m pytest tests/test_workout_analysis_v2.py
python -m pytest tests/test_idor_authorization.py
python -m pytest -n 0 tests/test_coach_contract_unified.py

cd ../frontend
npx craco test src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/coach-page.test.jsx --watchAll=false --forceExit
npm run build
```

## LLM validation limits

Prompt tests capture the prompts and context passed to the LLM call boundary, including sessions of 21.27 km / 160 bpm and 10.18 km / 127 bpm, with absent analysis and unavailable V2 conclusions. They verify factual context, payload structure, and explicit guardrails only. No live external LLM API call was made during automated tests, so these tests verify prompt assembly and guardrail presence rather than stochastic model execution.
