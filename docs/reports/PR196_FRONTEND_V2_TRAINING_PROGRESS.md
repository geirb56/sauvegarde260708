BASE_HEAD = 6b37cd0029bd18ba2fc4c680f449f37579fcbf7c
FINAL_HEAD = 306708f083a8e0c02e3ba8c411fde3e795b38f7d

OLD_PROGRESS_VMA_SOURCE = /api/training/vma-history (legacy VMA→VO2 derived path)
OLD_VMA_ENDPOINT_REMOVED = YES
OLD_VMA_FRONTEND_REMOVED = YES

GARMIN_VO2MAX_CURRENT_SOURCE = /api/run-index -> metrics.vo2max_running (+vo2max_date, vo2max_running_precise optional)
GARMIN_VO2MAX_HISTORY_SOURCE = garmin_vo2max sparse collection (real Garmin points only)
GARMIN_VO2MAX_HISTORY_ENDPOINT = /api/garmin/vo2max-history?period=12m

TRAINING_TODAY_SOURCE = /api/training/today
TRAINING_PACES_SOURCE = /api/training/v2/paces
TRAINING_WEEK_SOURCE = /api/training/v2/week
TRAINING_CYCLE_SOURCE = /api/training/v2/cycle

VDOT_VISIBLE = NO
VMA_VISIBLE = NO
GARMIN_VO2MAX_VISIBLE = YES

RACE_PREDICTIONS_PRESERVED = YES

FILES_CHANGED =
- backend/api/garmin.py
- backend/tests/test_garmin_vo2max_history_endpoint.py
- frontend/src/pages/TrainingPlanV2.jsx
- frontend/src/pages/Progress.jsx
- frontend/src/lib/i18n.js
- frontend/src/__tests__/training-v2-page.test.jsx
- frontend/src/__tests__/progress-v2-migration.test.jsx

DIFF_STAT =
- backend/api/garmin.py | 58 lines
- backend/tests/test_garmin_vo2max_history_endpoint.py | 142 lines
- frontend/src/__tests__/progress-v2-migration.test.jsx | 223 lines
- frontend/src/__tests__/training-v2-page.test.jsx | 306 lines
- frontend/src/lib/i18n.js | 72 lines
- frontend/src/pages/Progress.jsx | 232 lines
- frontend/src/pages/TrainingPlanV2.jsx | 400 lines

TEST_COMMANDS =
- CI=true yarn test --watchAll=false --runInBand src/__tests__/training-v2-page.test.jsx src/__tests__/progress-v2-migration.test.jsx src/__tests__/progress-race-predictions-v2.test.jsx
- python -m pytest tests/test_garmin_vo2max_history_endpoint.py

TEST_RESULTS =
- Frontend targeted suites: PASS (3 suites, 44 tests)
- Backend VO2max history endpoint tests: PASS (2 tests)

MOBILE_VALIDATED = YES (section-order test + mobile-first card structure)
I18N_VALIDATED = YES (EN/FR/ES keys added and static tests updated)

RUNINDEX_FORMULA_CHANGED = NO
READINESS_FORMULA_CHANGED = NO
TRAINING_PACES_FORMULA_CHANGED = NO
RACE_PREDICTIONS_FORMULA_CHANGED = NO

PR196_READY_FOR_REVIEW = YES
BLOCKERS = NONE
