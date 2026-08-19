# RUNINDEX_PR145_REPORT.md

## 1. HEAD copilot/dev

```
09a256f Merge pull request #144 from geirb56/claude/bug-137-01-runtime-response-parsing-fix
```

## 2. État #143/#144

- #143 = MERGED (commit 0b6b6a0)
- #144 = MERGED (commit 09a256f)
- Both confirmed present in HEAD

## 3. Inventaire legacy avant PR145

### server.py — `from training_engine import` (before)

| Symbol | Runtime usage | Endpoint |
|--------|--------------|----------|
| `DEFAULT_WEEKLY_KM` | ✅ active | `/training/week-plan` |
| `GOAL_CONFIG` | ✅ active (display) | `/training/goals`, `/training-plan/set-goal`, `/training/full-cycle` |
| `compute_current_weekly_km` | ✅ active | `/training/full-cycle`, `/training/week-plan` |
| `compute_cycle_dates` | ✅ active | `/training/full-cycle` |
| `compute_target_km` | ✅ active | `/training/full-cycle` |
| `apply_resume_guard` | ✅ active | `/training/full-cycle` |
| `resolve_chronic_base` | ✅ active | `/training/full-cycle` |
| `resolve_reprise_plan` | ✅ active | `/training/full-cycle`, `/training/week-plan` |
| `REPRISE_STABLE_WEEKS` | ✅ active | `/training/full-cycle` |
| `vma_pace` | ❌ DEAD import | none — never called |
| `vma_pace_range` | ❌ DEAD import | none — never called |
| `adapt_session_to_readiness` | ❌ DEAD import | none — never called |
| `compute_week_number` | ✅ active | `/training/week-plan` |
| `determine_phase` | ✅ active | `/training/full-cycle`, `/training/week-plan` |
| `get_phase_description` | ✅ active | `/training/full-cycle`, `/training/week-plan` |
| `is_running` | ✅ active | `/training/full-cycle`, `/training/week-plan` |
| `normalized_distance_km` | ✅ active | `/training/full-cycle`, `/training/week-plan` |
| `determine_target_load` | ✅ active (inline import) | `/training/week-plan` |

### llm_coach.py — `from training_engine import`

| Symbol | Runtime usage | Function |
|--------|--------------|----------|
| `DEFAULT_WEEKLY_KM` | ✅ active | `generate_cycle_week()` |
| `compute_target_km` | ✅ active | `generate_cycle_week()` |
| `apply_resume_guard` | ✅ active | `generate_cycle_week()` |
| `compute_long_run_km` | ✅ active | `generate_cycle_week()` |
| `build_reprise_week_structure` | ✅ active | `generate_cycle_week()` |
| `REPRISE_DEEP_SESSION_MINUTES` | ✅ active | `generate_cycle_week()` |
| `reprise_deep_durations` | ✅ active | `generate_cycle_week()` |
| `reprise_durations` | ✅ active | `generate_cycle_week()` |
| `VOLUME_GOAL_CONFIG` | ✅ active | `generate_cycle_week()` |

### coach_service.py

No `training_engine` imports — clean.

## 4. Classification

### Dead imports (removed in PR145)
- `vma_pace` — imported in server.py, never called
- `vma_pace_range` — imported in server.py, never called
- `adapt_session_to_readiness` — imported in server.py, never called

### Display-only (migrated in PR145)
- `GOAL_CONFIG` — pure static constant used for display; extracted to `backend/config/training_goals.py` as single source of truth

### Runtime active (NOT migrated)
- All other symbols in server.py and llm_coach.py

### Test-only consumers
| File | Symbol |
|------|--------|
| `test_plan_duration_decoupled.py` | `GOAL_CONFIG` |
| `test_resume_guard_pr76.py` | `apply_resume_guard`, `compute_target_km` |
| `test_current_weekly_km_unification.py` | `compute_current_weekly_km` + others |
| `test_training_metrics_pr127.py` | `determine_target_load`, `adjust_load_by_fatigue` |
| `test_run_index_r129_training_today_fallback.py` | `adapt_session_to_readiness` |
| `test_cycle_dates.py` | `compute_cycle_dates` |
| `test_training_engine_pr2.py` | multiple |
| `test_coach_load_context_pr128.py` | `build_training_context` |

## 5. Classement des candidats (plus simple → plus risqué)

| # | Consumer | Scope | V2 equiv? | Risque | Autonome? |
|---|----------|-------|-----------|--------|-----------|
| 1 | Dead imports (vma_pace, vma_pace_range, adapt_session_to_readiness) | 0 endpoints | N/A | zero | ✅ |
| 2 | GOAL_CONFIG (display) | 3 endpoints | Pure data | low | ✅ |
| 3 | `/training/week-plan` | 1 endpoint, 8+ symbols | Partial | medium | ❌ complex |
| 4 | `/training/full-cycle` | 1 endpoint, 12+ symbols | Partial | high | ❌ very complex |
| 5 | `llm_coach.generate_cycle_week()` | LLM path, 9 symbols | No | high | ❌ high risk |

## 6. Consumer choisi

**GOAL_CONFIG extraction to neutral source + dead import removal**

## 7. Justification

- `GOAL_CONFIG` is a pure static data constant with no computation logic
- Used only for display responses in 3 endpoints (`/training/goals`, `/training-plan/set-goal`, `/training/full-cycle`)
- All 3 endpoints use it only for field lookups (`cycle_weeks`, `description`, `long_run_ratio`, `intensity_pct`)
- No V2 computation depends on it — it's a UI contract
- Dead imports have zero runtime effect — their removal is provably safe
- Combined: removes 4 symbols from the legacy import (GOAL_CONFIG, vma_pace, vma_pace_range, adapt_session_to_readiness)

## 8. Migration effectuée

### Architecture

```
AVANT:
  server.py → training_engine.GOAL_CONFIG

APRÈS:
  backend/config/training_goals.py   ← single source of truth
      ↓
  server.py → from config.training_goals import GOAL_CONFIG

TEMPORAIREMENT:
  training_engine.GOAL_CONFIG → conservé pour legacy/tests
  → suppression future avec kill legacy
```

### Actions

1. Removed dead imports: `vma_pace`, `vma_pace_range`, `adapt_session_to_readiness`
2. Removed `GOAL_CONFIG` from `training_engine` import in server.py
3. Created `backend/config/training_goals.py` as single neutral source for `GOAL_CONFIG`
4. server.py imports from `config.training_goals` (not local copy, not training_engine)
5. All existing endpoint behavior preserved (same data, same structure)

## 9. Fichiers modifiés

- `backend/config/training_goals.py` — NEW: single source of truth for GOAL_CONFIG
- `backend/server.py` — import block cleaned + imports GOAL_CONFIG from config.training_goals
- `backend/tests/test_goal_config_pr145.py` — new characterization tests importing real constant
- `RUNINDEX_PR145_REPORT.md` — this report

## 10. Contrat avant/après

| Aspect | Before | After |
|--------|--------|-------|
| `/training/goals` response | `{goals: [...]}` from training_engine.GOAL_CONFIG | `{goals: [...]}` from config.training_goals.GOAL_CONFIG |
| `/training-plan/set-goal` response | `{cycle_weeks, description}` from training_engine.GOAL_CONFIG | identical values from config.training_goals.GOAL_CONFIG |
| `/training/full-cycle` cycle_weeks | from training_engine.GOAL_CONFIG | from config.training_goals.GOAL_CONFIG |
| HTTP contract | unchanged | unchanged |
| `training_engine.py` | still exports GOAL_CONFIG | unchanged (not deleted, kept for legacy/tests) |

## 11. Tests

- `test_goal_config_pr145.py` — 5 tests all passing:
  - `test_goal_config_matches_legacy` — config.training_goals.GOAL_CONFIG == training_engine.GOAL_CONFIG
  - `test_goal_config_keys` — all goal types present
  - `test_goal_config_fields` — all display fields present
  - `test_server_imports_from_config_training_goals` — server.py uses config.training_goals
  - `test_dead_imports_removed` — dead symbols removed from training_engine import

## 12. Consumers legacy restant après PR145

### Runtime consumers

| File | Endpoint/Path | Symbol | Future PR |
|------|---------------|--------|-----------|
| `server.py` | `/training/full-cycle` | `compute_cycle_dates`, `compute_current_weekly_km`, `compute_target_km`, `apply_resume_guard`, `resolve_chronic_base`, `resolve_reprise_plan`, `REPRISE_STABLE_WEEKS`, `determine_phase`, `get_phase_description`, `is_running`, `normalized_distance_km` | #146+ |
| `server.py` | `/training/week-plan` | `compute_current_weekly_km`, `compute_week_number`, `determine_phase`, `get_phase_description`, `is_running`, `normalized_distance_km`, `resolve_reprise_plan`, `DEFAULT_WEEKLY_KM`, `determine_target_load` | #146+ |
| `llm_coach.py` | `generate_cycle_week()` | `DEFAULT_WEEKLY_KM`, `compute_target_km`, `apply_resume_guard`, `compute_long_run_km`, `build_reprise_week_structure`, `REPRISE_DEEP_SESSION_MINUTES`, `reprise_deep_durations`, `reprise_durations`, `VOLUME_GOAL_CONFIG` | #147+ |

### Test-only consumers

| File | Symbol | Future |
|------|--------|--------|
| `test_plan_duration_decoupled.py` | `GOAL_CONFIG` | migrate to config.training_goals or remove when training_engine deleted |
| `test_resume_guard_pr76.py` | `apply_resume_guard`, `compute_target_km` | migrate with endpoint |
| `test_current_weekly_km_unification.py` | multiple | migrate with endpoint |
| `test_training_metrics_pr127.py` | `determine_target_load` | migrate with `/week-plan` |
| `test_run_index_r129_training_today_fallback.py` | `adapt_session_to_readiness` | dead — candidate for removal |
| `test_cycle_dates.py` | `compute_cycle_dates` | migrate with `/full-cycle` |
| `test_training_engine_pr2.py` | multiple | legacy test suite |
| `test_coach_load_context_pr128.py` | `build_training_context` | migrate with LLM coach |

## 13. Risques

- **Low** — GOAL_CONFIG is pure data, values are identical byte-for-byte
- Dead imports had no runtime effect
- `training_engine.py` is NOT modified or deleted
- Real modification of a runtime import dependency (server.py now imports from config.training_goals instead of training_engine)
- Parity test guarantees values remain synchronized with legacy

## 14. Dette long-run/reprise

Observed in `/training/full-cycle` and `llm_coach.generate_cycle_week()`:
- `compute_long_run_km` uses `long_run_ratio` from VOLUME_GOAL_CONFIG
- Potential disproportionate long run issue exists when base capacity is low vs goal distance
- NOT addressed in PR145 (out of scope)
- Recommend dedicated PR for long-run cap logic

## 15. Proposition #146

**Recommended next PR: `/training/week-plan` determine_target_load migration**

Rationale:
- Single endpoint
- `determine_target_load` is the only inline import (line 4634)
- If V2 TrainingLoad provides an equivalent, migration is straightforward
- If no V2 equivalent exists, `None` is acceptable per doctrine

Alternative: migrate `compute_week_number` and `determine_phase` first as they are pure utility functions that could live in a V2 module.

---

## Verdict

**READY FOR MERGE INTO copilot/dev**

- HEAD copilot/dev: `09a256f`
- HEAD PR#145: `a00a798`
- Consumer: GOAL_CONFIG extraction to neutral source + dead imports removal
- Files modified: `backend/config/training_goals.py`, `backend/server.py`, `backend/tests/test_goal_config_pr145.py`, `RUNINDEX_PR145_REPORT.md`
- Source unique runtime GOAL_CONFIG: `backend/config/training_goals.py`
- Symbols removed from training_engine import: `GOAL_CONFIG`, `vma_pace`, `vma_pace_range`, `adapt_session_to_readiness`
- Tests: 5/5 passing
- Risk: Low (pure data extraction, parity test, no behavior change)
