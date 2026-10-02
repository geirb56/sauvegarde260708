# PR305 Coach context corrections

## Revisions

- Base (`copilot/dev`): `933ab88f7bf5d5092b13e54d2ab1bdf5103fea73`
- Audited starting HEAD: `163e10d4cb66334e52a5c39e5bd51ea3adec2bf1` (previous audited HEADs: `e15c7f739c6ef4e5d5a740c32b0d491c4c4479da`, `be6f37b6ccf8d7916e93e1bf432e48ee03f38c0f`, `86baa8a181e5e83b256e2a4bfe0034dd47744339`)
- Branch: `copilot/restore-factual-context-coach`
- PR: [#305](https://github.com/geirb56/sauvegarde260708/pull/305)

All corrective commits are applied directly to the existing PR branch without creating a new PR and without merging.

## Files changed

- `backend/coach_context_v2.py`
- `backend/workout_analysis_v2_service.py`
- `backend/server.py`
- `backend/llm_coach.py`
- `backend/tests/test_coach_context_v2.py`
- `backend/tests/test_coach_contract_unified.py`
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
8. **Logging Workout Analysis V2 errors (P2):** in `backend/workout_analysis_v2_service.py`, eliminated silent `except Exception: analysis = None` by introducing module-level `logger = logging.getLogger(__name__)` and logging `logger.exception("Workout Analysis V2 unavailable for workout_id=%s", workout_id)`. Sensitive data (tokens, emails, raw payload) are never logged.
9. **Real `activity_to_workout` pipeline tests (P1):** replaced manual dictionary fixtures in `test_coach_context_v2.py` with true calls to `backend.garmin.service::activity_to_workout(raw_garmin_activity, user_id)`. Verified the minimal derived workout creation, memory enrichment via `load_scoped_workout_analysis_v2()`, non-mutation of `db.workouts`, retention of true zeros (`elevation_gain_m = 0.0`), absence of unprovided fields, and strict cross-user isolation.
10. **Test isolation and xdist gate resolution (P1):** identified and resolved two inter-suite interference bugs:
    - Starlette `State` attribute deletion: replaced `patch.object(server.app.state, "db", ..., create=True)` with explicit `orig_state_db` save and restoration in `try...finally`.
    - Asyncio concurrent patch race: in `test_coach_contract_unified.py`, wrapped `asyncio.gather` calls with an outer `_analyze_environment` context manager instead of entering separate patches inside concurrent coroutines.

## Cause of xdist inter-suite interference & exact correction

### Root Causes
1. **Starlette `State` Attribute Deletion**:
   Starlette's `State` stores attributes in internal dictionary `_state` rather than `__dict__`. When `patch.object(server.app.state, "db", fake_db, create=True)` was used, `unittest.mock._patch.__exit__` failed to find `"db"` in `__dict__`, assumed it was newly created, and called `delattr(server.app.state, "db")`. Any subsequent test accessing `server.app.state.db` failed with `AttributeError: 'State' object has no attribute 'db'`.
2. **Concurrent `patch()` Race Condition**:
   In `test_coach_contract_unified.py`, concurrency tests (`test_free_concurrency_allows_only_one_when_at_9_of_10` and `test_concurrent_first_use_initialization_creates_single_counter_document`) called `asyncio.gather(_run_analyze(...), _run_analyze(...))` where each coroutine entered its own `with patch("server.build_coach_context_v2", ...)` context. Because coroutine tasks interleaved, Task 2 saved Task 1's mock as the original target. When both exited, `server.build_coach_context_v2` was permanently left as an `AsyncMock` returning dummy data, causing subsequent tests in `test_coach_context_v2.py` to receive mocked responses instead of running the real context builder.

### Exact Correction Applied
- In `backend/tests/test_coach_contract_unified.py`:
  - Replaced `patch.object(server.app.state, ...)` with safe assignment/restoration saving `getattr(server, "db", None)` and `getattr(server.app.state, "db", None)` in `try...finally`.
  - Created `_analyze_environment` to enter all mocks once *outside* `asyncio.gather(...)`, eliminating nested and concurrent patch activation.
  - Refactored concurrent tests to use `_send_analyze_request` inside `_analyze_environment`.
- In `backend/tests/test_coach_context_v2.py`:
  - Replaced `patch.object(server.app.state, "db", fake_db, create=True)` in `_call_coach` and `_call_invalid_workout_coach` with `_patch_server_db` saving and restoring `server.db` and `server.app.state.db` in `try...finally`.

## Validation performed

### Combined backend test gate (mandatory configuration: `-n 2 --dist loadscope` from `pytest.ini`)
```sh
cd backend
python -m pytest \
  tests/test_coach_context_v2.py \
  tests/test_coach_contract_unified.py \
  tests/test_idor_authorization.py \
  tests/test_workout_analysis_v2.py
```
**Result**: **181 passed in 2.49s** (0 skipped, 0 xfailed, full xdist concurrency).

### Garmin data layer & normalization tests
```sh
cd backend
python -m pytest \
  tests/test_garmin_data_layer.py \
  tests/test_garmin_activity_normalization_pr02.py
```
**Result**: **44 passed in 0.65s**.

### Real `activity_to_workout` tests
Covered in `tests/test_coach_context_v2.py`:
- `test_load_scoped_workout_analysis_v2_enriches_minimal_garmin_workout`: real `activity_to_workout()`, product identity retention, factual enrichment (`max_hr`, `elevation_gain=0.0`, `avg_speed_kmh`, `avg_cadence_spm`), missing fields remain absent, no physiological metrics invented, `fake_db.workouts` not mutated.
- `test_load_scoped_workout_analysis_v2_no_matching_garmin_source`: minimal workout preserved without crash, partial analysis available.
- `test_load_scoped_workout_analysis_v2_user_scoping_no_cross_contamination`: foreign user activity with matching `external_id` ignored, cross-user isolation preserved, foreign lookup returns 404.
- `test_coach_analyze_with_minimal_garmin_workout_pipeline`: real `activity_to_workout()` integrated with `/api/coach/analyze`.

### Targeted frontend tests & build
```sh
cd frontend
npx craco test \
  src/__tests__/workout-analysis-v2-pages.test.jsx \
  src/__tests__/coach-page.test.jsx \
  --watchAll=false \
  --forceExit
```
**Result**: **2 test suites passed, 9 tests passed in 3.056s**.

```sh
cd frontend
npm run build
```
**Result**: **Compiled successfully**.

### Static checks
```sh
git diff --check
```
**Result**: **Clean (exit code 0)**.

## LLM validation limits

Prompt tests capture the prompts and context passed to the LLM call boundary, including sessions of 21.27 km / 160 bpm and 10.18 km / 127 bpm, with absent analysis and unavailable V2 conclusions. They verify factual context, payload structure, and explicit guardrails only. No live external LLM API call was made during automated tests, so these tests verify prompt assembly and guardrail presence rather than stochastic model execution.
