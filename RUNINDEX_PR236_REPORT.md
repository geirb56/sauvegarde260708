# RUNINDEX — PR #236 — TRAINING UX V3 — STRUCTURED SESSIONS

## Scope and revisions

- Integration target: `copilot/dev`.
- Verified base SHA: `d98434682b33e83f1a6e639b45e28f69a8aba30a`.
- The verified base contains merges for PR #234 and PR #235.
- Dedicated branch: `copilot/create-training-ux-v3-structured-sessions`.
- Initial PR implementation head: `00e885c0e551d521e2505712caf1f0955d08fee0`.
- C236 resumed from the existing remote branch at `eb1019a6a5291a3cfb8cfc147091456c359bf3f3`;
  no reset or replacement branch was used.
- No merge was performed and nothing was pushed directly to `copilot/dev`.
- The only backend change is additive structured serialization of the
  already-selected quality subtype; no selection or training-science rule changed.

## Files changed

- `frontend/src/components/training/StructuredWorkoutView.jsx`
- `frontend/src/pages/TrainingPlanV2.jsx`
- `frontend/src/lib/i18n.js`
- `frontend/src/__tests__/structured-workout-view.test.jsx`
- `frontend/src/__tests__/training-v2-page.test.jsx`
- `backend/training_v2/structured_workout.py`
- `backend/tests/test_structured_workout_pr234.py`
- `backend/tests/test_prescription_snapshot_v2_pr235.py`
- `backend/tests/test_pr235_c235_corrections.py`
- `RUNINDEX_PR236_REPORT.md`

## Components and contracts

### StructuredWorkoutView

The reusable component consumes only the backend `StructuredWorkoutPrescription`
contract. It renders warm-up, work, standalone recovery, continuous, cooldown,
and rest steps when present. It does not infer structure from `workout_type`.

- Repetitions are compacted as `N ×` rather than duplicated.
- Embedded recovery uses the backend `count`; a zero count is not displayed.
- Recovery distance and duration are rendered only when explicitly supplied.
- Step distance uses metres/kilometres in metric and yards/miles in imperial.
- Duration preserves exact seconds: examples include `45 s`, `1 min`, `1:30`,
  `2 min`, `2:30`, `1 h`, and `1 h 05`. A 90-second recovery is never rounded
  to two minutes.
- Numeric pace uses the existing `formatPace` unit authority.
- A single pace and a min/max range are supported.
- A semantic `pace_zone` without numeric pace does not create a numeric value.

### Today

- `/training/today` remains the source.
- `served_prescription` remains the first parent-session source.
- `structured_prescription` supplies all structured steps and numeric structured
  pace; the live plan is never used to replace a served structure.
- Quality labels use the serialized `quality_kind` selected by the backend.
- The card shows date, localized type, distance/duration, primary pace, exact
  steps, and the `Adapted` badge only when
  `session_modified_from_planned === true`.
- `prescription_id` remains hidden.

### Week

- `/training/v2/week` remains the source.
- Each day shows day/date, localized type, distance or duration, primary
  structured pace, concise repetition/recovery summary, and backend status
  without requiring expansion.
- Expanded detail clearly separates `PLANNED` from `COMPLETED (GARMIN)` and
  includes the complete structured prescription.
- `today_served`, `future_live`, and `historical_frozen` structures are rendered
  as supplied. `historical_unavailable` never creates detail.
- Quality labels use `structured.quality_kind` only when
  `structured.workout_type === "quality"`; legacy snapshots without it retain
  the generic quality label.
- `prescription_id` is used as the preferred stable React key and is never
  displayed.
- `session_modified_from_planned` is not recomputed.

## Statuses and Garmin actuals

The existing backend mappings remain authoritative:

- Matching: `planned`, `matched`, `missed`, `ambiguous`, `unmatched_actual`.
- Adherence: `completed_as_planned`, `completed_modified`,
  `completed_unverified`, `missed`, `ambiguous`, `not_applicable`.

Localized concise labels now communicate To do/Completed/Modified/Missed/Check/
Ambiguous. Garmin activities without an attributed prescription remain in the
separate unmatched section and are not included in completed planned volume.

## Access, i18n, and mobile

- FREE gating is unchanged: the paywall renders before premium endpoint calls,
  so structured data is not fetched or placed in the DOM.
- TRIAL/PREMIUM retain the complete Training experience.
- New labels are present in English, French, and Spanish through the existing
  i18n system.
- Existing dark RunIndex cards and restrained primary accents are preserved.
- Session rows use a 56 px minimum touch height, wrapped content, and
  `minmax(0,1fr)` to avoid narrow-screen overflow.
- Expand/collapse controls retain `aria-expanded` and `aria-controls`.

## Tests and validation

- Targeted Training tests:
  `npm test -- --watchAll=false --runTestsByPath src/__tests__/structured-workout-view.test.jsx src/__tests__/training-v2-page.test.jsx --forceExit`
  — 90 passed.
- Complete frontend suite:
  `npm test -- --watchAll=false --forceExit`
  — 18 suites, 306 tests passed.
- Structured backend regression suites:
  `python -m pytest tests/test_structured_workout_pr234.py tests/test_prescription_snapshot_v2_pr235.py tests/test_pr235_c235_corrections.py tests/test_pr232a_c231_week_endpoint.py -q`
  — 133 passed.
- Production build: `npm run build` — succeeded.
- Standalone lint attempt:
  `npx eslint ...` — unavailable because this repository has no ESLint 9 flat
  configuration. The CRA/CRACO production compilation completed successfully.
- `git diff --check` — passed.

The automated mobile rendering contract was exercised at 360 px and 390 px for
structured Today/Week, matched, missed, ambiguous, historical-unavailable,
future, FREE, metric, imperial, French, and English states. DOM hierarchy,
wrapping classes, touch height, repetition/recovery association, and duplicate
Today/Week presentation were reviewed. No authenticated browser fixture was
available, so no screenshot artifact was captured.

## GitHub CI

At report preparation time, GitHub Actions exposed only the cloud-agent run
`34272913232`, still in progress at base SHA `d984346`; no PR check run existed
yet because the draft PR had not been opened.

## Known limits

- `/training/today` exposes `structured_prescription` but not
  `structured_status`; Today is therefore treated as the served structure by
  endpoint contract. Week provides the complete status state machine.
- Legacy snapshots without `quality_kind` remain `None`; they are neither
  migrated nor retroactively recomputed and retain the generic quality label.
- Today has no matched Garmin `actual` object. Prescribed-versus-actual remains
  correctly available on Week sessions, where the backend supplies both.

## Non-regression

Today-first session content, immutable served prescriptions, real Garmin
actuals, unmatched Garmin separation, no manual feedback, no fake paces or
threshold structure, `None != 0`, local dates, unit preferences, and FREE
gating remain covered. Dashboard, Sessions, Coach, matching, snapshots,
readiness, weekly targets, goals, and all training-science modules are unchanged.
