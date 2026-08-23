# RUNINDEX PR185 REPORT

## VMA V2 + Race Predictions V2 — Patch final consolidé

---

## Architecture finale

```
VMA_PRIMARY_MODEL = INDIVIDUAL_HR_SPEED_REGRESSION

SOURCE_A_EXPLICIT_PERFORMANCE = REMOVED
  (all _is_explicit_performance, _select_explicit_performance,
   _vma_from_explicit_performance, _explicit_confidence, _merge_confidence
   code deleted; 78/85/90/95% duration-based fractions deleted)

AVG_PACE_070_FALLBACK = REMOVED
SYNTHETIC_RIEGEL_SOURCE = NO
FCMAX_PLUS_5 = NO
POPULATION_FCMAX_FALLBACK = NO
220_AGE_FORMULA = NO

HR_SPEED_MODEL = ACTIVE
MIN_ACTIVITY_COUNT = 4
MIN_HR_RANGE = 20 bpm
MIN_DISTINCT_HR_LEVELS = 3
REGRESSION_METHOD = OLS (speed = a * HR + b)
FIT_QUALITY_RULE = R² >= 0.30 and positive slope
MAX_EXTRAPOLATION_RULE = target_HR / max_observed_HR <= 1.25
EXTRAPOLATION_TARGET = 95% of FCmax (aerobic ceiling)
```

---

## FCmax Runtime

```
FCMAX_RUNTIME_SOURCE = ROBUST_OBSERVED_GARMIN_MAX_HR
FCMAX_OUTLIER_PROTECTION = YES
  Rule: if max(observed) > second_highest * 1.10 → discard max, use second_highest
  n = 0         → None
  n = 1 or 2   → raw max (no outlier protection, documented)
  n >= 3        → outlier protection active
  Examples:
    [178, 180, 182, 181, 218] → 218 > 182*1.10 → FCmax = 182
    [178, 182, 185, 188, 190] → 190 ≤ 188*1.10 → FCmax = 190

FCMAX_NO_LOOKAHEAD = PASS
  FCmax at snapshot J = max of observed max_hr in activities <= J only.
  A future activity with higher max_hr cannot raise FCmax retroactively.

USER_MAX_HR_EXISTS = NO
USER_MAX_HR_RUNTIME_WIRED = NOT_AVAILABLE
  No Mongo collection stores a user-declared max_hr.
  No new field, form, migration, or age-based fallback added.
```

---

## Riegel Source Qualification

```
RIEGEL_SOURCE = QUALIFIED_OBSERVED_ACTIVITY_ONLY

TRAIL_CAN_BE_ROAD_RIEGEL_SOURCE = NO
  trail_running type: excluded from all road prediction sources.

ELEVATION_FILTER = RELATIVE_PER_KM
  elevation_gain_per_km > MAX_ROAD_ELEVATION_GAIN_PER_KM (30 m/km) → excluded.

MIN_RIEGEL_RELATIVE_HR = 0.75
EASY_RUN_CAN_BE_RIEGEL_SOURCE = NO_WHEN_HR_AVAILABLE
  When both FCmax and average_hr are available:
    if average_hr / fcmax < 0.75 → activity not eligible (easy run, not informative).
  When HR data is unavailable: prediction still possible, confidence capped at MEDIUM.

NOTE: relative_hr >= 0.75 ≠ "maximum performance".
  It means "sufficiently intense to be informative".
  No chrono correction based on HR is applied. FORBIDDEN.
```

---

## VMA / Predictions Independence

```
RIEGEL_VMA_CONFIDENCE_DEPENDENCY = NO
  Prediction confidence is determined solely by:
    - Riegel source proximity
    - Recency
    - Relative HR (effort level)
    - Endurance support factor
  VMA confidence and VMA value are never used to modify prediction confidence.

PREDICTIONS_WITHOUT_VMA = PASS
VMA_WITHOUT_PREDICTIONS = PASS
```

---

## VMA History

```
VMA_HISTORY_WINDOW_DAYS = 42
VMA_HISTORY_CUMULATIVE = NO

Each snapshot uses only activities in [snapshot - 41 days, snapshot].
Sessions count = activities in the 42-day window only.
No look-ahead: each snapshot is limited to activities <= snapshot_date.
```

---

## duration_s Semantics

```
GARMIN_DURATION_SOURCE = summaryDTO.duration (Garmin Connect elapsed timer)
GARMIN_DURATION_SEMANTICS = elapsed timer duration (includes pauses)
  moving_duration_s is stored in GarminActivity but not used in performance_model.py.
  No correction is applied in #185.
```

---

## Source Migration

```
VMA_SOURCE_BEFORE = db.workouts
VMA_SOURCE_AFTER  = DomainActivity (from garmin_activities)

PREDICTION_SOURCE_BEFORE = legacy VMA model (avg_speed/0.70 fallback, synthetic effort)
PREDICTION_SOURCE_AFTER  = observed_activity (per-target Riegel from qualified activity)
```

---

## Database Dependencies

```
DB_WORKOUTS_VMA_DEPENDENCY        = NO
DB_WORKOUTS_PREDICTION_DEPENDENCY = NO
```

---

## Frontend Preservation

```
VMA_FRONTEND_PRESERVED          = YES
VMA_HISTORY_FRONTEND_PRESERVED  = YES
PREDICTIONS_FRONTEND_PRESERVED  = YES
PREDICTIONS_5K                  = YES
PREDICTIONS_10K                 = YES
PREDICTIONS_HALF                = YES
PREDICTIONS_MARATHON            = YES
```

Contract maintained:
- `GET /training/race-predictions` → `{ has_data, athlete_profile, predictions[], methodology }`
- `GET /training/vma-history` → `{ has_data, current_vma, current_vo2max, trend, history[], window_days=42 }`
- `Progress.jsx` is **not modified**

---

## Tests

```
tests = 88 passed / 0 failed / 0 skipped / 0 errors
```

**New tests added (patch final)**

| Group | Test | Purpose |
|-------|------|---------|
| A1 | test_a1_easy_run_not_riegel_source | rel_hr < 0.75 → score 0 |
| A2 | test_a2_sustained_run_is_eligible | rel_hr >= 0.75 → eligible |
| A3 | test_a3_easy_run_exact_target_rejected | proximity no override for effort gate |
| A4 | test_a4_less_close_but_sustained_can_beat_easy | intensity > proximity when HR available |
| A5 | test_a5_trail_not_road_riegel_source | trail excluded |
| A6 | test_a6_high_elevation_per_km_not_road_source | 40 m/km excluded |
| A7 | test_a7_no_hr_data_prediction_still_possible | no HR → prediction possible, capped |
| A8 | test_a8_no_defensible_source_prediction_null | no source → null |
| B1 | test_b1_outlier_high_fcmax_rejected | [178,180,182,181,218] → 182 |
| B2 | test_b2_credible_high_value_kept | [178,182,185,188,190] → 190 |
| B3 | test_b3_no_observations_returns_none | n=0 → None |
| B4 | test_b4_single_observation_no_outlier_protection | n=1 → raw value |
| B5 | test_b5_two_observations_no_outlier_protection | n=2 → max |
| B6 | test_b6_future_high_hr_no_effect_on_snapshot_fcmax | FCmax no-lookahead |
| C1 | test_c1_same_riegel_source_regardless_of_vma | VMA null → predictions unchanged |
| C2 | test_c2_vma_null_good_riegel_source_high_confidence_possible | predictions independent |
| C3 | test_c3_vma_confidence_not_in_prediction_confidence | no cross-dependency |
| D1 | test_d1_old_activity_not_in_snapshot_window | 180-day-old → outside window |
| D2 | test_d2_recent_activity_in_window | 30-day-old → inside window |
| D3 | test_d3_window_is_non_cumulative | window excludes old outlier |
| D4 | test_d4_sessions_counted_in_window_only | sessions = window only |
| D5 | test_d5_future_activity_not_in_any_window | future excluded |

---

## READY STATUS

```
VMA_PRIMARY_MODEL = INDIVIDUAL_HR_SPEED_REGRESSION

SOURCE_A_EXPLICIT_PERFORMANCE = REMOVED

FCMAX_RUNTIME_SOURCE = ROBUST_OBSERVED_GARMIN_MAX_HR
FCMAX_OUTLIER_PROTECTION = YES
FCMAX_NO_LOOKAHEAD = PASS

RIEGEL_SOURCE = QUALIFIED_OBSERVED_ACTIVITY_ONLY
MIN_RIEGEL_RELATIVE_HR = 0.75
EASY_RUN_CAN_BE_RIEGEL_SOURCE = NO_WHEN_HR_AVAILABLE
TRAIL_CAN_BE_ROAD_RIEGEL_SOURCE = NO
RIEGEL_VMA_CONFIDENCE_DEPENDENCY = NO

VMA_HISTORY_WINDOW_DAYS = 42
VMA_HISTORY_CUMULATIVE = NO

PREDICTIONS_WITHOUT_VMA = PASS
VMA_WITHOUT_PREDICTIONS = PASS
SYNTHETIC_RIEGEL_SOURCE = NO

GARMIN_DURATION_SOURCE = summaryDTO.duration
GARMIN_DURATION_SEMANTICS = elapsed timer duration (includes pauses)

USER_MAX_HR_EXISTS = NO
USER_MAX_HR_RUNTIME_WIRED = NOT_AVAILABLE

AVG_PACE_070_FALLBACK = REMOVED
POPULATION_FCMAX_FALLBACK = NO
FCMAX_PLUS_5 = NO
220_AGE_FORMULA = NO

DB_WORKOUTS_VMA_DEPENDENCY = NO
DB_WORKOUTS_PREDICTION_DEPENDENCY = NO

VMA_FRONTEND_PRESERVED = YES
VMA_HISTORY_FRONTEND_PRESERVED = YES
PREDICTIONS_FRONTEND_PRESERVED = YES

tests = 88 passed / 0 failed / 0 skipped / 0 errors
```

**Do not merge automatically. Do not start #186.**
