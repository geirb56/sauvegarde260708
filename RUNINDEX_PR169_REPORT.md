# RUNINDEX PR #169 — TRAININGPLAN V2 FRONTEND NATIF

## Summary

| Field | Value |
|---|---|
| **HEAD départ** | `af33c9f112b774771d52fe157429be8dcad01453` |
| **HEAD final** | see post-merge |
| **Base branch** | `copilot/dev` |

---

## Files Changed

| File | Action |
|---|---|
| `frontend/src/pages/TrainingPlanV2.jsx` | CREATED |
| `frontend/src/App.js` | MODIFIED — added import + route `/training-v2` |
| `frontend/src/lib/i18n.js` | MODIFIED — added `trainingV2` keys (en / fr / es) |
| `frontend/src/__tests__/training-plan-v2.test.jsx` | CREATED — 12 new tests |

---

## Checklist

| Item | Status |
|---|---|
| **TrainingPlanV2 created** | YES |
| **Route /training-v2** | YES |
| **TrainingPlan.jsx modified** | NO |
| **backend modified** | NO |
| **API consumed** | `GET /api/training/v2/week` only |
| **LEGACY_API_CALLS** | 0 |
| **NONE_TO_ZERO_COERCIONS** | 0 (`|| 0` not used on any business field) |
| **FORCED_KM_DISPLAYS** | 0 (all distances via `formatDistance`) |
| **UNKNOWN_TSS_PLACEHOLDERS** | 0 (null TSS not displayed) |
| **HARDCODED_USER_LABELS** | 0 (all labels via `t("trainingV2.*")`) |
| **V2_WORKOUT_TYPES_PRESERVED** | YES |
| **UnitContext used for all distances** | YES |
| **i18n used** | YES (en / fr / es) |
| **existing design system reused** | YES |

---

## Test Results

```
Tests:  12 passed, 0 failed  (training-plan-v2.test.jsx)

Pre-existing failures in dashboard-run-readiness-null.test.jsx: 5
(confirmed present on baseline af33c9f before PR changes)
```

Test coverage: A routing · B API · C distance basis · D duration basis ·
E active TSS null · F rest TSS zero · G unit system · H i18n ·
I error+retry · J old training route intact

---

## Static Scan

| Pattern | Count |
|---|---|
| `/training/v2/week` in TrainingPlanV2 | 1 |
| `/training/plan` | 0 |
| `/training/week-plan` | 0 |
| `/training/full-cycle` | 0 |
| `/training/metrics` | 0 |
| `/training/refresh` | 0 |
| `estimated_tss \|\| 0` | 0 |
| `distance_km \|\| 0` | 0 |
| `duration_minutes \|\| 0` | 0 |
| forced `" km"` display | 0 |
| unknown TSS placeholder | 0 |
| hardcoded user-facing FR/EN labels | 0 |

---

## Contract V2 Compliance

| Rule | Status |
|---|---|
| UNKNOWN != ZERO | ✅ null fields are not displayed, not coerced |
| TSS null → no badge | ✅ |
| TSS 0 → badge shown | ✅ |
| distance null → no "0 km" | ✅ |
| duration null → no "0 min" | ✅ |
| formatDistance for all distances | ✅ |
| UnitContext respected | ✅ |
| Paywall for free users | ✅ |
| No future cycle | ✅ (current week only) |
| No debug text in UI | ✅ |

---

## PRE_MERGE_RUNTIME

`NOT EXECUTABLE IN CURRENT ENVIRONMENT`

## POST_MERGE_EMERGENT_RUNTIME_REQUIRED

`YES`

Validate after merge:
- `/training` → old screen intact
- `/training-v2` → new V2 screen loads
- Goal, week state, sessions render correctly
- Units respected (metric / imperial)
- No artificial zeros
- No TSS placeholder on active sessions
- Translations correct
- No blocking console errors
- Mobile no overflow

---

## New Debt

`NONE`

---

## Verdict

**READY FOR MERGE INTO copilot/dev**
