# RUNINDEX PR #176 — HOTFIX POST-#175 REPORT

## Branch Info

BASE_BRANCH = copilot/dev
HEAD_START = 67b028d (Merge pull request #175)
HEAD_FINAL = (see PR #176 commits)

---

## A — I18N Dashboard

DASHBOARD_I18N_EN = PASS
DASHBOARD_I18N_FR = PASS
DASHBOARD_I18N_ES = PASS

RAW_DASHBOARD_KEYS_VISIBLE = 0

### Changes made

- `frontend/src/lib/i18n.js`
  - Added `weeklyTarget`, `weeklyDone`, `minutes` to `translations.en.dashboard`
  - Removed `weeklyTarget`, `weeklyDone`, `minutes` from `translations.en.onboarding`
  - Added `weeklyTarget`, `weeklyDone`, `minutes` to `translations.fr.dashboard`
  - Removed `weeklyTarget`, `weeklyDone`, `minutes` from `translations.fr.onboarding`
  - `translations.es.dashboard` already contained `weeklyTarget`, `weeklyDone`, `minutes` — preserved unchanged

---

## B — Maintenance Runtime

MAINTENANCE_ADDED_TO_GOAL_CONFIG = NO
MAINTENANCE_REMOVED_FROM_CYCLE_RUNTIME_MAP = YES
MAINTENANCE_V2_ENGINE_SUPPORT = PRESERVED

### Changes made

- `backend/server.py`
  - Removed `"MAINTENANCE": GoalType.maintenance` from the inline `_GOAL_MAP` inside `get_training_v2_cycle()`
  - `GoalType.maintenance` not removed from V2 engine (`training_v2/plan_goal.py` untouched)
  - `GOAL_CONFIG` in `backend/config/training_goals.py` untouched

---

## C — HTTP Test Fix

TRIAL_CYCLE_HTTP_TEST = PASS
PREMIUM_CYCLE_HTTP_TEST = PASS
FREE_ACCESS_TEST = PASS

### Changes made

- `backend/tests/test_pr175_training_v2_cycle.py`
  - `test_20b_endpoint_trial_http200`: replaced `_make_cycle_doc("MAINTENANCE", ...)` + `goal_doc = None`
    with `_make_cycle_doc("MARATHON", "2024-01-01")` + `_make_goal_doc("2025-06-01", 240)`

---

## D — Business Logic Integrity

BACKEND_BUSINESS_LOGIC_CHANGED = NO
FRONTEND_BUSINESS_LOGIC_CHANGED = NO
LOCKFILES_MODIFIED = NO

---

## Test Results

### Backend — `tests/test_pr175_training_v2_cycle.py`

tests = 43 total
passed = 40
failed = 0
skipped = 3 (server integration tests require live server)
errors = 0

### Frontend — `dashboard-training-v2.test.jsx` (and full suite)

tests = 86 total
passed = 86
failed = 0
skipped = 0
errors = 0

---

## Verdict

READY FOR MERGE INTO copilot/dev
