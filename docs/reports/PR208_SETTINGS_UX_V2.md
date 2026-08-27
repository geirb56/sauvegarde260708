BASE_SHA = 1b327cdc5662f8b334aae9620afbbd94d3fcebc2
HEAD_SHA = TO_UPDATE

SETTINGS_CONTRACT_AUDIT =

| Setting | READ_SUPPORTED | WRITE_SUPPORTED | ENDPOINT | CURRENT_UI |
| --- | --- | --- | --- | --- |
| PROFILE | YES (email, verification only) | NO | `GET /api/auth/me` | Now shown read-only in Account section |
| TRAINING_GOAL | YES | YES | `GET /api/training/v2/cycle`, `POST /api/training/set-goal?goal=` | Goal buttons limited to 5K / 10K / SEMI / MARATHON / ULTRA / MAINTENANCE |
| SESSIONS_PER_WEEK | YES | YES | `GET /api/training/full-cycle`, `POST /api/training/refresh?sessions=` | Buttons limited to 3 / 4 / 5 / 6 |
| PLAN_START_DATE | YES | NO | `GET /api/training/v2/cycle`, `GET /api/training/full-cycle` | Read-only value with explicit backend limitation |
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
READ: `/api/training/full-cycle`
WRITE: `/api/training/refresh?sessions=`
SUPPORTED: 3, 4, 5, 6

PLAN_START_DATE =
READ ONLY via `/api/training/v2/cycle`
EDIT_SUPPORTED = NO

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

BLOCKERS =
- NONE
