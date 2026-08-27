BASE_SHA = 7e197caf1c2d5713da0c4a4423df663b577ae2c5
HEAD_SHA = TBD_AFTER_FINAL_COMMIT

CURRENT_FLOW = Welcome → Fitness level → Goal lifestyle → Training frequency → Device choice (Apple/Garmin/Whoop/Fitbit) → Target + frontend recommendation → apply plan → /training (and Garmin panel CTA attempted /dashboard)
NEW_FLOW = Welcome → Connect Garmin → Sync / Analysis → First Value → Goal → Sessions per week → Dashboard

REGISTER_NEW_USER_TO_ONBOARDING = PASS
EXISTING_USER_NOT_FORCED_TO_ONBOARDING = PASS

GARMIN_ONLY_ONBOARDING = YES

GARMIN_USERNAME_AUTOCOMPLETE = PASS
GARMIN_PASSWORD_AUTOCOMPLETE = PASS
PASSWORD_MANAGER_COMPATIBLE = YES
PASSWORD_CLEARED_AFTER_CONNECT = YES
PASSWORD_PERSISTED_BY_RUNINDEX = NO

SYNC_PROGRESS_UX = Garmin connected row + imported activities + analysis/computing messages + background continuation note + sync error state
REAL_SYNC_PROGRESS_USED = YES

RUNINDEX_FIRST_VALUE = PASS
READINESS_FIRST_VALUE = PASS
READINESS_OPTIONAL = PASS
INSUFFICIENT_DATA_HANDLED = PASS

GOALS_CANONICAL =
5K / 10K / SEMI / MARATHON / ULTRA / MAINTENANCE

MAINTENANCE_ENABLED = YES

RACE_DATE_ONBOARDING = NO
PLAN_START_DATE_ONBOARDING = NO
PLAN_START_DATE_DEFAULT = TODAY
PLAN_START_DATE_EDIT_LATER_IN_SETTINGS = YES

SESSIONS_PER_WEEK = 3 / 4 / 5 / 6
TRAINING_API_USED = /api/training/set-goal then /api/training/refresh?sessions=N

FINAL_DASHBOARD_ROUTE = /

I18N_EN = PASS
I18N_FR = PASS
I18N_ES = PASS
MISSING_TRANSLATION_KEYS = 0
RAW_I18N_KEYS_VISIBLE = 0
NEW_HARDCODED_USER_TEXT = 0

MOBILE_390 = PASS
DESKTOP = PASS

FRONTEND_FILES_CHANGED =
- frontend/src/pages/Onboarding.jsx
- frontend/src/pages/Register.jsx
- frontend/src/lib/i18n.js
- frontend/src/__tests__/onboarding-garmin-autofill.test.jsx
- frontend/src/__tests__/onboarding-runindex-activation.test.jsx
- frontend/src/__tests__/auth-onboarding-routing.test.jsx

BACKEND_MODIFIED = NO
LOCKFILES_MODIFIED = NO
DEPENDENCIES_MODIFIED = NO

TESTS =
- npx craco test --watchAll=false --forceExit --runTestsByPath src/__tests__/onboarding-garmin-autofill.test.jsx src/__tests__/onboarding-runindex-activation.test.jsx src/__tests__/auth-onboarding-routing.test.jsx (PASS)

BLOCKERS = NONE
