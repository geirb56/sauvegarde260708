# RUNINDEX PR230 REPORT — PRESCRIBED vs PERFORMED (Garmin actual)

**Branch:** `copilot/create-data-moat-first-brick`
**Base:** `copilot/dev`
**Prerequisite:** PR #229 merged into `copilot/dev` — ✅ verified (`a92fdf5 Merge pull request #229`)
**Runtime:** DEFERRED TO FINAL RUNTIME GATE

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
| What was actually performed | `garmin_activities` → `mongo_garmin_to_domain()` → `DomainActivity` → `ObservedActivity` |
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

### `ObservedActivity` (input, frozen — Garmin truth)

`activity_id`, `user_id`, `local_date`, `start_time`, `activity_type`,
`distance_km`, `duration_min`, `pace_min_per_km`.

Built by `to_observed_activity(domain_activity, user_id=...)`. An activity with
no usable local date **or** no stable id is refused (returns `None`) — no
identifier is ever invented.

### `PerformedWorkout` (output, frozen)

`user_id`, `prescription_id`, `activity_id`, `planned_date`,
`actual_start_time`, `planned_workout_type`, `actual_activity_type`,
`planned_distance_km`, `actual_distance_km`, `planned_duration_min`,
`actual_duration_min`, `planned_intensity_class`, `planned_pace_min_per_km`,
`actual_pace_min_per_km`, `matching_status`, `adherence_status`,
`distance_delta_km`, `duration_delta_min`, `pace_delta_min_per_km`,
`comparison_basis`, `deviation_ratio`, `reason_codes`.

`PerformedWorkoutLedger` wraps the rows with `user_id`, `reference_date` and the
four counters (`matched / missed / planned / unmatched_actual`).

**No missing value is ever replaced by 0.** Absent = `None`, everywhere.

---

## States

| `matching_status` | Meaning |
|---|---|
| `planned` | window still open, or future session — nothing asserted |
| `matched` | a real running activity was deterministically attributed |
| `missed` | window definitively closed and no acceptable activity |
| `unmatched_actual` | real running activity attributable to no prescription |

There is **no `completed` state** produced by this engine. A past session never
becomes "completed" automatically.

| `adherence_status` | Meaning |
|---|---|
| `completed_as_planned` | matched, deviation ≤ 10 % on the comparison basis |
| `completed_modified` | matched, deviation > 10 % (still within the 50 % guard) |
| `completed_unverified` | matched on date + running type, no comparable dimension available |
| `missed` | mirrors `missed` |
| `unmatched_actual` | mirrors `unmatched_actual` |
| `pending` | nothing can be asserted yet |
| `not_applicable` | rest day — never matched, never missed |

No arbitrary "physiological adherence score". Only raw signed deltas
(`actual − planned`) plus the absolute `deviation_ratio` used for the decision.

---

## Matching algorithm (deterministic, no LLM, no fuzzy)

```
1. Keep prescriptions with prescription.user_id == user_id
   sort by (planned_date, prescription_id)                     ← deterministic order
2. Keep activities with activity.user_id == user_id
   AND local_date <= reference_date                            ← no-lookahead
   AND activity_type ∈ {running, trail_running, treadmill_running}
   sort by (local_date, start_time, activity_id)
3. For each prescription, in order:
   a. rest day  → planned / not_applicable, STOP
   b. candidates = free activities whose local_date is inside
      [planned_date - 0d, planned_date + 0d]
   c. compute the comparison for each candidate:
        distance if BOTH planned_distance_km and actual distance are > 0
        else duration if BOTH planned_duration_min and actual duration are > 0
        else no comparable dimension
      deviation = |actual - planned| / planned
   d. reject candidates with deviation > 50 %          (CANDIDATE_REJECTED_DEVIATION)
   e. no remaining candidate →
        window closed ? missed : planned
   f. rank remaining candidates by (deviation, start_time)
      → if the top-2 ranks are strictly equal: AMBIGUOUS, no match
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

## Date / timezone window

- The matching key is the **local calendar date** of the activity
  (`_parse_date`, shared with `TrainingHistory`), not a UTC instant.
- Window V1 = the planned local day only (`before = after = 0`). A wrong date or
  a wrong timezone therefore cannot create a false match: it simply does not
  match, and the activity remains visible as `unmatched_actual`.
- A 23:30 local run stays on its local day (tested).
- `missed` requires `reference_date > planned_date + MATCH_WINDOW_DAYS_AFTER`
  (strict). On the planned day itself the session is still `planned`.

---

## Multi-activity resolution

- Ranking key = `(deviation, start_time)` — **`activity_id` is deliberately
  excluded** from the decision key so a genuine tie is reported as ambiguous
  instead of being silently disambiguated by an arbitrary identifier.
- `activity_id` is only used for stable *sorting* of the output.
- Strict tie on the decision key → `AMBIGUOUS_MULTIPLE_CANDIDATES`, nothing is
  matched, both activities stay `unmatched_actual`.
- Extra same-day runs remain `unmatched_actual`.

---

## matched / modified / missed / unmatched rules

| Situation | Result |
|---|---|
| running activity same local day, deviation ≤ 10 % | `matched` + `completed_as_planned` |
| running activity same local day, 10 % < deviation ≤ 50 % | `matched` + `completed_modified` |
| deviation > 50 % (distance or duration) | **not matched** — prescription `missed`/`planned`, activity `unmatched_actual` |
| no comparable dimension on either side | `matched` + `completed_unverified` |
| no candidate, window closed | `missed` |
| no candidate, window open / future | `planned` |
| ambiguous candidates | `planned` / `missed` + `AMBIGUOUS_MULTIPLE_CANDIDATES` |
| running activity with no prescription | `unmatched_actual` |
| non-running activity | never matched, and out of scope of the running ledger |
| rest prescription | `planned` + `not_applicable` (never missed) |

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
| `backend/training_v2/performed_workout.py` | **New** — models, enums, reason codes, deterministic matching engine `build_performed_workouts()`, Garmin→`ObservedActivity` boundary. |
| `backend/training_v2/__init__.py` | Export the PR230 public surface. |
| `backend/tests/test_performed_workout_pr230.py` | **New** — 43 tests. |
| `RUNINDEX_PR230_REPORT.md` | **New** — this report. |

No runtime endpoint, no consumer and no legacy behaviour was modified in this PR.

---

## Tests executed

Command: `python -m pytest tests/test_performed_workout_pr230.py -q` (from `backend/`)
Result: **43 passed** — plus `test_mongo_garmin_boundary_pr137.py` and
`test_daily_adaptation_pr133.py` re-run as neighbours (**103 passed** total).

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
| very different duration → documented rule | PASS | `test_duration_basis_used_when_no_planned_distance`, `test_extreme_duration_deviation_is_not_matched` |
| no mutation of the original prescription | PASS | `test_prescription_is_never_mutated`, `test_prescription_model_is_frozen`, `test_performed_workout_keeps_planned_values_untouched` |
| no `None → 0` | PASS | `test_missing_values_stay_none_never_zero`, `test_unmatched_actual_row_has_no_fabricated_planned_values`, `test_zero_distance_activity_is_not_turned_into_zero_value` |
| multi-user isolation | PASS | `test_other_user_activity_never_matches`, `test_other_user_prescription_is_ignored` |
| no-lookahead | PASS | `test_future_activity_cannot_change_a_historical_prescription`, `test_historical_state_is_stable_when_replayed` |
| deterministic result | PASS | `test_result_is_deterministic_across_runs_and_input_order` |
| no legacy consumer can auto-mark completed | PASS (engine scope) / see debt | `test_engine_never_emits_a_completed_matching_status`, `test_past_session_without_evidence_is_never_completed`, `test_engine_module_has_no_io_dependencies` |

SKIP: none.
FAIL: none.

Runtime / E2E validation: **DEFERRED TO FINAL RUNTIME GATE**.

---

## Consumer audit — who still confuses "prescribed" with "performed"

Read-only audit; nothing was changed. This is the input backlog for #231.

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

1. **No consumer is wired to this engine yet.** `TrainingPlanV2.jsx:141`,
   `Dashboard.jsx` feedback buttons and `/training/feedback` keep their current
   behaviour in this PR.
2. **No persistence.** `PerformedWorkout` is computed, not stored. A
   `performed_workouts` collection / migration is out of scope here.
3. **No API surface.** No endpoint returns `matching_status` yet; `/training/v2/week`
   still ships prescriptions without execution state.
4. **Self-reported feedback is not reconciled** with `matching_status`
   (`user says done` vs `matched`) — the conflict policy belongs to #231.
5. **Window calibration is V1** (same local day only). Widening it (e.g. ±1 day)
   is a product decision, not a bug fix.
6. **Non-running cross-training** is out of scope of the running ledger; it is
   neither matched nor reported.
7. **Multi-timezone travel**: local dates are consumed as provided by the Garmin
   normalisation layer; no per-user timezone conversion layer is introduced here.

---

## C230
