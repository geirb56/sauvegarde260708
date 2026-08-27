BASE_SHA = 1b327cdc5662f8b334aae9620afbbd94d3fcebc2
HEAD_SHA = TO_UPDATE_AFTER_CORRECTION

SETTINGS_CONTRACT_AUDIT =

| Setting | READ_SUPPORTED | WRITE_SUPPORTED | ENDPOINT | CURRENT_UI |
| --- | --- | --- | --- | --- |
| PROFILE | YES (email, verification only) | NO | `GET /api/auth/me` | Now shown read-only in Account section |
| TRAINING_GOAL | YES | YES | `GET /api/training/v2/cycle`, `POST /api/training/set-goal?goal=` | Goal buttons limited to 5K / 10K / SEMI / MARATHON / ULTRA / MAINTENANCE |
| SESSIONS_PER_WEEK | YES | YES | `GET /api/training/v2/week` (`weekly_target.session_count`), `POST /api/training/refresh?sessions=` | Buttons limited to 3 / 4 / 5 / 6; `/training/full-cycle` removed from Settings |
| PLAN_START_DATE | YES | NO | `GET /api/training/v2/cycle` | Read-only value with explicit backend limitation |
| RACE_DATE | YES | YES for race goals | `GET /api/user/goal`, `POST /api/user/goal` | Editable only inside race-goal section |
| TARGET_TIME | YES | YES for race goals | `GET /api/user/goal`, `POST /api/user/goal` | Optional field in race-goal section |
| LANGUAGE | YES (frontend local setting) | YES (frontend local setting) | `LanguageContext`, localStorage | EN / FR / ES selector updates UI immediately |
| GARMIN | YES | YES | `GET /api/garmin/status`, `POST /api/garmin/connect`, `POST /api/garmin/sync`, `POST /api/garmin/disconnect` | Real connection status, last sync, reconnect/sync/disconnect actions |
| SUBSCRIPTION | YES | Existing management only | `SubscriptionContext`, `GET /api/subscription/info`, `/subscription` page | Real FREE / TRIAL / PREMIUM status + CTA to existing management page |
| UNITS | YES (frontend local setting) | YES (frontend local setting) | `UnitContext`, localStorage | Kept under Preferences as a real existing setting |

PROFILE =
READ: email + email verification via `/api/auth/me`
WRITE: not supported

TRAINING_GOAL =
READ: `/api/training/v2/cycle`
WRITE: `/api/training/set-goal?goal=`
SUPPORTED: 5K, 10K, SEMI, MARATHON, ULTRA, MAINTENANCE

SESSIONS_PER_WEEK =
READ: `/api/training/v2/week` → `weekly_target.session_count`
WRITE: `/api/training/refresh?sessions=`
SUPPORTED: 3, 4, 5, 6

PLAN_START_DATE =
READ ONLY via `/api/training/v2/cycle`
EDIT_SUPPORTED = NO
PLAN_START_DATE_WRITE_SUPPORTED = NO
BACKEND_GAP = No existing backend endpoint updates `training_cycles.start_date` directly. Current writes found in audit only set `start_date` implicitly inside `POST /api/training/set-goal` (`backend/server.py:3458-3464`). Training V2 consumers read the date from `training_cycles.start_date` in `GET /api/training/v2/week` (`backend/server.py:4654-4712`) and `GET /api/training/v2/cycle` (`backend/server.py:4816-4926`), but no dedicated schema, validation path, or recalculation workflow exists for a standalone user edit of plan start date.

RACE_DATE =
READ: `/api/user/goal`
WRITE: `/api/user/goal`
VISIBLE ONLY FOR RACE GOALS = YES

TARGET_TIME =
READ: `/api/user/goal`
WRITE: `/api/user/goal`
VISIBLE ONLY FOR RACE GOALS = YES

LANGUAGE =
EN / FR / ES via existing frontend i18n mechanism
IMMEDIATE_UI_UPDATE = YES

GARMIN =
STATUS = real `/api/garmin/status`
LAST_SYNC = shown when available
ACTIONS = connect / reconnect / sync / disconnect using existing workflows

SUBSCRIPTION =
SOURCE = `SubscriptionContext`
STATUS = FREE / TRIAL / PREMIUM
MANAGEMENT = existing `/subscription` page

GOALS_6_VISIBLE = PASS
MAINTENANCE_UI = PASS

GARMIN_PASSWORD_EXPOSED = NO
GARMIN_AUTOFILL_COMPATIBLE = YES

I18N_EN = PASS
I18N_FR = PASS
I18N_ES = PASS

MOBILE_390 = PASS
DESKTOP = PASS

BACKEND_MODIFIED = NO
LOCKFILES_MODIFIED = NO
DEPENDENCIES_MODIFIED = NO

TESTS =
- `frontend: npm test -- --watchAll=false --runInBand --runTestsByPath src/__tests__/settings-page.test.jsx src/__tests__/onboarding-garmin-autofill.test.jsx src/lib/i18n.test.js` = PASS
- `frontend: yarn build` = PASS

CORRECTION_C208 =
- Removed Settings dependency on `GET /api/training/full-cycle`
- Settings now loads:
  - training goal from `GET /api/training/v2/cycle`
  - sessions per week from `GET /api/training/v2/week` → `weekly_target.session_count`
  - plan start date from `GET /api/training/v2/cycle`
  - cycle status from `GET /api/training/v2/cycle`
- Added regression proof that Settings does not call `/api/training/full-cycle`

BLOCKERS =
- Plan start date write support is absent in the current backend contract
