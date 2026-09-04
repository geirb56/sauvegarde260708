# PR232 — Training UX V3

Base: `copilot/dev` · Starting HEAD: `4f0be2d03e45ee7a594d97ec7b2d440ea23027e6`

## Objective

Redesign the Training page so a user immediately understands, per PR231's frozen
Prescribed→Performed truth:

- what to run this week, on which day, how many km, at what pace, how the
  session is structured;
- what was actually done via Garmin (prescribed vs real, factually).

No execution logic recreated, no manual Done/Missed reintroduced, no engine
(Training/Readiness/PR230) touched.

## 1. Backend — minimal contract addition (display-only)

The existing `/training/v2/week` contract had no structured
blocks/splits/pace-target data — only a single `distance_km`/`duration_minutes`
per session. Per section 10 of the spec ("if the API doesn't carry enough
structure … add only the minimal necessary contract"), a new **display-only**
decomposition layer was added, without touching `WorkoutGenerator`,
`WeeklyTarget`, Readiness, or PR230:

- **`backend/training_v2/session_structure.py`** (new): pure function
  `build_session_blocks()` that decomposes an already-computed prescription
  (`workout_type`, `distance_km`/`duration_minutes`) into ordered
  `SessionBlock`s, reusing the existing VDOT paces from `training_paces.py`
  (never recomputing or inventing paces):
  - `quality`: warmup / main (N × distance @ threshold pace) / recovery (jog,
    no fabricated pace) / cooldown blocks. E.g. a 9 km quality session
    produces exactly `3 × 2 km @ 5:10–5:15/km` (matches the spec's example
    verbatim).
  - `long_easy` ≥ 15 km with marathon pace available: 3 ordered `segment`
    blocks (lead easy / sustained @ marathon pace / cooldown easy) — avoids
    the "absurd global range" the spec explicitly warns against.
  - Simple sessions (`easy`/`recovery`/`steady`, or `quality` < 4 km): a
    single block.
  - Rest, unknown `workout_type`, or missing distance/duration → `None`
    (no blocks array) — never fabricated.
- **`backend/training_v2/training_week_response.py`**: added
  `WeekV2PaceRangeResponse`, `WeekV2BlockResponse`, and `primary_pace`/
  `blocks` fields on `WeekV2SessionResponse`. Additive only — no existing
  field renamed or removed.
- **`backend/server.py`** (`get_training_v2_week`): computes
  `training_paces_v2` once per request and attaches blocks/`primary_pace` per
  session; empty/`None` for `rest` and `prescription_unavailable` sessions
  (respecting C231: no fabricated historical prescription).

### Backend tests

- `backend/tests/test_pr232_session_structure.py` — 10 new unit tests
  (rest / None / simple / quality / short-quality-fallback /
  long-run-below-threshold / long-run-above-threshold /
  insufficient-paces / None-paces / duration-only). **All pass.**
- `backend/tests/test_pr232a_c231_week_endpoint.py` — 2 new integration
  tests appended (`blocks`/`primary_pace` wiring; neutrality for
  `prescription_unavailable`). **All 6 tests in the file pass.**
- Regression run across `pr228|pr230|pr231|pr232|week_execution|handlers`:
  no new failures (only pre-existing/unrelated env-dependent skips).

## 2. Frontend — full redesign of `TrainingPlanV2.jsx`

### Week view (section 1)
New `WeekSummaryCard` inserted between the cycle header and Today: planned
km/duration, session count, a **factual** progress bar built only from real
`actual.distance_km` sums (never fabricated), and a 7-day status-dot strip —
lets a user understand the week without opening any session.

### Session cards (section 2/3)
`SessionCard` replaces the old row: compact by default (day/date, type,
distance, `primary_pace`, status pill). Tap-to-expand (no separate route)
reveals:
- `BlockLine`s: warmup/main/recovery/cooldown headings for quality sessions,
  numbered segments (1./2./3.) for long runs — matching the spec's exact
  layout examples.
- `ActualComparison`: prescribed vs real distance/duration/pace, **only**
  rendered when `session.actual` exists (never for planned/missed/
  unavailable/ambiguous).

### Data / source of truth (section 4)
`getSessionStatusKey` (unchanged, already correct) continues to read
`matching_status`/`adherence_status`/`execution_status` exclusively — no
legacy fields, no `past day => done` fallback, `prescription_unavailable` →
neutral display, `ambiguous` stays ambiguous, `None` stays `None`.

### Prescribed vs real (section 5)
`UnmatchedActualsSection`: extra Garmin activities from
`week.unmatched_actuals` shown in their own card, never attached to a
session card.

### Design (section 6)
Dark/green RunIndex theme preserved (no new palette introduced); status
colors: green=done, amber=modified, rose=missed, sky=planned,
slate=unverified/ambiguous/unavailable/rest.

### Interaction (section 7)
Whole row is a `<button>` (`training-v2-day-toggle-{day}`) toggling local
expand state — no "Réalisé/Manqué" buttons anywhere.

### Units (section 8)
Fixed a pre-existing bug: the Paces card hardcoded a `/km` suffix even in
imperial mode. Now uses `formatPaceValueLabel`/`formatPaceRangeLabel`
(unit-aware, built on `utils/units.js`) throughout, including inside
splits/blocks — imperial never shows `/km`.

## 3. States tested (section 9)

Covered via the extended `training-v2-page.test.jsx` suite: future planned,
matched+`completed_as_planned`, matched+`completed_modified`, missed,
ambiguous, `completed_unverified`, `prescription_unavailable`, rest, simple
session, structured (quality) session, long-run multi-block segments,
`unmatched_actual`, `None` values, metric, imperial, narrow mobile (360–390px).

## 4. Validation (section 11)

- Audited all Training consumers: `App.js` (route only), `Dashboard.jsx` and
  `Settings.jsx` (both call `/training/v2/week` but read only pre-existing
  fields — unaffected by the additive contract change).
- Today/Week consistency: `served_prescription` remains authoritative for
  Today (unchanged); Week reads `matching_status`/`adherence_status`/
  `execution_status`/`actual`/`unmatched_actuals` exclusively.
- Frontend: 34/34 tests in `training-v2-page.test.jsx` (24 pre-existing +
  10 new PR232 tests), 250/250 tests across the whole frontend suite,
  `npm run build` succeeds.
- Backend: 16/16 in the two PR232-related test files; no regression in the
  broader pr228/230/231/232 suite.
- No regression on `/training/feedback` (endpoint already removed in
  PR232A; not reintroduced — confirmed no `.post`/route reference added).
- No Garmin/PR230 truth bypassed; no fabricated status; no `None → 0`
  coercion; no `/km` shown in imperial mode.
- `code_review` run: 3 comments addressed (English-only comments, robust
  pace-range numeric extraction via `convertPace` instead of string
  replacement, `aria-controls` added to the day toggle for accessibility).
- `codeql_checker` run after fixes: **0 alerts** (python, javascript).

## Out of scope (per spec)

Dashboard polish (#233), Navigation cleanup (#234), Onboarding (#235),
Performance Curve (#236) — not touched.

## Status

**NOT MERGED**, per explicit instruction.
