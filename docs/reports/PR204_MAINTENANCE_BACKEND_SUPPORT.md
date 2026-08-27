# PR204 — Training Goal MAINTENANCE Backend Support

## Identifiers

```
BASE_SHA = d8bb513ed841c47bf514633c4965c032a0b7315c
OLD_HEAD  = c23cfe88733edc342c989130f1bd9d8abb0a475a
NEW_HEAD  = dfecee8861661ff2db7fb8914febcafac2efbd5e
```

---

## GOAL_CONFIG Consumer Audit

```
GOAL_CONFIG_CONSUMERS =
  GET /training/goals            — iterates GOAL_CONFIG for display listing (long_run_ratio, intensity_pct, cycle_weeks, description)
  GET /training/week-plan        — reads GOAL_CONFIG[goal]["cycle_weeks"] for legacy plan context
  GET /training/v2/week          — uses `goal_type not in GOAL_CONFIG` as gate-check only
  GET /training/v2/cycle         — uses `goal_type_raw not in GOAL_CONFIG` as gate-check only
  POST /training-plan/set-goal   — reads GOAL_CONFIG[goal]["cycle_weeks"] + description in response
  generate_dynamic_training_plan — reads GOAL_CONFIG.get(goal)["cycle_weeks"] for standard_weeks
```

```
MAINTENANCE_LONG_RUN_RATIO_CONSUMERS =
  GET /training/goals ONLY (display listing)
  — NOT consumed by V2 plan generation, NOT consumed by week bridge, NOT consumed by periodization

MAINTENANCE_INTENSITY_PCT_CONSUMERS =
  GET /training/goals ONLY (display listing)
  — line 4378 reads phase_info.get("intensity_pct") from training_engine.get_phase_description,
    NOT from GOAL_CONFIG

MAINTENANCE_CYCLE_WEEKS_CONSUMERS =
  GET /training/week-plan (legacy plan context)
  POST /training-plan/set-goal (response field)
  generate_dynamic_training_plan (standard_weeks fallback)
```

---

## BLOCKER A — GOAL_CONFIG Resolution

```
MAINTENANCE_GOAL_CONFIG_REQUIRED = YES
  (gate-check: `goal not in GOAL_CONFIG` in 4 endpoints)

MAINTENANCE_CYCLE_WEEKS_SOURCE = periodization.py:135 CONTINUOUS_CYCLE_LENGTH_WEEKS=12
                                  + coach_service.py:314 GOAL_METADATA["MAINTENANCE"]["base_weeks"]=12
MAINTENANCE_CYCLE_WEEKS = 12

MAINTENANCE_LONG_RUN_RATIO_REQUIRED = NO
  long_run_ratio is consumed only by GET /training/goals (display).
  No canonical MAINTENANCE-specific ratio exists in this codebase.
MAINTENANCE_LONG_RUN_RATIO = None
CANONICAL_MAINTENANCE_LONG_RUN_RATIO_SOURCE = N/A — field not applicable to MAINTENANCE

MAINTENANCE_INTENSITY_PCT_REQUIRED = NO
  intensity_pct is consumed only by GET /training/goals (display).
  The V2 engine and periodization do not read this field for MAINTENANCE.
  No canonical MAINTENANCE-specific intensity exists in this codebase.
MAINTENANCE_INTENSITY_PCT = None
CANONICAL_MAINTENANCE_INTENSITY_SOURCE = N/A — field not applicable to MAINTENANCE

VALUES_INVENTED = NO
```

Solution: `long_run_ratio=None` and `intensity_pct=None` in GOAL_CONFIG["MAINTENANCE"].
`GET /training/goals` updated to omit fields that are `None` from the per-goal response object.
Race goals (5K/10K/SEMI/MARATHON/ULTRA) are unchanged.

---

## BLOCKER B — Real Handler Tests

### set-goal

```
REAL_SET_GOAL_HANDLER_EXECUTED = YES
MAINTENANCE_SET_GOAL_RESULT    = PASS
MAINTENANCE_PERSISTED_GOAL     = MAINTENANCE
MAINTENANCE_PERSISTED_START_DATE = TODAY
MAINTENANCE_RACE_DATE_CREATED  = NO
MAINTENANCE_TARGET_TIME_CREATED = NO

Tests (test_pr204_maintenance_endpoint.py — httpx.AsyncClient + ASGITransport):
  test_set_goal_maintenance_http_success          → HTTP 200
  test_set_goal_maintenance_response_valid        → goal=MAINTENANCE, status=updated, no "Invalid goal"
  test_set_goal_maintenance_cycle_persisted       → training_cycles upserted with goal=MAINTENANCE
  test_set_goal_maintenance_start_date_persisted  → start_date = today (UTC, within call window)
  test_set_goal_maintenance_no_race_date_created  → race_date=None, target_time=None in persisted doc
  test_set_goal_invalid_value_rejected            → INVALID still returns error
```

### refresh

```
REAL_REFRESH_HANDLER_EXECUTED = YES

MAINTENANCE_REFRESH_REAL_HANDLER_3 = PASS
MAINTENANCE_REFRESH_REAL_HANDLER_4 = PASS
MAINTENANCE_REFRESH_REAL_HANDLER_5 = PASS
MAINTENANCE_REFRESH_REAL_HANDLER_6 = PASS

SESSIONS_CONTRACT        = sessions_override parameter passed to generate_dynamic_training_plan
SESSIONS_PERSISTED       = YES (sessions_per_week stored in training_prefs for sessions in [3,4,5,6])
SESSIONS_PASSED_TO_GENERATOR = sessions_override=sessions_value (verified via mock call_args)

Tests (test_pr204_maintenance_endpoint.py — real FastAPI handler):
  test_refresh_maintenance_sessions[3/4/5/6]                    → HTTP 200, no crash, goal=MAINTENANCE in response
  test_refresh_maintenance_sessions_stored[3/4/5/6]             → sessions_per_week stored in training_prefs
  test_refresh_maintenance_sessions_passed_to_generator[3/4/5/6]→ generator called with sessions_override=N
  test_refresh_maintenance_plan_returned                         → plan payload returned verbatim
```

---

## MAINTENANCE Behavior

```
MAINTENANCE_WEEK_GENERATION = YES (build_weekly_plan_from_workouts)
MAINTENANCE_CYCLE_MODE      = continuous (12-week cycling)
MAINTENANCE_TAPER           = NO (GoalType.maintenance not in _RACE_GOALS)
MAINTENANCE_RACE_WEEK       = NO (GoalType.maintenance not in _RACE_GOALS)
```

---

## Regression — Race Goals

```
REGRESSION_5K       = PASS
REGRESSION_10K      = PASS
REGRESSION_SEMI     = PASS
REGRESSION_MARATHON = PASS
REGRESSION_ULTRA    = PASS
```

---

## Files Changed

```
BACKEND_FILES_CHANGED =
  backend/config/training_goals.py           — long_run_ratio=None, intensity_pct=None for MAINTENANCE
  backend/server.py                          — /training/goals handler omits None fields;
                                               set-goal whitelists; _GOAL_MAP; race_date guard
  backend/training_v2/week_plan_bridge.py    — race_date guard for MAINTENANCE
  backend/tests/test_pr204_maintenance_backend.py  — unit/contract + REAL handler tests (43 passed, 1 skipped)
  backend/tests/test_pr204_maintenance_endpoint.py — ASGI endpoint integration tests
  docs/reports/PR204_MAINTENANCE_BACKEND_SUPPORT.md

REAL HANDLER TESTS (in test_pr204_maintenance_backend.py):
  test_real_handler_set_goal_maintenance_pass  — REAL_SET_GOAL_HANDLER_EXECUTED = YES
  test_real_handler_set_goal_invalid_rejected  — non-regression
  test_real_handler_refresh_maintenance[3]     — MAINTENANCE_REFRESH_REAL_HANDLER_3 = PASS
  test_real_handler_refresh_maintenance[4]     — MAINTENANCE_REFRESH_REAL_HANDLER_4 = PASS
  test_real_handler_refresh_maintenance[5]     — MAINTENANCE_REFRESH_REAL_HANDLER_5 = PASS
  test_real_handler_refresh_maintenance[6]     — MAINTENANCE_REFRESH_REAL_HANDLER_6 = PASS

REAL_SET_GOAL_HANDLER_EXECUTED     = YES
MAINTENANCE_SET_GOAL_REAL_HANDLER  = PASS
MAINTENANCE_PERSISTED_GOAL         = MAINTENANCE
MAINTENANCE_START_DATE             = today (UTC datetime, verified in test)
MAINTENANCE_RACE_DATE_CREATED      = NO
MAINTENANCE_TARGET_TIME_CREATED    = NO

REAL_REFRESH_HANDLER_EXECUTED      = YES
MAINTENANCE_REFRESH_REAL_HANDLER_3 = PASS
MAINTENANCE_REFRESH_REAL_HANDLER_4 = PASS
MAINTENANCE_REFRESH_REAL_HANDLER_5 = PASS
MAINTENANCE_REFRESH_REAL_HANDLER_6 = PASS

SESSIONS_CONTRACT         = sessions passed via query param → handler stores + forwards
SESSIONS_PERSISTED        = sessions_per_week stored in training_prefs via upsert
SESSIONS_PASSED_TO_GENERATOR = sessions_override=N forwarded to generate_dynamic_training_plan

VALUES_INVENTED           = NO

REAL_HANDLER_TESTS        = 6 passed (set-goal + refresh 3/4/5/6)
UNIT_CONTRACT_TESTS       = 37 passed, 1 skipped
TRAINING_REGRESSION_TESTS = included in UNIT_CONTRACT_TESTS (5K/10K/SEMI/MARATHON/ULTRA)

FRONTEND_MODIFIED    = NO
LOCKFILES_MODIFIED   = NO
DEPENDENCIES_MODIFIED = NO

PR_TITLE   = PR204 — Training Goal MAINTENANCE Backend Support
PR_BODY_UPDATED = YES

BLOCKERS = NONE
```

---

## Test Results

```
PR204_UNIT_TESTS         = 43 passed, 1 skipped (ULTRA/no-race: pre-existing expected behavior)
  — includes 6 REAL HANDLER TESTS (set-goal + refresh 3/4/5/6)
TRAINING_REGRESSION_TESTS = PASS (5K/10K/SEMI/MARATHON/ULTRA)

Total: 43 passed, 1 skipped, 0 failed
```

---

## Blockers

```
BLOCKERS = NONE
```

---

## PR Status

```
PR204_READY_FOR_REVIEW = YES
```
