# PR205 — Training Goal MAINTENANCE Backend Support

## Identifiers

```
BASE_SHA = d8bb513ed841c47bf514633c4965c032a0b7315c
HEAD_SHA = (set after commit)
```

---

## Audit Results

### SET_GOAL_ENDPOINT
```
SET_GOAL_ENDPOINT = POST /api/training/set-goal?goal=MAINTENANCE
```

### Goal Validation

```
GOAL_VALIDATION_BEFORE = ["5K", "10K", "SEMI", "MARATHON", "ULTRA"]
GOAL_VALIDATION_AFTER  = ["5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"]
```

Both `/training/set-goal` and `/training-plan/set-goal` extended.

---

## Downstream Support Audit

```
MAINTENANCE_ALREADY_SUPPORTED_DOWNSTREAM = YES (partial)
```

The following layers already supported MAINTENANCE before this PR:

| Layer | Status |
|---|---|
| `training_v2/plan_goal.py` — `GoalType.maintenance` | ✅ Already present |
| `training_v2/plan_goal.py` — validation rules (no race_date, no target_time, no target_distance) | ✅ Already present |
| `training_v2/week_plan_bridge.py` — `_GOAL_MAP["MAINTENANCE"]` | ✅ Already present |
| `training_v2/training_cycle_response.py` — maintenance treated as continuous (not in `_RACE_GOALS`) | ✅ Already present |
| `server.py` — `_WEEK_GOAL_NORM["MAINTENANCE"]` in `/training/v2/week` | ✅ Already present |

The following were **missing/broken** and fixed by this PR:

| Gap | Fix |
|---|---|
| `GOAL_CONFIG` did not include MAINTENANCE | Added MAINTENANCE to `config/training_goals.py` |
| `/training/set-goal` whitelist rejected MAINTENANCE | Whitelist extended |
| `/training-plan/set-goal` whitelist rejected MAINTENANCE | Whitelist extended |
| `_GOAL_MAP` in `/training/v2/cycle` did not map MAINTENANCE | MAINTENANCE → `GoalType.maintenance` added |
| `build_plan_goal` called with `race_date` for MAINTENANCE in cycle endpoint | `race_date=None` forced for MAINTENANCE |
| `week_plan_bridge` passed caller's `race_date` to MAINTENANCE `PlanGoal` | `race_date` stripped for MAINTENANCE in bridge |

---

## MAINTENANCE Behavior

```
MAINTENANCE_MAPPING      = GoalType.maintenance
MAINTENANCE_CYCLE_TYPE   = continuous (12-week cycling, no race phase)

MAINTENANCE_RACE_DATE_REQUIRED   = NO
MAINTENANCE_TARGET_TIME_REQUIRED = NO
MAINTENANCE_TAPER                = NO
MAINTENANCE_RACE_WEEK            = NO
MAINTENANCE_START_DATE           = TODAY (via existing backend behavior: start_date = datetime.now(UTC) at set-goal)

MAINTENANCE_REFRESH_SUPPORTED    = YES (sessions 3/4/5/6 via /training/refresh?sessions=N)
MAINTENANCE_WEEK_GENERATION      = YES (build_weekly_plan_from_workouts accepts MAINTENANCE)
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

No race goal behavior was modified. Whitelist change is additive only.

---

## Files Modified

```
BACKEND_FILES_CHANGED =
  backend/config/training_goals.py         — Added MAINTENANCE entry to GOAL_CONFIG
  backend/server.py                        — Extended both set-goal whitelists; added MAINTENANCE to _GOAL_MAP in /v2/cycle; force race_date=None for MAINTENANCE in build_plan_goal call
  backend/training_v2/week_plan_bridge.py  — Strip race_date for MAINTENANCE before calling build_plan_goal; use plan_goal.race_date for periodization branching

FRONTEND_MODIFIED    = NO
LOCKFILES_MODIFIED   = NO
DEPENDENCIES_MODIFIED = NO
```

---

## Tests

```
TESTS = backend/tests/test_pr205_maintenance_backend.py

Tests added:
  test_goal_config_includes_maintenance
  test_goal_config_race_goals_unchanged
  test_maintenance_in_whitelist
  test_race_goals_still_in_whitelist[5K/10K/SEMI/MARATHON/ULTRA]
  test_maintenance_in_goal_map
  test_race_goal_map_unchanged[5K/10K/SEMI/MARATHON/ULTRA]
  test_maintenance_plan_goal_no_race_date
  test_maintenance_plan_goal_no_target_time
  test_maintenance_plan_goal_rejects_race_date
  test_maintenance_plan_goal_rejects_target_time
  test_maintenance_not_in_race_goals
  test_race_goals_still_in_race_goals[five_k/ten_k/half_marathon/marathon/ultra]
  test_maintenance_cycle_is_continuous
  test_maintenance_cycle_start_date_today
  test_maintenance_week_generation
  test_maintenance_week_generation_ignores_race_date
  test_maintenance_week_generation_sessions[3/4/5/6]
  test_race_goal_non_regression[5K/10K/SEMI/MARATHON/ULTRA]
  test_maintenance_cycle_created
```

---

## Blockers

```
BLOCKERS = NONE
```

---

## PR Status

```
PR205_READY_FOR_REVIEW = YES
```
