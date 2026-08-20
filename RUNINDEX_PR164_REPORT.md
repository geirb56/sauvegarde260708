# RUNINDEX_PR164_REPORT

## Metadata

HEAD départ        : be2b7ac  (post-merge PR#163)  
HEAD #164          : see branch copilot/dev (PR#164 commit)

DRIFT_PR156_CONFIRMED = YES  
DRIFT_PR157_CONFIRMED = YES

---

## Scan complet

### A. `build_weekly_target_from_workouts` occurrences

| File | Occurrences | Classification |
|------|-------------|----------------|
| tests/test_pr157_remove_determine_target_load.py | 1 | OBSOLETE_BY_PR163 ← **FIXED** |
| tests/test_pr163_long_run_v2_authority.py | multiple | CURRENT_CONTRACT (tests both old and new bridge for parity) |
| tests/test_pr149_week_plan_v2.py | multiple | CURRENT_CONTRACT (unit tests of the helper itself) |
| tests/test_pr162_week_plan_observed_weekly_km.py | 1 | CURRENT_CONTRACT (mock of helper, not its caller) |

### B. `build_weekly_plan_from_workouts` occurrences

| File | Occurrences | Classification |
|------|-------------|----------------|
| tests/test_pr163_long_run_v2_authority.py | multiple | CURRENT_CONTRACT |
| tests/test_pr157_remove_determine_target_load.py | 1 | CURRENT_CONTRACT (after fix) |

### C. `distance_km > 0` on all active sessions without `target_basis` guard

| File | Occurrences | Classification |
|------|-------------|----------------|
| tests/test_pr156_no_unvalidated_tss_generate_cycle_week.py::test_distances_and_types_preserved | 1 | OBSOLETE_BY_PR163 ← **FIXED** |
| tests/test_resume_guard_pr76.py | 1 | UNRELATED (guard logic, not prescription contract) |
| tests/test_runner_profile_pr07.py | 2 | UNRELATED (profile window, not prescription) |
| tests/test_weekly_target_v2.py | 2 | CURRENT_CONTRACT (prior_running_window attribute) |
| tests/test_data_isolation.py | 1 | UNRELATED (pace calculation helper) |

### D. `compute_long_run_km` test occurrences

| File | Classification |
|------|----------------|
| tests/test_training_engine_pr2.py | LEGACY_UNIT_TEST_INTENTIONAL — tests the legacy helper directly, not runtime path |
| tests/test_workout_generator_v2.py | CURRENT_CONTRACT — tests `_compute_long_run_km` which is V2 internals |
| tests/test_dynamic_plan_v2_pr135.py | CURRENT_CONTRACT — scan confirms compute_long_run_km not called at runtime |
| tests/test_pr163_long_run_v2_authority.py | CURRENT_CONTRACT — tests that compute_long_run_km is NOT in llm_coach path |

### E. Legacy long-run minimum assertions (16 km semi / 28 km marathon)

| File | Classification |
|------|----------------|
| tests/test_pr163_long_run_v2_authority.py (lines 147–178, 200–211) | CURRENT_CONTRACT — these tests *prove* the minimums are NOT enforced (no artificial floor) |

---

## Summary

```
OBSOLETE_BY_PR163 found    = 2
OBSOLETE_BY_PR163 fixed    = 2
OBSOLETE_BY_PR163 remaining = 0
```

---

## Contract verification

### PR156 semantic contract after fix

**DISTANCE/DURATION AWARE : YES**

- `test_distances_and_types_preserved` — base context (no `long_run_km_v2`):
  - Non-long_run active sessions: `distance_km > 0` AND `duration > 0` (volume-driven, always true)
  - long_run: 0/0 placeholder acceptable when no V2 authority provided (duration-based)
- `test_distances_and_types_preserved_distance_based` — explicit distance context (`target_km_protected=42`, `long_run_km_v2=24`):
  - ALL active sessions including long_run: `distance_km > 0` AND `duration > 0`
- `test_distances_and_types_preserved_duration_based` — explicit duration context (no V2 long run):
  - Non-long_run: `duration > 0` (volume-driven fallback)
  - long_run: `distance_km >= 0` (no artificial km invented)

PR156 continues to prove:
- active `estimated_tss = None` ✓
- rest `estimated_tss = 0` ✓
- `total_tss = None` ✓
- session types valid ✓
- prescription distance valid when distance-based ✓
- prescription duration valid when duration-based ✓

### PR157 source check

**AST / STRING : AST (with string match inside AST-extracted function source)**

`test_weekly_target_v2_used_in_week_plan_source` now verifies via AST:
1. `build_weekly_plan_from_workouts` is present in `get_week_plan` source (PR#163 canonical entry point)
2. `weekly_target.target_basis` is consumed
3. `weekly_target.target_km` is consumed

PR157 continues to prove:
- `determine_target_load` absent from week-plan path ✓
- WeeklyTarget V2 remains authority ✓
- Canonical entry point = `build_weekly_plan_from_workouts` ✓
- `weekly_target.target_basis` used ✓
- `weekly_target.target_km` used ✓
- `target_load` does not influence prescription ✓

### WeeklyTarget authority still tested

**YES** — `weekly_target.target_basis` and `weekly_target.target_km` asserted in PR157 AST test.

---

## Quality checks

```
test weakening introduced   = NO
code applicatif modifié     = NO
```

---

## Test results (relevant suites)

| Suite | Passed | Failed | Errors |
|-------|--------|--------|--------|
| test_pr156_no_unvalidated_tss_generate_cycle_week.py | 16 | 0 | 0 |
| test_pr157_remove_determine_target_load.py | 10 | 0 | 0 |
| test_pr163_long_run_v2_authority.py | 55 | 0 | 0 |
| test_pr149_week_plan_v2.py | 41 | 0 | 0 |
| test_pr153_fallback_no_unvalidated_tss.py | ✓ | 0 | 0 |
| test_pr161_no_double_guard.py | ✓ | 0 | 0 |
| test_workout_generator_v2.py | ✓ | 0 | 0 |
| test_weekly_target_v2.py | ✓ | 0 | 0 |
| test_pr162_week_plan_observed_weekly_km.py | errors (httpx/fastapi not installed in sandbox) | — | 2 |
| test_pr155_week_plan_no_legacy.py | errors (httpx/fastapi not installed in sandbox) | — | 2 |

Total across all runnable suites: **271 passed, 0 failed** (4 collection errors due to missing fastapi/httpx in sandbox — unrelated to PR#164 changes).

---

## Mergeability

```
PR test-only                          = YES
PR156 rouge repasse vert              = YES
PR157 rouge repasse vert              = YES
scan complet effectué                 = YES
aucun autre drift PR163 restant       = YES
tests non affaiblis                   = YES
aucun code runtime modifié            = YES
PR163 reste verte                     = YES
WorkoutGenerator/WeeklyTarget verts   = YES
tests pertinents = 0 failed           = YES
mergeable                             = YES
dette test-drift PR163 totalement fermée = YES
```

## Files modified

- `backend/tests/test_pr156_no_unvalidated_tss_generate_cycle_week.py`
- `backend/tests/test_pr157_remove_determine_target_load.py`
- `RUNINDEX_PR164_REPORT.md`

---

## VERDICT

**READY FOR MERGE INTO copilot/dev**
