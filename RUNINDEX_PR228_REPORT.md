# RUNINDEX PR228 REPORT — Week / Today Unified Orchestration

**Branch:** `copilot/runindexpr-228`  
**Base:** `copilot/dev`  
**Status:** DEFERRED TO FINAL RUNTIME GATE

---

## Objective

Eliminate the divergence between the weekly prescription (`/training/v2/week`,
`/training/week-plan`) and the daily session (`/training/today`).

Before PR228:
- `/training/v2/week` and `/training/week-plan` used `build_weekly_plan_from_workouts`
  — no WeeklyReconciliation applied.
- `/training/today` used `generate_dynamic_training_plan` (coach_service.py),
  a separate code path that DID apply WeeklyReconciliation.
- Week and Today could diverge: Today could be reconciled while Week was not.

After PR228:
- **One canonical path** for both Week and Today:
  ```
  Garmin actual → TrainingHistory → TrainingLoad → RunnerProfile
    → TrainingState → PlanGoal → Periodization → WeeklyTarget
    → RecentTrainingResponse → WeeklyReconciliation
    → WorkoutGenerator → reconciled WeeklyPlan
  ```
- Week exposes the reconciled plan.
- Today derives its session from that **same** reconciled plan.
- DailyAdaptation is applied **only** for Today, after the canonical plan is built.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/training_v2/week_plan_bridge.py` | Added `WeeklyReconciliation` to canonical pipeline; added `CanonicalWeeklyPlan` dataclass and `build_canonical_weekly_plan()` function. |
| `backend/training_v2/training_week_response.py` | Added `reconciliation_action` and `reconciliation_reason_codes` fields to `TrainingWeekV2Response`. |
| `backend/server.py` `/training/today` | Replaced `generate_dynamic_training_plan` with `build_canonical_weekly_plan`; loads Garmin 90-day activities before plan building (same scope as `/training/v2/week`). |
| `backend/server.py` `/training/v2/week` | Switched from `build_weekly_plan_from_workouts` to `build_canonical_weekly_plan`; adds `reconciliation_action` + `reconciliation_reason_codes` to response. |
| `backend/tests/test_weekly_unification_pr228.py` | **New** — 45 tests covering all required invariants. |
| `backend/tests/test_pr167_training_v2_week_api.py` | Updated architecture test: `build_canonical_weekly_plan` replaces `build_weekly_plan_from_workouts` check. |

---

## Canonical Pipeline

```
_build_weekly_context_from_workouts()
  ├── build_training_history()
  ├── build_training_load()
  ├── build_runner_profile()
  ├── build_training_state()
  ├── build_plan_goal()
  ├── build_periodization()
  ├── build_weekly_target()           ← original target
  ├── build_recent_training_response()
  └── build_weekly_reconciliation()   ← PR228: now in canonical pipeline
        └── reconciled_target

build_canonical_weekly_plan()
  ├── _build_weekly_context_from_workouts()
  └── build_weekly_plan(reconciled_target)   ← single WorkoutGenerator call
```

---

## Design Rules

- **Preserve/reduce only**: `WeeklyReconciliation` can KEEP or reduce. Never increases.
- **None stays None**: No Garmin activities or unavailable response → KEEP action.
- **No double WorkoutGenerator**: `build_canonical_weekly_plan` calls `build_weekly_plan` exactly once.
- **No double WeeklyReconciliation**: Called once in `_build_weekly_context_from_workouts`.
- **DailyAdaptation is Today-only**: Never touches the canonical plan or Week target.
- **target_time propagated**: `target_time_seconds` flows through PlanGoal into the reconciled plan.
- **MAINTENANCE/ULTRA unchanged**: Both goal types continue to work; MAINTENANCE uses `race_date=None`.

---

## Tests — Results

**File:** `backend/tests/test_weekly_unification_pr228.py`

### Test Suite Results

| # | Test | Result |
|---|------|--------|
| 1 | `TestSharedSessionSource::test_canonical_plan_sessions_are_identical_for_week_and_today` | ✅ PASS |
| 2 | `TestSharedSessionSource::test_reconciliation_is_identical_for_week_and_today` | ✅ PASS |
| 3 | `TestSharedSessionSource::test_build_weekly_plan_from_workouts_uses_reconciliation` | ✅ PASS |
| 4 | `TestReconciliationReduce::test_reduce_volume_propagates_to_week_and_today` | ✅ PASS |
| 5 | `TestReconciliationReduce::test_reconciliation_reduce_is_consistent_across_calls` | ✅ PASS |
| 6 | `TestReconciliationKeep::test_keep_does_not_modify_target` | ✅ PASS |
| 7 | `TestReconciliationKeep::test_no_history_results_in_keep` | ✅ PASS |
| 8 | `TestReconciliationKeep::test_none_recent_response_results_in_keep` | ✅ PASS |
| 9 | `TestDailyAdaptationTodayOnly::test_daily_adaptation_does_not_modify_canonical_plan` | ✅ PASS |
| 10 | `TestDailyAdaptationTodayOnly::test_daily_adaptation_can_reduce_today` | ✅ PASS |
| 11 | `TestDailyAdaptationTodayOnly::test_daily_adaptation_reduces_today_not_week_target` | ✅ PASS |
| 12–16 | `TestDailyAdaptationNeverIncreases::test_daily_adaptation_never_increases_distance[*]` | ✅ PASS ×5 |
| 17 | `TestDailyAdaptationNeverIncreases::test_daily_adaptation_never_increases_rest` | ✅ PASS |
| 18 | `TestProtectionsConserved::test_no_history_produces_reprise_state` | ✅ PASS |
| 19 | `TestProtectionsConserved::test_reprise_reconciliation_is_keep` | ✅ PASS |
| 20 | `TestProtectionsConserved::test_reconciliation_never_increases_target` | ✅ PASS |
| 21 | `TestProtectionsConserved::test_reconciliation_never_increases_duration_target` | ✅ PASS |
| 22 | `TestNoDoubleCall::test_build_canonical_calls_reconciliation_exactly_once` | ✅ PASS |
| 23 | `TestNoDoubleCall::test_build_canonical_calls_workout_generator_once` | ✅ PASS |
| 24 | `TestNoDoubleCall::test_build_weekly_plan_from_workouts_calls_workout_generator_once` | ✅ PASS |
| 25 | `TestNoDoubleCall::test_reconciliation_not_in_build_weekly_plan_from_workouts_directly` | ✅ PASS |
| 26 | `TestTargetTimePropagated::test_target_time_survives_reconciliation` | ✅ PASS |
| 27 | `TestTargetTimePropagated::test_target_time_none_stays_none_through_reconciliation` | ✅ PASS |
| 28 | `TestMaintenanceUltraUnchanged::test_maintenance_goal_builds_without_error` | ✅ PASS |
| 29 | `TestMaintenanceUltraUnchanged::test_maintenance_reconciliation_is_keep_or_reduce` | ✅ PASS |
| 30 | `TestMaintenanceUltraUnchanged::test_ultra_goal_builds_without_error` | ✅ PASS |
| 31 | `TestMaintenanceUltraUnchanged::test_maintenance_sessions_never_have_quality` | ✅ PASS |
| 32–36 | `TestReconciliationResultAlwaysPresent::test_reconciliation_result_is_always_present[*]` | ✅ PASS ×5 |
| 37 | `TestNoneStaysNone::test_no_activities_no_crash` | ✅ PASS |
| 38 | `TestNoneStaysNone::test_reconciliation_with_none_response_is_keep` | ✅ PASS |
| 39 | `TestNoneStaysNone::test_daily_adaptation_with_none_readiness_keeps` | ✅ PASS |
| 40 | `TestArchitecture::test_today_uses_canonical_plan` | ✅ PASS |
| 41 | `TestArchitecture::test_today_does_not_use_generate_dynamic_training_plan` | ✅ PASS |
| 42 | `TestArchitecture::test_today_uses_daily_adaptation` | ✅ PASS |
| 43 | `TestArchitecture::test_today_does_not_call_build_weekly_plan_directly` | ✅ PASS |
| 44 | `TestArchitecture::test_v2_week_uses_canonical_plan` | ✅ PASS |
| 45 | `TestArchitecture::test_no_reconciliation_in_today_endpoint_body` | ✅ PASS |

**Total: 45 passed, 0 failed**

### Pre-existing test suites (non-regression)

| Suite | Result |
|-------|--------|
| `test_weekly_reconciliation_pr134.py` | ✅ All pass |
| `test_pr167_training_v2_week_api.py` | ✅ All pass (architecture test updated for `build_canonical_weekly_plan`) |
| `test_pr204_maintenance_backend.py` | ✅ Domain tests pass (server import tests require fastapi, unrelated to PR228) |

---

## Consumer Audit

| Consumer | Status |
|----------|--------|
| `/training/v2/week` | ✅ Now uses canonical reconciled pipeline; response adds `reconciliation_action`, `reconciliation_reason_codes` |
| `/training/today` (Dashboard Today) | ✅ Now uses `build_canonical_weekly_plan` — same plan as Week; DailyAdaptation applied on top |
| `/training/week-plan` | ✅ Uses `build_weekly_plan_from_workouts` which internally uses reconciled target (PR228 transparent) |
| Sessions/Training | ✅ No direct recipe changes; all V2 consumers get reconciled output |
| Bridges V2 | ✅ `week_plan_bridge.py` is the single canonical builder; `CanonicalWeeklyPlan` dataclass exposes full audit |
| Caches | ✅ No caching layer on V2 prescription path; reconciliation is pure/deterministic |

---

## Asymmetric Invariants Enforced

1. `reconciled_target.target_km ≤ original_target.target_km` (or None)
2. `reconciled_target.target_sessions ≤ original_target.target_sessions`
3. `reconciled_target.target_duration_minutes ≤ original_target.target_duration_minutes` (or None)
4. `adaptation_result.adapted_workout.distance_km ≤ planned_prescription.distance_km` (or None)
5. `adaptation_result.adapted_workout.duration_minutes ≤ planned_prescription.duration_minutes` (or None)

---

## Runtime Gate

DEFERRED TO FINAL RUNTIME GATE — no live Garmin data available in CI.
All pure-layer tests pass. Server integration tests require a running MongoDB instance.
