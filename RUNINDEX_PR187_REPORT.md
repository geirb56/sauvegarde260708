# RUNINDEX PR187 REPORT — PERFORMANCE MODEL V2 DATA QUALITY

## Git Metadata

```
BASE_BRANCH = copilot/dev
BASE_SHA    = c965ac58d905ae9104be57cdc7e3dfca3944d2c4
FINAL_SHA   = (set after push)
```

## Changed Files

```
CHANGED_FILES =
  backend/training_v2/domain_activity.py
  backend/garmin/domain_adapter.py
  backend/training_v2/performance_model.py
  backend/server.py
  backend/tests/test_performance_model_pr186.py
  backend/tests/test_performance_model_pr185.py  (test_c1 updated for new Riegel FCmax rule)
  RUNINDEX_PR187_REPORT.md
```

## Moving Duration

```
MOVING_DURATION_RAW_SOURCE      = summaryDTO.movingDuration
MOVING_DURATION_PERSISTED       = YES
  (GarminActivity.moving_duration_s → garmin_activity sub-document via model_dump())
DOMAIN_MOVING_DURATION          = YES
  (DomainActivity.moving_duration_s: Optional[float] = None)
MOVING_DURATION_PROPAGATED      = YES
  Paths:
    - training_v2/domain_activity.py : to_domain_activity() (generic)
    - garmin/domain_adapter.py       : to_domain_activity(GarminActivity)
    - garmin/domain_adapter.py       : mongo_garmin_to_domain(doc)
PERFORMANCE_DURATION_PRIORITY   = moving_duration_s > duration_s fallback
  Logic (_performance_duration_s):
    1. moving_duration_s if > 0 AND (duration_s absent OR moving_duration_s <= duration_s)
    2. duration_s if > 0
    3. None
  Scope: _speed_kmh(), _validate_activity(), _is_usable_for_hr_model(),
         Riegel source_duration_s in predict_races()
```

## VMA Window

```
VMA_WINDOW_DAYS                 = 42
  Constant: VMA_WINDOW_DAYS = 42 in performance_model.py
  Helper:   _activities_in_vma_window(activities, reference_date, window_days=42)
  Window:   [reference_date - 41 days, reference_date] (inclusive both ends)
CURRENT_HISTORY_SAME_WINDOW     = YES
  estimate_vma() applies the 42-day window internally.
  Server VMA history passes pre-filtered activities → idempotent, same result.
```

## Terrain Filter (VMA Model)

```
VMA_TRAIL_ALLOWED               = NO
  trail_running type hard-excluded from _is_usable_for_hr_model()
VMA_MAX_ELEVATION_GAIN_PER_KM   = 30
  Rule: elevation_gain_m / (distance_m / 1000) > 30 → excluded
  Applied in: _is_usable_for_hr_model() and _score_riegel_candidate()
  Removed: MAX_ELEVATION_GAIN_M = 400 (absolute threshold, no longer used)
  Absent D+: not rejected (only filtered when data present)
```

## Riegel Qualification

```
MIN_RIEGEL_RELATIVE_HR          = 0.80  (raised from 0.75)
RIEGEL_WITHOUT_AVG_HR_ALLOWED   = NO    (avg_hr None → score 0.0)
RIEGEL_WITHOUT_FCMAX_ALLOWED    = NO    (fcmax None/0 → score 0.0)
TRAIL_RIEGEL_ALLOWED            = NO
HIGH_ELEVATION_RIEGEL_ALLOWED   = NO    (same 30 m/km threshold as VMA)
SYNTHETIC_PREDICTIONS           = NO
```

## FCmax Policy (unchanged from PR185)

```
FCMAX_RUNTIME_SOURCE            = ROBUST_OBSERVED_GARMIN_MAX_HR
FCMAX_OUTLIER_PROTECTION        = YES (n >= 3)
USER_MAX_HR_RUNTIME_WIRED       = NOT_AVAILABLE
220_AGE_FORMULA                 = FORBIDDEN
HR_MAX_PLUS_5                   = FORBIDDEN
POPULATION_FALLBACK             = FORBIDDEN
FCmax resolves from ALL non-future activities (not restricted to 42-day window).
```

## VMA / Predictions Independence

```
RIEGEL_VMA_CONFIDENCE_DEPENDENCY = NO
  Prediction confidence determined solely by: source proximity, recency,
  relative HR, and endurance support. VMA confidence never affects predictions.
```

## total_sessions_6w Fix

```
TOTAL_SESSIONS_6W_WINDOW_DAYS   = 42
  Fix: server.py now filters to [reference_date - 41, reference_date]
  Only running activities (RUNNING_TYPES) counted.
  No future, no non-running, no all-time history.
```

## Frontend

```
FRONTEND_MODIFIED               = NO
  GET /training/race-predictions  → contract preserved
  GET /training/vma-history       → contract preserved
```

## Test Results

```
tests = 170 passed / 0 skipped / 0 failed / 0 errors

  test_performance_model_pr186.py : 29 passed  (new PR187 tests)
  test_performance_model_pr185.py : 112 passed (regression — 1 test updated for FCmax rule)
  test_training_v2_domain_activity.py : included in run
  test_mongo_garmin_boundary_pr137.py : included in run
```

## Summary Checklist

```
MOVING_DURATION_PROPAGATED      = YES
VMA_WINDOW_DAYS                 = 42
RIEGEL_MIN_RELATIVE_HR          = 0.80
RIEGEL_WITHOUT_HR_ALLOWED       = NO
TOTAL_SESSIONS_6W_FIXED         = YES
FRONTEND_MODIFIED               = NO
OUT_OF_SCOPE_FILES              = NO
LOCKFILES_MODIFIED              = NO
PR_BASE                         = copilot/dev
MERGEABLE                       = YES
READY                           = YES
```
