# RUNINDEX_PR179_REPORT.md

## PR #179 — RunIndex Score V2 — Source Garmin Canonique

---

BASE_BRANCH = copilot/dev
HEAD_START = 884b61ef0af515d8ce998976be8323097eb112ca
HEAD_FINAL = (set after merge)

---

## Source Migration Summary

CURRENT_RUNINDEX_SOURCE =
garmin_activities → mongo_garmin_activities_to_domain → DomainActivity → calculate_run_index_from_domain

HISTORY_RUNINDEX_SOURCE =
garmin_activities → mongo_garmin_activities_to_domain → DomainActivity → calculate_run_index_from_domain (reference_date=J)

DB_WORKOUTS_CURRENT_AUTHORITY = NO
DB_WORKOUTS_HISTORY_AUTHORITY = NO

POST_SYNC_REQUIRES_WORKOUT_FANOUT = NO

---

## Formula / Contract

RUNINDEX_FORMULA_MODIFIED = NO
RUNINDEX_WEIGHTS_MODIFIED = NO
RUNINDEX_THRESHOLDS_MODIFIED = NO
INSUFFICIENT_CONTRACT_MODIFIED = NO

READINESS_MODIFIED = NO
TRAINING_V2_MODIFIED = NO
FRONTEND_MODIFIED = NO
LOCKFILES_MODIFIED = NO

---

## calculate_run_index Callers

CALCULATE_RUN_INDEX_CALLERS:
- CURRENT_RUNTIME:
  - `server.py` `/dashboard/insight` → `calculate_run_index_from_domain(garmin_domain_activities)` ✅ Garmin DomainActivity
  - `garmin/insights.py` `compute_run_index()` → does NOT call `calculate_run_index`; it builds a separate payload. Not a RunIndex Score caller.
- HISTORY_RUNTIME:
  - `services/run_index_history.py` `build_snapshot_document_from_domain` → `calculate_run_index_from_domain(activities, reference_date=snapshot_date)` ✅ Garmin DomainActivity
  - `services/run_index_history.py` `backfill_run_index_history` → uses `build_snapshot_document_from_domain` ✅
  - `services/run_index_history.py` `upsert_run_index_snapshot` → uses `build_snapshot_document_from_domain` ✅
- TEST:
  - `tests/test_run_index_engine.py` → uses `calculate_run_index(list[dict])` directly (engine unit tests, legacy dict path — no I/O)
  - `tests/test_run_index_history_service.py` → uses `backfill_run_index_history` with FakeDB backed by garmin_activities (migrated to PR179 canonical path)
  - `tests/test_run_index_pr179_domain_source.py` → uses `calculate_run_index_from_domain` ✅
- LEGACY_OTHER:
  - `engine/run_index_engine.py` `calculate_run_index(list[dict])` — the existing dict-based entry point is kept for backward compatibility (used by engine unit tests). It is NOT called by any CURRENT_RUNTIME or HISTORY_RUNTIME path after PR179.
  - `services/run_index_history.py` `build_snapshot_document(user_id, workouts, snapshot_date)` — kept for reference but NOT called by any runtime path after PR179.
  - `services/run_index_history.py` `select_snapshot_dates(workouts, reference_date)` — kept for reference but NOT called by any runtime path after PR179.
  - `services/run_index_history.py` `load_user_workouts(db, user_id)` — reads db.workouts. Kept for reference but NOT called by any runtime path after PR179. Explicitly documented as LEGACY.

---

## New Symbols Introduced

### `engine/run_index_engine.py`
- `_RUNNING_ACTIVITY_TYPES` — frozenset of canonical running activity type strings
- `_domain_activity_to_workout_dict(activity: DomainActivity) → Optional[dict]` — converts a single DomainActivity to an internal engine dict; returns None for non-running or incomplete activities
- `prepare_workout_dicts_from_domain(activities: list[DomainActivity]) → list[dict]` — converts a list; filters non-running/incomplete
- `calculate_run_index_from_domain(activities: list[DomainActivity], reference_date=None) → dict` — **canonical PR179 entry point**

### `services/run_index_history.py`
- `load_garmin_domain_activities(db, user_id) → list[DomainActivity]` — reads garmin_activities, converts via `mongo_garmin_activities_to_domain`
- `_domain_activity_day(activity: DomainActivity) → Optional[date]` — extracts date from start_time
- `_first_domain_activity_day(activities, reference_date) → Optional[date]`
- `select_snapshot_dates_from_domain(activities, reference_date) → list[date]` — canonical snapshot grid from DomainActivity
- `build_snapshot_document_from_domain(user_id, activities, snapshot_date, computed_at) → dict` — canonical snapshot builder

### Modified signatures
- `upsert_run_index_snapshot(db, user_id, activities=None, snapshot_date=None)` — now accepts `list[DomainActivity]` (breaking change: old positional `workouts: list[dict]` removed)
- `backfill_run_index_history(db, user_id, activities=None, reference_date=None)` — now accepts `list[DomainActivity]`
- `backfill_run_index_history_after_garmin_sync(db, user_id, activities=None)` — now accepts `list[DomainActivity]`
- `refresh_today_run_index_after_garmin_activities(db, user_id)` — no longer calls `garmin.backfill.backfill_user` (fan-out eliminated)
- `refresh_run_index_after_garmin_sync(db, user_id)` — loads DomainActivity once, shares with backfill
- `backfill_connected_users_run_index_history(db)` — no longer calls `garmin.backfill.backfill_user`

---

## Invariants

### Future Leakage Prevention
The `calculate_run_index_from_domain` function passes `reference_date` to
`calculate_run_index`, which uses `_prepare_running_workouts(workouts, reference_date)`.
That function filters out any activity with `workout_date > today` (where `today = reference_date`).
For snapshot J: `build_snapshot_document_from_domain(user_id, activities, snapshot_date=J)` passes
`reference_date=J`, ensuring no activity after J influences the J-snapshot.

Test: `test_reference_date_excludes_future_activities` — PASS

### Post-sync No Fan-out
`refresh_today_run_index_after_garmin_activities` no longer calls
`garmin.backfill.backfill_user`. It reads directly from `garmin_activities`.
An activity present in `garmin_activities` but absent from `db.workouts` is
immediately visible to RunIndex.

Test: `test_post_sync_no_fanout_required` — PASS

### User Isolation
`load_garmin_domain_activities(db, user_id)` filters by `{"user_id": user_id}`.
Activities from other users are never loaded.

Test: `test_user_isolation` — PASS

---

## Manual / Terra User Behavior

**User with only manual workouts or Terra activities (no garmin_activities):**

After PR179, `calculate_run_index_from_domain` with an empty activities list
returns `{"run_index": 0, "confidence_score": 0, ...}` — same as before with
no running data. The behavior is: RunIndex = 0 with confidence = 0.

No implicit merge with Terra or manual workouts is created. The RunIndex Garmin
score is strictly sourced from `garmin_activities`. This is intentional:
PR179 is a data source migration, not a multi-provider merge feature.

**For the `/dashboard/insight` endpoint:**
- `week_stats`, `month_stats`, `recovery_score` still use `db.workouts` (unchanged)
- Only `run_index` now uses `garmin_activities → DomainActivity`
- If a user has no Garmin activities but has manual workouts, `run_index` will
  return `{"run_index": 0, "confidence_score": 0, ...}` instead of a value
  derived from manual workouts. This is the documented result of PR179.

**Policy decision deferred:** Whether to expose a "no Garmin data" state
(INSUFFICIENT) differently from a "Garmin user with no runs" state is
deferred to PR180, which will audit the INSUFFICIENT contract.

---

## Parity Test

PARITY_TEST = PASS

`test_parity_domain_vs_workout_dict` verifies that semantically identical data
produces identical scores when passed as a DomainActivity vs a legacy workout dict.

The boundary conversion is:
- `distance_m / 1000.0 → distance_km` (lossless for float values)
- `duration_s / 60.0 → duration_minutes` (lossless for float values)
- `average_hr → avg_heart_rate` (direct pass-through)
- `activity_type: "running" → type: "run"` (normalized)

Scores match exactly because `_prepare_running_workouts` produces the same
internal representation in both paths.

---

## Test Results

FUTURE_LEAKAGE_TEST = PASS
POST_SYNC_NO_FANOUT_TEST = PASS
USER_ISOLATION_TEST = PASS
SELF_HEAL_WORKOUTS_PRESERVED = YES
RUNINDEX_DEPENDS_ON_WORKOUT_SELF_HEAL = NO

POST_SYNC_RUNINDEX_SOURCE =
garmin_activities → mongo_garmin_activities_to_domain → DomainActivity → calculate_run_index_from_domain

WORKOUT_SELF_HEAL_SOURCE =
garmin_activities → backfill_user(prune=False) → db.workouts

SELF_HEAL_LOCATION =
`garmin/service.py` — called in two places, both AFTER RunIndex has been
computed and persisted, using `_backfill_workouts_user` (alias for
`garmin.backfill.backfill_user`):

1. `_complete_post_activities_pipeline` (deep/full sync path):
   RunIndex is computed and history is backfilled first; then
   `_backfill_workouts_user(db, user_id, prune=False)` is called in a
   try/except that logs errors but never surfaces them to RunIndex.

2. Incremental sync path (`sync_activities` inner try block):
   Same pattern — RunIndex first, self-heal workouts after, errors isolated.

Neither call passes its return value to RunIndex.  The return value of
`_backfill_workouts_user` is discarded.

---

## Post-Correction Audit

CORRECTION_APPLIED = YES

BLOCKER_FIXED:
Before this correction, `garmin/service.py` called
`backfill_run_index_history_after_garmin_sync` with the stale keyword
argument `workouts=refreshed.get("workouts")`, which was undefined after
PR179 (the function signature was changed to `activities=`).  This would
have caused a `TypeError` at runtime.  Both call sites are now fixed.

SELF_HEAL_RESTORED:
`backfill_user(db, user_id, prune=False)` is now explicitly called at both
post-sync call sites in `garmin/service.py`, decoupled from and downstream
of RunIndex computation.  Its result is never passed to RunIndex.

tests =
- test_run_index_pr179_domain_source.py: 26 passed / 0 failed / 0 skipped / 0 errors
- test_run_index_history_service.py: 7 passed / 0 failed / 0 skipped / 0 errors
- test_run_index_engine.py: 5 passed / 0 failed / 0 skipped / 0 errors

Total: 38 passed / 0 failed / 0 skipped / 0 errors

FILES_MODIFIED:
- backend/garmin/service.py (+17 / -11)
- backend/tests/test_run_index_pr179_domain_source.py (+107 / 0)

FILES_UNCHANGED:
- engine/run_index_engine.py
- services/run_index_history.py
- garmin/backfill.py
- All frontend files
- All lockfiles

git diff --stat HEAD~1:
 backend/garmin/service.py                          |  26 ++---
 backend/tests/test_run_index_pr179_domain_source.py | 107 +++++++++++++++++++++
 2 files changed, 122 insertions(+), 11 deletions(-)

---

## Post-Test-Correction Audit (C179)

REAL_PIPELINE_SELF_HEAL_TEST = PASS

SELF_HEAL_ASSERT_AWAITED =
PASS — `mock_backfill.assert_awaited_once_with(db, user_id, prune=False)` verified
in `test_real_pipeline_self_heal_wiring`.

SELF_HEAL_PRUNE_FALSE =
PASS — `prune=False` confirmed by `assert_awaited_once_with`.

RUNINDEX_USES_SELF_HEAL_RESULT =
NO — sentinel `{"SENTINEL_WORKOUT_SELF_HEAL": True}` returned by mock; confirmed
absent from `incremental_sync` result.

RUNINDEX_DEPENDS_ON_DB_WORKOUTS =
NO — `refresh_today_run_index_after_garmin_activities` is mocked and called before
self-heal; db.workouts is empty in the test and never consulted for RunIndex.

SELF_HEAL_FAILURE_FALLBACK_TO_WORKOUTS =
NO — `test_real_pipeline_self_heal_failure_isolation` verifies that when
`_backfill_workouts_user` raises `RuntimeError`, `incremental_sync` still returns
`success=True` and `workouts_upserted` does not appear in the result.

RUNINDEX_FORMULA_MODIFIED = NO
READINESS_MODIFIED = NO
TRAINING_V2_MODIFIED = NO
FRONTEND_MODIFIED = NO
LOCKFILES_MODIFIED = NO

TESTS_REPLACED:
- `test_self_heal_decoupled_from_run_index` (called `_fake_backfill_user` directly — not a real wiring test) replaced by:
  - `test_real_pipeline_self_heal_wiring` — calls real `garmin.service.incremental_sync`; patches `garmin.service._backfill_workouts_user` as AsyncMock; asserts `assert_awaited_once_with(db, user_id, prune=False)`; sentinel not in result.
  - `test_real_pipeline_self_heal_failure_isolation` — same pipeline with self-heal raising; pipeline still succeeds.

tests (C179) =
- test_run_index_pr179_domain_source.py: 27 passed / 0 failed / 0 skipped / 0 errors
- test_run_index_history_service.py: 7 passed / 0 failed / 0 skipped / 0 errors
- test_run_index_engine.py: 5 passed / 0 failed / 0 skipped / 0 errors

Total: 39 passed / 0 failed / 0 skipped / 0 errors

---

## Verdict

READY FOR RUNTIME SMOKE
