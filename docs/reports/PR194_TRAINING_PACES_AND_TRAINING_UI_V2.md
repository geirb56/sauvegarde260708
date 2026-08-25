# PR #194 — Training Paces V2 + Training UI V2 — Correction Report

## A. Base SHA / Head SHA

| Field | Value |
|-------|-------|
| Base (merge of PR #193) | `6f02c91` |
| PR #194 pre-correction head | `dc38239` |
| PR #194 post-correction head | see git log on branch |

---

## B. Files Modified

| File | Change |
|------|--------|
| `backend/training_v2/training_paces.py` | C1 paces contract; C3 docstring; C6 determinism; module docstring PR→#194 |
| `backend/server.py` | Comment + docstring updated for PR #194 and nested paces contract |
| `backend/tests/test_training_paces_pr196.py` | **Deleted** (C9) |
| `backend/tests/test_training_paces_pr194.py` | **Created** — renamed + C7 serialization tests + C6 reference_date tests |
| `frontend/src/pages/TrainingPlanV2.jsx` | C2 — TodaySection reads real /training/today fields |
| `frontend/src/__tests__/training-v2-page.test.jsx` | C2+C7 — buildTodayResponse, buildPacesResponse aligned to real contracts; PR #194 |
| `frontend/package-lock.json` | Restored to base (C8) |
| `frontend/yarn.lock` | Restored to base (C8) |

---

## C. VDOT Authority

VDOT is derived **exclusively** from qualified running performances evaluated
by `evaluate_performance_quality()` (performance_model.py, PR #188).

Single path:  
`DomainActivity list → _collect_vdot_evidence() → _select_vdot_reference() → _build_training_paces()`

**Forbidden inputs (hard boundaries, never read by training_paces.py):**
- Garmin VO2max field
- VMA (speed × 3.5 shortcut)
- Race Predictions V2 outputs
- Readiness scores

---

## D. Equations Used

### VDOT from performance (Daniels/Gilbert 2004)

```
v       = distance_m / (duration_s / 60)          [m/min]
t       = duration_s / 60                          [min]
pct_VO2 = 0.8
        + 0.1894393 × exp(−0.012778 × t)
        + 0.2989558 × exp(−0.1932605 × t)
VO2     = −4.60 + 0.182258 × v + 0.000104 × v²
VDOT    = VO2 / pct_VO2
```

Valid range: `[20, 85]` — clamped.

### Pace from VDOT (inverse solve)

```
target_VO2  = fraction × VDOT
v           = (−0.182258 + sqrt(0.182258² + 4×0.000104×(target_VO2+4.60)))
              / (2 × 0.000104)
pace_min_km = 1000 / v
```

---

## E. Pace Definitions (E/M/T/I/R)

| Zone | Fraction(s) | Type | Physiological target |
|------|-------------|------|----------------------|
| E (Easy) | [0.56, 0.68] | Range (slower→faster) | Aerobic base |
| M (Marathon) | 0.79 | Single | Marathon race pace |
| T (Threshold) | 0.88 | Single | ~1-hr race / lactate threshold |
| I (Interval) | [1.0, 1.0915] | Range | ~5-min rep effort |
| R (Repetition) | 1.2335 | Single | ~1-min rep effort |

Ordering invariant (always verified): `pace_R < pace_I < pace_T < pace_M < pace_E_lower < pace_E_upper`  
(smaller min/km = faster)

---

## F. Daniels Status

**These are RUNINDEX_DANIELS_TABLE_CALIBRATION values**, not exact Daniels published
fractions. They are inverse-solve parameters calibrated to reproduce the official
Daniels VDOT pace tables via the VO2-speed polynomial.

- Fractions >1.0 (I = 1.0915, R = 1.2335) are **NOT** physiological VO2max percentages;
  they are the inverse-solve inputs that reproduce the tables for short-effort paces.
- Measured tolerance against published Daniels tables: **≤12 s/km** across VDOT 30–70.
- The previous docstring claim of `±2 s/km` was incorrect and has been removed.

---

## G. VDOT Selection Policy

Recency windows (from `performance_model.py` constants):

| Window constant | Days |
|-----------------|------|
| `CONFIDENCE_HIGH_DAYS` | 21 |
| `CONFIDENCE_MEDIUM_DAYS` | 56 |
| `CONFIDENCE_LOW_DAYS` | 120 |

These windows are reused from the performance quality model. They are fit for
training-pace purposes: a HIGH performance within 21 days is a reliable capability
anchor; 21–56 days is usable but stale; >56 days MEDIUM and >120 days (or LOW-only)
evidence is discarded (INSUFFICIENT).

| Case | Condition | paces_confidence |
|------|-----------|-----------------|
| 1 | ≥2 concordant HIGH (≤21 d) | HIGH |
| 1 + jump guard | Case 1 but ref > prior MEDIUM + 5 VDOT | MEDIUM |
| 2 | 1 recent HIGH (≤21 d) | MEDIUM |
| 3 | HIGH stale (21–56 d) | LOW |
| 4 | MEDIUM only (≤56 d) | LOW |
| 5 | All evidence >56 d or LOW-quality only | INSUFFICIENT |

Constants: `VDOT_CONCORDANCE_BAND = 5.0`, `VDOT_JUMP_GUARD = 5.0`

---

## H. Contract JSON — /training/v2/paces

```json
{
  "reference_date": "2026-08-25",
  "confidence": "HIGH | MEDIUM | LOW | INSUFFICIENT",
  "vdot_reference": 47.3,
  "vdot_evidence_count": 3,
  "vdot_high_count": 2,
  "vdot_medium_count": 1,
  "vdot_concordant": true,
  "vdot_reason": "case1_multiple_concordant_high",
  "paces": {
    "easy":       { "lower": { "min_per_km": 5.48, "km_per_hour": 10.95, "pace_str": "5:29", "method": "daniels_fraction" },
                    "upper": { "min_per_km": 6.43, "km_per_hour": 9.33,  "pace_str": "6:26", "method": "daniels_fraction" },
                    "lower_str": "5:29", "upper_str": "6:26", "method": "daniels_fraction" },
    "marathon":   { "min_per_km": 5.04, "km_per_hour": 11.90, "pace_str": "5:02", "method": "daniels_fraction" },
    "threshold":  { "min_per_km": 4.62, "km_per_hour": 12.99, "pace_str": "4:37", "method": "daniels_fraction" },
    "interval":   { "lower": { "min_per_km": 4.04, ... }, "upper": { "min_per_km": 4.24, ... }, ... },
    "repetition": { "min_per_km": 3.60, "km_per_hour": 16.67, "pace_str": "3:36", "method": "daniels_fraction" }
  },
  "reason": "vdot=47.30 confidence=high reason=case1_multiple_concordant_high",
  "model_version": "v2"
}
```

When `confidence == "INSUFFICIENT"`: all `paces.*` values are `null`, `vdot_reference` is `null`.

---

## I. /training/today Contract (consumed by TodaySection)

Real fields from PR #137 runtime (server.py, lines 3630–3792):

| Field | Type | Used for |
|-------|------|----------|
| `adaptation_applied` | bool | isAdapted flag (authoritative) |
| `original_prescription` | dict | session to show when not adapted |
| `adapted_prescription` | dict | session to show when adapted |
| `planned_session` | dict | fallback if prescription absent |
| `readiness.band` | str | readiness label key |
| `adaptation_reason` | str | reason text shown on adapted badge |
| `reason_codes` | list | raw codes (available for future display) |

**Removed from frontend (were never in the real contract):**
- `readiness_band` (top-level) → now `readiness.band`
- `adapted_session` → now `adapted_prescription`
- `original_session` → now `original_prescription` / `planned_session`
- Object identity comparison for `isAdapted` → now uses `adaptation_applied` boolean

---

## J. Garmin VO2max Independence

`training_paces.py` never imports or reads any Garmin VO2max field.
`compute_training_paces(activities, reference_date, user_max_hr=None)` — `user_max_hr`
is wired to `None` at the server boundary.  
`DomainActivity` has no `garmin_vo2max` field.  
Test: `TestGarminVO2maxIndependence::test_garmin_vo2max_ignored` (verifies signature).

---

## K. Readiness Independence

`training_paces.py` has no import of `readiness_decision.py` or any readiness layer.
`TrainingPaces` dataclass has no `readiness_band`, `readiness_score`, or `adapted_session` field.  
Test: `TestReadinessIndependence::test_paces_are_capability_not_prescription`.

---

## L. No-Lookahead Proof

`_collect_vdot_evidence`: every activity with `act_date > reference_date` is skipped (`continue`).  
Test: `TestNoLookahead::test_adding_future_activity_no_effect` — adds activity at `REF_DATE + 30d`;
asserts identical VDOT and confidence.

---

## M. Tests Executed + Results

### Backend — `test_training_paces_pr194.py`

```
44 passed in 0.64s
```

Classes covered:
- `TestVdotFromPerformance` (8 tests)
- `TestDanielsPaceFormula` (8 tests — incl. monotonicity, E/M/T/I/R order)
- `TestNoLookahead` (2 tests)
- `TestVdotConfidenceCases` (8 tests — Cases 1–5)
- `TestGarminVO2maxIndependence` (2 tests)
- `TestReadinessIndependence` (2 tests)
- `TestDeterminism` (2 tests)
- `TestApiSerialization` (7 tests — incl. C1 contract, C6 reference_date)
- `TestVdotConcordanceAndJumpGuard` (2 tests)
- `TestHistorySupport` (2 tests)

### Frontend — `training-v2-page.test.jsx`

Payload fixtures (`buildTodayResponse`, `buildPacesResponse`) aligned to real
backend contracts. Tests cover: today adapted/non-adapted/no-session/error,
paces 5-zone display, INSUFFICIENT, endpoint failure, no i18n key leaks,
no VO2max/VMA in paces section.

---

## N. Remaining Divergences / Technical Debt

| Item | Status |
|------|--------|
| `daniels_paces(vdot)` with `reference_date=None` still calls `date.today()` | Acceptable — documented; only used by utilities/tests |
| Frontend tests run in jest/craco environment requiring `npm install` | Infrastructure-dependent; logic verified via code review |
| CASE 5: LOW-quality-only evidence silently produces INSUFFICIENT | By design — LOW evidence is only acceptable within HIGH/MEDIUM recency windows |

---

## O. Elements Explicitly NOT Modified

- RunIndex formula
- Readiness formula / `build_readiness_decision()`
- Race Predictions formula / Race Predictions V2
- Training Load
- Weekly Target
- Periodization
- Workout Generator
- Paddle / Auth / Garmin sync
- `performance_model.py` CONFIDENCE windows (HIGH_DAYS=21, MEDIUM_DAYS=56, LOW_DAYS=120)
- Any other endpoint outside `/training/v2/paces` and `/training/today` (read-only)
