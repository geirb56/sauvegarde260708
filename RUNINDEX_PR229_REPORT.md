# RUNINDEX PR229 — Daily Metrics / Readiness Robustness

## Scope
- Scheduler → incremental_sync → gccli daily metrics → Mongo daily metrics → Readiness V2 → UI status messaging.
- Dedicated fix for technical-failure masking (`success=true + metrics_count=0`) and readiness blocking edge-cases.

## Implemented changes

### 1) Daily metrics fetch outcome is now explicit
- Added `DailyMetricsFetchResult` in `backend/garmin/runner.py`.
- Added `GccliRunner.fetch_daily_metrics_result(...)` with explicit status:
  - `success`
  - `success_no_data`
  - `partial_success`
  - `technical_failure`
  - `session_unavailable`
- `fetch_daily_metrics(...)` stays backward-compatible and returns only `metrics`.
- Endpoint-level failures are preserved (`endpoint_failures`) instead of silently collapsing to empty data.

### 2) Provider contract extended without breaking old callers
- Added default `Provider.get_daily_metrics_fetch_result(...)` in `backend/garmin/providers/base.py`.
- Added concrete `GccliProvider.get_daily_metrics_fetch_result(...)` in `backend/garmin/providers/gccli_provider.py`.

### 3) incremental_sync robustness and retry correctness
- `backend/garmin/service.py` incremental path now consumes explicit fetch outcomes.
- Technical daily-metrics failure returns hard failure:
  - `success=False`
  - `status="failed"`
  - `error="daily_metrics_fetch_failed"`
  - sync progress marks `daily_metrics_status="failed"`.
- Session-unavailable daily-metrics failure is separated with `error="session_unavailable"`.
- True no-data case without exceptions maps to `daily_metrics_status="no_usable_data"`.
- Added `daily_metrics_fetch_status` in sync progress payload for UI transparency.
- Avoided masking failures via `last_sync`:
  - `_finalize_connection(..., update_last_sync=False)` used before daily metrics stage.
  - `last_sync` updated only after full incremental completion.
  - A technical failure does not advance `last_sync`.

### 4) Readiness canonical edge-case adjustment (no fake fallback)
- Added optional `hrv_supported` to readiness sufficiency input.
- In `backend/training_v2/readiness_sufficiency.py`:
  - HRV unsupported (`hrv_supported=False`) no longer creates `missing_hrv`.
  - Full physio branch absence is not automatically blocking when HRV is intrinsically unsupported.
- In `backend/garmin/readiness_adapter.py`:
  - Added optional `hrv_supported` propagation to sufficiency input.
- In `backend/garmin/insights.py`:
  - Reads `garmin_capabilities.has_hrv` and passes `hrv_supported` into Readiness V2 build (current + history).

### 5) UI now surfaces known causes instead of generic unavailable
- `frontend/src/pages/Settings.jsx` now computes detailed sync helper messages using:
  - `status`, `error_code`, `daily_metrics_status`, `daily_metrics_fetch_status`.
- `frontend/src/pages/Onboarding.jsx` now maps sync errors to specific causes (session expired vs daily metrics fetch failure).
- Added i18n keys (EN/FR/ES) in `frontend/src/lib/i18n.js`:
  - reconnect required
  - daily metrics retrieval error
  - partial data state
  - no data available yet

## Tests added/updated
- `backend/tests/test_garmin_daily_metrics_pr03.py`
  - technical failure on all endpoints is not treated as no-data
  - `health hr` technical error classified
  - `health sleep` technical error classified
  - true no-data without exception classified `success_no_data`
- `backend/tests/test_garmin_phased_sync_pr07a.py`
  - incremental technical failure returns failed state, not false success
  - incremental true no-data returns complete + `no_usable_data`
- `backend/tests/test_training_v2_readiness_sufficiency.py`
  - HRV unsupported + RHR present remains computable
  - HRV unsupported + temporary RHR absent + sleep/load available is non-blocking (degraded)
- `backend/tests/test_run_index_r3_readiness_v2.py`
  - adapter-level case: HRV unsupported + RHR absent + sleep/load available remains computable
- `backend/tests/test_readiness_data_truth_pr225.py`
  - updated to new provider fetch-result path
- `backend/tests/test_garmin_queue_backfill_pr197.py`
  - daily-metrics failure in incremental worker path does not set cooldown and is retried

## Runtime validation plan (deferred runtime gate)
1. Persist a valid Garmin session for a test user.
2. Wait for automatic incremental sync trigger from scheduler.
3. Verify Redis sync progress transitions (including `daily_metrics_fetch_status` and `error_code`).
4. Verify Mongo:
   - `garmin_daily_metrics` J0/J-1 persistence behavior
   - `garmin_connections.last_sync` not advanced on technical daily failure
5. Verify readiness:
   - J0/J-1 used as current
   - J-2+ never used as current
   - no invented physio values
   - sleep-only-missing is degraded/computable, not blocked
6. Verify UI labels:
   - data not yet available
   - sync in progress
   - Garmin fetch error
   - reconnect only for real session invalidation.

## Non-goals
- No fabricated neutral fallback values for HRV/RHR/sleep.
- No forced reconnect on technical daily-metrics endpoint failures when session remains valid.
