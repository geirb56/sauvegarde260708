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

## C232 — CORRECTION (this section supersedes parts of section 1/2 above)

**PRESCRIPTION CANONIQUE ≠ PRÉSENTATION.** The initial #232 implementation
(described above) violated this principle in two ways ("blockers"), both now
corrected. The corrected contract, tests, frontend, and build have all been
re-validated (see below). **NOT MERGED**, per explicit instruction.

### BLOCKER 1 — fabricated splits removed from the display layer

`backend/training_v2/session_structure.py`'s original `build_session_blocks()`
invented a full physiological prescription — warmup/N-reps-at-threshold/
recovery/cooldown for `quality`, a 65/20/15 marathon-pace progression for
`long_easy` — from nothing but `workout_type` and a fixed set of UX constants
(`_QUALITY_WARMUP_KM`, `_QUALITY_REP_LENGTH_KM`, `_QUALITY_RECOVERY_MINUTES`,
long-run fractions, etc.). `WorkoutPrescription`'s own contract explicitly
states quality's "exact nature is NOT decided here" and the prescription
"does NOT include specific paces / specific intervals". Fabricating that
structure in the API/UI layer was a hidden second prescription engine, not a
display concern — **forbidden**, and now removed.

**Fix**: `session_structure.py` was rewritten from scratch. It no longer
defines any block/split/repetition/warmup/cooldown concept, and no longer
contains a single calibration constant. It exports exactly one function:

```
resolve_session_pace_zone(*, workout_type, paces) -> Optional[PaceRange]
```

This returns the single, literal, whole-session Easy pace range
(`paces.easy`) for `workout_type in {"easy", "recovery", "long_easy"}` —
because by definition the *entire* session is run at Easy pace for those
three types, so this is not an invented split, just naming the category's
own meaning. For every other type — `quality`, `steady`, `rest`, unknown, or
`None` — it returns `None`: the Training Engine has not decided the exact
nature/pace-zone of those sessions, so the UI shows no pace zone rather than
fabricate one (frontend renders no pace line at all for these types).
`None` in → `None` out (no fallback, ever); `paces=None`/INSUFFICIENT
confidence → `None` for every type.

- `WeekV2BlockResponse` and the `blocks` field on `WeekV2SessionResponse`
  (`training_week_response.py`) were removed entirely — there is no longer
  any block/split concept anywhere in the V2 Week API.
- `backend/server.py`'s `/training/v2/week` handler now calls
  `resolve_session_pace_zone(...)` directly instead of decomposing a
  prescription into blocks; `primary_pace` remains on the response (still a
  single pace-range field), but it is honestly sourced.
- Frontend (`TrainingPlanV2.jsx`): the `BlockLine`/`formatBlockLine`
  components and the entire "splits" rendering section were removed (dead
  code, since the backend never sends `blocks` any more). `primary_pace` is
  still rendered as a single line when present; when `None` (e.g. for
  `quality`), no pace line is shown at all — never "unspecified" text
  invented in its place, since the spec's example ("Allure cible : non
  spécifiée") was one option among several and showing nothing at all is at
  least as honest and simpler.

**If real splits are wanted later**: they must become a canonical output of
the Training Engine itself (a `structure`/`blocks` field produced
deterministically *inside* `WorkoutPrescription`, before the C231 snapshot
freeze) — never re-derived after the fact from `workout_type` alone, and
never added to an already-served historical `PrescriptionSnapshot` (that
would let a historical session's structure silently change later if the
heuristic/engine rules evolve). Out of scope for #232 per the correction's
explicit instruction ("Si cette extension nécessite un chantier moteur trop
important : STOP. Ne pas la faire dans #232.").

### BLOCKER 2 — one canonical Training Paces loader for all V2 consumers

`/training/v2/week` computed Training Paces from
`compute_training_paces(domain_activities_90, reference_date)`, where
`domain_activities_90` was a **90-day-windowed** Mongo query (built only to
feed the C231 canonical reference-date resolver). `/training/v2/paces`
loaded up to **500 most-recent** activities with **no calendar window at
all**. `training_paces.py`'s own selection policy explicitly retains a
HIGH-quality historical performance beyond any recent window as LOW-
confidence fallback evidence ("HIGH_HISTORICAL_NEVER_EXPIRES = YES" — see
that module's docstring). Truncating to 90 days could silently discard
exactly that fallback evidence — so the two endpoints could show a pace on
one and `None` on the other, for the same user and the same day. **Forbidden
per #231's single-source-of-truth doctrine.**

**Fix**: new module `backend/training_v2/canonical_training_paces.py`
exposes the single function every V2 consumer must call:

```
load_canonical_training_paces(db, *, user_id, reference_date) -> TrainingPaces
```

It loads up to 500 most-recent `garmin_activities` docs (no calendar-date
filter — matches the pre-existing `/training/v2/paces` window/depth so no
new consumer inherits a *narrower* window than before) and calls
`compute_training_paces(..., user_max_hr=None)` with the caller-supplied
canonical `reference_date`. Both `/training/v2/paces` and
`GET /training/v2/week` (in `backend/server.py`) now call this one function,
using the **same** `_resolve_canonical_reference_date` (C231) reference
date, so they can never disagree for the same user + day. No consumer
re-derives its own activity window or its own reference date.

### Tests added/updated for the correction

- `backend/tests/test_pr232_session_structure.py` — fully rewritten (old
  `build_session_blocks`/`SessionBlock` API tests deleted). New coverage:
  `quality` and `long_easy` never get a fabricated split/marathon-segment
  pace; no UX calibration constant exists in the module (explicit
  `hasattr` check for every removed constant/class); `easy`/`recovery`/
  `long_easy` resolve to the whole-session Easy range; `quality`/`steady`/
  `rest`/unknown/`None` resolve to `None`; `paces=None` and INSUFFICIENT
  confidence never fall back to a fabricated zone. **13/13 pass.**
- `backend/tests/test_pr232a_c231_week_endpoint.py` — the 2 old
  blocks-asserting integration tests were rewritten for the no-blocks
  contract (`primary_pace` only; `"blocks" not in session`); 4 new
  integration tests added covering the mandatory C232 list: paces/week
  agreement when the last HIGH performance is >90 days old, identical
  pace values across both endpoints for the same input, no-lookahead
  (a future activity never changes `/training/v2/paces`'s result), and
  INSUFFICIENT confidence → `None` pace fields with no fallback on both
  endpoints. **13/13 pass** (9 pre-existing C231 tests unaffected + 4 new).
- `frontend/src/__tests__/training-v2-page.test.jsx` — fixtures no longer
  include `blocks`; the `quality` fixture now sends `primary_pace: null`
  (matching the honest backend contract). The two blocks-rendering tests
  were replaced with tests asserting no fabricated pace/split ever renders
  for `quality`, and that `easy`/`long_easy` show only the honest
  whole-session pace with no `session-blocks-*`/`session-block-*` testids
  anywhere in the DOM. **34/34 pass** in the file, **250/250** across the
  whole frontend suite.

### Full re-validation after the correction

- Backend: targeted PR232/PR231/PR230/PR228/training_paces regression run —
  **315 passed** (the handful of failures/errors present are pre-existing,
  environment-only: a global rate-limit hit on an unrelated race-day test,
  a missing `_generate_fallback_week_plan` symbol in an unrelated PR153
  test, a Redis-dependent SSE test, and a missing `REACT_APP_BACKEND_URL`
  env var in an unrelated subscription test — none touch
  `session_structure.py`, `canonical_training_paces.py`, or the two
  corrected endpoints).
- Frontend: `npx craco test --watchAll=false --forceExit` — **250/250
  pass**. `npm run build` — **compiles successfully**.
- `code_review`/CodeQL tools were unavailable in this session; all diffs
  were manually re-reviewed instead (no dangling references to the removed
  `build_session_blocks`/`SessionBlock`/`WeekV2BlockResponse` symbols remain
  anywhere in `backend/` or `frontend/`).

## Status

**NOT MERGED**, per explicit instruction. Scope strictly limited to the two
blockers above — #233/#234/#235/#236 not touched.

---

## CORRECTION C232 — round 2 (historical immutability + real-volume audit)

A second audit re-confirmed BLOCKER 1 (fabricated splits) is already fixed
by the correction above, and raised **new** findings, all addressed in this
round. **NOT MERGED.**

### 1. Historical immutability of `primary_pace` (BLOCKER)

Before this round, `GET /training/v2/week` resolved `primary_pace` for
**every** session — including one whose `planned_date <= reference_date` —
from `training_paces_v2`, a **live** recompute of the user's current
TrainingPaces. Once a session's effective prescription is a FROZEN
`PrescriptionSnapshot` (see `training_v2/prescription_snapshot.py`), that
snapshot does **not** persist any pace field — so a past (or even today's,
just-frozen) session's displayed pace could silently change on a later day
if the live TrainingPaces changed in between (e.g. a Monday session
showing a different pace on Wednesday than it showed on Monday). Forbidden
per the new correction: *"une ancienne prescription ne doit jamais acquérir
rétroactivement une allure... qui n'avait pas été figée avec elle."*

**Fix**: `backend/server.py`'s `_session_response()` (inside
`GET /training/v2/week`) now resolves `primary_pace` **only** for a session
whose `planned_date` is **strictly in the future** relative to
`reference_date` (never yet frozen — the live prescription may still
legitimately evolve for it). Any session with `planned_date <= reference_date`
(today or the past — i.e. matched against a frozen snapshot, or
`prescription_unavailable`) now always gets `primary_pace = None`: unknown,
never reconstructed from today's live paces. `None` stays `None`.

`PrescriptionSnapshot` itself was deliberately **not** extended with a new
pace field in this round — that would be introducing a new persisted
concept without a real structured-prescription engine behind it (out of
scope, see below). The honest answer for an already-frozen session, today,
is "unknown", not a value invented from a field that doesn't exist yet.

### 2. Single canonical Training Paces source (reconfirmed, no change needed)

The prior correction round already made `canonical_training_paces.py` the
single function called by both `/training/v2/paces` and
`GET /training/v2/week`. With fix #1 above, `/training/v2/week` now only
ever needs a live pace for still-future sessions — which is exactly the
scope where using the shared canonical loader is legitimate (the plan may
still evolve for them). No second/duplicate computation was introduced or
remains; the same `load_canonical_training_paces()` call is kept (not
removed), since future sessions still need it, but it is no longer
consulted at all for frozen/past sessions.

### 3. Week Summary — plan vs. real Garmin volume (BLOCKER)

Before this round, `WeekSummaryCard` (frontend) computed a single
"progress" figure by summing only `session.actual.distance_km` across
matched sessions — silently excluding `unmatched_actuals` (real Garmin
activities that could not be attributed to any prescribed session). A
runner's real extra activity for the week could therefore be invisible
from the week summary entirely.

**Fix**: `WeekSummaryCard` now exposes **two distinct, clearly-labelled**
notions, never conflated:
- **plan progress** (`week-summary-progress-value` / `-progress-bar`):
  matched sessions only, against the planned volume — unchanged from
  before, still 100%-factual (no fabricated DONE/MISSED).
- **real Garmin volume this week** (`week-summary-real-volume`, only shown
  when non-zero): matched `actual.distance_km` **+** `unmatched_actuals`
  distances, summed with **no double counting** — PR230's own matching
  guarantees an activity is never simultaneously a matched `session.actual`
  and an `unmatched_actuals` entry (mutually exclusive `matching_status`
  values), so the two summed sets are always disjoint by construction. This
  real-volume figure can legitimately **exceed** the planned volume; it is
  never presented as "plan progress", and an extra activity is never
  silently promoted into a planned session.

### 4. Structured prescription — explicit architectural limit (reiterated)

**Structured workout prescription is not yet available in
`WorkoutPrescription` V2. PR232 does not fabricate it.** Training UX V3 is
ready to *display* a structured prescription (per-block type, repetitions,
distance/duration, recovery, E/M/T/I/R pace zone) the moment the Training
Engine actually produces one — but that engine does not exist yet, and this
PR does **not** build it. `session_structure.py` continues to expose only
the single honest whole-session pace ZONE for `easy`/`recovery`/
`long_easy`, and `None` for everything else (`quality`'s exact subtype is
never guessed; `steady` never gets an invented zone).

### Tests added for this round

- `backend/tests/test_pr232a_c231_week_endpoint.py`:
  - `test_paces_and_week_agree_when_last_high_performance_is_over_90_days_old`
    — restricted its equivalence assertion to strictly-**future**
    easy/recovery/long_easy sessions (the only scope where `/training/v2/week`
    is still allowed to attach a live-resolved pace after fix #1).
  - **new** `test_frozen_session_pace_is_never_recomputed_from_live_paces`
    (mandatory test **C**) — Monday's session is frozen (`primary_pace`
    already `None` on the very call that freezes it); viewing the same week
    later, with new evidence that would change the live TrainingPaces if
    recomputed, still shows `primary_pace = None` for Monday, and its
    frozen `distance_km`/`workout_type` are unaffected.
  - **new**
    `test_unmatched_actuals_distance_is_disjoint_from_matched_sessions`
    (mandatory test **E**) — a matched Monday activity and a genuinely
    extra rest-day activity end up in disjoint sets (`session.actual` vs
    `unmatched_actuals`), proving a frontend real-volume sum can never
    double-count the same Garmin activity.
  - **11/11 pass** in the file (9 pre-existing + 2 new).
- `frontend/src/__tests__/training-v2-page.test.jsx` — **new**
  `"C232 (correction round 2): week summary distinguishes plan progress
  from real Garmin volume (matched + unmatched, no double counting)"` —
  asserts `week-summary-progress-value` stays exactly the matched sum
  (8.1 km) while `week-summary-real-volume` shows the combined matched +
  unmatched total (13.3 km), using the existing fixture's unmatched extra
  activity (5.2 km). **35/35 pass** in the file.

### Full re-validation after this round

- Backend: `tests/test_pr232a_c231_week_endpoint.py`,
  `tests/test_pr232_session_structure.py`,
  `tests/test_pr232a_week_execution.py`,
  `tests/test_performed_workout_pr230.py` — **all pass**. Wider regression
  sweep (`-k "pr228 or pr230 or pr232 or training_paces or week_execution or
  readiness"`) — **580 passed**; the handful of failures are unrelated and
  pre-existing (a rate-limited unrelated race-day test, two Redis/mock
  environment issues in unrelated fatigue-removal tests, a missing symbol
  in an unrelated PR153 test, an unrelated SSE import error, and a missing
  `REACT_APP_BACKEND_URL` env var in an unrelated subscription test) — none
  touch `server.py`'s week handler, `training_week_response.py`, or
  `prescription_snapshot.py`.
- Frontend: `npx craco test --watchAll=false --forceExit` — **251/251
  pass**. `npm run build` — **compiles successfully**.

### Status

**NOT MERGED**, per explicit instruction. #233 not touched. No new
structured-prescription engine was implemented in this PR.

C232


