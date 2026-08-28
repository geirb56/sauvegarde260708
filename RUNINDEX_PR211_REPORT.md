# RUNINDEX PR211 REPORT — Coach / LLM Legacy Cleanup

## Base / Head
- Base branch: `copilot/dev`
- Base SHA: `38e36e197ed10695c1cf7cf420326cc90836caf1` (includes merged PR #210)
- HEAD (core cleanup commit): `d3b54cf19e7bd670a9f59408a96314d502e691f0`

## Audit callers before changes
### `llm_coach.generate_cycle_week`
- Definition: `backend/llm_coach.py`
- Consumer import: `backend/coach_service.py` (imported but not runtime-called)
- Runtime caller audit:
  - No AST/runtime call in backend runtime paths.
  - `backend/server.py` contained only comments mentioning `generate_cycle_week`.
  - Existing references were mostly legacy tests.

### `coach_service._compute_legacy_performance_compatibility`
- Definition and runtime use were both inside `backend/coach_service.py`.
- Called by `generate_dynamic_training_plan()` to synthesize:
  - estimated VMA
  - fallback `12.0` VMA
  - derived VO2max (`VMA * 3.5`)
  - VMA-percent paces

### `coach_service._readiness_compatibility_score`
- Definition and runtime use were both inside `backend/coach_service.py`.
- Called by `generate_dynamic_training_plan()` (upcoming branch + active branch).
- Produced a compatibility metric but exposed as `readiness_score` (semantic collision risk with Readiness V2).

## Coach/LLM architecture before/after
### Before
- LLM module still contained a parallel deterministic weekly plan generator (`generate_cycle_week`) tied to legacy `training_engine`.
- Coach dynamic plan used legacy performance compatibility fallback generation.
- Compatibility metric surfaced as `readiness_score`.
- `/coach/analyze` built LLM physiological context using legacy VMA/prediction calculations from workouts.

### After
- `llm_coach.generate_cycle_week()` removed.
- `llm_coach` no longer imports `training_engine`.
- `coach_service` no longer imports or references `generate_cycle_week`.
- Legacy performance compatibility function removed and replaced by canonical sources:
  - Performance Model V2 (`predict_races` on Garmin DomainActivity) for VMA/method/confidence
  - Garmin observed VO2max (`garmin_vo2max` latest `vo2max_running`)
  - Training paces V2 (`compute_training_paces`) mapped to runtime pace slots
- Compatibility metric renamed to `goal_compatibility_score` (no `readiness_score` field in coach response payload/context).
- `/coach/analyze` now uses canonical V2 performance/paces context and Garmin observed VO2max (or unavailable), without synthetic fallback generation.

## Legacy functions removed
- `backend/llm_coach.py`
  - `generate_cycle_week` removed
- `backend/coach_service.py`
  - `_compute_legacy_performance_compatibility` removed
  - `_readiness_compatibility_score` removed

## Canonical replacement sources used
- Garmin VO2max observed:
  - `db.garmin_vo2max` latest `vo2max_running` (no invented fallback)
- Performance Model V2:
  - `training_v2.performance_model.predict_races(...)` for VMA signal (`vma_kmh`, `method`, `confidence`)
- Training paces canonical:
  - `training_v2.training_paces.compute_training_paces(...)`
- Missing data policy:
  - returns `None` / `{}` for unavailable VO2max/VMA/paces (no synthetic defaults)

## `_readiness_compatibility_score` treatment
- Removed and replaced with `_goal_compatibility_score`.
- Metric semantics now explicit compatibility for goal prep, not daily Readiness V2.
- Output key changed from `readiness_score` to `goal_compatibility_score`.

## LLM context fields and sources (audited)
### `/coach/analyze` (LLM chat enrichment)
- `stats_7j` / `stats_28j`: from `db.workouts` activity aggregation
- `fitness.acwr`: from `build_training_load(...)` on Garmin DomainActivity when available
- `fitness.tsb`: `None` (no synthetic alias)
- `all_sessions`: from recent workouts history formatting
- `training_plan`: from `db.training_plans`
- `current_goal`: from `db.training_plans`
- `vma`: from Performance Model V2 output (`predict_races`)
- `vo2max`: from Garmin observed `garmin_vo2max.vo2max_running`
- `predictions`: from Performance Model V2 predictions list
- `paces`: from Training Paces V2 output

### `/chat/send` via `coach_service.chat_response`
- LLM enrichment wrappers retained (`enrich_chat_response`, `enrich_weekly_review`, `enrich_workout_analysis`, `_call_gpt`).
- Fallback language handling updated to include Spanish unavailability message.

## LLM cleanup
- Removed stale `GPT-4o-mini` wording from edited module doc/comments.
- SYSTEM prompt goals list updated to include `MAINTENANCE`.
- Spanish unavailability message now returned in Spanish in coach fallback paths.

## Tests added/updated
- Added:
  - `backend/tests/test_pr211_coach_llm_cleanup.py`
- Reworked legacy generate-cycle suites to validate removal/no-caller state:
  - `backend/tests/test_pr156_no_unvalidated_tss_generate_cycle_week.py`
  - `backend/tests/test_pr157_remove_determine_target_load.py`
  - `backend/tests/test_pr161_no_double_guard.py`
  - `backend/tests/test_pr162_week_plan_observed_weekly_km.py`
  - `backend/tests/test_pr163_long_run_v2_authority.py`
- Updated compatibility test scaffolding:
  - `backend/tests/test_coach_load_context_pr128.py`

## Tests executed
- Command:
  - `python -m pytest tests/test_pr211_coach_llm_cleanup.py tests/test_dynamic_plan_v2_pr135.py tests/test_coach_load_context_pr128.py tests/test_pr156_no_unvalidated_tss_generate_cycle_week.py tests/test_pr157_remove_determine_target_load.py tests/test_pr161_no_double_guard.py tests/test_pr162_week_plan_observed_weekly_km.py tests/test_pr163_long_run_v2_authority.py`
- Result:
  - `36 passed`

## Blockers / notes
- Full `pip install -r backend/requirements.txt` was blocked by unreachable private wheel host (`customer-assets.emergentagent.com`) in this sandbox.
- Validation proceeded with minimal required test dependencies installed locally (`pytest`, `pytest-xdist`, `pytest-asyncio`, `python-dotenv`, `pydantic`).

LLM_TRAINING_ENGINE_IMPORTS = 0
LLM_PLAN_GENERATOR_LEGACY = 0
COACH_LEGACY_PERFORMANCE_FALLBACKS = 0

TRAINING_V2_PIPELINE_UNCHANGED = TRUE
READINESS_V2_FORMULA_UNCHANGED = TRUE
PERFORMANCE_V2_FORMULA_UNCHANGED = TRUE

Verdict :
PASS
