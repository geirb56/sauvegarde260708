# PR #194 — Training Paces V2 Backend

## Metadata

```
BASE_HEAD  = 6f02c91b27391aeec947ed242b0bc88f0c386d59  (copilot/dev)
HEAD       = b14f570bb54a5d5548ba421d022aac11a18a6119
FILES_CHANGED = 4
DIFF_STAT  = backend/server.py +49
             backend/tests/test_training_paces_pr194.py +897
             backend/training_v2/training_paces.py +781
             docs/reports/PR194_TRAINING_PACES_V2.md +139
             4 files changed, 1866 insertions(+)
```

## Methods

```
VDOT_METHOD  = Daniels/Gilbert (2004) formula.
               v = d / (t_s/60)  [m/min]
               pct_vo2 = 0.8 + 0.1894393·exp(−0.012778·t) + 0.2989558·exp(−0.1932605·t)
               VO2  = −4.60 + 0.182258·v + 0.000104·v²
               VDOT = VO2 / pct_vo2
               Valid range: [20, 85] — clamped.

PACE_METHOD  = Inverse solve: given target_VO2 = fraction × VDOT,
               v = (−0.182258 + sqrt(0.182258² + 4·0.000104·(target_VO2+4.60))) / (2·0.000104)
               pace_min_km = 1000 / v

               RUNINDEX_DANIELS_TABLE_CALIBRATION fractions (≤12 s/km tolerance vs published tables):
                 E  (Easy)       : [0.56, 0.68] → range [faster, slower]
                 M  (Marathon)   : 0.79          → single pace
                 T  (Threshold)  : 0.88          → single pace
                 I  (Interval)   : faster=I_FRACTION=1.0915, slower=I_FRACTION_SLOW=1.0 → range
                 R  (Repetition) : 1.2335        → single pace

               Fractions >1.0 are inverse-solve calibration parameters, NOT
               physiological percentages of VO2max.
               I_FRACTION and I_FRACTION_SLOW are explicit named constants.
               The code uses I_FRACTION_SLOW (1.0) for interval.upper, not I_FRACTION*0.95.
```

## VDOT Selection Policy

```
VDOT_SELECTION_POLICY =
  Input: qualified performances from evaluate_performance_quality()
         (confidence = high | medium | low)

  Recency windows — LOCAL to training_paces, NOT inherited from Race Predictions:
    TP_STALE_HIGH_DAYS = 180  (Training Paces-specific)
    CONFIDENCE_HIGH_DAYS   = 21  (shared with performance_model)
    CONFIDENCE_MEDIUM_DAYS = 56  (shared with performance_model)

  CASE 1 — ≥2 concordant HIGH (within VDOT_CONCORDANCE_BAND), most-recent
            within CONFIDENCE_HIGH_DAYS:
            → weighted mean of concordant HIGH VDOTs; paces_confidence = HIGH

  CASE 2 — exactly 1 HIGH, within CONFIDENCE_HIGH_DAYS:
            → that VDOT; paces_confidence = MEDIUM

  CASE 3 — stale HIGH (CONFIDENCE_HIGH_DAYS < age ≤ TP_STALE_HIGH_DAYS):
            → that VDOT; paces_confidence = LOW
            (paces survive — no abrupt deletion at day 22 or day 57)

  CASE 4 — MEDIUM only (no HIGH within CONFIDENCE_MEDIUM_DAYS):
            → best MEDIUM VDOT; paces_confidence = LOW

  CASE 5 — no HIGH within TP_STALE_HIGH_DAYS AND no usable MEDIUM:
            → paces_confidence = INSUFFICIENT; all paces = null
            LOW-only also maps to INSUFFICIENT.

STALE_HIGH_POLICY =
  STALE_HIGH_DOES_NOT_ABRUPTLY_DELETE_PACES = YES
  A HIGH performance aged up to 180 days continues to produce paces
  at LOW confidence.  Paces go null only at INSUFFICIENT (CASE 5).
  TP_STALE_HIGH_DAYS is deliberately decoupled from CONFIDENCE_MEDIUM_DAYS=56
  (Race Predictions boundary) — they serve different purposes.
```

## Invariants

```
NO_LOOKAHEAD              = YES — activities with date > reference_date excluded
DETERMINISTIC             = YES — no date.today() in business layer;
                            daniels_paces(vdot, reference_date) is fully pure
GARMIN_VO2MAX_AFFECTS_PACES = NO — explicitly excluded from VDOT computation
READINESS_AFFECTS_PACES   = NO — readiness adapts sessions, not pace definitions
```

## API Contract

```
API_CONTRACT =
  GET /training/v2/paces

  Response:
  {
    "reference_date": "YYYY-MM-DD",
    "confidence":     "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT",
    "vdot_reference": <float | null>,
    "paces": {
      "easy":        { "lower": {...}, "upper": {...} } | null,
      "marathon":    { "min_per_km": ..., "km_per_hour": ..., "pace_str": "M:SS" } | null,
      "threshold":   { ... } | null,
      "interval":    { "lower": {...}, "upper": {...} } | null,
      "repetition":  { ... } | null
    }
  }

  INSUFFICIENT → all paces = null.
  vdot_reference exposed for debug/internal only; not a product metric.
```

## Tests

```
TESTS =
  TestVdotFromPerformance      — VDOT formula (4 performances + clamp + invalid)
  TestDanielsPaceFormula       — VDOT 40 & 50 vs Daniels tables ±12 s/km;
                                 pace ordering (R<I<T<M<E); km_per_hour; pace_str
  TestNoLookahead              — future activities have no effect; date isolation
  TestVdotConfidenceCases      — CASE1 multiple HIGH; CASE2 single HIGH;
                                 CASE3 stale HIGH; CASE4 MEDIUM-only;
                                 CASE5 no evidence; CASE5 empty; INSUFFICIENT null paces;
                                 new HIGH replaces prior
  TestGarminVO2maxIndependence — Garmin VO2max field ignored
  TestReadinessIndependence    — no readiness_band on TrainingPaces; T pace unchanged
  TestDeterminism              — deterministic across calls; date vs datetime identical
  TestApiSerialization         — INSUFFICIENT → null paces; full paces serializable;
                                 required keys present; no flat pace keys at top level;
                                 threshold pace_str format; reference_date used not today;
                                 deterministic with explicit date
  TestHistorySupport           — historical reference_date; future activities invisible
  TestStaleHighPolicy          — stale HIGH at J+57 → paces survive (LOW);
                                 stale HIGH at J+30/60/120/TP-1 → paces survive;
                                 stale HIGH age<TP → not INSUFFICIENT;
                                 LOW-only → INSUFFICIENT;
                                 stale HIGH age>TP → INSUFFICIENT
  TestIntervalDefinition       — I_FRACTION/I_FRACTION_SLOW constants defined;
                                 interval.lower < interval.upper (faster < slower);
                                 upper matches I_FRACTION_SLOW exactly (not *0.95);
                                 lower matches I_FRACTION exactly

TEST_RESULTS = 51 passed, 0 failed
```

## Scope

```
FRONTEND_CHANGED      = NO
LOCKFILES_CHANGED     = NO
PR196_REFERENCES_REMAINING = NO
RACE_PREDICTIONS_CHANGED   = NO
INTERVAL_DEFINITION_CONSISTENT = YES (I_FRACTION=1.0915 fast end, I_FRACTION_SLOW=1.0 slow end)

PR194_READY_FOR_REVIEW = YES
BLOCKERS               = none
```
