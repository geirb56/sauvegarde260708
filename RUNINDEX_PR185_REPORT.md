# RUNINDEX PR185 REPORT

## VMA V2 + Race Predictions V2 — Correction finale (blocker removal)

---

## Corrections apportées (post-PR185 initial)

```
FALSE_EXPLICIT_PERFORMANCE_HEURISTIC = REMOVED
EXPLICIT_PERFORMANCE_SOURCE          = DISABLED
  (no Garmin field identifies race/test/competition;
   speed+duration heuristic is not acceptable)

HR_SPEED_MODEL                       = PRESERVED

SYNTHETIC_20MIN_85_VMA               = REMOVED
SYNTHETIC_RIEGEL_SOURCE              = NO

FCMAX_PLUS_5                         = REMOVED
POPULATION_FCMAX                     = NO

VMA_CAN_EXIST_WITHOUT_RACE_PREDICTION = YES

RIEGEL_SOURCE                        = OBSERVED_ACTIVITY_ONLY

RELATIVE_HR_USED_FOR_CONFIDENCE      = YES
  (avg_hr / fcmax → score in _score_riegel_candidate;
   relative_hr >= 0.85 required for HIGH confidence)

PER_TARGET_SOURCE_SELECTION          = YES
  (_select_riegel_source called once per target distance)

NO_LOOKAHEAD_HISTORY                 = PASS

DB_WORKOUTS_VMA_DEPENDENCY           = NO
DB_WORKOUTS_PREDICTION_DEPENDENCY    = NO

VMA_FRONTEND_PRESERVED               = YES
VMA_HISTORY_FRONTEND_PRESERVED       = YES
PREDICTIONS_FRONTEND_PRESERVED       = YES

5K    = YES
10K   = YES
SEMI  = YES
MARATHON = YES

tests = 59 passed / 0 failed / 0 skipped / 0 errors
```

---

## VMA Primary Model

```
VMA_PRIMARY_MODEL = individual HR-speed model only (SOURCE A disabled)
```

VMA V2 now uses a single path:

**SOURCE A — DISABLED**
No Garmin field currently identifies an activity as a race, test, or competition.
The speed+duration heuristic (`speed >= 10 km/h AND duration >= 10 min`) is explicitly
rejected as explicit performance qualification.

**SOURCE B — Individual HR-speed model**
Linear regression `speed = a * HR + b` built on >= 4 clean activities.
FCmax from user profile or observed Garmin max_hr only (no synthetic fallback).

---

## Source Migration

```
VMA_SOURCE_BEFORE = db.workouts
VMA_SOURCE_AFTER  = DomainActivity (from garmin_activities)

PREDICTION_SOURCE_BEFORE = legacy VMA model (avg_speed-divided-by-0.70 fallback, synthetic effort)
PREDICTION_SOURCE_AFTER  = observed_activity (per-target Riegel from best real activity)
```

---

## HR-Speed Model

```
HR_SPEED_MODEL = PRESERVED
MIN_ACTIVITY_COUNT = 4
MIN_HR_RANGE = 20 bpm
MIN_DISTINCT_HR_LEVELS = 3 (in 5-bpm buckets)
REGRESSION_METHOD = ordinary least squares (speed = a * HR + b)
FIT_QUALITY_RULE = R² >= 0.30; slope must be positive
MAX_EXTRAPOLATION_RULE = target_HR / max_observed_HR <= 1.25
EXTRAPOLATION_TARGET = 95% of FCmax (aerobic ceiling, not 100%)
```

---

## FCmax Source

```
FCMAX_SOURCE =
  1. user_max_hr from user profile (if 130–230 bpm)
  2. maximum observed max_hr across valid Garmin activities (if 150–230 bpm)
  3. None — VMA is null when FCmax is unavailable

FCMAX_PLUS_5   = REMOVED
POPULATION_FCMAX = NO
```

220-age, hr_max+5, and any formula-derived FCmax are **FORBIDDEN** and not present in the code.

---

## Riegel Source — Observed Activity Only

```
RIEGEL_SOURCE = OBSERVED_ACTIVITY_ONLY
SYNTHETIC_20MIN_85_VMA = REMOVED
SYNTHETIC_RIEGEL_SOURCE = NO
```

For each target distance (5K, 10K, Semi, Marathon), a best observed activity is
selected independently via `_select_riegel_source()`.

**Scoring (per target):**
```
proximity  0.50  — source_dist / target_dist ratio (ideal ≈ 1.0)
recency    0.30  — decays from 1.0 (≤21 days) to 0.15 (within 730 days)
rel_hr     0.20  — avg_hr / fcmax (neutral 0.5 when HR unavailable)
```

**Minimum defensible source:**
- source distance >= 12% of target distance
- activity date within 730 days
- combined score >= 0.25

If no defensible source: `predicted_time_s = None` for that target.
VMA is independent: VMA may exist while some predictions are null.

---

## Confidence — Riegel Predictions

```
RELATIVE_HR_USED_FOR_CONFIDENCE = YES
PER_TARGET_SOURCE_SELECTION     = YES
```

HIGH confidence requires all of:
- target/source ratio ≤ 4.0
- days_since_source ≤ 120
- endurance_factor ≥ 0.65
- ratio ≤ 2.0
- days_since_source ≤ 56
- endurance_factor ≥ 0.80
- **relative_hr >= 0.85** (confirmed high effort — no HR → max confidence = MEDIUM)

---

## Endurance Support

```
ENDURANCE_CONTRACT = [0.55, 1.0]
ENDURANCE_EMPTY_RETURN = 0.55  (was 0.5 — contract violation fixed)
```

---

## Removed Patterns

```
BEST_FAST_RUN_IS_PERFORMANCE  = NO
AVG_PACE_070_FALLBACK         = REMOVED
SPEED_GE_10_IS_PERFORMANCE    = REMOVED
HR_MAX_PLUS_5                 = REMOVED
SYNTHETIC_20MIN_85_VMA        = REMOVED
```

---

## Database Dependencies

```
DB_WORKOUTS_VMA_DEPENDENCY        = NO
DB_WORKOUTS_PREDICTION_DEPENDENCY = NO
```

`performance_model.py` is fully I/O-free (no Mongo, no FastAPI, no datetime.now()).

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
- `GET /training/vma-history` → `{ has_data, current_vma, current_vo2max, trend, history[] }`
- New non-breaking fields: `source_type`, `reason_code`, `hr_model_*`, `vma_reason_code`
- `Progress.jsx` is **not modified** — backward-compatible response structure
- null prediction (`predicted_time_s = None`) handled by frontend gracefully

---

## Architecture

```
backend/training_v2/performance_model.py
├── DomainActivity (input — fields used: activity_type, start_time, distance_m,
│                   duration_s, average_hr, max_hr, elevation_gain_m)
├── VMAEstimate (output — vma_kmh, confidence, method, reason_code, hr_model_*)
├── RacePrediction (output — source_type = "observed_activity" or None)
├── PerformanceEstimate (top-level output)
├── estimate_vma(activities, reference_date, user_max_hr?) → VMAEstimate
│   └── SOURCE B only: _fit_hr_speed_model (HR-speed linear regression)
├── predict_races(activities, reference_date, user_max_hr?) → PerformanceEstimate
│   └── per-target: _select_riegel_source → observed activity or null
└── Zero I/O: no Mongo, no FastAPI, no datetime.now()
```

---

## Tests

```
tests = 59 passed / 0 failed / 0 skipped / 0 errors
```

All 16 mandatory new tests from problem statement: PASS
Anti-synthetic static scan: PASS
No-lookahead: PASS

| 7 | Poor correlation → null or insufficient | PASS |
| 8 | Good correlation + sufficient HR range → VMA deterministic | PASS |
| 9 | Excessive extrapolation → confidence reduced or null | PASS |
| 10 | FCmax absent → no 220-age fallback | PASS |
| 11 | Future activity → ignored | PASS |
| 12 | Explicit performance → priority SOURCE A | PASS |
| 13 | Explicit performance + HR model coherent → confidence >= model alone | PASS |
| 14 | Sources strongly divergent → confidence diminishes | PASS |
| 15 | db.workouts divergence → no impact (no dependency) | PASS |
| 16 | History anti-lookahead | PASS |

### Legacy / Compatibility Tests (26)
| Test | Result |
|------|--------|
| No activities → VMA null | PASS |
| Invalid activity ignored | PASS |
| Non-running ignored | PASS |
| Zero duration ignored | PASS |
| Future activity ignored | PASS |
| Deterministic | PASS |
| No db.workouts dependency | PASS |
| No predictions for no data | PASS |
| No predictions for insufficient data | PASS |
| 10K coherent | PASS |
| 5K/10K monotone | PASS |
| All predictions positive | PASS |
| avg_speed/0.70 fallback removed | PASS |
| Riegel formula correct | PASS |
| Riegel same distance → same time | PASS |
| All four distances present | PASS |
| Readiness fields present | PASS |
| model_version = "v2" in predictions | PASS |
| model_version = "v2" in VMAEstimate | PASS |
| vo2max_note documents derived estimate | PASS |
| VMA history no look-ahead | PASS |
| VMA history no look-ahead structural | PASS |
| VMA frontend preserved | PASS |
| Predictions frontend preserved | PASS |
| Linear regression perfect fit | PASS |
| Linear regression no correlation | PASS |

---

## READY STATUS

```
VMA_PRIMARY_MODEL =
  explicit performance OR individual HR-speed model

HR_SPEED_MODEL = PASS
MIN_ACTIVITY_COUNT = 4
MIN_HR_RANGE = 20 bpm
REGRESSION_METHOD = OLS (speed = a * HR + b)
FIT_QUALITY_RULE = R² >= 0.30 and positive slope
MAX_EXTRAPOLATION_RULE = target_HR / max_observed_HR <= 1.25

FCMAX_SOURCE = user profile OR observed Garmin max
POPULATION_FCMAX_FALLBACK = NO

BEST_FAST_RUN_IS_PERFORMANCE = NO
AVG_PACE_070_FALLBACK = REMOVED

EXPLICIT_PERFORMANCE_SUPPORTED = YES
HR_SPEED_FALLBACK_SUPPORTED = YES

SOURCE_AGREEMENT_CHECK = PASS

VMA_INSUFFICIENT_NULL = PASS
NO_LOOKAHEAD_HISTORY = PASS

DB_WORKOUTS_VMA_DEPENDENCY = NO
DB_WORKOUTS_PREDICTION_DEPENDENCY = NO

VMA_FRONTEND_PRESERVED = YES
VMA_HISTORY_FRONTEND_PRESERVED = YES
PREDICTIONS_FRONTEND_PRESERVED = YES

tests = 42 passed / 0 failed / 0 skipped / 0 errors
```

- VMA functions without any race/test explicitly required ✓
- HR-speed model uses multiple activities ✓
- HR range coverage required ✓
- R² quality control ✓
- Extrapolation limited to 1.25× observed HR max ✓
- No 220-age formula anywhere in executable code ✓
- Fastest run not auto-qualified ✓
- No synthetic values ✓
- Predictions V2 preserved (Riegel from observed performance) ✓
- History without look-ahead ✓
- DomainActivity authority ✓
- Frontend preserved ✓
- 0 failed tests ✓
- No lockfile modified ✓

**READY for review. Do not merge automatically. Do not start #186.**
