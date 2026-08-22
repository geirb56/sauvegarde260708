# RUNINDEX PR #181 REPORT — V2 FINAL

## OLD_FORMULA

```
RunIndex = (0.40 × speed + 0.25 × endurance + 0.20 × consistency + 0.15 × efficiency) × 10
```

Missing component → replaced with 0 (fabricated).
Insufficient data (0 runs) → returned 0 with status absent.
No `status` field in output.

## NEW_FORMULA

```
RunIndex = weighted_average_nullable([speed×0.40, endurance×0.25, consistency×0.20, efficiency×0.15]) × 10
```

Missing component → excluded from weighted average (renormalised weights).  
Insufficient gate not satisfied → `run_index = null`, `status = "insufficient"`.  
`status` field always present: `"sufficient"` | `"insufficient"`.

## RUNINDEX_WEIGHTS

| Pillar      | Weight |
|-------------|--------|
| Speed       | 40 %   |
| Endurance   | 25 %   |
| Consistency | 20 %   |
| Efficiency  | 15 %   |

Weights unchanged from prior version. Applied only when gate is satisfied.

---

## SPEED_COMPONENTS

| Component              | Weight | Notes                                                         |
|------------------------|--------|---------------------------------------------------------------|
| race_performance_score | 60 %   | Best predicted time for 5K/10K/half within ±20 % target dist |
| speed_proxy_score      | 25 %   | Proxy for sustainable speed (NOT a VO2max measurement)        |
| sustained_speed_score  | 15 %   | Fastest pace in 20–75 min effort (NOT LT2/threshold)          |

- `speed_proxy_score` replaces old `vo2max_score`. The proxy uses estimated VMA × 3.5 but is NOT a physiological VO2max measurement.
- `sustained_speed_score` replaces old `threshold_score`. The 20–75 min best pace is NOT a lactate threshold.
- All components use `_weighted_average_nullable`: absent component → excluded.

## ENDURANCE_COMPONENTS

| Component                | Weight | Notes                               |
|--------------------------|--------|-------------------------------------|
| long_run_score           | 45 %   | Longest run in last 30 days (6–32 km) |
| volume_score             | 35 %   | Weekly km average (15–110 km)       |
| long_run_frequency_score | 20 %   | Count of long runs in last 30 days  |

- Old `durability_score` (which included a fake `pace_stability_score = 60` when `long_run_cv` unknown) is removed.
- No synthetic 60 for unknown long-run pace stability.
- Missing component → excluded from weighted average.

## CONSISTENCY_COMPONENTS

| Component       | Weight | Notes                                            |
|-----------------|--------|--------------------------------------------------|
| frequency_score | 40 %   | Active weeks + avg runs/week (8-week window)     |
| stability_score | 40 %   | Weekly volume CV — None when not computable       |
| habit_score     | 20 %   | avg/max gap between sessions — None when <2 runs |

- Old `stability_score = 35.0 if distance_cv is None` → removed. Unknown stability = `None`.
- Old `avg_gap = _safe_mean(gaps) or 14.0` → removed. No gaps = `None`.
- Old `max_gap = max(gaps) if gaps else 21` → removed. No gaps = `None`.

## EFFICIENCY_COMPONENTS

| Component                               | Weight | Notes                                                    |
|-----------------------------------------|--------|----------------------------------------------------------|
| pace_heart_rate_score                   | 100 %  | Median speed/HR ratio (55–90 index, monotonic)           |
| inter_run_efficiency_variability_score  | —      | Informational only — NOT used in score aggregation       |

- Efficiency score = `pace_heart_rate_score` only (monotonic guarantee: better speed/HR → score never decreases).
- `inter_run_efficiency_variability_score` retained for observability but does not affect the score.
- HR absent → `efficiency_score = None`. Never 0.
- Old `pace_stability_score` removed from efficiency (was a consistency metric, not efficiency).
- Old confidence defaults `35.0` and `45.0` for missing drift/stability → removed.

---

## INSUFFICIENT_RULE

```
Gate satisfied when:
  - valid running activities in scope ≥ 3
  AND
  - calculable pillar scores ≥ 2

If gate NOT satisfied:
  status = "insufficient"
  run_index = null
  (pillar scores may be null or non-null individually)
```

A real score of 0 is theoretically possible (all pillars near minimum) and remains distinct from `null`.  
`null` is never stored as `0` in MongoDB snapshots.

---

## CONFIDENCE_RULE

Confidence measures **quality and quantity of available data**.

- More activities → confidence increases.
- Fresher activities → confidence increases.
- Absent component → excluded from confidence weighted average.
- Absent pillar → excluded from global confidence.
- `run_count < 6` → confidence × 0.75.
- No data → confidence = 0.

Removed synthetic confidence defaults:
- `100.0 if long_run_cv is not None else 55.0` → removed
- `100.0 if drift_score is not None else 35.0` → removed
- `100.0 if pace_stability_score is not None else 45.0` → removed

---

## REMOVED_SYNTHETIC_DEFAULTS

| Location             | Old value             | New value |
|----------------------|-----------------------|-----------|
| Endurance: pace_stability_score | `60.0` when long_run_cv unknown | Removed entirely |
| Consistency: stability_score    | `35.0` when distance_cv unknown | `None`          |
| Consistency: avg_gap            | `14.0` when no gaps             | `None`          |
| Consistency: max_gap            | `21` when no gaps               | `None`          |
| Efficiency: drift confidence    | `35.0` when drift absent        | Removed         |
| Efficiency: stability confidence| `45.0` when stability absent    | Removed         |
| Global: empty run → score 0     | `run_index = 0`                 | `run_index = null`, `status = insufficient` |

---

## CARDIAC_DRIFT_CLAIM_REMOVED = YES

The old `cardiac_drift_score` key has been removed from all output.  
A new informational `inter_run_efficiency_variability_score` describes what is actually computed: dispersion of the speed/HR proxy **between sessions**, not intra-session cardiac drift.  
True cardiac drift requires time-series or split data not available in `DomainActivity`.  
This score is informational only and does not affect the efficiency pillar score.

## LT1_LT2_CLAIMED = NO

`sustained_speed_score` (formerly `threshold_score`) explicitly documents that it is the **fastest pace in a 20–75 min effort**, not a lactate threshold. No LT1/LT2 claims in any docstring or output key.

## VO2MAX_MEASURED_CLAIMED = NO

`speed_proxy_score` (formerly `vo2max_score`) explicitly documents that it is an **internal proxy for sustainable speed** based on effort duration — not a physiological VO2max measurement. The docstring states: "This is NOT a physiological VO2max measurement".

---

## CURRENT_HISTORY_PARITY = PASS

`calculate_run_index` and `calculate_run_index_from_domain` are the single engine used for both CURRENT and HISTORY snapshots.  
`build_snapshot_document_from_domain(user_id, activities, snapshot_date)` passes `reference_date=snapshot_date` to the engine so no future activity leaks.  
Test 14 (`test_current_and_history_same_date_same_result`) confirms identical output for same date + same activities.

## FUTURE_LEAKAGE = PASS

Activities with `workout_date > reference_date` are excluded in `_prepare_running_workouts`.  
Test 13 (`test_future_activity_excluded_from_historical_reference`) confirms a future run (days_ago = -5) does not influence the score at `reference_date`.

## DOMAIN_ACTIVITY_AUTHORITY = PASS

`calculate_run_index_from_domain` is the canonical entry point.  
`db.workouts` is never consulted for RunIndex scoring.  
`load_garmin_domain_activities` reads `garmin_activities` → `mongo_garmin_activities_to_domain` → `DomainActivity`.  
Test 15 (`test_domain_activity_path_no_workouts_dependency`) confirms the contract.

## DASHBOARD_NULL_SEMANTICS = PASS

`Dashboard.jsx`:
- `run_index = null` or `status = "insufficient"` → displays "Insufficient data" (not "0 / 1000").
- Pillar `null` → shows "—" (not "0%").
- `RunIndexPillar` component updated to handle `value === null`.

## PROGRESS_NULL_SEMANTICS = PASS

`Progress.jsx`:
- `current_run_index = null` → `?? "--"` already handles this (no change needed for the score display).
- Pillar `data.current = null` → fixed to show "—" instead of "--%".
- Chart already filters `h.run_index !== null` — null history entries are preserved in DB and excluded from chart rendering only.

## CACHE_STALE_RUNINDEX = PASS

`dashboard_insight_cache.invalidate_user(user_id)` is now called in **two** places in `garmin/service.py`:

1. **`_complete_post_activities_pipeline`** — immediately after `backfill_run_index_history_after_garmin_sync`.  
   This covers the **normal sync** path used by `sync_worker` (via `garmin_service.sync`).

2. **`incremental_sync`** — immediately after `backfill_run_index_history_after_garmin_sync`.  
   This covers the **incremental sync** path used by `sync_worker` (via `garmin_service.incremental_sync`).

3. **`api/garmin.py` `garmin_backfill_endpoint`** — unchanged from PR #181 initial patch.  
   Covers the explicit backfill endpoint.

`dashboard_insight_cache` has **zero external imports** — no circular-import risk.

## NORMAL_SYNC_PATH

```
POST /api/garmin/sync  (or scheduler_loop / enqueue_sync)
  → workers/sync_worker.py : process_job()
    → garmin_service.sync(db, user_id)           [JOB_SYNC_USER / JOB_SYNC_ACTIVITY]
    OR garmin_service.incremental_sync(db, user_id)  [JOB_INCREMENTAL_SYNC]
      → garmin.providers.*.sync_activities()
      → _ingest_activities(db, user_id, activities)   ← garmin_activities persisted
      → _complete_post_activities_pipeline(...)
          → refresh_today_run_index_after_garmin_activities(db, user_id)   ← RunIndex CURRENT refreshed
          → backfill_run_index_history_after_garmin_sync(db, user_id)      ← RunIndex history refreshed
          → dashboard_insight_cache.invalidate_user(user_id)              ← cache wiped ✓
          → update_sync_progress(phase="complete")
      OR (incremental path):
          → refresh_today_run_index_after_garmin_activities(db, user_id)
          → backfill_run_index_history_after_garmin_sync(db, user_id)
          → dashboard_insight_cache.invalidate_user(user_id)              ← cache wiped ✓
```

**Lowest and safest common point**: end of `backfill_run_index_history_after_garmin_sync`, in both service branches, before `update_sync_progress(phase="complete")`.  
At this point: new activities already persisted ✓, RunIndex CURRENT + history refreshed ✓, sync considered successful ✓.

## NO_CIRCULAR_IMPORT = PASS

`dashboard_insight_cache.py` — imports: `from __future__ import annotations` uniquement.  
Aucune dépendance vers `server`, `garmin`, `api`, ou tout autre module applicatif.  
Chaîne d'import: `garmin.service → dashboard_insight_cache` (sens unique, pas de cycle).

### Cache invalidation tests (`tests/test_cache_stale_runindex_pr181.py`)

| Test | Description | Result |
|------|-------------|--------|
| test_normal_sync_invalidates_user_x_not_user_y | `_complete_post_activities_pipeline` wipes X, preserves Y | PASS |
| test_incremental_sync_invalidates_user_x_not_user_y | `incremental_sync` wipes X, preserves Y | PASS |

**Total new tests: 2 passed / 0 failed**


## TRAINING_V2_MODIFIED = NO
## COACH_MODIFIED = NO
## LOCKFILES_MODIFIED = NO

---

## TESTS

### Engine tests (`tests/test_run_index_engine.py`)

| Test | Description | Result |
|------|-------------|--------|
| test_profiles_produce_ordered_run_index_scores | Beginner < Intermediate < Advanced < Elite | PASS |
| test_score_ranges_are_always_valid_for_all_profiles | 0–1000 run_index, 0–100 pillars when non-null | PASS |
| test_missing_heart_rate_data_reduces_confidence | No HR → lower confidence | PASS |
| test_reference_date_changes_run_index_for_progressive_runner | Late date → better score | PASS |
| test_zero_activities_returns_insufficient_null | Test 1: 0 activities → insufficient | PASS |
| test_one_activity_returns_insufficient | Test 2: 1 activity → insufficient | PASS |
| test_two_activities_returns_insufficient | Test 3: 2 activities → insufficient | PASS |
| test_three_activities_with_two_pillars_returns_sufficient | Test 4: ≥3 + ≥2 pillars → sufficient | PASS |
| test_no_hr_efficiency_is_null_not_zero | Test 5: HR absent → efficiency null | PASS |
| test_endurance_no_multiple_long_runs_stability_not_60 | Test 6: unknown stability ≠ 60 | PASS |
| test_consistency_stability_unknown_is_none_not_35 | Test 7: unknown stability ≠ 35 | PASS |
| test_consistency_no_gaps_when_less_than_2_sessions | Test 8a: no gaps → not 21 | PASS |
| test_consistency_gaps_not_fabricated_with_single_session | Test 8b: no gaps → not 14 | PASS |
| test_missing_component_causes_renormalisation | Test 9: renormalisation | PASS |
| test_missing_pillar_does_not_produce_zero_run_index | Test 10: missing pillar renorm | PASS |
| test_empty_input_is_insufficient | Test 11: all missing → insufficient | PASS |
| test_confidence_increases_with_more_data | Test 12: confidence monotone | PASS |
| test_future_activity_excluded_from_historical_reference | Test 13: no future leak | PASS |
| test_current_and_history_same_date_same_result | Test 14: parity | PASS |
| test_domain_activity_path_no_workouts_dependency | Test 15: DomainActivity only | PASS |
| test_non_running_activities_ignored | Test 16: non-running ignored | PASS |
| test_run_index_in_valid_range_when_sufficient | Test 17: 0–1000 when sufficient | PASS |
| test_pillar_scores_in_valid_range_when_non_null | Test 18: 0–100 when non-null | PASS |
| test_better_speed_does_not_decrease_speed_score | Monotone: speed | PASS |
| test_more_volume_does_not_decrease_endurance_score | Monotone: endurance | PASS |
| test_more_active_weeks_does_not_decrease_consistency_score | Monotone: consistency | PASS |
| test_better_speed_hr_ratio_does_not_decrease_efficiency_score | Monotone: efficiency | PASS |
| test_output_has_required_contract_fields | Contract fields present | PASS |
| test_insufficient_output_has_null_run_index | null when insufficient | PASS |
| test_no_cardiac_drift_score_in_output | cardiac_drift_score absent | PASS |
| test_no_vo2max_score_in_output | vo2max_score absent | PASS |
| test_no_threshold_score_in_output | threshold_score absent | PASS |

**Total: 32 passed / 0 failed / 0 skipped / 0 errors**

---

## RUNTIME SMOKE

> Note: Smoke test against a real Garmin account must be performed by the operator before merge.
> 
> Steps:
> 1. Call `/dashboard/insight` → record run_index, speed, endurance, consistency, efficiency, confidence.
> 2. Deploy PR #181.
> 3. Call `/dashboard/insight` again → compare values.
> 4. Verify `/run-index/history` → 200.
> 5. Verify Dashboard rendered correctly (no "0 / 1000" for insufficient users).
> 6. Verify Progression rendered correctly (null history preserved, "—" for null pillars).
>
> Expected score changes:
> - Users with <3 valid activities: `run_index` changes from `0` to `null` (insufficient).
> - Users with fabricated stability = 35: consistency_score changes.
> - Users with fabricated stability = 60: endurance_score changes.
> - Users without HR data: efficiency_score changes from integer to `null`.
> - All changes are explained by removal of synthetic defaults documented above.

---

## VERDICT

**NOT READY FOR AUTO-MERGE.**

All engine tests pass (32/32).  
Operator must run smoke test on real Garmin account and confirm:
- Score changes are explained by formula.
- Dashboard and Progression render correctly.
- `/dashboard/insight` and `/run-index/history` return 200.

STOP. Do not begin #182.
