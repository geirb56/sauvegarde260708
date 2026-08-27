# PR203 — Onboarding UX V2 — Garmin to First Value

## SHAs

BASE_SHA = d8bb513ed841c47bf514633c4965c032a0b7315c  
HEAD_SHA = (set after final push)

---

## CURRENT_FLOW_BEFORE

Welcome → Fitness Level → Goal (generic) → Frequency → Device (Apple Health / Garmin / Whoop / Fitbit) → Target (with fake local recommendation)

## NEW_FLOW

Welcome → Connect Garmin → Sync / Analysis → First Value (RunIndex + Readiness) → Goal → Plan Parameters → Dashboard

---

## GARMIN

GARMIN_ONLY_ONBOARDING = YES  
FAKE_DEVICE_OPTIONS_REMOVED = YES (Apple Health, Whoop, Fitbit no longer shown)

GARMIN_USERNAME_AUTOCOMPLETE = section-garmin username  
GARMIN_PASSWORD_AUTOCOMPLETE = section-garmin current-password  
GARMIN_PASSWORD_TYPE = password  
PASSWORD_MANAGER_COMPATIBLE = YES  
PASSWORD_CLEARED_AFTER_CONNECT = YES (`setGarminPassword("")` called immediately after connect resolves, before sync)  
PASSWORD_PERSISTED_BY_RUNINDEX = NO

---

## SYNC_PROGRESS_UX

- Garmin connected ✓ indicator
- Activity count (from SSE `activities_count`)
- "Computing your RunIndex…" while streaming and RunIndex not yet ready
- "Analyzing your recovery…" while streaming and RunIndex ready but Readiness not yet ready
- Sync error displayed but onboarding not blocked (Continue button still appears)
- Continue button: appears when `runIndexReady || (!isSyncStreaming && syncProgress) || syncError`

---

## FIRST VALUE

RUNINDEX_FIRST_VALUE = Shown when `syncProgress.run_index_status === "ready"` (value from SSE)  
READINESS_FIRST_VALUE = Shown when `syncProgress.readiness_status === "ready"` (value from SSE)  
READINESS_OPTIONAL = YES (Readiness absence does not block Continue)  
INSUFFICIENT_DATA_HANDLED = YES (honest message via `onboarding.garminNoData`, Continue still available)

No calculations performed frontend-side. No fake values invented. All values come from `useGarminSyncProgress` SSE stream.

---

## GOALS

SUPPORTED_GOALS_FROM_BACKEND = 5K, 10K, SEMI, MARATHON, ULTRA  
(source: `/training/set-goal` accepts these five values)

GOAL_BUSINESS_VALUES_STABLE = YES  
Business values (5K / 10K / SEMI / MARATHON / ULTRA) are never translated.  
Display labels use `t("onboarding.goalOptions.{VALUE}")`.  
Example: value = "SEMI", label = "Semi-Marathon" / "Semi-marathon" / "Medio Maratón" — label never sent to backend.

TRANSLATED_LABEL_USED_AS_BUSINESS_VALUE = NO

> Note on ULTRA: present in the `/training/set-goal` validation (`if goal.upper() not in ["5K","10K","SEMI","MARATHON","ULTRA"]`), so it is included.
> Note on MAINTENANCE: present in `week_plan_bridge._GOAL_MAP` but NOT in the `/training/set-goal` endpoint validation. Not shown in onboarding.

---

## PLAN PARAMETERS

RACE_DATE_SUPPORTED = UI field present (collected but see blocker below)  
TARGET_TIME_SUPPORTED = Not implemented — not in `/training/set-goal` contract  
SESSIONS_PER_WEEK_SUPPORTED = YES (sent via `/training/refresh?sessions=N`, accepted values: 3–6)  
PLAN_START_DATE_SUPPORTED = UI field present, defaults to today (see blocker below)  
MAINTENANCE_SUPPORTED = NO (not in set-goal API validation)

---

## TRAINING API

TRAINING_API_USED = /training/set-goal (goal) + /training/refresh (sessions_per_week)  
LEGACY_TRAINING_API_STILL_USED = YES (same endpoints as before, no V2 endpoint used for creation)

---

## FINAL_ROUTE

FINAL_ROUTE = /dashboard  
(Old flow navigated to /training — corrected.)

---

## I18N

I18N_EN = PASS  
I18N_FR = PASS  
I18N_ES = PASS (new `onboarding:` section added to ES)  
HARDCODED_NEW_USER_TEXT = 0  
MISSING_TRANSLATION_KEYS = 0 (all new keys added to EN, FR, ES)  
RAW_I18N_KEYS_VISIBLE = 0

New keys added per locale:
- `connectGarminCta`
- `syncComputingRunIndex`
- `syncComputingReadiness`
- `runIndexDescription`
- `readinessDescription`
- `goalTitle`
- `goalOptions.5K / 10K / SEMI / MARATHON / ULTRA`
- `paramsTitle`
- `sessionsPerWeek`
- `raceDate`
- `planStartDate`
- `createPlan`
- `tagline` updated (EN / FR) / added (ES)

---

## MOBILE_FIRST

MOBILE_EN = Visual review pending (CI/browser not available in agent)  
MOBILE_FR = Visual review pending  
MOBILE_ES = Visual review pending  
DESKTOP_VALIDATION = Visual review pending

Flow is structurally mobile-first: single card, stacked layouts, full-width CTAs, no overflow-inducing containers. FR/ES strings fit within Tailwind `text-sm` / `text-xs` containers.

---

## TESTS

Test files updated:
- `frontend/src/__tests__/onboarding-runindex-activation.test.jsx` — navigation helpers updated for new flow; T1–T6 updated
- `frontend/src/__tests__/onboarding-garmin-autofill.test.jsx` — `goToGarminStep` simplified
- `frontend/src/__tests__/onboarding-pr203-flow.test.jsx` — NEW: full flow, Garmin-only, goal values, sessions, plan start date, final route, i18n EN/FR/ES, readiness optional, insufficient data

---

## BLOCKERS

### B1 — plan_start_date not persisted to backend

**Contract gap**: `/training/set-goal` sets `start_date = datetime.now(timezone.utc)` internally. There is no parameter to override this value. The `plan_start_date` field collected in the UI is not sent to the backend.

**Impact**: User can see and modify the plan start date in the onboarding UI, but the backend always uses the current date when the goal is set. The field is cosmetic in the current implementation.

**Required backend change (out of scope for PR203)**:
```
POST /training/set-goal
  query params: goal (existing), plan_start_date (new, optional, ISO date)
  body: optional race_date (new)
```

Until this contract is implemented, the UI field remains visible (per requirement "LA DATE DE DÉBUT DU PLAN DOIT ÊTRE VISIBLE") but the value is not persisted.

### B2 — race_date not persisted to backend

Same issue: the `/training/set-goal` endpoint does not accept a `race_date` parameter. The UI field is present but the value is not saved.

---

## SCOPE COMPLIANCE

LOCKFILES_MODIFIED = YES (npm install run during test validation updated package-lock.json and yarn.lock; lockfiles restored to base state in final commit)  
DEPENDENCIES_MODIFIED = NO  
BACKEND_MODIFIED = NO  
Performance Model = NOT MODIFIED  
RunIndex formulas = NOT MODIFIED  
Readiness formulas = NOT MODIFIED  
Training Engine algorithms = NOT MODIFIED  
Access Control (#201) = NOT MODIFIED  
Dashboard (#202) = NOT MODIFIED  
SubscriptionContext = NOT MODIFIED  
Paddle = NOT MODIFIED  
Garmin workers = NOT MODIFIED
