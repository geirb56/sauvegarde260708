# RUNINDEX PR230 REPORT — PRESCRIBED vs PERFORMED (Garmin actual)

**Branch:** `copilot/create-data-moat-first-brick`
**Base:** `copilot/dev`
**Prerequisite:** PR #229 merged into `copilot/dev` — ✅ verified (`a92fdf5 Merge pull request #229`)
**Runtime:** DEFERRED TO FINAL RUNTIME GATE
**Revision:** C230 corrections applied on top of `8945213` (4 Data Truth blockers).

---

## Objective

First real Data Moat brick: separate

```
RUNINDEX PRESCRIPTION   ≠   TRAINING ACTUALLY PERFORMED
```

Target chain:

```
Prescription
  → real Garmin activity (garmin_activities → DomainActivity)
  → deterministic matching
  → PerformedWorkout
  → adherence / outcome
```

This PR delivers the **engine + contract + tests + audit**. It deliberately does
**not** touch the UX / API consumers — that is #231.

---

## Source of truth

| Concern | Source |
|---|---|
| What was actually performed | `garmin_activities` → `mongo_garmin_to_observed_activity()` (dedicated adapter, Garmin provenance + real local time enforced) → `ObservedActivity` |
| What was prescribed | plan layer (`WorkoutPrescription` / weekly plan) → copied into `PrescribedWorkout` |
| **NOT** used as Garmin truth | `db.workouts` (explicitly excluded, documented in the module docstring) |

The prescription stays independent of the observed activity. The engine never
rewrites a prescription to make it fit an activity (all models are frozen; a
regression test asserts non-mutation).

---

## Exact model — prescription vs actual

### `PrescribedWorkout` (input, frozen)

| Field | Type |
|---|---|
| `prescription_id` | `str` |
| `user_id` | `str` |
| `planned_date` | `date` |
| `workout_type` | `str` (`rest \| recovery \| easy \| steady \| quality \| long_easy`) |
| `intensity_class` | `Optional[str]` |
| `planned_distance_km` | `Optional[float]` |
| `planned_duration_min` | `Optional[float]` |
| `planned_pace_min_per_km` | `Optional[float]` — only when a pace was really prescribed |
| `planned_start_time` | `Optional[time]` — only when a start time was really prescribed (C230 #2) |

### `ObservedActivity` (input, frozen — Garmin truth)

`activity_id`, `user_id`, `local_date`, `start_time`, `source`,
`activity_type`, `distance_km`, `duration_min`, `pace_min_per_km`.

Built by `to_observed_activity(domain_activity, user_id=..., local_start_time=...)`,
normally through the dedicated adapter
`garmin.domain_adapter.mongo_garmin_to_observed_activity(doc, user_id=...)`.
An activity with non-Garmin provenance, no real local start time, or no stable
id is refused (returns `None`).

### `PerformedWorkout` (output, frozen)

`user_id`, `prescription_id`, `activity_id`, `planned_date`,
`actual_start_time`, `planned_workout_type`, `actual_activity_type`,
`planned_distance_km`, `actual_distance_km`, `planned_duration_min`,
`actual_duration_min`, `planned_intensity_class`, `planned_pace_min_per_km`,
`actual_pace_min_per_km`, `matching_status`, `adherence_status`,
`distance_delta_km`, `duration_delta_min`, `pace_delta_min_per_km`,
`distance_deviation_ratio`, `duration_deviation_ratio`, `pace_deviation_ratio`,
`comparison_dimensions`, `deviation_ratio`, `candidate_activity_ids`,
`reason_codes`.

`PerformedWorkoutLedger` wraps the rows with `user_id`, `reference_date` and the
five counters (`matched / missed / planned / ambiguous / unmatched_actual`).

**No missing value is ever replaced by 0.** Absent = `None`, everywhere.

---

## C230 #1 — Real Garmin local date contract

### The bug

| Layer | Field | Priority |
|---|---|---|
| `garmin_activity` sub-document (`GarminActivity.from_summary`) | `start_time` | **GMT first** (`startTimeGMT` → `startTimeLocal`) |
| top-level Mongo document (`gccli_provider`) | `start_time` | **local first** (`startTimeLocal` → `startTimeGMT`) |

`mongo_garmin_to_domain()` prefers the sub-document, so
`DomainActivity.start_time` is **GMT-first**. A run started at `00:30` local
(`22:30` GMT the previous day) was therefore attributed to the **wrong calendar
day**.

### The fix

1. `GarminActivity` now carries an explicit `start_time_local` field, populated
   from `startTimeLocal` only (`backend/garmin/data_layer.py`). It is persisted
   through the existing `model_dump()` in `gccli_provider`.
2. `garmin.domain_adapter.garmin_local_start_time(doc)` resolves the REAL local
   start time with **no GMT fallback**:
   1. `garmin_activity.start_time_local`
   2. document-level `startTimeLocal`
   3. top-level `start_time` — **only** when it differs from the sub-document
      GMT value (otherwise it is provably the GMT fallback and carries no local
      evidence)
   → `None` when no local evidence exists.
3. `mongo_garmin_to_observed_activity(doc, user_id=...)` is the dedicated
   `garmin_activities` → `ObservedActivity` adapter.
4. `to_observed_activity(..., local_start_time=...)` now **requires** the local
   time explicitly. `DomainActivity.start_time` is never used for the day.

**Contract:** `ObservedActivity.local_date` is always a real Garmin
`startTimeLocal` day. When no local evidence exists the activity is refused
rather than matched on a GMT-derived day.

Source chain unchanged: `garmin_activities` → Garmin normalisation → domain →
`ObservedActivity`. `db.workouts` is still never used.

---

## C230 #4 — Guaranteed Garmin provenance

- `to_observed_activity` returns `None` unless `DomainActivity.source == "garmin"`.
- `mongo_garmin_to_observed_activity` additionally requires the Mongo document
  itself to carry `source == "garmin"` at the top level (as written by the
  Garmin sync in `gccli_provider.py`). There is no sub-document fallback and no
  `model_copy` that would rewrite the domain source.
- `build_performed_workouts` re-checks `activity.source == GARMIN_SOURCE`, so a
  hand-built `ObservedActivity` cannot smuggle in non-Garmin evidence.
- **No fallback re-labels an activity as Garmin.** `legacy`, `manual`,
  `workout`, `strava`, `None` → refused.

---

## States

| `matching_status` | Meaning |
|---|---|
| `planned` | window still open, or future session — nothing asserted |
| `matched` | a real running activity was deterministically attributed |
| `missed` | window definitively closed, no acceptable activity, **and no ambiguity** |
| `ambiguous` | several activities are equally compatible — the engine refuses to choose (C230 #2) |
| `unmatched_actual` | real running activity attributable to no prescription |

There is **no `completed` state** produced by this engine. A past session never
becomes "completed" automatically.

| `adherence_status` | Meaning |
|---|---|
| `completed_as_planned` | matched, **all** comparable dimensions ≤ 10 % |
| `completed_modified` | matched, at least one comparable dimension > 10 % (all ≤ 50 %) |
| `completed_unverified` | matched on date + running type, no comparable dimension at all |
| `missed` | mirrors `missed` |
| `ambiguous` | mirrors `ambiguous` |
| `unmatched_actual` | mirrors `unmatched_actual` |
| `pending` | nothing can be asserted yet |
| `not_applicable` | rest day — never matched, never missed |

No arbitrary "physiological adherence score". Only raw signed deltas
(`actual − planned`) plus per-dimension deviation ratios.

---

## Matching algorithm (deterministic, no LLM, no fuzzy)

```
1. Keep prescriptions with prescription.user_id == user_id
   sort by (planned_date, prescription_id)                     ← deterministic order
2. Keep activities with activity.user_id == user_id
   AND activity.source == "garmin"                             ← provenance lock
   AND local_date <= reference_date                            ← no-lookahead
   AND activity_type ∈ {running, trail_running, treadmill_running}
   sort by (local_date, start_time, activity_id)               ← output stability only
3. For each prescription, in order:
   a. rest day  → planned / not_applicable, STOP
   b. candidates = free activities whose LOCAL date is inside
      [planned_date - 0d, planned_date + 0d]
   c. compute the deviation of EVERY dimension comparable on both sides:
        distance : planned_distance_km      vs actual distance
        duration : planned_duration_min     vs actual duration
        pace     : planned_pace_min_per_km  vs actual pace   (only if prescribed)
      deviation = |actual - planned| / planned
   d. reject a candidate as soon as ANY comparable dimension deviates by
      more than 50 %                                  (CANDIDATE_REJECTED_DEVIATION)
   e. no remaining candidate →
        window closed ? missed : planned
   f. rank remaining candidates by:
        1. worst deviation across comparable dimensions
        2. gap to planned_start_time, ONLY when a start time was prescribed
      → if the top-2 ranks are strictly equal: matching_status = ambiguous
        (never missed), candidates stay unattributed
      → else: best candidate is matched, and consumed
        (one activity is attributed to at most one prescription)
4. Every remaining running activity → unmatched_actual (never dropped)
```

### Calibration constants (V1, recalibrable — not physiological law)

| Constant | Value | Role |
|---|---|---|
| `MATCH_WINDOW_DAYS_BEFORE` | `0` | window lower bound |
| `MATCH_WINDOW_DAYS_AFTER` | `0` | window upper bound |
| `ADHERENCE_TOLERANCE_RATIO` | `0.10` | as-planned vs modified |
| `MATCH_MAX_DEVIATION_RATIO` | `0.50` | beyond → not the realisation of that session |

---

## C230 #3 — Multi-dimension adherence logic

A dimension is **comparable** only when both sides carry a strictly positive
value. A missing dimension is never fabricated, and pace is only compared when
a pace was **really prescribed** (never derived from planned distance/duration).

```
deviations = {d : |actual_d - planned_d| / planned_d  for every comparable d}
worst      = max(deviations)

worst > 50 %                    → NOT the realisation → candidate rejected
no comparable dimension         → matched + completed_unverified
worst <= 10 %                   → matched + completed_as_planned
otherwise                       → matched + completed_modified
```

Worked cases:

| Prescribed | Performed | Deviations | Result |
|---|---|---|---|
| 10 km / 60 min | 10 km / 60 min | dist 0 %, dur 0 % | `matched` + `completed_as_planned` |
| 10 km / 60 min | 10 km / 75 min | dist 0 %, **dur 25 %** | `matched` + `completed_modified` |
| 10 km / 60 min | 10 km / 120 min | dist 0 %, **dur 100 %** | **not matched** → prescription `missed`, activity `unmatched_actual` |
| — / 60 min | 10 km / 62 min | dur 3 % | `matched` + `completed_as_planned`, distance never fabricated |
| 10 km @ 5:00/km | 10 km / 65 min (6:30/km) | dist 0 %, **pace 30 %** | `matched` + `completed_modified` |
| 10 km @ 4:00/km | 10 km / 90 min (9:00/km) | **pace 125 %** | **not matched** |

The previous single-basis logic (`distance` else `duration`) could report
10 km / 120 min as `completed_as_planned`; that is now impossible.

Raw signed deltas (`distance_delta_km`, `duration_delta_min`,
`pace_delta_min_per_km`) and per-dimension ratios are always kept.

---

## Date / timezone window

- The matching key is the **real Garmin local calendar date** (`startTimeLocal`),
  never a GMT-derived day (see C230 #1).
- Window V1 = the planned local day only (`before = after = 0`). A wrong date or
  a wrong timezone therefore cannot create a false match: it simply does not
  match, and the activity remains visible as `unmatched_actual`.
- `missed` requires `reference_date > planned_date + MATCH_WINDOW_DAYS_AFTER`
  (strict). On the planned day itself the session is still `planned`.

---

## Multi-activity resolution / ambiguity policy (C230 #2)

- Ranking key = `(worst deviation across comparable prescribed dimensions,
  gap to the prescribed start time)`.
- **Clock time is not a business criterion by itself.** Without a
  `planned_start_time`, an earlier run is *not* better evidence than a later
  one, so the second key is neutral for every candidate and a tie stays a tie.
- `activity_id` is never part of the decision key.
- Strict tie → `matching_status = ambiguous`, `adherence_status = ambiguous`,
  `candidate_activity_ids` lists the tied activities, and **nothing is
  attributed**. Those activities remain `unmatched_actual`.
- An ambiguous prescription is **never matched, never missed, never completed** —
  including after the matching window has closed.
- A candidate that is clearly better on the prescribed dimensions is matched
  deterministically, even when it is the later run.

---

## No-lookahead guarantees

- `reference_date` is mandatory and explicit; the module never calls
  `datetime.now()` / `date.today()` (asserted by test).
- Activities with `local_date > reference_date` are removed **before** any
  matching: they can neither match nor appear as `unmatched_actual`.
- A future prescription is always `planned`, never `missed`, never completed.
- Replaying a historical `reference_date` with newer data reproduces the
  historical state exactly (tested).

---

## Files touched

| File | Change |
|---|---|
| `backend/training_v2/performed_workout.py` | **New** — models, enums, reason codes, deterministic matching engine `build_performed_workouts()`, provenance-locked `to_observed_activity()`. C230: `ambiguous` state, multi-dimension adherence, mandatory `local_start_time`, `source == "garmin"` lock. |
| `backend/garmin/data_layer.py` | C230 #1 — `GarminActivity.start_time_local` populated from `startTimeLocal` only (additive, non-breaking). |
| `backend/garmin/domain_adapter.py` | C230 #1/#4 — `garmin_local_start_time()`, `mongo_garmin_to_observed_activity()`, `mongo_garmin_to_observed_activities()`: the sanctioned `garmin_activities` → `ObservedActivity` boundary. |
| `backend/training_v2/__init__.py` | Export the PR230 public surface. |
| `backend/tests/test_performed_workout_pr230.py` | **New** — 72 tests. |
| `RUNINDEX_PR230_REPORT.md` | **New** — this report. |

No runtime endpoint, no consumer and no legacy behaviour was modified in this PR.

---

## Tests executed

Commands (from `backend/`):

```
python -m pytest tests/test_performed_workout_pr230.py -q                 → 72 passed
python -m pytest tests/test_performed_workout_pr230.py \
                tests/test_mongo_garmin_boundary_pr137.py \
                tests/test_garmin_data_layer.py \
                tests/test_garmin_activity_normalization_pr02.py \
                tests/test_daily_adaptation_pr133.py -q                   → 176 passed
```

**0 FAIL, 0 SKIP** on the PR230 scope and on all replayed neighbour suites
(Garmin domain adapter / Mongo boundary, Garmin data layer + activity
normalisation, DomainActivity, TrainingHistory consumers, DailyAdaptation).

> Note: a broader `-k "garmin or training_v2 or domain"` sweep also surfaces
> pre-existing environment failures unrelated to this PR (missing `fastapi`,
> `httpx`, `pymongo`, no asyncio plugin, network-dependent tests). None of them
> touch the PR230 scope.

### Original mandate

| Required test | Status | Test |
|---|---|---|
| prescribed + compatible Garmin run → matched | PASS | `test_planned_session_with_compatible_run_is_matched` |
| prescribed + no activity after window end → missed | PASS | `test_no_activity_after_window_end_is_missed` |
| future session without activity → planned | PASS | `test_future_session_is_planned_never_missed_never_completed` |
| extra activity without prescription → unmatched_actual | PASS | `test_extra_activity_without_prescription_is_unmatched_actual`, `test_second_run_same_day_stays_visible_as_unmatched_actual` |
| non-running activity never matched | PASS | `test_non_running_activity_is_never_matched` (4 params), `test_all_running_types_are_matchable` |
| two runs same day → deterministic or ambiguous | PASS | `test_two_runs_same_day_deterministic_best_match`, `test_two_strictly_equivalent_runs_are_ambiguous_and_not_matched`, `test_one_activity_is_attributed_to_at_most_one_prescription` |
| wrong date / timezone → no false match | PASS | `test_activity_on_another_day_does_not_match`, `test_local_date_drives_matching_not_utc_string` |
| very different distance → documented rule | PASS | `test_moderate_distance_deviation_is_completed_modified`, `test_extreme_distance_deviation_is_not_matched` |
| very different duration → documented rule | PASS | `test_case_D_duration_used_when_distance_absent_on_one_side`, `test_extreme_duration_deviation_is_not_matched` |
| no mutation of the original prescription | PASS | `test_prescription_is_never_mutated`, `test_prescription_model_is_frozen`, `test_performed_workout_keeps_planned_values_untouched` |
| no `None → 0` | PASS | `test_missing_values_stay_none_never_zero`, `test_unmatched_actual_row_has_no_fabricated_planned_values`, `test_zero_distance_activity_is_not_turned_into_zero_value` |
| multi-user isolation | PASS | `test_other_user_activity_never_matches`, `test_other_user_prescription_is_ignored` |
| no-lookahead | PASS | `test_future_activity_cannot_change_a_historical_prescription`, `test_historical_state_is_stable_when_replayed` |
| deterministic result | PASS | `test_result_is_deterministic_across_runs_and_input_order`, `test_full_mongo_to_ledger_integration_is_deterministic` |
| **the PR230 engine** never auto-marks completed | PASS | `test_engine_never_emits_a_completed_matching_status`, `test_past_session_without_evidence_is_never_completed`, `test_engine_module_has_no_io_dependencies` |
| **legacy consumers** cannot auto-mark completed | **FAIL — NOT FIXED, DEBT #231** | not testable here; see audit below |

### C230 #1 — real Garmin local date

| Scenario | Status | Test |
|---|---|---|
| `startTimeLocal 2026-06-10 00:30` / `startTimeGMT 2026-06-09 22:30`, prescription `2026-06-10` → MATCHED on 10 June, through the real Mongo chain | PASS | `test_mongo_chain_matches_on_real_local_day_not_gmt_day` |
| the GMT day (06-09) must not receive the activity | PASS | `test_mongo_chain_does_not_match_the_gmt_day` |
| regression guard: `DomainActivity.start_time` really is the GMT day | PASS | `test_domain_start_time_alone_would_have_picked_the_wrong_day` |
| explicit local field wins over a degraded top-level value | PASS | `test_garmin_local_start_time_prefers_explicit_local_field` |
| GMT-only document → refused, no fabricated local day | PASS | `test_garmin_local_start_time_refuses_gmt_only_document` |
| raw `startTimeLocal` key accepted | PASS | `test_garmin_local_start_time_accepts_raw_start_time_local_key` |
| Garmin normalisation really exposes `start_time_local` | PASS | `test_garmin_activity_model_exposes_start_time_local` |
| unusable documents skipped | PASS | `test_mongo_garmin_to_observed_activities_skips_unusable_documents` |
| full chain Mongo → domain → ObservedActivity → ledger | PASS | `test_full_mongo_to_ledger_integration_is_deterministic` |

### C230 #2 — ambiguity ≠ missed

| Scenario | Status | Test |
|---|---|---|
| two identical 10 km runs at 07:00 and 18:00, prescription without a time → AMBIGUOUS | PASS | `test_two_identical_runs_morning_and_evening_are_ambiguous` |
| same situation after the window closed → still AMBIGUOUS, never MISSED | PASS | `test_ambiguity_stays_ambiguous_after_window_closes` |
| ambiguous is never matched / missed / completed | PASS | `test_ambiguous_prescription_is_never_matched_missed_or_completed` |
| a clearly better candidate on prescribed dimensions → deterministic MATCHED | PASS | `test_clearly_better_candidate_on_prescribed_dimensions_is_matched` |
| a really prescribed start time is a legitimate tiebreaker | PASS | `test_prescribed_start_time_is_a_legitimate_tiebreaker` |
| without a prescribed start time, the earlier run is not preferred | PASS | `test_without_prescribed_start_time_earlier_run_is_not_preferred` |

### C230 #3 — multi-dimension adherence

| Case | Scenario | Status | Test |
|---|---|---|---|
| A | 10 km / 60 min → 10 km / 60 min = `completed_as_planned` | PASS | `test_case_A_all_dimensions_within_tolerance_is_as_planned` |
| B | 10 km / 60 min → 10 km / 75 min = `completed_modified` | PASS | `test_case_B_perfect_distance_but_long_duration_is_modified_not_as_planned` |
| C | 10 km / 60 min → 10 km / 120 min = incompatible, never `completed_as_planned` | PASS | `test_case_C_perfect_distance_but_double_duration_is_never_as_planned` |
| D | distance absent, duration comparable → duration used | PASS | `test_case_D_duration_used_when_distance_absent_on_one_side` |
| E | prescribed pace vs very different real pace → not ignored | PASS | `test_case_E_prescribed_pace_divergence_is_not_ignored` |
| E' | extreme prescribed-pace divergence → candidate rejected | PASS | `test_extreme_prescribed_pace_divergence_rejects_the_candidate` |
| — | pace never compared when not really prescribed | PASS | `test_pace_is_never_compared_when_not_really_prescribed` |

### C230 #4 — Garmin provenance

| Scenario | Status | Test |
|---|---|---|
| `source=garmin` accepted | PASS | `test_garmin_source_is_accepted_as_evidence` |
| `source=legacy/workout/manual/strava/None` refused | PASS | `test_non_garmin_source_is_refused_as_evidence` (5 params) |
| no fallback re-labels an activity as Garmin | PASS | `test_no_fallback_relabels_an_activity_as_garmin` |
| engine drops non-Garmin ObservedActivity | PASS | `test_engine_drops_activities_whose_source_is_not_garmin` |

**Totals: 72 PASS / 0 FAIL / 0 SKIP** on `test_performed_workout_pr230.py`.

Runtime / E2E validation: **DEFERRED TO FINAL RUNTIME GATE**.

---

## Consumer audit — who still confuses "prescribed" with "performed"

Read-only audit; nothing was changed. This is the input backlog for #231.

> **Explicit correction (C230 #5).** The statement
> *"no legacy consumer can auto-mark a session completed"* is **NOT** globally
> PASS.
>
> - ✅ **TRUE for the PR230 engine**: it never produces `completed`, and a past
>   session without Garmin evidence can only become `missed` or `ambiguous`.
> - ❌ **FALSE for the existing consumers**: they are untouched by this PR and
>   still auto-mark sessions as done. Two live offenders:
>   1. `frontend/src/pages/TrainingPlanV2.jsx:141` — `dayIndex < todayIndex ? "done" : "planned"`:
>      every past day is rendered as done from the calendar alone.
>   2. `backend/server.py:3284–3322` (`POST /training/feedback`) + `Dashboard.jsx`
>      Done/Missed buttons — user self-report accepted with **no Garmin proof**.
>
> These are declared **open debt for #231**, not resolved here.

### Backend

| File | Lines | Finding | Proof of real activity? |
|---|---|---|---|
| `backend/server.py` | 3284–3322 | `POST /training/feedback` accepts `done` / `missed` purely as user self-report | ❌ none |
| `backend/server.py` | 3299–3307 | Feedback stored against an arbitrary `workout_id`, no link to `garmin_activities` | ❌ none |
| `backend/server.py` | 3484–3488, 3535 | `/training/today` returns `recent_feedback` as if it were factual execution | ❌ self-report |
| `backend/server.py` | 4107–4117 | `/training/v2/week` returns prescriptions with **no execution status field at all** | n/a (gap) |
| `backend/services/dashboard_service.py` | ~67 | `today_workout` selection ignores whether past prescriptions were really performed | ❌ ignored |
| `backend/training_v2/training_response.py` | whole module | `RecentTrainingResponse` aggregates observed activity but never matches it to prescriptions | ❌ never matched |
| `backend/training_v2/daily_runtime_helpers.py` | 88–113 | Prescription treated as truth, not validated against actual activity | ❌ none |
| `backend/coach_service.py` | 54–87 | Coach reasons on unverified past prescriptions | ❌ none |

### Frontend

| File | Lines | Finding | Proof of real activity? |
|---|---|---|---|
| `frontend/src/pages/TrainingPlanV2.jsx` | **141** | **`dayIndex < todayIndex ? "done" : "planned"`** — a past day is displayed as done by calendar position alone | ❌ **none — main offender** |
| `frontend/src/pages/TrainingPlanV2.jsx` | 143–149, 369 | Checkmark rendering driven by the same date-only logic | ❌ none |
| `frontend/src/pages/TrainingPlanV2.jsx` | 51–62 | `getSessionStatusKey()` reads `session.status / state / completion_status` — fields the backend never sends | ❌ n/a |
| `frontend/src/pages/Dashboard.jsx` | 677–702, 688 | `handleFeedback()` stores done/missed locally, never cross-checked with Garmin | ❌ self-report |
| `frontend/src/pages/Dashboard.jsx` | 1019–1041 | "Done" / "Missed" buttons can mark any session | ❌ arbitrary |
| `frontend/src/i18n.js` | 584, 1380 | "Done" / "Completed" wording reinforces the unverified completion concept | ⚠️ wording |

**Root cause:** the backend exposes prescriptions only (no execution status), so
the frontend fabricates one from the calendar, and the feedback endpoint accepts
self-declared completion without any Garmin evidence.

---

## Debt deliberately left for #231

1. **`TrainingPlanV2.jsx:141` still marks past days `done` from the calendar.**
   Not fixed here — this is the flagship UX offender.
2. **`POST /training/feedback` still accepts self-declared `done`/`missed`
   without any Garmin evidence**, and `Dashboard.jsx` still exposes the buttons.
   The reconciliation policy between *"user says done"* and `matching_status`
   belongs to #231.
3. **No consumer is wired to this engine yet.** No endpoint returns
   `matching_status`; `/training/v2/week` still ships prescriptions without any
   execution state.
4. **No persistence.** `PerformedWorkout` is computed, not stored. A
   `performed_workouts` collection / migration is out of scope here.
5. **Backfill of `start_time_local`.** New Garmin syncs persist it; documents
   ingested before this PR keep only the local-first top-level `start_time`, and
   GMT-only legacy documents are deliberately refused as evidence rather than
   matched on a possibly wrong day.
6. **Window calibration is V1** (same local day only). Widening it (e.g. ±1 day)
   is a product decision, not a bug fix.
7. **Ambiguity has no UX yet.** `matching_status = ambiguous` and
   `candidate_activity_ids` need an explicit "we cannot tell" presentation
   instead of being silently rendered as done or missed.
8. **Non-running cross-training** is out of scope of the running ledger; it is
   neither matched nor reported.
9. **Multi-timezone travel**: local dates are consumed exactly as Garmin
   reported them; no per-user timezone conversion layer is introduced here.

---

**C230** — corrections applied: real Garmin local date, ambiguity ≠ missed,
multi-dimension adherence, guaranteed Garmin provenance, honest legacy-consumer
reporting. 72 PASS / 0 FAIL / 0 SKIP. PR #230 updated, NOT merged.
