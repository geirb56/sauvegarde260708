# C352 — Workout Intelligence V3 Core

Snapshot report. The current behaviour is defined by the code and its tests, not by this document.

- **Base:** `ccc939270a3c00ba0e4050b0605048dc5ec1da46` (merge of #351, C351), integration branch `copilot/dev`
- **Head:** branch `copilot/c352-workout-intelligence-v3-core`
- **Scope:** backend only. No frontend change, no change to WorkoutDetail, no Mongo write, no Garmin/GCCLI call, no deployment, no merge.
- **Validation:** every fixture in this PR is **synthetic**. Nothing here has been validated against real Garmin data.

## 1. Modified files

| File | Change |
|---|---|
| `backend/workout_intelligence_v3_models.py` | New. Explicit input contract (`WorkoutIntelligenceV3Input`, session, profile, thresholds, history, prescription context) and output contract (`WorkoutIntelligenceV3` + `WorkoutIntelligenceV3Response` envelope). |
| `backend/workout_intelligence_v3.py` | New. Pure deterministic engine with seven stages: extraction → intensity → classification → history comparison → trend → prescription → coach assessment (FR/EN/ES). |
| `backend/workout_intelligence_v3_service.py` | New. Read-only loader that reuses the Workout Analysis V2 helpers and `build_workout_analysis_v2` unchanged. |
| `backend/server.py` | Additive endpoint `GET /api/coach/workout-intelligence/{workout_id}?language=fr|en|es`, using the same auth and subscription gate as `/coach/workout-analysis`. |
| `backend/tests/test_workout_intelligence_v3.py` | New. 85 tests: 43 core, 18 loader-level physiological wiring (§11) and 24 Level C individual-history tests (§12). |
| `docs/reports/c352_examples/*.json` | Synthetic example outputs. |

The `WorkoutAnalysisV2Response` contract is **unchanged**. A test pins its exact key set. V3 has its own endpoint, so no existing consumer (WorkoutDetail, Coach Context V2, Ask Coach) sees a different payload.

## 2. Data actually used

| Input | Source (read-only) | Notes |
|---|---|---|
| Date, sport, distance, duration, average pace (or `60 / avg_speed_kmh`), average/max HR, elevation | `workouts`, enriched by `enrich_workout_from_garmin_activity` (V2) | Splits are **never required**. |
| Precise activity type (`running`, `treadmill_running`, …) | `garmin_activities` via `_reliable_activity_type` (V2) | Comes from the source document only, never from a name. |
| Garmin phases, current and historical | Cached `activity_details` via `_cached_activity_phases` (V2) | Optional. |
| Session structure, efforts, recoveries, regularity | `WorkoutAnalysisV2Response.signals.session_structure` and `phase_analysis` | Reused as-is. |
| V2 similar comparison | `comparison.similar` (echoed in `historical_comparison.v2_similar_reference`) | Reused as-is. |
| History | Same query as the V2 loader: same user, same `type`, 180-day window, maximum 200 rows | The engine then keeps **strictly prior** sessions only. |
| Declared FCmax | `runner_profile` declared inputs (`physiological_metrics` then `user_profile`, keys `max_hr` / `max_heart_rate`), same priority as `build_runner_profile` | `fcmax_source="user_declared"`. None is supplied at runtime (§11). Used for consistency checks only. |
| Observed max HR | Strictly-prior `max_hr` values in the 150–230 bpm range, combined with `training_v2.performance_model._resolve_fcmax_robust` (the existing Training V2 rule) | Reported as `observed_max_hr_bpm`, a **lower bound**. It is never shown as `fcmax_bpm` and never used to derive a zone. |
| LT1 / LT2 | **None persisted in RunIndex**. See §7 (blocker). | The input contract accepts them, with source, date and confidence. |
| Historical prescription | `training_prescription_snapshots` filtered on `{user_id, planned_date = Garmin-local date}` | Checked with `is_snapshot_authoritative` (Training V2). |
| Garmin-local date | `garmin.domain_adapter.garmin_local_start_time` | Never falls back to GMT. |

VMA, LT1/LT2 computation, Readiness and Training Load are not touched. The historical RAG engine is not reintroduced.

## 3. Intensity rules (`intensity_assessment`)

- **HR used:** the session's average HR. It is rejected as `hr_missing`, `hr_aberrant_above_credible_ceiling` (above 230 bpm, the existing Training V2 ceiling) or `hr_aberrant_average_above_max`.
- **Thresholds:** a threshold is used only when all of these hold:
  - its source is `lab_test`, `field_test` or `device_estimate`;
  - its confidence is `high` or `medium`;
  - its estimate date is known and **on or before** the session date;
  - LT1 < LT2.

  `generic_formula`, `user_declared`, `unknown`, an undated estimate and any estimate dated after the session are rejected. The reason is reported in `rejected_thresholds`.
- **Declared FCmax check:** when the FCmax is declared, LT2 must be below it and the average HR must not exceed it. An *observed* historical maximum is only a lower bound of the true FCmax, so it is never used to reject anything.
- **Position:**
  - `below_LT1` when HR < LT1;
  - `above_LT2` when HR > LT2;
  - `between_LT1_LT2` when both thresholds are known and neither of the above applies;
  - `unknown` otherwise. This includes the case where only one threshold is known and the HR falls on its uncovered side.
- **Confidence:** the minimum of the threshold confidences, **capped at `medium`**. The limitation `average_hr_is_not_time_in_zone` is always present, and the engine never claims a dominant zone.

## 4. Classification rules (`session_classification`)

The rules are evaluated in this order:

1. **`intervals`:** V2 `session_structure == intervals` (a recorded recovery between efforts), with at least 2 efforts and at least 1 recovery. Confidence is `high` when V2 effort regularity is available, `medium` otherwise. **This is the only path to `intervals`.**
2. **`tempo_probable` from structure:** V2 structure `other`, with a single effort block, no recovery, a warm-up or cool-down, and effort average HR at or above a personal LT1. Confidence `medium`.
3. **`long_run_probable`:** duration at least **1.5×** the median duration of at least **5** strictly-prior same-sport sessions, with intensity `below_LT1` (confidence `medium`) or `unknown` (confidence `low`, volume-based only).
4. **`easy_run_probable`:** `below_LT1`. Confidence is at most `medium`.
5. **`steady_run_probable`:** `between_LT1_LT2`. Confidence `low`, limitation `tempo_not_distinguishable_from_average_hr`.
6. **`tempo_probable`:** `above_LT2` without phases. Confidence `low`, limitation `intervals_not_identifiable_without_phases`.
7. **Level C, individual history (only when `position = unknown`):** `easy_run_probable` or `steady_run_probable`, always with confidence `low`. See §12.
8. **`unknown`:** everything else.

A fast average pace or a high average HR **never** produces `intervals`.

## 5. Historical comparison rules

A candidate is eligible only if every one of these checks passes. Each failed check is counted in `exclusion_reasons`:

| Criterion | Exclusion code |
|---|---|
| Strictly before the session (datetime) | `not_strictly_prior` |
| Within the 180-day window (V2 constant) | `outside_window` |
| Same sport | `different_sport` |
| Same, **known** precise activity type. Treadmill and outdoor are never mixed; unknown is never mixed. | `different_environment`, `environment_unknown`, `current_environment_unknown` |
| Same training/race nature when both are known (V2 `_competition_flag`) | `different_session_nature` |
| Reference is not intervals or other structured work | `different_structure` |
| Valid pace and valid HR | `missing_pace`, `missing_or_aberrant_hr` |
| Duration within ±30% (reused V2 tolerance) | `duration_not_comparable`, `duration_unknown` |

Two cohorts are then built:

- **Pace at comparable HR:** references with |HR − current HR| ≤ **5 bpm**.
- **HR at comparable pace:** references with |pace − current pace| ≤ **15 s/km**.

Distance proximity alone never makes two sessions comparable.

Comparability levels:

- `strong`: at least 2 references (V2 `SIMILAR_MIN_COMPARABLE_SAMPLE`), with the current session and all references recorded as continuous;
- `moderate`: at least 2 references, but some structure is unknown (limitation `reference_structure_unknown`);
- `low`: 1 reference;
- `insufficient`: none.

If the current session is intervals or other structured work, its whole-session averages are not compared: status `not_applicable`.

## 6. Trend rules (`performance_trend`)

- **Observations:** the pace-at-comparable-HR cohort plus the current session. All observations must be on distinct dates.
- **Requirements:** at least **4** observations, at least **2** in each half, and a span of at least **21 days**. Otherwise `insufficient_data`.
- **Computation:** split the observations chronologically (the earlier half takes the odd extra one). `median_change` is the median pace of the later half minus the median pace of the earlier half, in s/km.
- **Status:**
  - `stable` when |change| < **10 s/km**;
  - `probable_improvement` or `possible_decline` only if **every** later observation moves past the earlier median by the margin, in the same direction;
  - otherwise `stable`, with `isolated_variation_not_confirmed`.
- **Observed variation vs probable evolution:** `observed_variation_sec_per_km` (current session vs references) is reported separately from `status`. `variation_confirmed` is true only for a trend status.
- **Confidence:** never `high`. It is `medium` only when all structures are recorded as continuous **and** the status does not change in the sensitivity grid. Otherwise it is `low`. The coach text mentions a trend only at `medium`.
- **Sensitivity:** the status is recomputed for HR tolerance ∈ {3, 5, 8} bpm × margin ∈ {5, 10, 15} s/km and exposed in `sensitivity`. Any disagreement adds `status_sensitive_to_criteria`.
- **Rationale for the constants:**
  - The 5 bpm tolerance is of the order of usual chest-strap or optical session-average variability.
  - 15 s/km is about 4% at 6:00/km.
  - The 10 s/km margin is below the pace band, so a trend requires a shift larger than the cohort's own matching noise.

  These values are **operational choices, not physiological constants**. The sensitivity grid exists to make their influence visible.

## 7. Abstention cases

| Situation | Output |
|---|---|
| No personal LT1/LT2, or thresholds are generic, low-confidence, undated, future-dated or inconsistent | `position=unknown`, classification `unknown` (unless phases or volume apply), advice to establish thresholds |
| HR missing, NaN, above 230 bpm, or average above max | `position=unknown`, `limit.hr_unusable`, no advice, trend `insufficient_data` |
| Fast session without phases | Never `intervals`. `tempo_probable` (low) when HR > LT2, else `unknown` |
| Too few, too close in time, or not comparable references | `insufficient_data` |
| Treadmill vs outdoor, or unknown environment | Excluded |
| Unknown structure of references | At most `moderate` comparability and `low` trend confidence. No trend sentence in the coach output. |
| No snapshot | `prescription_assessment=unavailable` |
| Snapshot not authoritative for the date | `unavailable` (`snapshot_not_authoritative_for_date`) |
| Local date not provable | `indeterminate` |
| Several snapshots or several same-day sessions | `indeterminate` |
| Session type unknown, or low confidence | `indeterminate` (never a forced deviation) |
| Race or rest prescription | `indeterminate` |

The coach output never states fatigue, overtraining, recovery or physiological progression, and never restates distance, duration, pace or HR totals on their own.

### Documented blocker

RunIndex currently persists **no personal LT1/LT2** and wires **no declared FCmax**:

- `runner_profile` holds `max_hr` only;
- `performance_model` states that `user_max_hr` is "wired to None at runtime".

The loader therefore resolves `lt_source_status="not_persisted"` (see §11 for the source-by-source evidence). In production, until a measured or estimated personal threshold source exists, every session will be:

- `intensity_assessment.position = "unknown"`;
- `session_classification` = `intervals` (from phases), `long_run_probable` (low confidence), a Level C relative classification (low confidence, §12) or `unknown`.

This is intentional. No threshold was invented, and no %FCmax formula was used, to work around it.

## 8. Test results

`cd backend && python -m pytest tests/test_workout_intelligence_v3.py` → **61 passed** (43 at the first C352 head, plus 18 loader-level tests from the correction in §11).

The 15 required scenarios map to tests as follows:

1. `test_easy_run_below_lt1_with_coherent_history`
2. `test_run_between_lt1_and_lt2_is_steady_with_low_confidence`
3. `test_missing_or_unreliable_thresholds_return_unknown` (5 variants), `test_generic_threshold_is_never_reported_as_personal`, `test_only_lt1_cannot_place_hr_above_it`
4. `test_fast_session_without_phases_never_becomes_intervals`
5. `test_intervals_identified_from_reliable_garmin_phases`
6. `test_improved_pace_at_comparable_hr_is_probable_improvement`
7. `test_isolated_fast_session_is_not_a_trend`
8. `test_insufficient_history`, `test_trend_requires_spread_in_time`
9. `test_treadmill_history_is_excluded_from_outdoor_session`, `test_unknown_environment_is_never_mixed`, `test_distance_proximity_alone_is_not_comparability`
10. `test_unknown_reference_structure_prevents_strong_conclusion`, `test_historical_interval_sessions_are_excluded`
11. `test_prescription_absent_or_not_authoritative`, `test_prescription_consistent_deviation_and_ambiguous`
12. `test_session_without_splits_is_fully_analyzed`
13. `test_missing_or_aberrant_hr` (4 variants)
14. `test_old_session_never_reads_future_data`, `test_engine_rejects_future_history_even_when_input_is_built_directly`
15. `test_translations_and_provenance` (FR/EN/ES), `test_translation_texts_differ_between_languages`, `test_coach_never_repeats_raw_totals_or_claims_fatigue`

Additional tests:

- **Loader:** read-only, user-scoped, strictly prior (`test_loader_*`), plus a source scan with no writes, Garmin calls, RAG or clock (`test_v3_sources_have_no_writes_garmin_calls_or_rag`).
- **Non-regression:**
  - V2 contract key set unchanged;
  - V2 result identical when the loader passes a superset of historical phases and types;
  - Training V2 `is_snapshot_authoritative` behaviour unchanged;
  - endpoint additive (403/404 handled, V2 route still present).

**Existing suites:**

- Workout Analysis V2, Coach Language, C351 synthesis, Coach Context V2 and Training V2 snapshot/week: 1144 passed, 3 failed.
- The 3 failures, `test_workout_analysis_v2.py::test_comparable_history_stays_separate_and_metrics_are_unchanged[en|fr|es]`, **also fail on the base commit** and are unrelated to this PR.
- Full backend suite, run serially (`-n 0 --continue-on-collection-errors`): the failure and error set is **identical** before and after this PR (environment failures: no MongoDB, missing optional packages). Passed tests rose from 4772 to 4814 (measured with 42 tests; one more test added after review).
- Under the default `-n 2` the totals vary between runs on the base commit itself (order-dependent tests), so the serial run is the reference comparison.

## 9. Known limitations

- **LT1/LT2 and declared FCmax:** not persisted anywhere (see §7 and §11), so intensity is `unknown` in production today.
- **Average HR only:** there is no time-in-zone distribution. Positions are average positions.
- **Not controlled:** terrain, elevation, weather, heat and cardiac drift (limitation `terrain_weather_not_controlled`).
- **Same-day ambiguity check:** it uses the stored `workouts.date` prefix, which can be UTC. This is conservative: it can only increase `indeterminate`.
- **Prescription check:** it compares session *type* only. Deviation advice ("keep easy days easy") is only emitted for `easy`, `recovery` or `long_easy` prescriptions. Prescribed distance and duration are reported, not judged.
- **Trend:** it uses pace at comparable HR. HR at comparable pace is reported as supporting evidence and does not drive the status.
- **Validation:** all results come from synthetic fixtures. **No real Garmin validation has been performed.**

## 10. Example outputs (synthetic)

These are full payloads in `docs/reports/c352_examples/`. They were regenerated through `load_scoped_workout_intelligence_v3` using a read-only fake DB, so they are **not real Garmin activities**.

**Reliable personal thresholds: footing below LT1 (FR)**, from `footing_below_lt1_fr.json`. The `physiological_metrics` are injected (LT1 150 / LT2 170 `lab_test` dated 2026-01-01, declared FCmax 192 dated 2026-01-15):

- `intensity_assessment.position = below_LT1`, confidence `medium`; `fcmax_bpm = 192` (`user_declared`); `observed_max_hr_bpm = 170` (4 observations, lower bound)
- `session_classification = easy_run_probable`, `decision_tier = personal_thresholds`
- `historical_comparison`: available, comparability `strong`, 4 references; `performance_trend = stable` (low)
- Diagnosis: « Probablement un footing d'endurance : la FC moyenne est restée sous votre LT1 personnel. »

**Intervals with Garmin phases (EN)**, from `intervals_with_phases_en.json`, with the runtime default inputs (no physiological data):

- `session_classification = intervals`, `decision_tier = garmin_phases`, confidence `high`, evidence `{effort_count: 5, recovery_count: 5}`
- `intensity_assessment.position = unknown`
- Diagnosis: "Interval session identified from 5 Garmin effort phases separated by recoveries."

**Probable footing without LT1/LT2 (FR)** and **indeterminate session (ES)**: see §12.6. The former `footing_without_thresholds_es.json` example is replaced by `indeterminate_session_es.json`.

## 11. Correction: physiological wiring

- **Reviewed head:** `8d66efc`.
- **Scope:** PR #352 only. No change to the LT1/LT2, VMA or Training V2 algorithms, no new formula, no Mongo write, no Garmin/GCCLI call, no frontend change.

### 11.1 Sources actually present (code inspection)

| Data | Real source | Persisted? | Usable by C352? |
|---|---|---|---|
| Personal FCmax | Contract only: `training_v2/runner_profile.py:408-410` reads `max_hr` / `max_heart_rate` from `physiological_metrics`, then `user_profile`. At runtime `week_plan_bridge.py:231-238` passes `physiological_metrics=None` and `user_profile` = active training preferences. Those are restricted to `sessions_per_week`, `preferred_training_days` and `preferred_long_run_day` (`training_preferences.py:12-18`, `extra="forbid"`). `performance_model` runs with `user_max_hr=None` (`week_plan_bridge.py:282`, `training_paces_authority.py:100`). No write path for an FCmax exists in `users`, `user_goals`, `training_prefs` or any other collection. | **No** | Wired: the loader accepts the same declared inputs and applies the same priority. Absent at runtime, so `fcmax_source="unavailable"`. |
| Observed max HR | `garmin_activities` `summaryDTO.maxHR` → `max_hr` (`garmin/data_layer.py:169`), copied to `workouts.max_heart_rate`. Unit bpm, per activity, dated by the activity. It is an observed value, not a physiological measurement. | Yes (per activity) | Yes, as `observed_max_hr_bpm` (strictly prior, 150–230 bpm, `_resolve_fcmax_robust`), and **only as a lower bound**. It is not used for zones or consistency checks. |
| LT1 | None. `lactate` appears only in docstrings that disclaim LT (`training_paces.py:164`, `engine/run_index_engine.py:172`, `training_intensity.py:11`). Garmin ingestion parses no lactate-threshold field. | **No** | No: `position=unknown`, `lt_source_status=not_persisted`. |
| LT2 | Same as LT1. `training_paces.T_FRACTION=0.88` is a VDOT **pace** fraction, not an HR threshold. | **No** | No. |
| Training V2 zones | `training_v2/training_paces.py`: Daniels VDOT **pace** zones E/M/T/I/R (min/km), recomputed from activities. They are not persisted as HR. The generator prescribes paces only (`workout_generator.py:91`: "hardcoded HR ranges → NOT MIGRATED"). | No (computed) | No. These are pace zones, not HR thresholds. They are reported as `kind="pace_based_not_hr"`. |
| `workouts.effort_zone_distribution` (bonus) | Optional legacy/manual field. Zone bounds have no provenance, and V2 already treats it as untrusted (`workout_analysis_v2.py:1242`, `_has_trusted_zone_provenance → False`). Garmin ingestion only records the `hasHrTimeInZones` flag. | Sometimes | No. It is reported as `kind="unverified"`. |

Conclusion: **no personal LT1/LT2 and no declared FCmax exist anywhere in RunIndex.** No raccordement can produce them. Per the instruction, the gap is shown here and is not worked around.

### 11.2 Changes

- `WIV3FcMax` is **declared only** (`user_declared` | `unavailable`, with `declared_on` and `provenance`). The observed maximum moved to `WIV3ObservedMaxHr` (`kind="observed_maximum_lower_bound"`).
- `resolve_physiological_profile(physiological_metrics, user_profile)` (pure):
  - **FCmax** uses the RunnerProfile priority and parser (`_first_valid_number`, `_parse_hr`).
  - **LT1/LT2** are read only from the V3 threshold contract (`physiological_metrics["lt1"|"lt2"]` with `source`, `estimated_on` and `confidence`).
  - It emits one `WIV3PhysiologicalSource` audit row per data item: `fcmax_declared`, `lt1`, `lt2`, `training_v2_zones`, plus `workout_hr_zone_distribution` when present.
- `assess_intensity`:
  - rejects a declared FCmax that is dated after the session or outside 150–230 bpm, and flags an undated one (`fcmax_declaration_date_unknown`);
  - exposes `observed_max_hr_bpm`, `observed_max_hr_observation_count` and `physiological_sources`.
- `session_classification.decision_tier` makes the hierarchy explicit:
  1. `garmin_phases` (intervals / structured block)
  2. `personal_thresholds` (average HR vs reliable LT1/LT2)
  3. `individual_history` (long run relative to the athlete's own median duration, intensity unknown)
  4. `insufficient_data` → `unknown`

  Slow pace never yields `easy_run_probable`, and average HR below LT1 is never presented as time below LT1 (`average_hr_is_not_time_in_zone`).
- `load_scoped_workout_intelligence_v3(..., physiological_metrics=None, user_profile=None)`: the endpoint passes nothing, like the Training V2 runtime.

### 11.3 Exact flow source → `intensity_assessment`

```
GET /api/coach/workout-intelligence/{id}
 └ load_scoped_workout_intelligence_v3(db, user, id, lang, physiological_metrics=None, user_profile=None)
    ├ workouts (+ garmin_activities: phases, type, local date) ── read-only
    ├ resolve_physiological_profile(physiological_metrics, user_profile)
    │    ├ FCmax  : physiological_metrics.max_hr|max_heart_rate → user_profile.max_hr|max_heart_rate → unavailable
    │    ├ LT1/LT2: physiological_metrics.lt1|lt2 {value_bpm, source, estimated_on, confidence} → else not_persisted
    │    └ sources[] audit (+ training_v2_zones = pace_based_not_hr)
    ├ extract_workout_intelligence_input(...)
    │    └ observed_max_hr(strictly-prior history)  (lower bound; _resolve_fcmax_robust)
    └ build_workout_intelligence_v3 → assess_intensity
         ├ _usable_threshold: source ∈ {lab_test, field_test, device_estimate}, confidence ∈ {high, medium},
         │                    estimated_on ≤ session date, LT1 < LT2, LT2 < declared FCmax
         ├ declared FCmax: date ≤ session, 150–230 bpm (consistency only)
         └ position vs average HR → below_LT1 | between_LT1_LT2 | above_LT2 | unknown
```

### 11.4 Tests (all synthetic, through the loader)

These are the `test_loader_*` tests added in `tests/test_workout_intelligence_v3.py`:

| Required case | Test |
|---|---|
| Persisted personal FCmax | `test_loader_declared_fcmax_follows_runner_profile_priority` (priority, provenance, undated, declared after session) |
| Garmin observed max only | `test_loader_observed_garmin_max_is_only_a_lower_bound` |
| Reliable LT1/LT2 | `test_loader_reliable_thresholds_place_footing_below_lt1` |
| Generic / unreliable LT1/LT2 | `test_loader_generic_or_unreliable_thresholds_are_rejected` (4 variants), `test_loader_generic_source_is_labelled_generic_not_personal`, `test_loader_hr_zone_distribution_is_flagged_unverified` |
| Thresholds computed after the session | `test_loader_thresholds_estimated_after_session_are_ignored` |
| Footing below LT1 | `test_loader_reliable_thresholds_place_footing_below_lt1` |
| Between LT1 and LT2 | `test_loader_session_between_lt1_and_lt2` |
| Intervals from Garmin phases | `test_loader_intervals_from_garmin_phases_without_thresholds` |
| No splits | `test_loader_session_without_splits_still_classified` |
| Insufficient history | `test_loader_insufficient_history` |
| No reliable physiological data | `test_loader_without_any_reliable_physiological_data`, `test_loader_runtime_default_abstains_and_audits_every_source`, `test_loader_slow_pace_alone_is_never_an_easy_run` |
| No regression of C352 comparison/trend | `test_loader_comparison_and_trend_unchanged_by_physiological_wiring`, plus the 43 existing tests |

**Results:**

- `python -m pytest tests/test_workout_intelligence_v3.py -n 0` → **61 passed**.
- Regression batch (V3 + `test_workout_analysis_v2.py` + `test_coach_context_v2.py` + runner_profile / performance_model / training_paces / prescription_snapshot / week_plan suites) → 639 passed, 5 failed. All 5 failures **also fail on `8d66efc`**:
  - `test_workout_analysis_v2.py::test_comparable_history_stays_separate_and_metrics_are_unchanged[en|fr|es]`
  - `test_pr165_week_plan_v2_authority.py::test_partial_reprise_distance_prescription_is_conserved`
  - `test_training_week_plan_route_removed.py` (needs MongoDB)

### 11.5 Residual limitations

- In production, V3 intensity stays `unknown` because no personal LT1/LT2 is stored. Since §12, footings can still be classified *relative to the athlete's history* (Level C, low confidence). **No validation on real Garmin activities was performed.**
- An observed maximum is only a lower bound. It cannot replace a declared FCmax, and V3 derives no zone from it.
- An undated declared FCmax (the RunnerProfile contract carries no date) is accepted for consistency checks only, with the limitation `fcmax_declaration_date_unknown`.

### 11.6 Smallest data work required (proposal, not implemented)

1. Persist a dated, user-scoped physiological profile, for example `physiological_profiles` with `{user_id, max_hr, max_hr_declared_on, lt1:{value_bpm, source, estimated_on, confidence}, lt2:{…}}`. This needs a write endpoint and a settings UI, so it is outside this PR.
2. In `get_workout_intelligence_v3`, read that document (read-only) and pass it as `physiological_metrics`. No engine change is needed: date validity, source and confidence filtering, and audit are already enforced and tested.
3. Optionally, ingest Garmin's own lactate-threshold HR (user settings) as `source="device_estimate"` with its measurement date. This would need a new GCCLI endpoint, which is out of scope here.

## 12. Correction: individual-history classification without LT1/LT2 (Level C)

- **Reviewed head:** `0907b4a`.
- **Scope:** PR #352 only. No frontend change, no new physiological engine, no FCmax formula, no LT1/LT2 created, no Garmin/GCCLI call, no Mongo write.

### 12.1 Hierarchy

| Tier (`decision_tier`) | Condition | Possible types |
|---|---|---|
| A `garmin_phases` | Reliable V2 phases: efforts separated by recoveries, or a single effort block with warm-up/cool-down | `intervals`, `tempo_probable` (the block rule needs a personal LT1) |
| B `personal_thresholds` | Reliable LT1/LT2, dated on or before the session (C352 rules, unchanged) | `easy_run_probable`, `steady_run_probable`, `tempo_probable`, `long_run_probable` |
| C `individual_history` | **Only** when `intensity_assessment.position = unknown` | `long_run_probable` (existing volume rule), `easy_run_probable`, `steady_run_probable`, all with confidence `low` |
| D `insufficient_data` | Everything else | `unknown`, with explicit `rules` and `limitations` |

A missing phase is **not** treated as a confirmed continuous session. Only a V2 `continuous` structure (`continuous_recorded`) allows the Level C `steady_run_probable`.

### 12.2 Level C method

`relative_effort_reference()` places the session's **average HR** within the distribution of average HRs from the athlete's own admissible earlier sessions. It uses robust statistics only: quartiles with `statistics.quantiles(method="inclusive")`, the interquartile range (IQR), and the minimum and maximum. No absolute HR, no %FCmax and no generic formula is used.

**Reference admissibility** (`_relative_exclusions`, independent from the comparison and trend eligibility, which is unchanged). Each excluded session is counted under its reason in `relative_effort.exclusions`:

| Criterion | Exclusion code |
|---|---|
| Strictly prior, within the V2 180-day window | `not_strictly_prior`, `outside_window` |
| Same sport | `different_sport` |
| Known and identical environment (`running` ≠ `treadmill_running`) | `environment_unknown`, `different_environment` |
| Not an identified competition (`_competition_flag` is True) | `competition` |
| No known interval or structured session | `interval_or_structured_session` |
| Valid pace | `missing_pace` |
| Valid HR (≤ 230 bpm, average ≤ max) | `missing_or_aberrant_hr` |
| Duration between 0.5× and 2× the current duration | `duration_unknown`, `duration_not_comparable` |

**Exact criteria.** These are module constants, exposed in `relative_effort.criteria`. They are operational choices, not physiological constants.

| Constant | Value | Justification |
|---|---|---|
| `RELATIVE_MIN_REFERENCES` | 8 references on 8 distinct days | Quartiles of fewer than 8 values are each driven by 1–2 sessions. |
| `RELATIVE_MIN_IQR_BPM` | 8 bpm | Below this, the central half of the history is too homogeneous to separate effort levels (`no_separation`). This is the guard against "almost every run is fast": a history dominated by sustained runs has a narrow IQR, so V3 abstains. |
| `RELATIVE_RANGE_MARGIN_BPM` | 5 bpm | Same value as the existing HR match tolerance. A current HR outside [min − 5, max + 5] of the references is not interpreted (`out_of_reference_range`). It could come from walking, pauses, the sensor or terrain. |
| `RELATIVE_DURATION_RATIO_RANGE` | 0.5–2.0× | Excludes much shorter or longer sessions, where HR drift differs. |

**Decision rules**, with relative position `low` when HR ≤ Q1, `high` when HR ≥ Q3, and `intermediate` otherwise:

| Situation | Result |
|---|---|
| `low`, and pace not faster than the references' fast quartile (pace Q1) | `easy_run_probable`, `low` |
| `low` with a pace in the fastest quartile | `unknown` (`incoherent_hr_pace`, `low_hr_with_fast_pace_not_interpreted`) |
| `high`, V2 structure `continuous`, and pace not slower than the slow quartile (pace Q3) | `steady_run_probable`, `low` (limitation `tempo_not_distinguishable_from_average_hr`) |
| `high` with a slow pace | `unknown` (`high_hr_with_slow_pace_not_interpreted`) |
| `high` without a recorded continuous structure | `unknown`. The session could be intervals without phases. |
| `intermediate` | `unknown` |
| Current session is a competition, is structured, has an unusable HR, no pace or an unknown environment | `relative_effort.status = not_applicable`, `unknown` |
| Long run (existing volume rule) | Kept, except when the relative position is `high` |

The `relative_effort` block always reports:

- the current HR and pace;
- the reference count and workout IDs;
- the period (`period_start`, `period_end`);
- the HR minimum, Q1, median, Q3, maximum and IQR;
- the pace Q1 and Q3;
- the exclusions, criteria, status and limitations.

### 12.3 Relative vs physiological intensity

- `intensity_assessment.position` keeps its meaning: physiological position against **personal LT1/LT2**. Without reliable thresholds it stays `unknown`, even when the session is classified at Level C. The combination `position=unknown` + `easy_run_probable / low / individual_history` is intended.
- A relatively low HR **is not proof** of easy physiological intensity. Every Level C output carries:
  - `relative_effort_not_physiological_intensity` (classification);
  - `relative_position_is_not_a_physiological_zone` and `low_hr_may_reflect_walking_pauses_sensor_or_terrain` (`relative_effort`);
  - the coach limitation `limit.relative_not_physiological`.
- Coach wording, FR/EN/ES. Diagnoses `diagnosis.easy_run_relative` and `diagnosis.steady_run_relative`, plus evidence `evidence.relative_hr_low` / `evidence.relative_hr_high` (HR, count, quartiles). For example: « Cette séance ressemble à un footing relativement facile par rapport à vos efforts habituels. » / « Votre FC moyenne (139 bpm) se situe dans la partie basse de vos 12 séances de référence personnelles… » / « Sans seuil LT1 fiable, je ne peux pas confirmer une zone d'intensité physiologique… ». No "zone 2", "fundamental endurance", fatigue, recovery or adaptation claims (tested). No new training advice: the only advice remains the pre-existing threshold-measurement advice.
- `historical_comparison`, `performance_trend` and comparison eligibility are **unchanged**. Classification and trend stay independent (tested: identical dumps with and without thresholds).
- `prescription_assessment` still sees confidence `low`, so it returns `indeterminate` and never a forced deviation.

### 12.4 Misclassification risks (residual)

- A runner whose "easy" runs are all too hard still gets a *relative* label. This is mitigated by the IQR guard and by the wording, but not eliminated: a varied history of runs that are all hard would still yield a low quartile.
- Average HR hides within-session variation. Intervals without phases with long recoveries can have a low average. The limitation `intervals_not_identifiable_without_phases` is always present.
- Heat, terrain, elevation, sensor drop-outs and cardiac drift are not controlled. Heart-rate trends over months (fitness changes) shift the distribution, and the 180-day window bounds but does not remove this.
- The quartile thresholds and the 8-bpm IQR are operational choices, not physiological constants.

### 12.5 Tests

`python -m pytest tests/test_workout_intelligence_v3.py -n 0` → **85 passed**. All fixtures are synthetic and run through `load_scoped_workout_intelligence_v3` with a read-only fake DB.

| # | Required case | Test |
|---|---|---|
| 1 | Probable footing, varied history | `test_level_c_easy_run_with_varied_history_without_thresholds` |
| 2 | Without splits | `test_level_c_easy_run_without_splits` |
| 3 | Insufficient history | `test_level_c_insufficient_history_abstains` |
| 4 | Homogeneous history | `test_level_c_homogeneous_history_abstains` |
| 5 | Mostly sustained history | `test_level_c_mostly_sustained_history_is_not_an_easy_reference` |
| 6 | Slow session with high HR | `test_level_c_slow_session_with_high_hr_is_never_easy` |
| 7 | Fast session with low HR | `test_level_c_fast_session_with_low_hr_is_not_interpreted`, `test_level_c_hr_far_below_reference_range_may_be_an_artifact` |
| 8 | Intervals from Garmin phases | `test_level_a_phases_keep_priority_over_relative_history` |
| 9 | Intervals without phases | `test_level_c_high_effort_without_recorded_structure_stays_unknown` |
| 10 | Competition exclusion | `test_level_c_competitions_are_excluded` |
| 11 | Treadmill / outdoor | `test_level_c_treadmill_and_outdoor_are_never_mixed` |
| 12 | Strictly prior | `test_level_c_uses_strictly_prior_history_only` |
| 13 | Missing / aberrant HR | `test_level_c_missing_or_aberrant_hr_abstains` (3 variants), `test_level_c_aberrant_reference_hr_is_excluded` |
| 14 | No LT1/LT2 | covered by test 1 (`position=unknown`, `lt1=lt2=None`) |
| 15 | Reliable LT1/LT2 keep priority | `test_level_b_reliable_thresholds_keep_priority` |
| 16 | Trend non-regression | `test_level_c_does_not_change_comparison_or_trend`, plus the existing trend tests |
| 17 | FR / EN / ES | `test_level_c_coach_assessment_is_translated` (3 variants) |
| — | Intermediate effort / steady | `test_level_c_intermediate_effort_stays_unknown`, `test_level_c_high_effort_with_recorded_continuous_structure_is_steady` |

**Regressions.** Batch run of V3, V2, Coach Context V2, Coach Language, session synthesis, runner_profile, performance_model, training_paces, prescription_snapshot and week_plan: **1081 passed, 5 failed**. The 5 failures are the same tests that already fail on `8d66efc` and `0907b4a`:

- `test_workout_analysis_v2.py::test_comparable_history_stays_separate_and_metrics_are_unchanged[en|fr|es]`
- `test_pr165_week_plan_v2_authority.py::test_partial_reprise_distance_prescription_is_conserved`
- `test_training_week_plan_route_removed.py` (needs MongoDB)

No new regression.

### 12.6 Example JSON outputs (synthetic, complete payloads)

- **`c352_examples/footing_relative_history_fr.json`**: probable footing without LT1/LT2.
  - `position=unknown`; `easy_run_probable`, `low`, `individual_history`.
  - `relative_effort`: `used`, `low`, 12 references from 2026-01-02 to 2026-03-23, Q1 141.5 / median 151 / Q3 160.5 bpm, current HR 139 bpm.
  - Comparison: `strong`; trend: `stable`.
- **`c352_examples/indeterminate_session_es.json`**: indeterminate session.
  - Same history, HR 151 bpm.
  - `relative_effort`: `used`, `intermediate`.
  - Classification `unknown`, `insufficient_data`, rule `relative_effort_intermediate_type_not_identifiable`.
  - The historical comparison stays descriptive.
- **`c352_examples/intervals_with_phases_en.json`**: Garmin intervals.
  - `intervals`, `garmin_phases`, `high`; `relative_effort.status = not_evaluated`.
- `c352_examples/footing_below_lt1_fr.json` (unchanged scenario, regenerated): Level B with injected reliable thresholds.

These outputs are simulations. **They are not a validation on real Garmin activities.**
