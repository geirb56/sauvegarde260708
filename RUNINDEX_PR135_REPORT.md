# RUNINDEX PR #135 — Runtime Plan V2 Migration Report

## 1) Canonical starting state

- `main` HEAD: `8564060b1162d4d56ea2136397e3ae8606a08b3e`
- PR #133: MERGED
- PR #134: MERGED

## 2) Scope delivered

- Migrated `backend/coach_service.py::generate_dynamic_training_plan()` from legacy structural decisions to Training V2 runtime orchestration.
- Added `backend/training_v2/runtime_plan_adapter.py` for V2→runtime payload adaptation only.
- Updated `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` canonical status:
  - #134 = MERGED
  - #135 = IMPLEMENTED / PENDING MERGE
  - NEXT = #136 Daily runtime migration

## 3) Effective V2 runtime chain now used

`TrainingHistory -> RunnerProfile -> TrainingState -> PlanGoal -> Periodization -> WeeklyTarget -> RecentTrainingResponse -> WeeklyReconciliation -> WorkoutGenerator -> runtime adapter payload`

## 4) PlanGoal mapping (runtime -> V2)

- `5K` -> `GoalType.five_k`
- `10K` -> `GoalType.ten_k`
- `SEMI` / `HALF_MARATHON` -> `GoalType.half_marathon`
- `MARATHON` -> `GoalType.marathon`
- `ULTRA` -> `GoalType.ultra`
- `MAINTENANCE` / `MAINTAIN` / `MAINTIEN EN FORME` -> `GoalType.maintenance`

ULTRA contract:
- `target_distance_km` required and must be strictly `> 42.195`.
- If ULTRA without exploitable distance: explicit `status="unavailable"` + `ULTRA_TARGET_DISTANCE_REQUIRED` (no invented distance).

## 5) Runtime payload compatibility notes

- Preserved runtime top-level fields used by consumers:
  - `plan`, `week`, `phase`, `goal`, `sessions_per_week`, `current_week`, `total_weeks`, `status`,
    `event_date`, `start_date`, `end_date`, `debug_volume`
- Preserved compatibility performance fields:
  - `vma`, `vo2max`, `vma_method`, `vma_confidence`, `paces`
- `readiness_score` kept as legacy compatibility field (not Readiness V2, not injected into V2 decision layers).

## 6) Legacy compatibility fields and exclusions

- `vma` / `vo2max` / `vma_method` / `vma_confidence` / `paces`:
  - kept temporarily for compatibility only
  - not used to decide TrainingState/WeeklyTarget/WeeklyReconciliation/Periodization
- `readiness_score`:
  - legacy compatibility field (volume/fitness weighted formula)
  - explicitly not Readiness V2
  - not used for structural V2 decisions
- static HR zones:
  - not used as canonical physiological source in V2 plan decisions
- `estimated_tss`:
  - not used as V2 physiological decision signal
  - represented as unavailable (`None`) in runtime session payload

## 7) Cache strategy (PR135)

Deterministic plan cache key now fingerprints structural V2 inputs:
- user
- reference date
- PlanGoal (`goal_type`, race date, distance if ultra)
- Periodization snapshot (mode/phase/cycle metadata)
- reconciled target (`basis`, km/minutes, sessions, allow_intensity, continuity_state)
- RecentTrainingResponse structural facts (`status`, confidence, observed volume/frequency, selected count)
- sessions override

Uses stable SHA-256 over sorted JSON (no `hash()`).

## 8) Error strategy (PR135)

- No silent `try V2 / except legacy training_engine fallback`.
- Explicit unavailable states returned for:
  - invalid/incomplete ULTRA target distance
  - periodization contract errors

## 9) Legacy callers remaining after #135 (search-based audit)

Search basis: `rg "from training_engine import|import training_engine" backend`

### Runtime/non-test callers

1. `backend/server.py`
   - imports and uses legacy planning functions for endpoints outside PR135 scope (`/training/full-cycle`, training metrics helpers, adaptation path pieces)
   - planned migration: #137 (`server/full-cycle legacy migration`) and later #139 (full engine removal)

2. `backend/llm_coach.py`
   - deterministic week generation helpers still import legacy planning utilities
   - remains out of PR135 structural migration path for `generate_dynamic_training_plan()`
   - planned migration: #137/#139 sequence

### Test-only callers (remaining intentionally)

- `backend/tests/test_plan_duration_decoupled.py`
- `backend/tests/test_resume_guard_pr76.py`
- `backend/tests/test_training_metrics_pr127.py`
- `backend/tests/test_current_weekly_km_unification.py`
- `backend/tests/test_run_index_r129_training_today_fallback.py`
- `backend/tests/test_training_engine_pr2.py`
- `backend/tests/test_coach_load_context_pr128.py`
- `backend/tests/test_cycle_dates.py`

## 10) `generate_dynamic_training_plan()` real callers (runtime)

- `backend/server.py`
  - `GET /training/plan`
  - `POST /training/refresh`
  - `GET /training-plan`
  - `GET /training/dynamic-plan` (legacy alias)
  - `GET /training/today` (consumes generated `plan.sessions`)

## 11) `generate_cycle_week()` boundary after PR135

- `generate_cycle_week()` is not removed.
- In PR135 migrated path, structural source of truth is V2 (`WorkoutGenerator` from reconciled target).
- No structural decision from `training_engine.py` is supplied as truth to the migrated runtime path.

## 12) Correction ciblée complémentaire (PR #135)

1. `sessions_override` / préférence fréquence côté runtime est maintenant un **cap utilisateur**:
   - `effective_sessions = min(weekly_target.target_sessions, sessions_preference)` si préférence valide.
   - La préférence peut réduire, jamais augmenter la prescription V2.
   - Cette règle reste dans le runtime (`coach_service`), pas dans `WeeklyTarget`.

2. La fréquence exposée dans le payload runtime est désormais canonique:
   - `sessions_per_week = reconciled_target.target_sessions`.
   - Le champ reflète toujours la prescription finale réellement planifiée.

3. TSS en runtime V2:
   - RunIndex V2 ne calcule pas de TSS dans ce chemin.
   - `estimated_tss = None` (séance) et `total_tss = None` (semaine).
   - `runtime_plan_adapter.py` reste un adaptateur de sérialisation sans calcul physiologique.

4. Roadmap conservée:
   - #134 = MERGED
   - #135 Runtime Plan V2 migration = IMPLEMENTED / PENDING MERGE
   - NEXT = #136 Daily runtime migration
