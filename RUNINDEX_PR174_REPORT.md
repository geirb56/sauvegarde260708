# RUNINDEX PR #174 — DASHBOARD TRAINING V2 REPORT

BASE_BRANCH = copilot/dev
HEAD_START = 3c1e60503b7ee6eafd146896b68b0a57fadbfdd2
HEAD_FINAL = (see final commit after merge)

FILES_CHANGED =
- frontend/src/pages/Dashboard.jsx
- frontend/src/__tests__/dashboard-training-v2.test.jsx (new)
- frontend/src/__tests__/dashboard-run-readiness-null.test.jsx (mock compat update)
- frontend/src/lib/i18n.js (i18n correction)
- RUNINDEX_PR174_REPORT.md (new)

FILES_CHANGED_COUNT = 4

BACKEND_MODIFIED = NO
LOCKFILES_MODIFIED = NO

---

## I18N Correction

I18N_KEYS_ADDED_EN = YES
I18N_KEYS_ADDED_FR = YES
I18N_KEYS_ADDED_ES = YES
T_SECOND_ARGUMENT = 0
RAW_DASHBOARD_I18N_KEYS_VISIBLE = 0
BACKEND_MODIFIED = NO
LOCKFILES_MODIFIED = NO

Keys added to translations.en.dashboard, translations.fr.dashboard, translations.es.dashboard:
- weeklyTarget: "Weekly target" / "Cible hebdomadaire" / "Objetivo semanal"
- weeklyDone: "completed" / "réalisé" / "realizado"
- minutes: "min" / "min" / "min"

Dashboard.jsx t() calls corrected (second fallback argument removed):
- t("dashboard.weeklyTarget")
- t("dashboard.weeklyDone")
- t("dashboard.minutes")

---

## Dashboard Authority Migration

DASHBOARD_WEEK_AUTHORITY =
/api/training/v2/week
→ fetched for TRIAL/PREMIUM only (isFree === false, subLoading === false)
→ state: trainingWeekV2
→ displayed via dedicated weekly-target-card section

DASHBOARD_TODAY_AUTHORITY =
/api/training/today
→ unchanged authority for today's session
→ SessionCard continues to render planned_session / adaptive_session from this endpoint

---

## Legacy Removal

LEGACY_WEEKLY_TARGET_FORMULA =
REMOVED
→ `trainingMetrics?.load_28 ? Math.round(trainingMetrics.load_28 / 4 * 1.1) : 80` deleted

FALLBACK_80_KM =
REMOVED
→ `: 80` default deleted along with load_28 formula

TRAINING_METRICS_DASHBOARD_CALL =
REMOVED
→ `GET /training/metrics` removed from fetchData Promise.all
→ `trainingMetrics` state removed
→ Scan confirmed: no other consumer of trainingMetrics remained in Dashboard

---

## Subscription Gate

FREE_V2_WEEK_FETCH = 0
→ useSubscription().isFree guard in useEffect prevents fetch entirely
→ trainingWeekV2 remains null for FREE users
→ weekly-target-card section does not render for FREE users (no fallback shown)

---

## TSS Fix

NONE_TO_ZERO_TSS = 0
→ SessionCard: `session.estimated_tss || 0` replaced with `session.estimated_tss != null` guard
→ null/undefined → no TSS badge rendered
→ 0 → "0 TSS" badge rendered (valid zero preserved)

---

## Weekly Target Display

distance basis (target_basis === "distance"):
- weekly_target.target_km displayed via formatDistance(wt.target_km, { unitSystem })
- realised volume from insight.week.volume_km via formatDistance
- progress bar = volume_km / target_km (no artificial conversion)

duration basis (target_basis === "duration"):
- target_duration_minutes displayed as "{N} min"
- NO km conversion
- NO fake progress bar (volume_km in minutes not available → UNKNOWN ≠ ZERO)

---

## Unit System

→ formatDistance imported from @/utils/units
→ { unitSystem } from useUnitSystem() passed to each formatDistance call
→ metric → km, imperial → mi (via existing convertDistance logic)

---

## Static Scan Results

training/metrics in Dashboard.jsx → 0 occurrences
load_28 / 4 → 0 occurrences
* 1.1 for target → 0 occurrences
fallback 80 (`: 80`) → 0 occurrences
estimated_tss || 0 → 0 occurrences
training/v2/week → present only inside TRIAL/PREMIUM useEffect guard

---

## Tests

tests = passed / 0 failed / 0 skipped / 0 errors

New test file: frontend/src/__tests__/dashboard-training-v2.test.jsx
16 tests covering all required scenarios:

1.  TRIAL/PREMIUM: /training/v2/week called ✓
2.  FREE: /training/v2/week never called ✓
3.  /training/metrics: 0 calls ✓
4.  distance basis: weekly_target.target_km used ✓
5.  no load_28/4*1.1 formula (source check) ✓
6.  no fallback 80 km (source check) ✓
7a. duration basis: target_duration_minutes shown, no fake km ✓
7b. duration basis: no fake progress bar ✓
8.  Today session source: /training/today ✓
9.  estimated_tss=null: no "0 TSS" ✓
10. estimated_tss=0: "0 TSS" rendered ✓
11a. metric: km via UnitContext ✓
11b. imperial: miles via UnitContext ✓
12. no extra legacy endpoints ✓
13. i18n dashboard keys exist in EN ✓
14. i18n dashboard keys exist in FR ✓
15. i18n dashboard keys exist in ES ✓
16. no raw dashboard i18n keys rendered ✓

---

## Verdict

READY FOR MERGE INTO copilot/dev

Conditions met:
- [x] base copilot/dev real post-#173
- [x] Dashboard FREE remains functional (no v2/week call, weekly-target section hidden)
- [x] V2 week fetch only for TRIAL/PREMIUM
- [x] weekly target = weekly_target from V2 authority
- [x] no fallback 80 km
- [x] no load_28 × 1.1 calculation
- [x] Today remains authority for today's session
- [x] null TSS remains null (no "0 TSS")
- [x] units correct via UnitContext/formatDistance
- [x] no backend changes
- [x] no lockfile changes
- [x] 0 tests failed

DO NOT MERGE AUTOMATICALLY.
DO NOT BEGIN #175.
