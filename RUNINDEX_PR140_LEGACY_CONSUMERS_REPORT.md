# RUNINDEX PR140 — LEGACY CONSUMERS REPORT

## A. HEAD main

- `origin/main` = `9d1165627d991014b122d1ad51c6fd2e63c33117`

## B. HEAD PR

- Branche courante = `9d1165627d991014b122d1ad51c6fd2e63c33117`
- Donc `HEAD PR == HEAD main` au départ de ce nouveau livrable.

## C. Exhaustive consumer inventory of `training_engine.py`

`backend/training_engine.py` a été relu en entier (929 lignes). Les consommateurs directs actuels trouvés par lecture/grep sont :

| File | Kind | Direct import/use | Notes |
|---|---|---|---|
| `backend/server.py` | runtime | import bloc ligne 83 + import local `determine_target_load` ligne 4617 | principal consumer runtime |
| `backend/llm_coach.py` | runtime | import bloc ligne 21 | génération hebdo déterministe |
| `backend/tests/test_training_engine_pr2.py` | test | import direct | volume / long run / VMA legacy |
| `backend/tests/test_resume_guard_pr76.py` | test | import direct | resume guard |
| `backend/tests/test_cycle_dates.py` | test | import direct | cycle dates |
| `backend/tests/test_current_weekly_km_unification.py` | test | import direct | weekly km invariants |
| `backend/tests/test_training_metrics_pr127.py` | test | import direct | `determine_target_load`, `adjust_load_by_fatigue` |
| `backend/tests/test_coach_load_context_pr128.py` | test | import direct | `build_training_context` |
| `backend/tests/test_plan_duration_decoupled.py` | test | import direct | `GOAL_CONFIG` |
| `backend/tests/test_run_index_r129_training_today_fallback.py` | test | import direct | `adapt_session_to_readiness` legacy fallback |

Total direct consumers: **10** = **2 runtime + 8 test-only**.

## D. Classification A/B/C/D/E/F for each consumer

Legend used in this report:

- **A** = no direct consumer left
- **B** = migrated to extracted performance layer (`training_v2.performance`)
- **C** = indirect compat-only path, no direct `training_engine` import
- **D** = active runtime direct legacy consumer
- **E** = dead runtime residue / unused direct dependency
- **F** = test-only direct consumer

Current direct consumer classification:

| Consumer | Class | Why |
|---|---|---|
| `backend/server.py` | D | direct runtime dependency across goal metadata, reprise state, full-cycle and week-plan |
| `backend/llm_coach.py` | D | direct runtime dependency for weekly structure / target volume / reprise helpers |
| `backend/tests/test_training_engine_pr2.py` | F | direct import only for regression coverage |
| `backend/tests/test_resume_guard_pr76.py` | F | test-only |
| `backend/tests/test_cycle_dates.py` | F | test-only |
| `backend/tests/test_current_weekly_km_unification.py` | F | test-only |
| `backend/tests/test_training_metrics_pr127.py` | F | test-only |
| `backend/tests/test_coach_load_context_pr128.py` | F | test-only |
| `backend/tests/test_plan_duration_decoupled.py` | F | test-only |
| `backend/tests/test_run_index_r129_training_today_fallback.py` | F | test-only |

Notes:

- No current direct consumer is class **E** on HEAD: the dead runtime performance imports noted in the old audit were already removed before this report.
- The performance extraction itself is class **B**, but it now lives in `training_v2.performance`/`coach_service.py`, not as a current direct consumer of `training_engine.py`.

## E. Endpoints concerned

Runtime paths still tied to `training_engine.py` from the actual code:

- `/training/plan` → `generate_dynamic_training_plan()` (runtime payload later exposes VMA/VO2max/paces computed outside `training_engine`, but route family remains in the legacy surface area)
- `/training/refresh` → same path as above
- `/training-plan` → same path as above
- `/training/dynamic-plan` → same path as above
- `/training/metrics` → still uses `classify_training_state()` to derive `acwr_reliable`
- `/training/full-cycle` → still uses `GOAL_CONFIG`, `compute_cycle_dates`, `compute_current_weekly_km`, `resolve_chronic_base`, `resolve_reprise_plan`, `determine_phase`, `get_phase_description`, running filters
- `/training/week-plan` → still uses `compute_current_weekly_km`, `determine_phase`, `determine_target_load`, `resolve_reprise_plan`, running filters, plus `llm_coach.generate_cycle_week()`
- `/training-plan/set-goal` and `/training/goals` → still expose `GOAL_CONFIG`

## F. VMA inventory

- Extracted compatibility source of truth: `backend/training_v2/performance.py`
  - `DEFAULT_COMPATIBILITY_VMA_KMH = 12.0`
  - `estimate_legacy_vma_from_normalized_runs()`
  - `build_legacy_performance_compatibility()`
- `backend/training_engine.py` no longer owns VMA math; it only imports/re-exports `vma_pace` and `vma_pace_range` from `training_v2.performance`.
- `backend/tests/test_performance_extraction_pr138.py` characterizes VMA parity on effort / average / invalid / empty inputs.
- `backend/tests/test_training_plan_vma.py` expects runtime `/api/training/plan` and `/api/training/full-cycle` payloads to expose VMA-related fields, but that file needs a live backend URL to run successfully.

## G. VO2max inventory

- Extracted compatibility function: `training_v2.performance.compute_vo2max_from_vma()`
- Formula preserved: `VO2max = VMA * 3.5`
- `build_legacy_performance_compatibility()` returns `(vma, vo2max, method, confidence, paces)`
- Characterization coverage exists in `test_performance_extraction_pr138.py`
- `test_training_plan_vma.py` also expects `/api/training/plan` responses to expose `vo2max` when a live environment is available.

## H. Paces inventory

- Extracted helpers:
  - `vma_pace()`
  - `vma_pace_range()`
  - `build_legacy_pace_zones()`
- Pace zones preserved in the extracted layer:
  - `z1`, `z2`, `z3`, `z4`, `z5`, `marathon`, `semi`
- `llm_coach.generate_cycle_week()` consumes `personalized_paces` / `context["paces"]` and falls back to parsing default strings if absent.
- `server.py` fallback week plan still contains hard-coded fallback pace strings when LLM generation fails.

## I. Fallbacks

- `training_v2.performance`:
  - invalid/non-positive VMA input → `compute_vo2max_from_vma()` returns `None`
  - invalid pace computation → `vma_pace()` returns `"--:--"`
  - no usable run sample → default VMA `12.0`, method `default`, confidence `low`
- `llm_coach.generate_cycle_week()`:
  - `target_km_protected` absent → recompute from `compute_target_km()`
  - missing pace strings → local `parse_pace()` falls back to `6.0`
- `server.py` `/training/week-plan`:
  - failed `generate_cycle_week()` → `_generate_fallback_week_plan()`
- Runtime smoke:
  - no live backend/auth/db context here, so endpoint-level compatibility cannot be proven locally.

## J. Extraction performed

- Verified extracted file: `backend/training_v2/performance.py`
- Verified legacy module import now points at extracted helpers: `backend/training_engine.py` imports `vma_pace`, `vma_pace_range` from `training_v2.performance`
- Verified runtime compatibility layer uses extraction: `backend/coach_service.py` imports `build_legacy_performance_compatibility` and propagates `vma`, `vo2max`, `vma_method`, `vma_confidence`, `paces`
- No modification was made to `training_engine.py`, `training_v2/*.py`, or tests for this deliverable.

## K. Parity tests

Executed successfully:

- `cd backend && python -m pytest tests/test_performance_extraction_pr138.py tests/test_performance_architecture_pr138.py -v`
- Result: **23 passed in 0.52s**

What this proves:

- extracted VMA/VO2max/pace math matches the characterized legacy behavior
- architecture guards pass: `training_state`, `weekly_target`, `weekly_reconciliation`, `readiness_decision`, `daily_adaptation` do not import `training_v2.performance`
- `training_v2` public namespace does not expose the legacy performance API

## L. Consumers remaining to migrate

Runtime remaining before `training_engine.py` can die:

1. `backend/server.py`
   - `/training/metrics`
   - `/training/full-cycle`
   - `/training/week-plan`
   - `GOAL_CONFIG` exposure in goal endpoints
2. `backend/llm_coach.py`
   - `compute_target_km`
   - `apply_resume_guard`
   - `compute_long_run_km`
   - `build_reprise_week_structure`
   - `reprise_deep_durations`
   - `reprise_durations`
   - `REPRISE_DEEP_SESSION_MINUTES`
   - `VOLUME_GOAL_CONFIG`
   - `DEFAULT_WEEKLY_KM`
3. Test-only consumers listed in section C, to be rewired only after runtime consumers are eliminated.

## M. Dead code identified

Dead-or-near-dead legacy surface identified from the current codebase:

- `adapt_session_to_readiness` → test-only direct consumer found
- `build_training_context` → test-only direct consumer found
- `adjust_load_by_fatigue` → test-only direct consumer found
- `compute_week_number` → no current direct runtime consumer found
- `compute_monotony` → no current direct runtime consumer found
- `compute_strain` → no current direct runtime consumer found

Important nuance: these are **not** safe-to-delete yet simply because `training_engine.py` still has runtime consumers elsewhere.

## N. Blockers before killing `training_engine.py`

- runtime direct consumers still exist in `server.py` and `llm_coach.py`
- `training/full-cycle` still depends on legacy cycle/phase/reprise helpers
- `training/metrics` still depends on legacy reprise classification for ACWR reliability
- `training/week-plan` still depends on legacy target load / reprise plumbing
- 8 test files still import `training_engine.py`
- required zero-runtime-consumer proof is not yet met

## O. Tests

Executed in this task:

1. `cd backend && python -m pytest tests/test_performance_extraction_pr138.py tests/test_performance_architecture_pr138.py -v`
   - **PASS**: 23 passed in 0.52s

2. `cd backend && python -m pytest tests/test_daily_adaptation_pr133.py tests/test_training_v2_readiness_decision.py tests/test_weekly_target_v2.py -v`
   - **PASS**: 96 passed in 0.61s

3. `cd backend && python -m pytest tests/test_performance_extraction_pr138.py tests/test_performance_architecture_pr138.py tests/test_training_plan_vma.py -v`
   - **PARTIAL / ENV-BOUND**
   - `test_performance_extraction_pr138.py` + `test_performance_architecture_pr138.py` pass
   - `test_training_plan_vma.py` fails locally: **20 failed, 23 passed in 13.90s**
   - failure mode is environment/config, not extraction parity: `requests.exceptions.MissingSchema` because `REACT_APP_BACKEND_URL` is empty, so the test tries to call URLs like `/api/training/plan` and `/api/training/full-cycle` without a scheme/host

## P. Runtime smoke

- Not verifiable in this non-live environment.
- No backend server, auth context, Mongo dataset, or `REACT_APP_BACKEND_URL` was available here.
- The existing HTTP smoke file `test_training_plan_vma.py` confirms that live endpoint checks are still external-environment dependent.

## Q. Next logical step

- Migrate the remaining runtime helpers out of `training_engine.py` starting with `server.py` (`/training/full-cycle`, `/training/metrics`, `/training/week-plan`) and `llm_coach.generate_cycle_week()`.
- Keep `training_v2.performance` unchanged; that extraction is already in place and verified.
- After runtime consumers are removed, rewire the 8 test-only importers, then prove zero runtime dependency before any final deletion of `training_engine.py`.
