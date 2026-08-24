# RUNINDEX PR #189 — Performance Curve V2
## Cohérence globale des prédictions 5K / 10K / Semi / Marathon

---

## CURRENT_ARCHITECTURE (before PR #189)

```
predict_races(activities, ref_date):
    pool = _build_qualified_performance_pool(activities, ref_date)
    for target in [5K, 10K, Semi, Marathon]:
        source = _select_riegel_source(pool, ref_date, target)   ← INDEPENDENT PER TARGET
        if source:
            T = _riegel_predict(source, target)
        else:
            prediction = null
```

`_select_riegel_source` scores each qualified activity with `_score_riegel_candidate`,
which includes a **proximity weight of 0.50** that biases selection toward the target distance.

Result: 4 independent source selections → 4 potentially incompatible extrapolations.

**CURRENT_SOURCE_SELECTION_PER_TARGET = YES**
**CURRENT_MONOTONICITY_GUARANTEE = NO**

### Problem Demonstration

With a pool containing:
- Excellent 5K: 22:00 → k=1.06 → Semi ≈ 1h45 (pace ~5:00/km)
- Moderate 20K: 1h50  → k=1.06 → Semi ≈ 1h55 (pace ~5:26/km)

Old engine:
- 5K target   → selects excellent 5K (proximity) → fast Semi projection
- Semi target  → selects moderate 20K (proximity) → slow Semi projection
- Marathon target → selects moderate 20K → slower Marathon

Observed inversion in production runtime after #188:
```
5K    29:37  =  5:55/km
10K   1h01   =  6:06/km
Semi  2h01   =  5:44/km  ← FASTER per km than 10K (architecturally wrong)
Marathon 4h23 = 6:14/km
```

The semi-marathon pace is better per km than the 10K pace.
This is not a data error — it is a structural consequence of 4 independent source selections.

---

## CHOSEN_CURVE_MODEL

**T(D) = A × D^k**

where:
- `T` = predicted time (seconds)
- `D` = distance (metres)
- `A` = performance level coefficient (dimensionless)
- `k` = endurance exponent (≥ 1.0)

### ALTERNATIVES_CONSIDERED

| Model | Rejected reason |
|-------|----------------|
| Independent Riegel per target (existing) | Architecturally incompatible — proved to cause pace inversions |
| Margaria–Keren VO2 model | Requires VO2max / VMA → violates RACE_PREDICTIONS_VMA_DEPENDENCY = NO |
| Exponential decay: T = a·e^(b·D) | Not scale-invariant, no physiological basis for running |
| Polynomial fit | Overfits, no monotonicity guarantee for arbitrary coefficients |
| Power law in log-space (chosen) | Log-linear, interpretable, Riegel-compatible, closed-form guarantee of monotonicity |

### WHY_CHOSEN

The power law T(D) = A·D^k in log-space is exactly the Riegel (1977) model.
It is standard in running prediction literature. The key insight for PR #189:

> A single (A, k) pair fitted to the entire qualified pool produces ONE curve that
> serves all four target distances. Pace(D) = T(D)/D = A·D^(k−1) is non-decreasing
> if and only if k ≥ 1 — monotonicity is a mathematical consequence, not a patch.

---

## FIT_METHOD

Weighted OLS (ordinary least squares) in log-space:

```
log(T_i) = log(A) + k · log(D_i) + ε_i
```

With weights:
```
w_i = quality_score_i × recency_weight_i
recency_weight_i = exp(−days_ago_i / CURVE_RECENCY_DECAY_DAYS)
```

where `CURVE_RECENCY_DECAY_DAYS = 180`.

The weighted centred regression gives the closed-form solution:
```
k = Σ w_i (x_i − x̄)(y_i − ȳ) / Σ w_i (x_i − x̄)²
b0 = ȳ − k·x̄
A = exp(b0)
```

Fit quality (R²) is reported when n ≥ 2.

---

## WEIGHTING

Each qualified observation is weighted by:

```
w = quality_score × exp(−days_ago / 180)
```

**Quality score** (`quality_score` from #188): ranges 0.0–1.0.
A high-quality performance (score=1.0, HR well above threshold) weighs twice as much
as a borderline performance (score=0.5).

**Recency weight**: exponential decay with half-life ≈ 125 days.
A performance at 180 days ago has weight `1/e ≈ 0.37` relative to today.

---

## RECENCY_POLICY

Recency influences the CONSTRUCTION of the common curve, not the target selection.

- Recent performances weigh more in the log-space OLS.
- The same (A, k) curve is used for all four targets.
- There is no "different k per target based on recency of nearby observations".

This is the key architectural invariant: **one curve, four evaluations**.

---

## QUALITY_POLICY

- Only activities where `quality.qualified is True` enter the qualified pool.
- Within the pool, `quality.score` is used as the OLS weight.
- `quality.score = None` is treated as `0.5` (neutral weight).
- **NON_QUALIFIED_CONTRIBUTION = 0**: `qualified=False` activities do not enter the pool and do not contribute to (A, k).

Note: non-qualified activities may still contribute to `athlete_profile.weekly_km`
and endurance readiness — this is architecturally correct (training volume ≠ performance).

---

## K_POLICY

**Prior**: `K_PRIOR = 1.06` (Riegel 1977 standard exponent).

**Bounds**: `K_MIN = 1.0`, `K_MAX = 1.20`.

### Justification for K_MIN = 1.0

The physiological meaning: k = 1.0 means pace is constant across distances (unrealistic
for long distances but a safe lower bound). k < 1.0 means pace *improves* with distance —
physiologically impossible for maximal efforts. K_MIN = 1.0 is the strictest bound that
guarantees pace monotonicity.

### Justification for K_MAX = 1.20

Empirical literature (Riegel 1977, van Manen & Cohen 2014) finds typical values k ∈ [1.03, 1.13]
for trained runners. K_MAX = 1.20 allows up to ~0.14 above the median to handle outlier
datasets (e.g., specialized ultra-runners, beginners with large performance drops over
distance). Values above 1.20 suggest data incompatibility or artefacts.

### Clamping policy

When raw OLS gives k outside [K_MIN, K_MAX]:
- k is clamped to the bound.
- `k_clamped = True` is recorded in `PerformanceCurveV2`.
- Confidence is not automatically reduced by clamping alone (clamping may be benign
  when all observations are at similar distances and k cannot be estimated reliably).

If `ss_xx < 1e-12` (all observations at identical distances):
- k = K_PRIOR (cannot estimate slope from zero variance in x).
- `k_clamped = True`.

---

## OUTLIER_POLICY

**Method**: Weighted OLS with quality-score weighting.

A single high-quality outlier observation cannot dominate the curve if there are
multiple lower-quality but consistent observations. The `quality_score` weighting
naturally dampens outliers that are borderline-qualified (low score).

For n=2 observations that are contradictory (raw k < K_MIN or > K_MAX):
- k is clamped to the bound.
- A is recomputed from the weighted centroid at the clamped k.
- This is architecturally better than rejecting observations: the curve still uses
  all available data, just with bounded exponent.

**OUTLIER_DOMINATES_CURVE = NO** (demonstrated in Test E).

---

## EXTRAPOLATION_POLICY

Symmetric ratio metric:
```
extrapolation_ratio = max(target_m / nearest_observed_m,
                          nearest_observed_m / target_m)
```

where `nearest_observed_m` is the observed distance (from the pool) closest to the target.

| Ratio | Confidence |
|-------|-----------|
| < 2.0 | quality-based (fit_quality or single-source quality) |
| 2.0 – 3.0 | `medium` |
| 3.0 – 6.0 | `low` |
| ≥ 6.0 | `null` (prediction suppressed — preferred over false precision) |

**SYMMETRIC_EXTRAPOLATION = YES**: 5K→Marathon (ratio=8.44) and Marathon→5K (ratio=8.44)
are both treated identically.

Thresholds constants:
```python
EXTRAPOLATION_NULL_RATIO = 6.0
EXTRAPOLATION_LOW_RATIO = 3.0
EXTRAPOLATION_MEDIUM_RATIO = 2.0
```

**Justification for NULL at ratio ≥ 6.0**: 5K to Marathon extrapolation is 8.44×, far
outside any empirical validation of the power law. Reporting a number here would create
false confidence. `null` is preferred.

---

## CONFIDENCE_POLICY

```
if extrapolation_ratio >= EXTRAPOLATION_NULL_RATIO:
    return None  (null prediction)

if extrapolation_ratio >= EXTRAPOLATION_LOW_RATIO:
    return "low"

if extrapolation_ratio >= EXTRAPOLATION_MEDIUM_RATIO:
    return "medium"

# Within reasonable extrapolation range:
if multi-contributor:
    if fit_quality >= 0.90: "high"
    elif fit_quality >= 0.60: "medium"
    else: "low"
else (single contributor):
    map quality_confidence from #188 quality assessment
```

---

## ENDURANCE_SUPPORT_POLICY

The endurance penalty `_endurance_penalty(D)` applies to the raw curve output:
```
T_adjusted(D) = T_curve(D) × endurance_penalty(D)
```

where `endurance_penalty = 1 + (1 − endurance_support) × 0.40`.

`endurance_support` is non-decreasing with training specificity (max_run, weekly_km).
`endurance_penalty` is therefore non-increasing with training quality and
non-decreasing with target distance (since larger distances require more endurance).

**No double-counting**: The curve's k captures *how fast pace degrades with distance*
(fitness). The endurance penalty captures *whether the runner is currently trained for
this distance* (readiness/specificity). These are orthogonal: a fast 10K runner with
k=1.06 may still have low endurance_support for the marathon if they have never run > 20km.

**Monotonicity preservation**: For any fixed (A, k) with k ≥ 1, the composition
`T_curve(D) × penalty(D)` remains monotonically non-decreasing in pace because:
- `T_curve(D)/D = A·D^(k−1)` is non-decreasing (k ≥ 1).
- `penalty(D)` is non-decreasing in D (worse endurance support for longer distances).
- Product of two non-decreasing non-negative functions → non-decreasing.

---

## SINGLE_PERFORMANCE_FALLBACK

When exactly one qualified observation exists:
```
k = K_PRIOR = 1.06
A = T_observed / D_observed^1.06
```

This is identical to the original Riegel extrapolation from a single source, but now
applied consistently to all four targets from the same (A, k).

`method = "single_riegel_fallback"` in diagnostics.

---

## ZERO_PERFORMANCE_BEHAVIOR

When the qualified pool is empty:
- `predict_races` returns `PerformanceEstimate` with `predictions = []` (empty list).
- No synthetic data.
- No fallback on ordinary training runs.

---

## PROPERTY_TEST_RESULTS

Test L generates ≥ 100 deterministic scenarios across:
- Speed levels: 10.0 / 12.0 / 14.0 km/h
- n_perfs: 1 / 2 / 3 qualified performances
- Distances: [5K], [10K], [Marathon], [5K+10K], [5K+Semi], [10K+Marathon], [5K+10K+Marathon], [10K+Semi+Marathon]
- HR: True (with HR) / True (HR, different base) / False (speed-only)
- Intervals: 7 days / 30 days
- Total: 3 × 3 × 8 × 3 × 2 = 432 scenarios

**Monotonicity assertion**: For every scenario producing ≥ 2 non-null predictions:
```
pace_5K ≤ pace_10K ≤ pace_Semi ≤ pace_Marathon
```

**PROPERTY_TEST_FAILURES = 0**

---

## REGRESSION_RESULTS

All existing tests maintained:

| Test suite | Count | Passed | Failed |
|-----------|-------|--------|--------|
| PR185 | baseline | ✓ | 0 |
| PR186/#187 | baseline | ✓ | 0 |
| PR188 | baseline + 2 minimal adaptations | ✓ | 0 |
| PR189 (new) | 13 classes + invariants | ✓ | 0 |
| **Total** | **188** | **187 passed, 1 skipped** | **0** |

Note on PR188 adaptations (minimal):
1. `test_case_b_known_10k_performance_qualified_and_selected_for_5k_10k`: removed
   source_distance_m check (now None for multi-contributor), added monotonicity assertion.
2. `test_predictions_are_deterministic_with_quality_fields`: removed source_quality_confidence
   check, added curve_k/curve_a assertions.

---

## OUTPUT_FIELDS

### New fields on `RacePrediction`

| Field | Description |
|-------|-------------|
| `curve_k` | Fitted endurance exponent |
| `curve_a` | Fitted level coefficient |
| `curve_method` | `"single_riegel_fallback"` or `"weighted_ols_logspace"` |
| `curve_extrapolation_ratio` | Symmetric distance ratio for this target |
| `contributors_count` | Number of qualified observations in the curve |
| `observed_distance_min_m` | Closest observation distance |
| `observed_distance_max_m` | Furthest observation distance |
| `curve_fit_quality` | R² of OLS fit (None for single contributor) |

### Backward-compatible fields

When `contributors_count == 1` (single contributor), the legacy single-source fields
remain populated for backward compatibility:
- `source_distance_m`, `source_type = "observed_activity"`
- `source_quality_score`, `source_quality_confidence`
- `source_speed_percentile`, `source_relative_hr`

When `contributors_count >= 2`:
- These fields are `None` (no single "source" — the curve is the source)
- `source_type = "performance_curve_v2"`

---

## FINAL OUTPUT METRICS

```
PR = 189
BASE_SHA = (see git log)
FINAL_SHA = (see git log)

CURRENT_SOURCE_SELECTION_PER_TARGET = YES (was) / NO (now)
CURRENT_MONOTONICITY_GUARANTEE = NO (was) / YES (now)

PERFORMANCE_CURVE_IMPLEMENTED = YES
CURVE_METHOD = weighted_ols_logspace (n>=2) / single_riegel_fallback (n=1)
CURVE_K_POLICY = K_MIN=1.0, K_MAX=1.20, K_PRIOR=1.06 (fallback)
SINGLE_PERFORMANCE_FALLBACK = T(D) = T_source * (D/D_source)^1.06

NON_QUALIFIED_CONTRIBUTION = NO
FUTURE_LOOKAHEAD = NO
INPUT_ORDER_DEPENDENCY = NO

RAW_CURVE_MONOTONIC = YES
POST_HOC_MONOTONICITY_PATCH = NO

ONE_PERFORMANCE_TEST = PASSED (Test A)
MULTI_PERFORMANCE_TEST = PASSED (Test B)
CROSSING_SOURCES_TEST = PASSED (Test C)
OUTLIER_TEST = PASSED (Test E)
SPEED_ONLY_TEST = PASSED (Test I)
5K_ONLY_TEST = PASSED (Test K)
MARATHON_ONLY_TEST = PASSED (Test J)
PROPERTY_TEST_SCENARIOS = 432
PROPERTY_TEST_FAILURES = 0

EXTRAPOLATION_POLICY = null>=6.0x | low>=3.0x | medium>=2.0x | quality-based<2.0x
SYMMETRIC_EXTRAPOLATION = YES

RACE_PREDICTIONS_VMA_DEPENDENCY = NO
VMA_MODIFIED = NO
FRONTEND_MODIFIED = NO
OUT_OF_SCOPE_FILES = NO

TESTS = 187 passed, 1 skipped, 0 failed
LIVE_ACCOUNT_TEST = NOT_RUN_IN_GITHUB_ENVIRONMENT
PR_BASE = copilot/dev
MERGEABLE = YES
READY = YES
```

---

## SCOPE

Files modified:
- `backend/training_v2/performance_model.py` — Performance Curve V2 implementation
- `backend/tests/test_performance_model_pr188.py` — minimal adaptation (2 tests)
- `backend/tests/test_performance_model_pr189.py` — new test file (created)
- `RUNINDEX_PR189_REPORT.md` — this report

Files NOT modified:
- `backend/server.py` — no changes needed (endpoint contract preserved)
- `frontend/*` — not modified
- VMA formula — not modified
- #188 thresholds — not modified
- Garmin ingestion, training load, readiness, planning engine — not modified
