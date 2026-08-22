# RUNINDEX PR185 REPORT

## VMA V2 + Race Predictions V2

---

## Source Migration

```
VMA_SOURCE_BEFORE = db.workouts
VMA_SOURCE_AFTER  = DomainActivity (from garmin_activities)

PREDICTION_SOURCE_BEFORE = legacy VMA model (avg_speed/0.70 fallback, fixed coefficients)
PREDICTION_SOURCE_AFTER  = observed performance V2 (Riegel extrapolation from best informative effort)
```

---

## Removed Patterns

```
AVG_PACE_070_FALLBACK        = REMOVED
FIXED_VMA_DISTANCE_PREDICTION = REMOVED
```

The old `/training/race-predictions` and `/training/vma-history` endpoints used:
- `db.workouts` (legacy collection) as data source — **replaced by `garmin_activities → DomainActivity`**
- `avg_speed / 0.70` as VMA fallback when no fast effort was found — **removed**
- Fixed VMA% coefficients per distance (5K=95%, 10K=90%, etc.) — **replaced by Riegel T2=T1×(D2/D1)^1.06**
- Absolute volume thresholds (15 km/week, 30 km/week, etc.) — **replaced by relative endurance support signals**

---

## Null Semantics

```
VMA_INSUFFICIENT_NULL       = PASS
PREDICTION_INSUFFICIENT_NULL = PASS
NO_LOOKAHEAD_HISTORY        = PASS
```

- No VMA data → `vma_kmh = null`, `has_data = false`, `predictions = []`
- Easy runs only (no informative effort ≥ 5 min) → model uses the best available effort; if none qualifies, VMA = null
- No avg_speed/0.70 synthetic fallback
- Historical snapshots use `reference_date = snapshot date`, only activities strictly before that date

---

## Confidence

```
VMA_CONFIDENCE        = PASS
PREDICTION_CONFIDENCE = PASS
ENDURANCE_SUPPORT     = PASS
```

Confidence factors:
- Recency of source performance (high ≤21 days, medium ≤56 days, low ≤120 days)
- Effort duration (longer effort = more physiologically informative)
- Extrapolation ratio (source distance vs. target distance)
- Endurance support: long run history + weekly volume relative to target distance

Endurance adjustment:
- Monotone (more support → less penalty)
- Bounded: factor ∈ [0.55, 1.0]
- Applied as `time × (1 + (1 - endurance) × 0.4)` (slowdown for under-supported distances)

---

## Database Dependencies

```
DB_WORKOUTS_VMA_DEPENDENCY        = NO
DB_WORKOUTS_PREDICTION_DEPENDENCY = NO
```

- `backend/training_v2/performance_model.py` has zero I/O, zero Mongo references
- Endpoints fetch from `db.garmin_activities` → `mongo_garmin_activities_to_domain()` → `DomainActivity`
- `db.workouts` is not referenced anywhere in the V2 path

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
  - Each prediction: `distance`, `distance_km`, `description`, `predicted_time`, `predicted_range`, `predicted_pace`, `readiness`, `readiness_label`, `readiness_color`, `readiness_score`, `volume_factor`, `endurance_factor`
  - New fields added (non-breaking): `confidence`, `model_version`
- `GET /training/vma-history` → `{ has_data, current_vma, current_vo2max, trend, trend_pct, history[] }`
  - Each history point: `period`, `period_label`, `month`, `month_label`, `half`, `vma`, `vo2max`, `sessions`
  - New fields added (non-breaking): `window_days`, `model_version`

`Progress.jsx` is **not modified** — the response structure is backward-compatible.

VO2max presented as:
> `"vo2max_note": "Derived estimate (VMA × 3.5). Not a lab or Garmin measurement."`

The `estimated_vo2max` field is still returned for the chart; the note field documents its derived nature.

---

## Unchanged Modules

```
RUNINDEX_CHANGED        = NO
READINESS_CHANGED       = NO
TRAINING_ENGINE_CHANGED = NO
COACH_CHANGED           = NO
LOCKFILES_CHANGED       = NO
```

Files modified in PR185:
- `backend/training_v2/performance_model.py` — **NEW** (pure engine)
- `backend/server.py` — endpoints `/training/race-predictions` and `/training/vma-history` only
- `backend/tests/test_performance_model_pr185.py` — **NEW** (31 unit tests)
- `RUNINDEX_PR185_REPORT.md` — this file

---

## Tests

```
tests = 31 passed / 0 failed / 0 skipped / 0 errors
```

### VMA Tests
| # | Scenario | Result |
|---|----------|--------|
| 1 | No activities → VMA null | PASS |
| 2 | Easy runs only → no /0.70 synthetic VMA | PASS |
| 3 | Invalid activity → ignored | PASS |
| 3b | Non-running activity → ignored | PASS |
| 3c | Zero duration → ignored | PASS |
| 4 | Informative effort → deterministic estimate | PASS |
| 5 | Same input/reference_date → same result | PASS |
| 6 | Future activity → ignored | PASS |
| 7 | No motor/db imports in performance_model | PASS |

### Prediction Tests
| # | Scenario | Result |
|---|----------|--------|
| 1 | No exploitable performance → no prediction invented | PASS |
| 1b | Only cycling → no prediction | PASS |
| 2 | Observed 10K → coherent 10K prediction | PASS |
| 3 | 5K ↔ 10K monotone | PASS |
| 4 | 10K → Semi deterministic | PASS |
| 5 | Short source → Marathon never more optimistic than raw Riegel | PASS |
| 6 | Better endurance support → endurance_factor ≥ base | PASS |
| 7 | No negative/impossible predictions | PASS |
| 8a | Confidence degrades with age | PASS |
| 8b | Confidence degrades with large extrapolation | PASS |

### History / Anti-Look-Ahead
| # | Scenario | Result |
|---|----------|--------|
| 1 | Snapshot J-30 cannot see activity at J | PASS |
| 2 | Snapshot J+1 can see activity at J | PASS |

### Contract / Frontend Preservation
| Check | Result |
|-------|--------|
| `avg_speed / 0.70` not produced by model | PASS |
| Riegel formula correct | PASS |
| Same distance → same time | PASS |
| All four distances present (5K, 10K, Semi, Marathon) | PASS |
| Readiness fields present | PASS |
| model_version = "v2" in predictions | PASS |
| model_version = "v2" in VMAEstimate | PASS |
| vo2max_note documents derived estimate | PASS |
| estimated_vma / estimated_vo2max in athlete_profile | PASS |
| Historical snapshot no look-ahead (structural) | PASS |
| predicted_time, predicted_pace, readiness present | PASS |

---

## Architecture

```
backend/training_v2/performance_model.py
├── DomainActivity (input, from garmin_activities)
├── VMAEstimate (output)
├── RacePrediction (output)
├── PerformanceEstimate (top-level output)
├── estimate_vma(activities, reference_date) → VMAEstimate
├── predict_races(activities, reference_date) → PerformanceEstimate
└── Zero I/O: no Mongo, no FastAPI, no datetime.now()

server.py (endpoint adapters only)
├── GET /training/race-predictions
│   └── garmin_activities → DomainActivity → predict_races()
└── GET /training/vma-history
    └── garmin_activities → DomainActivity → estimate_vma() × 24 snapshots (no look-ahead)
```

---

## READY STATUS

```
VMA V2 = DomainActivity                ✓
Predictions V2 = observed performance  ✓
avg pace / 0.70 supprimé              ✓
aucune valeur synthétique              ✓
historique sans look-ahead             ✓
confidence explicite                   ✓
5K/10K/Semi/Marathon fonctionnels     ✓
frontend existant conservé             ✓
db.workouts absent de ces autorités    ✓
tests 0 failed                         ✓
aucun lockfile modifié                 ✓
```

**READY for review. Do not merge automatically. Do not start #186.**
