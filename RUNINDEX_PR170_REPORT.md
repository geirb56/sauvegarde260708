# RUNINDEX PR170 REPORT

BASE_BRANCH = PR34

HEAD_START = f33b65c8214371096a2df1e23d84c98f55748dd8

HEAD_FINAL = (populated after engine-tools-report_progress push)

FILES_CHANGED =
  frontend/src/pages/TrainingPlanV2.jsx (modified — subscription contract fix; extract chained expressions to helper functions to avoid babel-metadata-plugin stack overflow)
  frontend/src/__tests__/training-plan-v2.test.jsx (modified — subscription + TSS tests K/L/M/N + F/G)
  frontend/craco.config.js (modified — exclude babel-metadata-plugin during NODE_ENV=test to prevent infinite recursion)
  RUNINDEX_PR170_REPORT.md (updated)

LOCKFILES_MODIFIED = NO

BACKEND_MODIFIED = NO

TRAININGPLAN_LEGACY_MODIFIED = NO

API_CONSUMED = /api/training/v2/week

API_CONTRACT_SOURCE = backend/training_v2/training_week_response.py

REAL_RESPONSE_PATHS =
  goal
  state
  weekly_target
  week.sessions

INVENTED_RESPONSE_PATHS = NONE

LEGACY_API_CALLS = 0

NONE_TO_ZERO_COERCIONS = 0
  (estimated_tss null check: `session.estimated_tss != null` — never uses `|| 0`)
  (distance_km null check: `session.distance_km != null` — never uses `|| 0`)
  (duration_minutes null check: `session.duration_minutes != null` — never uses `|| 0`)

FORCED_KM = 0
  (formatDistance receives km directly, no multiplication by 1000)

UNKNOWN_TSS_PLACEHOLDER = 0
  (TSS rendered only when estimated_tss != null — no placeholder for unknown)

HARDCODED_USER_LABELS = 0
  (all user-facing text goes through t("trainingV2.*") or t("trainingPlanDays.*"))

---

## Subscription contract

SUBSCRIPTION_CONTRACT_SOURCE = frontend/src/context/SubscriptionContext.jsx

SUBSCRIPTION_STATUSES = free / trial / premium

SUBSCRIPTION_HELPERS_USED =
  isFree   (boolean — from subscription.status === "free")
  isTrial  (boolean — from subscription.status === "trial")
  isPremium (boolean — from subscription.status === "premium")
  loading  (boolean — true while fetching)

FAKE_ACTIVE_INACTIVE_STATUSES = 0
  (scan: status === "inactive" → 0 occurrences in TrainingPlanV2.jsx)
  (scan: status: "active" → 0 occurrences in test file)
  (scan: status: "inactive" → 0 occurrences in test file)

FREE_PAYWALL = PASS
  (isFree === true → <Paywall /> rendered, no Training V2 data shown — test K)

TRIAL_ACCESS = PASS
  (isTrial === true, isFree === false → TrainingPlanV2 accessible, no Paywall — test L)

PREMIUM_ACCESS = PASS
  (isPremium === true, isFree === false → TrainingPlanV2 accessible, no Paywall — test M)

LOADING_STATE = PASS
  (loading === true → skeleton shown, no false Paywall — test N)

---

## TSS contract

TSS_NULL_RENDERED = NO
  (estimated_tss === null → SessionCard renders no TSS element at all)
  (verified: "null TSS", "0 TSS", "— TSS", "N/A TSS" all absent — test F)

TSS_ZERO_PRESERVED = YES
  (estimated_tss === 0 → SessionCard renders "0 TSS")
  (verified: container.textContent contains "0 TSS" on rest card — test G)

---

## Scan results (static)

status === "inactive" in TrainingPlanV2 = 0
status: "active" in tests = 0
status: "inactive" in tests = 0
/training/plan calls from TrainingPlanV2 = 0
/training/week-plan calls = 0
/training/full-cycle calls = 0
/training/metrics calls = 0
/training/refresh calls = 0
estimated_tss || 0 = 0
distance_km || 0 = 0
duration_minutes || 0 = 0

---

tests:
  passed = 17
  failed = 0
  skipped = 0
  errors = 0

NOTE_DASHBOARD_FAILURES = pre-existing on PR34 base branch, not caused by PR170 changes

PRE_MERGE_RUNTIME = NOT EXECUTABLE IN CURRENT ENVIRONMENT

POST_MERGE_EMERGENT_RUNTIME_REQUIRED = YES

NEW_DEBT = NONE

CRACO_TEST_FIX =
  babel-metadata-plugin (visual-edits) caused infinite recursion in getArrayIterationContext
  when analyzing data.week.sessions.map(...) in TrainingPlanV2.jsx.
  Fix: isDevServer = process.env.NODE_ENV === "development" (was !== "production")
  Effect: plugin disabled during NODE_ENV=test; dev server behaviour unchanged.

---

## Contract compliance summary

### TrainingWeekV2Response paths consumed
| Field path                    | Component location          |
|-------------------------------|-----------------------------|
| data.goal                     | GoalBlock                   |
| data.goal.goal_type           | GoalBlock InfoRow           |
| data.goal.race_date           | GoalBlock InfoRow (if ≠ null) |
| data.goal.target_time_seconds | GoalBlock InfoRow (if ≠ null) |
| data.state                    | StateSectionBlock           |
| data.state.continuity_state   | StateSectionBlock InfoRow   |
| data.state.allow_intensity    | StateSectionBlock InfoRow   |
| data.weekly_target            | StateSectionBlock           |
| data.weekly_target.target_basis      | StateSectionBlock InfoRow |
| data.weekly_target.target_km         | StateSectionBlock (if ≠ null) |
| data.weekly_target.target_duration_minutes | StateSectionBlock (if ≠ null) |
| data.weekly_target.session_count     | StateSectionBlock InfoRow |
| data.weekly_target.confidence        | StateSectionBlock InfoRow |
| data.week.sessions            | SessionCard list            |
| session.day                   | SessionCard day label       |
| session.workout_type          | SessionCard badge label     |
| session.intensity_class       | SessionCard detail          |
| session.distance_km           | SessionCard (if ≠ null)     |
| session.duration_minutes      | SessionCard (if ≠ null)     |
| session.estimated_tss         | SessionCard (if ≠ null)     |

### Paths NOT accessed (per prohibition)
- data.week_state → undefined, never accessed
- data.sessions → undefined, never accessed
- data.target → undefined, never accessed
- data.plan → undefined, never accessed

### Test fixture (trainingWeekV2ApiFixture) structure
Exactly mirrors TrainingWeekV2Response:
- reference_date ✓
- goal { goal_type, race_date, target_time_seconds } ✓
- state { continuity_state, allow_intensity } ✓
- weekly_target { target_basis, target_km, target_duration_minutes, session_count, confidence } ✓
- week { planned_km, planned_duration_minutes, session_count, sessions[] } ✓

### None != Zero compliance
- `distance_km != null` check before rendering (not `|| 0`)
- `duration_minutes != null` check before rendering (not `|| 0`)
- `estimated_tss != null` check before rendering (not `|| 0`)
- estimated_tss = 0 renders as "0 TSS" (test G)
- estimated_tss = null renders nothing (test F)

---

VERDICT: READY FOR MERGE INTO PR34

CORRECTION_APPLIED =
  craco.config.js: babel-metadata-plugin now correctly excluded during NODE_ENV=test
  TrainingPlanV2.jsx: chained member expressions extracted into workoutTypeToLabelKey/intensityClassToLabelKey helpers
  All 17 tests pass: 0 failed, 0 skipped, 0 errors
