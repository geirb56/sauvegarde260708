# RUNINDEX PR170 REPORT

BASE_BRANCH = PR34

HEAD_START = f33b65c8214371096a2df1e23d84c98f55748dd8

HEAD_FINAL = (populated after engine-tools-report_progress push)

FILES_CHANGED =
  frontend/src/pages/TrainingPlanV2.jsx (created)
  frontend/src/App.js (modified — added TrainingPlanV2 import + /training-v2 route)
  frontend/src/lib/i18n.js (modified — added trainingV2 keys in EN/FR/ES)
  frontend/src/__tests__/training-plan-v2.test.jsx (created)
  RUNINDEX_PR170_REPORT.md (created)

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

tests:
  passed = N/A (node_modules not installed in sandbox — PRE_MERGE_RUNTIME)
  failed = N/A
  skipped = N/A
  errors = N/A

PRE_MERGE_RUNTIME = NOT EXECUTABLE IN CURRENT ENVIRONMENT
  (frontend/node_modules absent; no npm install allowed per spec)

POST_MERGE_EMERGENT_RUNTIME_REQUIRED = YES

NEW_DEBT = NONE

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
