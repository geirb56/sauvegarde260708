# PR #196 — Training Paces V2 + Training UI Rebuild

## 1. Audit — Old Training Page

**Commit found:** `7097a29`  
**File:** `frontend/src/pages/TrainingPlan.jsx`  
**Status:** Deleted before this PR

The old page (`TrainingPlan.jsx`) consumed:
- `/training/plan` (legacy, now removed)
- `/training/metrics` (legacy, now removed)
- VMA-derived paces from user profile (`vma_kmh`)
- TSB (Training Stress Balance) for readiness proxy
- Manual zone calculation in the frontend (VO2max × percentage)

### Feature matrix

| FEATURE | OLD_FRONTEND | CURRENT_FRONTEND | V2_BACKEND | LEGACY_DEP | DECISION |
|---|---|---|---|---|---|
| Weekly sessions | YES | YES | `/training/v2/week` | None | KEEP |
| Cycle/Plan | NO | YES | `/training/v2/cycle` | None | KEEP |
| Today's session | NO | NO | `/training/today` | None | REBUILD |
| Training Paces E/M/T/I/R | YES (VMA-based) | NO | `/training/v2/paces` (new) | VMA HR-speed model | REBUILD |
| Readiness display | Partial (TSB) | NO | `readiness_band` in today | TSB | REBUILD (V2 only) |
| VDOT display | NO | NO | Internal | — | INTERNAL ONLY |
| Race Predictions | NO | NO | `/training/v2/predictions` | — | OUT OF SCOPE |
| VO2max display | NO | NO | — | Garmin VO2max | NOT RESTORED |
| Old VMA field | YES | NO | — | vma_kmh | NOT RESTORED |
| TSB | YES | NO | — | Training Stress Balance | NOT RESTORED |

---

## 2. Current Training Page State (pre-PR196)

`frontend/src/pages/TrainingPlanV2.jsx` (393 lines):
- Fetches `/training/v2/week` and `/training/v2/cycle`
- Shows weekly sessions (7 days), objective, state, weekly target, cycle weeks
- Missing: Today block, Training Paces block
- No dependency on legacy VMA, VO2max, TSB

---

## 3. Features Kept

- Weekly sessions grid (7 days, workout type, distance/duration)
- Objective card (goal type, race date, target time)
- State card (continuity, allow_intensity, confidence)
- Weekly target card (target km/duration, session count)
- Cycle/Plan section (weeks, phases, current week badge)

---

## 4. Features Rebuilt (PR #196)

### H1 — Today's Session
- Source: `GET /training/today`
- Shows original or adapted session
- Adapted badge when `adapted_session ≠ original_session`
- Displays readiness band (HIGH/MEDIUM/LOW) as human label
- Graceful degradation: missing Garmin sleep → readiness absent but page still renders
- `data-testid="training-v2-today"`, `today-session-card`, `today-adapted-badge`

### H2 — Training Paces V2
- Source: `GET /training/v2/paces` (new endpoint, PR #196)
- Displays all 5 Daniels zones: Easy (range), Marathon, Threshold, Interval (range), Repetition
- Confidence badge: HIGH / MEDIUM / LOW
- INSUFFICIENT: shows user-facing message, never undefined pace values
- VDOT is internal: never displayed to user
- `data-testid="training-v2-paces"`, `paces-grid`, `pace-zone-{key}`, `paces-confidence-badge`

---

## 5. Features Dropped / Not Restored

- Old `/training/plan` endpoint (legacy)
- Old `/training/metrics` endpoint (legacy)
- VMA (`vma_kmh`) field from user profile
- TSB (Training Stress Balance) for readiness
- Manual frontend zone calculation
- VO2max Garmin → paces mapping
- Old goal types outside `[5k, 10k, semi, marathon, maintenance]` contract

---

## 6. Legacy Dependencies NOT Restored

- `vma_kmh` user profile field
- `estimate_vma()` HR-speed model
- `db.workouts` legacy collection
- `training_stress_balance` / TSB
- Garmin VO2max → pace mapping

---

## 7. Backend — VDOT Engine (`training_paces.py`)

### 7.1 VDOT Formula (Daniels/Gilbert 2004)

```
v = distance_m / (duration_s / 60)        # m/min
t = duration_s / 60                        # minutes
pct = 0.8 + 0.1894 * exp(-0.012778 * t)
    + 0.2990 * exp(-0.1932605 * t)
VO2 = -4.60 + 0.182258 * v + 0.000104 * v²
VDOT = VO2 / pct
```

Inverse (pace from target VO2):
```
target_vo2 = fraction × VDOT
v = (-0.182258 + sqrt(0.182258² + 4 × 0.000104 × (target_vo2 + 4.60))) / (2 × 0.000104)
pace_min_per_km = 1000 / v
```

### 7.2 Calibrated Intensity Fractions

Verified against Daniels (2014) VDOT tables ±12 s/km:

| Zone | Fraction | Form | Justification |
|---|---|---|---|
| E (Easy) | [0.56, 0.68] | Range | Daniels prescribes 59–74% VO2max; range reflects natural variability |
| M (Marathon) | 0.79 | Single | ~80% VO2max for marathon-specific adaptation |
| T (Threshold) | 0.88 | Single | ~88% VO2max ≈ 1-hour effort (lactate threshold) |
| I (Interval) | [1.0, 1.1115] | Range | 95–100%+ VO2max for 3–5 min reps; using [1.0, 1.0915] |
| R (Repetition) | 1.2335 | Single | ~1-min sprint; fastest mechanically sound speed |

### 7.3 VDOT Selection Policy

Input: `List[VdotEvidence]` with fields `(vdot, confidence, days_ago)`

**Case 1 — Multiple concordant HIGH (≤21 days, spread ≤3 VDOT pts):**  
→ Weighted mean of top HIGH evidences. Confidence = HIGH.

**Case 2 — Single HIGH recent (≤21 days):**  
→ VDOT from that evidence. Confidence = MEDIUM (single data point).

**Case 3 — HIGH stale (21–56 days):**  
→ Use stale HIGH, decay toward lower bound. Confidence = LOW.

**Case 4 — MEDIUM evidences only (≤56 days), no HIGH:**  
→ Conservative weighted mean, capped at 5th-percentile MEDIUM. Confidence = LOW.

**Case 5 — No valid evidence:**  
→ VDOT = None, Confidence = INSUFFICIENT. No paces generated.

Jump guard: prevents a new HIGH from increasing VDOT by more than 4 points in a single step.

Stale guard: if most recent HIGH is >120 days old, treat as INSUFFICIENT.

### 7.4 Confidence Levels

| Level | Condition |
|---|---|
| HIGH | Multiple concordant HIGH evidences ≤21 days |
| MEDIUM | Single HIGH evidence ≤21 days |
| LOW | Stale HIGH or MEDIUM-only evidences |
| INSUFFICIENT | No defensible evidence |

---

## 8. No-Lookahead Invariant

`compute_training_paces(activities, reference_date)` filters all activities to `activity_date ≤ reference_date` before computing VDOT.

**Test:**
```
paces_at_J = compute_training_paces(activities, J)
add activity at J+30
paces_at_J_again = compute_training_paces(activities_extended, J)
assert paces_at_J == paces_at_J_again  # PASS
```

---

## 9. API Endpoint

```
GET /training/v2/paces
```

Response:
```json
{
  "reference_date": "2026-08-25",
  "vdot_reference": 42.1,
  "confidence": "MEDIUM",
  "reason": "Single high-quality performance within 21 days",
  "paces": {
    "easy": {
      "method": "daniels_range",
      "pace_faster_min_per_km": 5.12,
      "pace_slower_min_per_km": 6.24,
      "lower_bound_km_h": 9.6,
      "upper_bound_km_h": 11.7
    },
    "marathon": { "method": "daniels_single", "pace_min_per_km": 5.37, "km_h": 11.18 },
    "threshold": { "method": "daniels_single", "pace_min_per_km": 4.82, "km_h": 12.45 },
    "interval": {
      "method": "daniels_range",
      "pace_faster_min_per_km": 4.31,
      "pace_slower_min_per_km": 4.56
    },
    "repetition": { "method": "daniels_single", "pace_min_per_km": 3.89, "km_h": 15.42 }
  }
}
```

---

## 10. Frontend Rebuild

### Page Structure (mobile-first order)
1. **Today** (`TodaySection`) — H1
2. **Training Paces** (`TrainingPacesSection`) — H2
3. **Objective / State / Weekly Target** — H4
4. **Weekly Sessions grid** — H4
5. **Training Cycle** (`CycleSection`) — H5

### New Components
- `TodaySection` — adapted/original session, readiness band, adapted badge
- `TrainingPacesSection` — 5 zone cards, confidence badge, INSUFFICIENT fallback
- `PaceCard` — single zone rendering, range or single pace, formatted as `M:SS`

### Key UX Rules
- INSUFFICIENT → message only, no undefined pace values
- Confidence badge only shown when paces available
- VDOT value never displayed (internal)
- Adapted session badge when readiness modifies the original plan
- Today endpoint failure → error message, page still renders
- Paces endpoint failure → INSUFFICIENT message, page still renders

---

## 11. i18n

New keys added to all 3 language blocks (EN / FR / ES):

- `trainingV2.todayTitle`, `todayNoSession`, `todayAdapted`, `todayOriginal`, `todayAdaptedSession`, `todayAdaptedBecause`, `todayReadinessHigh/Medium/Low`, `todayNoReadiness`, `todayLoadingError`
- `trainingV2.pacesTitle`, `pacesSubtitle`, `pacesEasyLabel`, `pacesMarathonLabel`, `pacesThresholdLabel`, `pacesIntervalLabel`, `pacesRepetitionLabel`, `pacesEasy/Marathon/Threshold/Interval/RepetitionDesc`
- `trainingV2.pacesConfidenceHigh/Medium/Low/Insufficient`, `pacesInsufficientMessage`, `pacesPerKm`
- `trainingV2.thisWeekTitle`, `thisWeekTarget`, `thisWeekActual`, `thisWeekSessions`, `thisWeekRemaining`, `thisWeekProgress`

---

## 12. Tests

### Backend (`backend/tests/test_training_paces_pr196.py`) — 41 tests

- VDOT formula accuracy (multiple distances)
- All 5 Daniels zones (E range, M, T, I range, R single)
- Pace bounds validation
- 5 confidence cases
- No-lookahead invariant
- Determinism
- Garmin VO2max independence
- Readiness independence
- API serialization
- `select_vdot_reference` direct unit tests

### Frontend (`frontend/src/__tests__/training-v2-page.test.jsx`) — 14 new tests (PR #196 suite)

- Today's session renders
- Adapted session badge
- No session → no-session message
- Today endpoint failure → page still renders
- 5 pace zones render
- Pace range for Easy zone
- Single pace for Marathon zone
- Confidence badge visible
- INSUFFICIENT message (no paces grid)
- Paces endpoint failure → INSUFFICIENT message
- Weekly target still visible
- Plan/cycle still visible
- No raw i18n keys in output
- No VO2max/VMA in paces section

---

## 13. Invariants Verified

| Invariant | Status |
|---|---|
| `GARMIN_VO2MAX_AFFECTS_PACES = NO` | `user_max_hr=None` enforced in endpoint; never passed to VDOT function |
| `READINESS_AFFECTS_PACE_DEFINITION = NO` | Readiness adapts session, never modifies Daniels fractions |
| `RACE_PREDICTIONS_FORMULA_CHANGED = NO` | `performance_model.py` not modified |
| `RUNINDEX_FORMULA_CHANGED = NO` | `runindex_v2.py` not modified |
| `READINESS_FORMULA_CHANGED = NO` | `readiness_decision.py` not modified |
| `NO_LOOKAHEAD = PASS` | Tested with future activity injection |
| `VDOT_SOURCE = qualified_performances` | Pipeline: qualified HIGH/MEDIUM activities → VDOT formula |

---

## 14. Limitations

1. **`/training/today` endpoint** — the existing endpoint may not yet return `readiness_band` or `adaptation_reason` in all code paths; the frontend handles missing fields gracefully.
2. **VDOT jump guard** — 4-point cap is conservative; may slightly delay adaptation to genuine fitness improvement after a long gap.
3. **Stale guard threshold** — 120-day cutoff is a policy choice; athletes returning from injury may have no valid evidence even if their last race was strong.
4. **I zone as range** — Using `[1.0, 1.0915]` instead of a single pace. This is intentional (Daniels validates a range for interval training) but may differ from some coach implementations that give a single target.
5. **ES (Spanish) i18n** — Added in parallel with FR/EN; should be reviewed by a native speaker.
