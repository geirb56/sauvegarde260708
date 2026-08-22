# RUNINDEX_PR184_REPORT

## Migration V2 — Progress Sources

---

## Authorities

```
RUNINDEX_HISTORY_AUTHORITY = GET /run-index/history (engine PR#181 — unchanged)

STATS_BEFORE   = db.workouts (synthetic fallback if empty)
STATS_AFTER    = garmin_activities → DomainActivity (running only, rolling windows)
               Helpers: calculate_week_stats_from_domain + calculate_month_stats_from_domain
               (same helpers as /dashboard/insight introduced in #182 — no third impl)

CYCLE_BEFORE   = GET /training/full-cycle
CYCLE_AFTER    = GET /training/v2/cycle
               Only field consumed: goal.goal_type → mapped to pred.distance for highlight
               V2 contract is sufficient — no session prescription needed by Progress
```

---

## Frontend Dependencies

```
PROGRESS_VISIBLE_DB_WORKOUTS_DEPENDENCY = NONE
  /stats endpoint now reads from garmin_activities → DomainActivity exclusively.
  db.workouts no longer used as visible authority in Progress.
```

---

## VMA

```
VMA_FRONTEND_PRESERVED         = YES
VMA_HISTORY_FRONTEND_PRESERVED = YES
VMA_CURRENT_BACKEND_AUTHORITY  = GET /training/vma-history (legacy, unchanged)
VMA_BACKEND_V2                 = PENDING_PR185
```

---

## Race Predictions

```
PREDICTIONS_FRONTEND_PRESERVED       = YES
PREDICTIONS_CURRENT_BACKEND_AUTHORITY = GET /training/race-predictions (legacy, unchanged)
PREDICTIONS_BACKEND_V2               = PENDING_PR185
```

---

## Semantic Checks

```
RUNINDEX_NULL_SEMANTICS  = PASS
  - connectNulls={false} on RunIndex Line chart
  - null values kept in chart data array (not pre-filtered)
  - gap periods render as broken line, never as 0

PILLAR_NULL_SEMANTICS    = PASS
  - data.current === null → renders "—" (em-dash), not 0%

RUNINDEX_GAP_SEMANTICS   = PASS
  - connectNulls={false} ensures no false visual continuity across null periods

GARMIN_HEALTH_NULL_SEMANTICS = PASS
  - garminHealth section only rendered when count > 0
  - null HRV/RHR/sleep → "?? '--'" (never a fabricated value)
  - Section absent when Garmin not connected
```

---

## i18n

```
I18N_EN = PASS
I18N_FR = PASS
I18N_ES = PASS
RAW_I18N_KEY_VISIBLE = NO

New keys added to all three locales:
  progressExtended.garminHealthTitle  — "Garmin Health · 7 days / jours / días"
  progressExtended.garminRestingHr    — "Resting HR / FC repos / FC reposo"
  progressExtended.garminSleep        — "Sleep / Sommeil / Sueño"
  progressExtended.goalLabel          — "GOAL / OBJECTIF / OBJETIVO"
  progressExtended.readinessPct       — "ready / prêt / listo"
```

---

## Invariants (no change to engines)

```
RUNINDEX_CHANGED         = NO
VMA_FORMULA_CHANGED      = NO
PREDICTION_FORMULA_CHANGED = NO
READINESS_CHANGED        = NO
TRAINING_ENGINE_CHANGED  = NO
COACH_CHANGED            = NO
LOCKFILES_CHANGED        = NO
```

---

## Test Results

```
Backend tests (tests/test_progress_stats_v2_pr184.py):
  20 passed / 0 failed / 0 skipped

  TestDomainActivityWindowSemantics (3 tests)
    - test_week_sessions_rolling_7_days         PASSED
    - test_week_km_rolling_7_days               PASSED
    - test_non_running_excluded                 PASSED

  TestZeroActivity (4 tests)
    - test_empty_sessions_7d                    PASSED
    - test_empty_km_7d                          PASSED
    - test_empty_km_30d                         PASSED
    - test_empty_sessions_30d                   PASSED

  TestDomainActivityDivergence (2 tests)
    - test_domain_wins_over_workouts            PASSED
    - test_domain_zero_when_workouts_nonzero    PASSED

  TestStatsEndpointStaticAnalysis (5 tests)
    - test_stats_uses_load_garmin_domain_activities        PASSED
    - test_stats_uses_calculate_week_stats_from_domain     PASSED
    - test_stats_uses_calculate_month_stats_from_domain    PASSED
    - test_stats_no_synthetic_fallback                     PASSED
    - test_stats_response_contract_preserved               PASSED

  TestProgressFrontendStaticAnalysis (6 tests)
    - test_connectNulls_is_false                PASSED
    - test_no_filter_removes_null_run_index     PASSED
    - test_vma_history_endpoint_preserved       PASSED
    - test_race_predictions_endpoint_preserved  PASSED
    - test_cycle_v2_used_not_full_cycle         PASSED
    - test_no_raw_i18n_keys_in_progress         PASSED

Frontend tests (src/__tests__/progress-v2-migration.test.jsx):
  Static analysis tests — see CI for DOM rendering tests
  (node_modules not available in sandbox; existing tests have same constraint)
```

---

## Smoke Endpoints (post-pull)

```
GET /api/run-index/history?period=6m       → 200  (PR#181 authority, unchanged)
GET /api/stats                             → 200  (DomainActivity source)
GET /api/training/vma-history              → 200  (VMA_FRONTEND_PRESERVED)
GET /api/training/race-predictions         → 200  (PREDICTIONS_FRONTEND_PRESERVED)
GET /api/garmin/daily-metrics?days=7       → 200  (Garmin health source, unchanged)
GET /api/training/v2/cycle                 → 200  (migrated from full-cycle)
```

---

## READY Checklist

```
[x] Progress stats = DomainActivity
[x] RunIndex history = #181
[x] null ≠ 0 (connectNulls={false}, no pre-filter)
[x] No frontend loss — VMA, predictions, health, cycle, pillars all present
[x] VMA frontend preserved (VMA_FRONTEND_PRESERVED = YES)
[x] VMA history frontend preserved (VMA_HISTORY_FRONTEND_PRESERVED = YES)
[x] Predictions frontend preserved (PREDICTIONS_FRONTEND_PRESERVED = YES)
[x] Cycle migrated to V2 when contract sufficient
[x] i18n correct (EN/FR/ES, no raw keys)
[x] Backend tests 20/20 passed
[x] No lockfile changes
```

**Do NOT merge automatically. Do NOT begin #185.**

VMA and Predictions use their current backend temporarily — this debt is
explicitly transferred to PR#185.
