WEEK_SOURCE_BEFORE = db.workouts
WEEK_SOURCE_AFTER = DomainActivity

MONTH_SOURCE_BEFORE = db.workouts
MONTH_SOURCE_AFTER = DomainActivity

RECOVERY_LEGACY_VISIBLE = NO

READINESS_AUTHORITY = V2
RUNINDEX_AUTHORITY = DomainActivity
TRAINING_TODAY_AUTHORITY = V2
WEEKLY_TARGET_AUTHORITY = V2
WEEKLY_ACTUAL_AUTHORITY = DomainActivity

DISTANCE_PROGRESS = PASS
DURATION_PROGRESS = PASS

UNKNOWN_READINESS_GRAY = PASS
NULL_METRIC_DASH = PASS
NO_RUN_HARD_FALLBACK = PASS

DASHBOARD_VISIBLE_DB_WORKOUTS_DEPENDENCY = NO

RUNINDEX_FORMULA_CHANGED = NO
READINESS_ENGINE_CHANGED = NO
TRAINING_ENGINE_CHANGED = NO
PROGRESS_PAGE_CHANGED = NO
COACH_CHANGED = NO
LOCKFILES_CHANGED = NO

tests =
passed:
- backend: `python -m pytest -q tests/test_dashboard_insight_pr182.py tests/test_cache_stale_runindex_pr181.py` → 8 passed
- frontend: `CI=true npm test -- --runInBand --watch=false src/__tests__/dashboard-training-v2.test.jsx src/__tests__/dashboard-run-readiness-v2.test.jsx src/__tests__/dashboard-run-readiness-null.test.jsx` → 57 passed
- runtime smoke: `/api/dashboard/insight`, `/api/run-index`, `/api/training/today`, `/api/training/v2/week` → 200
failed: 0
skipped: 0
errors: 0
