# RUNINDEX PR #143 — Migration Report

## 1. HEAD main reel de depart
```
9d1165627d991014b122d1ad51c6fd2e63c33117 — Merge pull request #138 from geirb56/copilot/audit-consumers-legacy
```

## 2. HEAD copilot/dev avant travail
```
7ebfe167ccf5d559b7686596f9eebeaa795e5969 — Auto-generated changes (from abandoned #141/#142)
```

## 3. Preuve d'alignement
Changes applied on top of copilot/dev HEAD. PR #138 content verified present.

## 4. Fichiers modifies
- `backend/server.py` — migrated `/training/metrics` endpoint
- `backend/tests/test_training_metrics_pr143.py` — new test file (12 tests)
- `RUNINDEX_PR143_REPORT.md` — this report

## 5. Consumers legacy avant PR (runtime imports from training_engine in server.py)

| Symbol | Used by | Status |
|--------|---------|--------|
| `classify_training_state` | `/training/metrics` | **MIGRATED in this PR** |
| `DEFAULT_WEEKLY_KM` | `/training/full-cycle`, `/training/week-plan` | remaining |
| `GOAL_CONFIG` | `/training/full-cycle` | remaining |
| `compute_current_weekly_km` | `/training/full-cycle` | remaining |
| `compute_cycle_dates` | `/training/full-cycle` | remaining |
| `compute_target_km` | `/training/full-cycle`, `/training/week-plan` | remaining |
| `apply_resume_guard` | `/training/full-cycle`, `/training/week-plan` | remaining |
| `resolve_chronic_base` | `/training/full-cycle` | remaining |
| `resolve_reprise_plan` | `/training/full-cycle`, `/training/week-plan` | remaining |
| `REPRISE_STABLE_WEEKS` | `/training/full-cycle` | remaining |
| `vma_pace` | performance endpoints | remaining |
| `vma_pace_range` | performance endpoints | remaining |
| `adapt_session_to_readiness` | legacy adapter | remaining |
| `compute_week_number` | `/training/full-cycle` | remaining |
| `determine_phase` | `/training/full-cycle`, `/training/week-plan` | remaining |
| `get_phase_description` | `/training/full-cycle` | remaining |
| `is_running` | `/training/full-cycle` | remaining |
| `normalized_distance_km` | `/training/full-cycle` | remaining |
| `determine_target_load` | `/training/week-plan` (inline import) | remaining |

### llm_coach.py legacy imports (runtime)

| Symbol | Status |
|--------|--------|
| `DEFAULT_WEEKLY_KM` | remaining |
| `compute_target_km` | remaining |
| `apply_resume_guard` | remaining |
| `compute_long_run_km` | remaining |
| `build_reprise_week_structure` | remaining |
| `REPRISE_DEEP_SESSION_MINUTES` | remaining |
| `reprise_deep_durations` | remaining |
| `reprise_durations` | remaining |
| `VOLUME_GOAL_CONFIG` | remaining |

## 6. Migration reellement realisee

### `/training/metrics` — `acwr_reliable` derivation

**Before:** `classify_training_state(activities_28)` — legacy function receiving raw `db.workouts` Mongo docs.

**After:** Full V2 chain:
```
garmin_activities (Mongo)
-> mongo_garmin_activities_to_domain() -> DomainActivity[]
-> build_training_load() -> TrainingLoadSnapshot
-> build_training_history() -> TrainingHistory
-> build_runner_profile() -> RunnerProfile
-> build_training_state() -> TrainingState
-> .continuity_state -> acwr_reliable derivation
```

Also fixed: `build_training_load` now receives DomainActivity[] instead of raw Mongo docs.

## 7. Consumers legacy restant apres PR

### server.py runtime imports from training_engine:
- `DEFAULT_WEEKLY_KM`, `GOAL_CONFIG`, `compute_current_weekly_km`, `compute_cycle_dates`
- `compute_target_km`, `apply_resume_guard`, `resolve_chronic_base`, `resolve_reprise_plan`
- `REPRISE_STABLE_WEEKS`, `vma_pace`, `vma_pace_range`, `adapt_session_to_readiness`
- `compute_week_number`, `determine_phase`, `get_phase_description`
- `is_running`, `normalized_distance_km`
- `determine_target_load` (inline import line ~4620)

### llm_coach.py: 9 symbols (listed above)

### Test files: 6 test files import from training_engine (acceptable — testing legacy)

## 8. Endpoints affectes
- `/training/metrics` — migrated (reprise state detection only)

Endpoints NOT modified:
- `/training/today` — already uses V2 chain
- `/training/full-cycle` — remaining (complex, many legacy deps)
- `/training/week-plan` — remaining (depends on determine_target_load)

## 9. Invariants verifies
- acwr=None preserved when no chronic load
- No ACWR=1.0 default
- No raw Mongo docs passed to V2 layers in `/training/metrics`
- None != 0 respected
- No training_v2 -> training_engine dependency
- Reprise states correctly propagated
- /training/today untouched
- performance.py untouched
- No TSS/CTL/ATL fictif

## 10. Tests executes + resultats
- `test_training_metrics_pr143.py`: 12/12 passed
- `test_training_metrics_pr127.py`: 41/41 passed
- `test_weekly_target_v2.py`: passed
- `test_workout_generator_v2.py`: passed
- `test_resume_guard_pr76.py`: passed
- Total: 279 passed, 1 pre-existing failure unrelated to this PR

## 11. Diff scope
- 3 files added/modified
- ~25 lines changed in server.py (import + endpoint logic)
- 1 new test file (~120 lines)

## 12. Blockers restants
- `/training/full-cycle` uses ~14 legacy symbols — large scope
- `/training/week-plan` uses `determine_target_load` — needs WeeklyTarget V2 equivalent
- `llm_coach.generate_cycle_week()` — 9 legacy symbols for volume/reprise structure
- Long-run problem: goal-driven floor in `compute_long_run_km` — needs dedicated PR

## 13. Proposition PR #144
**Target:** Migrate `/training/week-plan` endpoint.
- `determine_target_load` -> derive from TrainingLoad V2 + WeeklyTarget V2
- Remove last inline `from training_engine import determine_target_load`
- Scope: single endpoint, well-contained
