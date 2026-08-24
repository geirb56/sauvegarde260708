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

## FCmax Policy (VMA — updated BLOCKER 1 fix)

```
FCMAX_RUNTIME_SOURCE            = ROBUST_OBSERVED_GARMIN_MAX_HR
FCMAX_OUTLIER_PROTECTION        = YES (n >= 3)
USER_MAX_HR_RUNTIME_WIRED       = NOT_AVAILABLE
220_AGE_FORMULA                 = FORBIDDEN
HR_MAX_PLUS_5                   = FORBIDDEN
POPULATION_FALLBACK             = FORBIDDEN
VMA_FCMAX_WINDOW_DAYS           = 42
  FCmax for VMA resolved from the same 42-day window as the model activities.
  This ensures CURRENT == HISTORY snapshots (strict equality).
  (Race Predictions FCmax remains independent — resolved from all valid activities.)
```

## VMA / Predictions Independence

```
RIEGEL_VMA_CONFIDENCE_DEPENDENCY = NO
  Prediction confidence determined solely by: source proximity, recency,
  relative HR, and endurance support. VMA confidence never affects predictions.
```

## FCmax Window (BLOCKER 1 — PR187 Audit Fix)

```
VMA_FCMAX_WINDOW_DAYS           = 42
  estimate_vma() now resolves FCmax from the same 42-day windowed activities
  used by the HR-speed model, not from ALL non-future activities.
OLD_FCMAX_OUTSIDE_WINDOW_AFFECTS_VMA = NO
  An activity at J-100 with max_hr=205 does not change VMA when recent
  activities in the window have max_hr=185–187.
CURRENT_HISTORY_STRICT_EQUALITY_TESTED = YES
  test_30 asserts: estimate_vma(all, ref) == estimate_vma(windowed, ref)
  for both vma_kmh and reason_code.
```

## Riegel VMA Independence (BLOCKER 2 — PR187 Audit Fix)

```
RIEGEL_VMA_CONFIDENCE_DEPENDENCY = NO
  test_24 (rewritten): asserts SAME_SOURCE + SAME_TIME + SAME_CONFIDENCE.

  Design:
  - source: 10K run at days_ago=5, avg_hr=160, max_hr=190 (rel_hr=0.84 ≥ 0.80)
  - vma_extras: four 5K runs at days_ago=35–38, avg_hr=140 (rel_hr=0.74 < 0.80)
    → hard-excluded from Riegel; outside 28-day weekly_km window; endurance=1.0 for 10K
  → Riegel source for 10K is strictly the same in both cases.

  Asserts:
    pred_no_vma.source_distance_m  == pred_with_vma.source_distance_m
    pred_no_vma.predicted_time_s   == pred_with_vma.predicted_time_s
    pred_no_vma.confidence         == pred_with_vma.confidence

RIEGEL_VMA_SAME_SOURCE_TEST     = PASS
RIEGEL_VMA_SAME_TIME_TEST       = PASS
RIEGEL_VMA_SAME_CONFIDENCE_TEST = PASS
```

## total_sessions_6w Validation (BLOCKER 3 — PR187 Audit Fix)

```
TOTAL_SESSIONS_6W_REQUIRES_VALID_ACTIVITY = YES
  server.py now uses validate_activity(a, reference_date) as the authority,
  reusing the same business logic as the Performance Model.
  No manual duplication of validation logic.

  Counts:
  - running (checked by validate_activity → _is_running)
  - date [J-41, J] (reference_date check inside validate_activity + window filter)
  - not future (validate_activity: d > reference_date → False)
  - distance valid (>= MIN_DISTANCE_M = 500 m, not None/0)
  - duration valid (_performance_duration_s > 0)
  - speed in [3, 30] km/h
  - NO avg_hr required
  - NO FCmax required
  - NO Riegel threshold

  New tests (tests 31–34):
  - test_31: distance_m=None → NOT counted
  - test_32: distance_m=0    → NOT counted
  - test_33: duration_s=None AND moving_duration_s=None → NOT counted
  - test_34: valid run, no HR → COUNTED
```


## Frontend

```
FRONTEND_MODIFIED               = NO
  GET /training/race-predictions  → contract preserved
  GET /training/vma-history       → contract preserved
```

## Test Results

```
tests = 141 passed / 0 skipped / 0 failed / 0 errors

  test_performance_model_pr186.py : 34 passed  (29 original + 5 new PR187 audit fixes)
  test_performance_model_pr185.py : 107 passed (regression)
  test_training_v2_domain_activity.py : included in run
```

## Summary Checklist

```
MOVING_DURATION_PROPAGATED      = YES
VMA_WINDOW_DAYS                 = 42
VMA_FCMAX_WINDOW_DAYS           = 42
OLD_FCMAX_OUTSIDE_WINDOW_AFFECTS_VMA = NO
CURRENT_HISTORY_STRICT_EQUALITY_TESTED = YES
RIEGEL_VMA_INDEPENDENCE_TEST    = SAME_SOURCE + SAME_TIME + SAME_CONFIDENCE
  RIEGEL_VMA_SAME_SOURCE_TEST   = PASS
  RIEGEL_VMA_SAME_TIME_TEST     = PASS
  RIEGEL_VMA_SAME_CONFIDENCE_TEST = PASS
TOTAL_SESSIONS_6W_REQUIRES_VALID_ACTIVITY = YES
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
