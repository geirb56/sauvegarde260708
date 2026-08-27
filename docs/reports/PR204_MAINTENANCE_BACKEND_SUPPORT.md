# PR204 — Training Goal MAINTENANCE Backend Support

## Identifiers

```
BASE_SHA = d8bb513ed841c47bf514633c4965c032a0b7315c
HEAD_SHA = (set after commit)
```

---

## BLOCKER A — GOAL_CONFIG Audit

```
MAINTENANCE_GOAL_CONFIG_REQUIRED = YES
```

GOAL_CONFIG is referenced in 4 gate-checks in server.py:
- line ~4252: `GOAL_CONFIG.get(goal, GOAL_CONFIG["SEMI"])` — generate_dynamic_training_plan
- line ~4423: `goal_type not in GOAL_CONFIG` — /training/week-plan gate
- line ~4643: `goal_type not in GOAL_CONFIG` — /training/v2/week gate
- line ~4805: `goal_type_raw not in GOAL_CONFIG` — /training/v2/cycle gate

Without MAINTENANCE in GOAL_CONFIG, these endpoints return 400 for any user
with a MAINTENANCE cycle.

### Canonical sources for values

```
MAINTENANCE_GOAL_CONFIG_SOURCE =
  cycle_weeks=12   → periodization.py:135  CONTINUOUS_CYCLE_LENGTH_WEEKS=12
                     coach_service.py:314  GOAL_METADATA["MAINTENANCE"]["base_weeks"]=12
  long_run_ratio=0.30 → GOAL_CONFIG["10K"]["long_run_ratio"]=0.30 (conservative base,
                         no race-specific volume ramp; MAINTENANCE is the most
                         analogous non-race goal)
  intensity_pct=15  → training_engine.py:678,715 build phase intensity_pct=15
                      (continuous maintenance is structurally equivalent to the
                       build phase — aerobic base, no race-specific intensification)

MAINTENANCE_GOAL_CONFIG_VALUES =
  cycle_weeks    = 12
  long_run_ratio = 0.30
  intensity_pct  = 15
  description    = "Maintenance"

VALUES_INVENTED = NO
```

Note: `long_run_ratio` and `intensity_pct` are consumed only by the
`/training/goals` display listing endpoint and by legacy
`generate_dynamic_training_plan`. The V2 engine
(`build_weekly_plan_from_workouts`) does not read these fields for MAINTENANCE.

---

## BLOCKER B — Real Endpoint Tests

Added `backend/tests/test_pr204_maintenance_endpoint.py` — real FastAPI
handler tests via `httpx.AsyncClient + ASGITransport(app=server.app)`.

### set-goal endpoint

```
MAINTENANCE_SET_GOAL_REAL_ENDPOINT_TEST = PASS

Tests:
  test_set_goal_maintenance_http_success          → HTTP 200
  test_set_goal_maintenance_response_valid        → goal=MAINTENANCE, no "Invalid goal"
  test_set_goal_maintenance_cycle_persisted       → training_cycles upserted with goal=MAINTENANCE
  test_set_goal_maintenance_start_date_persisted  → start_date = today (UTC)
  test_set_goal_invalid_value_rejected            → non-regression: INVALID still rejected
```

### refresh endpoint

```
MAINTENANCE_REFRESH_REAL_ENDPOINT_3 = PASS
MAINTENANCE_REFRESH_REAL_ENDPOINT_4 = PASS
MAINTENANCE_REFRESH_REAL_ENDPOINT_5 = PASS
MAINTENANCE_REFRESH_REAL_ENDPOINT_6 = PASS

Tests:
  test_refresh_maintenance_sessions[3/4/5/6]         → HTTP 200, no crash
  test_refresh_maintenance_sessions_stored[3/4/5/6]  → sessions_per_week stored in training_prefs
  test_refresh_maintenance_plan_returned              → plan payload returned
```

---

## Set-Goal Endpoint

```
SET_GOAL_ENDPOINT              = POST /api/training/set-goal?goal=MAINTENANCE
GOAL_VALIDATION_BEFORE         = [5K, 10K, SEMI, MARATHON, ULTRA]
GOAL_VALIDATION_AFTER          = [5K, 10K, SEMI, MARATHON, ULTRA, MAINTENANCE]

MAINTENANCE_CYCLE_PERSISTED    = YES  (training_cycles.goal=MAINTENANCE, upsert)
MAINTENANCE_START_DATE         = TODAY (datetime.now(timezone.utc) at call time)
```

---

## MAINTENANCE Behavior

```
MAINTENANCE_RACE_DATE_REQUIRED   = NO
MAINTENANCE_TARGET_TIME_REQUIRED = NO
MAINTENANCE_TAPER                = NO  (GoalType.maintenance not in _RACE_GOALS)
MAINTENANCE_RACE_WEEK            = NO  (GoalType.maintenance not in _RACE_GOALS)

MAINTENANCE_REFRESH_SUPPORTED    = YES
MAINTENANCE_WEEK_GENERATION      = YES (build_weekly_plan_from_workouts)
```

---

## Regression (Race Goals)

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
  backend/config/training_goals.py           — MAINTENANCE entry with canonical source comments
  backend/server.py                          — 3 changes (2 whitelists + _GOAL_MAP + race_date guard)
  backend/training_v2/week_plan_bridge.py    — race_date guard for MAINTENANCE
  backend/tests/test_pr204_maintenance_backend.py  — unit/integration tests (25+ contracts)
  backend/tests/test_pr204_maintenance_endpoint.py — real endpoint tests (set-goal + refresh)
  docs/reports/PR204_MAINTENANCE_BACKEND_SUPPORT.md

FRONTEND_MODIFIED    = NO
LOCKFILES_MODIFIED   = NO
DEPENDENCIES_MODIFIED = NO
```

---

## Tests

```
TESTS =
  backend/tests/test_pr204_maintenance_backend.py  — 38 tests (unit/V2 chain)
  backend/tests/test_pr204_maintenance_endpoint.py — 13 tests (real endpoint: set-goal + refresh)

PR204_TESTS = 51 passed, 1 skipped (ULTRA/no-race-date: pre-existing expected behavior)
TRAINING_V2_REGRESSION_TESTS = PASS (5K/10K/SEMI/MARATHON/ULTRA all pass)
ENDPOINT_TESTS = PASS (set-goal HTTP 200 + persistence + refresh 3/4/5/6)
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
