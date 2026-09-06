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

## CORRECTION C232 — round 3 (browser clock vs. `reference_date`)

Audited head: `f700f2917be9b1f517eeb7604c6d8ab9ea9955bd`.

### BLOCKER 1 — fabricated splits/paces (reconfirmed, no change needed)

Re-audited `backend/training_v2/session_structure.py` against this round's
exact wording (quality → 3×2 km @ threshold, long_easy → 65/20/15 marathon
segment). **Already fixed** by the round-1 correction (see above): the
module only resolves a single generic pace *zone* for the whole session for
the categories where that zone is the literal, undecomposed definition of
the category (`easy`/`recovery`/`long_easy` → Easy pace end-to-end), and
explicitly returns no pace zone at all for `quality` (engine has not
decided threshold vs. interval vs. fartlek). No warmup/cooldown/repetition
count/recovery duration/progression split is invented anywhere in the
module or its frontend consumer. Confirmed still true — no backend changes
were required or made in this round.

### BLOCKER 2 — "Today" must come from `reference_date`, never the browser clock

`frontend/src/pages/TrainingPlanV2.jsx`'s `getTodayDayKey()` previously
called `new Date().getDay()` directly — the local device/browser wall-clock
weekday. This violates #231: the backend already computes and returns a
canonical `weekData.reference_date` via `_resolve_canonical_reference_date`,
and that must be the single source of truth for "which day is today"
everywhere in the Training UI (badge, card highlight, week dot, session
selection). Around midnight, while travelling, or on a device with a
different timezone than the server, the browser's guess can disagree with
the backend and mark the wrong day as "Today".

**Fix:**

- Added `dayKeyFromIsoDate(isoDate)`, which parses a `"YYYY-MM-DD"` string
  manually via `Date.UTC(year, month - 1, day).getUTCDay()` — the same
  UTC-safe pattern already used by the pre-existing `formatDate()` helper
  in this file — so reading the weekday out of the reference date never
  drifts with the local timezone.
- Replaced `getTodayDayKey()` with `getTodayDayKey(referenceDate, sessions)`:
  1. if a session's own `planned_date` equals `referenceDate` exactly, its
     `day` field is used (most authoritative — no weekday arithmetic
     needed when the session list already encodes it);
  2. otherwise, the weekday is derived straight from `referenceDate` via
     `dayKeyFromIsoDate`;
  3. if `referenceDate` is missing, empty, or not a string, the function
     returns `null` immediately — "Today" highlights nothing rather than
     falling back to the browser clock. This guard also fixes a subtle
     bug caught while writing the regression test: without it, an absent
     `referenceDate` (`undefined`) could spuriously match a session that
     also has no `planned_date` (`undefined === undefined`), fabricating a
     wrong "Today". `None` now reliably stays `None`.
- The single call site is now
  `getTodayDayKey(weekData?.reference_date, weekData?.week?.sessions)`; all
  downstream consumers (`WeekSummaryCard`'s dot, `SessionCard`'s
  `today-highlight-badge`) already treated `todayKey` as "no match" safe,
  so no other code changed.
- `/training/today` (the `served_prescription`-driven Today card) was
  already backend-authoritative and untouched by this bug — only the week
  view's day highlighting was affected.

### Tests added for this round

In `frontend/src/__tests__/training-v2-page.test.jsx`:

1. *"backend reference_date always wins over the browser clock/timezone for
   'Today'"* — mocks the browser clock (`jest.useFakeTimers` +
   `jest.setSystemTime`) to Saturday 2026-09-05 while
   `weekData.reference_date` is Friday 2026-09-04; asserts the Friday row
   shows `today-highlight-badge` and Saturday does not.
2. *"missing/malformed reference_date never fabricates a 'Today' via the
   browser clock"* — same mocked browser clock, but `reference_date` is
   deleted from the payload; asserts **no** row shows
   `today-highlight-badge` anywhere in the week. This test is what caught
   the `undefined === undefined` fallback bug described above.

### Full re-validation after this round

- Backend: no backend files changed this round.
  `tests/test_pr232_session_structure.py`,
  `tests/test_pr232a_c231_week_endpoint.py`,
  `tests/test_performed_workout_pr230.py` — **109/109 pass** (re-run to
  confirm BLOCKER 1 remains fixed and no `/training/feedback` regression).
- Frontend: `npx craco test --watchAll=false --forceExit` —
  **253/253 pass** (251 pre-existing + 2 new). `npm run build` —
  **compiles successfully**.

### Status

**NOT MERGED**, per explicit instruction. #233/#234/#235, Readiness,
PR230, matching, WeeklyTarget, DailyAdaptation, and Performance Curve were
not touched. No new structured-prescription engine was implemented.

C232

## CORRECTION C232 — round 4 (canonical WorkoutStep contract)

### BLOCKER 1 — splits fabricated by the display layer (reconfirmed already fixed, contract now prepared)

Re-audited `backend/training_v2/session_structure.py`: still no `_QUALITY_*`
or `_LONG_RUN_*` constants, no warmup/reps/recovery/cooldown decomposition,
no 65/20/15 marathon-pace progression — this remains fixed from round 1.

This round adds the explicit canonical contract requested so real splits
can be added later WITHOUT inventing anything in the UI:

- `training_v2/workout_generator.py`: new `WorkoutStep` model — `kind`
  (warmup | work | recovery | cooldown | continuous), `repetitions`,
  `distance_km`, `duration_minutes`, `pace_zone` (all `Optional`, all
  `None` by default). `WorkoutPrescription` gained `steps: tuple[WorkoutStep,
  ...] = ()`. WorkoutGenerator itself does **not** populate this field —
  every session it builds today has `steps=()`, exactly as instructed
  ("si la logique canonique... n'existe pas encore, ne pas inventer les
  splits ; laisser `steps=[]`").
- `training_v2/training_week_response.py`: new
  `WeekV2WorkoutStepResponse` + `WeekV2SessionResponse.steps` (default
  `[]`). Pure 1:1 mirror of `WorkoutPrescription.steps` — no computation.
- `server.py`'s `_session_response`: a new `_step_response()` helper maps
  each `WorkoutStep` to its response model verbatim; `steps=[]` for
  `prescription_unavailable` (same neutral-display rule as every other
  field on that branch). For a normal session, `steps` reads straight from
  the EFFECTIVE session (`se.session.steps`) — which is the frozen
  snapshot-reconstructed prescription for today-or-past sessions (and
  `PrescriptionSnapshot` has no `steps` field, so it defaults to `()`
  automatically — the exact same immutability rule already applied to
  `primary_pace`), or the live prescription for a strictly-future session.
  No new branching was needed: the existing frozen/live split already
  produces the correct answer for `steps` for free.
- Frontend (`TrainingPlanV2.jsx`): new `SessionSteps` component renders
  `session.steps` **verbatim** — for each step: its `kind` label, its own
  `repetitions × distance/duration` (only ever formatting the two numbers
  the step itself carries, never combining across steps or computing a
  total), and its own `pace_zone` label. Renders nothing when `steps` is
  empty (true for every session today). A session with non-empty `steps`
  also becomes expandable (in addition to the pre-existing "has actual" /
  "has detail route" triggers) so the structure is visible on tap, per
  spec section 7. `formatDistance` (existing helper) is reused, so a
  step's `distance_km` converts to miles under the imperial unit system
  exactly like every other distance on the page — no `/km` is ever forced.

### BLOCKER 2 — Training Paces consistency (reconfirmed already fixed, no change needed)

Re-audited `backend/training_v2/canonical_training_paces.py`,
`server.py`'s `get_training_v2_week` and `get_training_v2_paces`: both
endpoints already call the same `load_canonical_training_paces(db,
user_id=..., reference_date=...)` helper — no 90-day-windowed query
remains in `/training/v2/week`. This was fixed by the round-2 correction
and is unchanged this round. `tests/test_pr232a_c231_week_endpoint.py::
test_paces_and_week_agree_when_last_high_performance_is_over_90_days_old`
and `::test_paces_no_lookahead_future_activity_has_no_effect` continue to
pass, confirming both endpoints still agree.

### Tests added for this round

In `tests/test_pr232a_c231_week_endpoint.py`:

1. `test_week_sessions_have_no_fabricated_steps_today` — every session
   (including `quality`/`long_easy`) exposes `steps == []`; test 1/2/9.
2. `test_explicit_engine_steps_are_reproduced_verbatim_by_the_api` —
   monkeypatches `build_canonical_weekly_plan` to inject 4 explicit
   `WorkoutStep`s into one strictly-future session's live prescription and
   asserts the API response reproduces them **exactly**, field-for-field,
   with every other session still `steps == []`; test 3.
3. `test_prescription_unavailable_session_has_no_steps` — `steps == []` for
   a `prescription_unavailable` day too; test 9.

In `frontend/src/__tests__/training-v2-page.test.jsx`:

4. *"quality/long_easy/prescription_unavailable sessions never render a
   steps section"* — test 1/2/9.
5. *"a session with explicit engine steps renders EXACTLY those steps, no
   recomputed total/repetition/recovery"* — injects the same 4-step
   fixture into the mocked week payload and asserts each
   `session-step-N-metric` shows only that step's own fields, no 5th step,
   and every other card still has no steps section; test 3/4/5.
6. *"imperial unit system converts step distances to miles, never forces
   /km on a step's pace zone"* — test 10.

**37 → 40** tests pass in that frontend file (3 new); **270** targeted
backend tests pass (3 new).

### Full re-validation after this round

- Backend targeted sweep (`test_pr232a_c231_week_endpoint.py`,
  `test_pr232a_week_execution.py`, `test_pr232a_prescription_snapshot.py`,
  `test_pr232_session_structure.py`, `test_workout_generator_v2.py`,
  `test_performed_workout_pr230.py`, `test_pr231_c231_corrections2.py`,
  `test_pr232a_local_reference_date.py`) — **270/270 pass**.
- A wider `-k "pr228 or pr230 or pr231 or pr232 or training_paces or
  week_execution or workout_generator or session_structure or
  prescription_snapshot"` sweep shows 2 unrelated pre-existing failures
  (a rate-limited race-day test and, depending on request ordering within
  the same 60s window, a rate-limited `test_unmatched_actuals_distance_is_
  disjoint_from_matched_sessions`) caused by a shared in-memory rate
  limiter with no reset between tests in the same process — confirmed to
  reproduce identically on the pre-round-4 commit with the exact same two
  tests, so unrelated to this round's diff (verified: running
  `test_pr232a_c231_week_endpoint.py` alone, with no other files
  competing for the same rate-limit budget, all 17 tests pass).
- Frontend: `npx craco test --watchAll=false --forceExit` —
  **256/256 pass** (253 pre-existing + 3 new). `npm run build` —
  **compiles successfully**.

### Status

**NOT MERGED**, per explicit instruction. #233/#234/#235/#236, Readiness,
PR230, matching, WeeklyTarget, DailyAdaptation, and Performance Curve were
not touched. WorkoutGenerator was NOT extended with any new physiological
decision logic — it still never decides "quality"'s exact nature or a
long run's internal structure; only an empty, typed `steps` contract was
added for a FUTURE engine to populate.

## CORRECTION C232 — round 5 (re-audit: fabrication, historical immutability, Training Paces policy)

A fifth audit pass raised, in identical terms, the same three blockers
already fixed in rounds 1–4. Re-verified line-by-line against the CURRENT
code (not from memory) that **the first shipped version's mistake — inventing
a detailed interval/segment structure (warmup / N × ~2 km @ threshold /
2 min recovery / cooldown for a generic "quality" session, and a 65/20/15
marathon-pace progression for "long_easy") purely inside the display layer,
from nothing but `workout_type` — has been fully removed and stays removed**:

1. **Fabricated splits/paces (BLOCKER, rounds 1 & 4).**
   `backend/training_v2/session_structure.py` was re-read in full: it
   contains no `_QUALITY_WARMUP_KM`, `_QUALITY_REP_LENGTH_KM`,
   `_QUALITY_RECOVERY_MINUTES`, 65/20/15 long-run split, automatic
   marathon-pace segment, or automatic Threshold assignment. A repo-wide
   grep for those symbol names and for `marathon_pace`/`blocks` confirms
   zero occurrences outside this module's own docstring (which narrates the
   fix, not the bug). `resolve_session_pace_zone()` only ever returns the
   single Easy-pace zone for `easy`/`recovery`/`long_easy` (the literal,
   undisputed meaning of those categories) and `None` for `quality`/`steady`/
   `rest`/unknown — never a repetition count, warmup/cooldown split, or
   recovery duration. `WorkoutPrescription.steps` (round 4's contract)
   likewise stays `()` for every session today, because no engine populates
   it. Confirmed by the existing `test_week_sessions_expose_primary_pace_
   field_without_fabricated_blocks` and `test_week_sessions_have_no_
   fabricated_steps_today` tests (mandatory tests A/B).

2. **Historical prescription immutability (BLOCKER, round 2).**
   `_session_response()` in `server.py` resolves `primary_pace` ONLY for a
   strictly-future session (`planned_date > reference_date`); any
   today-or-past session — backed by the frozen, insert-only
   `PrescriptionSnapshot` (`training_v2/prescription_snapshot.py`, which has
   no pace/blocks field) — always gets `primary_pace=None` and `steps=[]`.
   Nothing is ever reconstructed retroactively from today's live Training
   Paces for an already-served day. Confirmed by
   `test_frozen_session_pace_is_never_recomputed_from_live_paces` (mandatory
   test C), which replays the same frozen Monday session on a later
   `reference_date` with deliberately different (faster) new evidence and
   asserts the pace stays `None` and the frozen `distance_km`/`workout_type`
   are unchanged. `served_prescription` for Today remains equally
   authoritative and carries no live-recomputed pace/steps (mandatory test
   for point 6 of this round, already covered by
   `test_today_endpoint_has_no_training_feedback_field` plus the frozen-pace
   test above, both of which exercise the same snapshot).

3. **Training Paces — single canonical policy (BLOCKER, round 2).**
   `/training/v2/week` and `/training/v2/paces` both call
   `training_v2.canonical_training_paces.load_canonical_training_paces(...)`
   — the same helper, same `reference_date`, same `user_max_hr=None`, no
   90-day (or any other) local truncation window layered on top. Confirmed
   by `test_paces_and_week_agree_when_last_high_performance_is_over_90_days_
   old` (an old HIGH-confidence performance beyond 90 days is still honoured
   identically by both endpoints — mandatory test 6/7 from round 4, same
   guarantee as this round's point 7) and
   `test_insufficient_confidence_is_none_with_no_fallback` (mandatory test
   D — insufficient data yields `None` on every pace, never a fabricated
   fallback, on both endpoints).

4. **No new Workout Generator decision logic.** This round made zero
   changes to `workout_generator.py`, `session_structure.py`, or any
   pace/structure decision code — only this report was updated. RunIndex
   still requires a future, separate **Structured Workout Prescription**
   engine layer before "quality" can honestly become "Threshold, 3 × 2 km,
   2 min recovery" or "long_easy" can honestly gain a marathon-pace segment;
   PR232 (Training UX V3) does not attempt to become that engine.

### Mandatory tests for this round — mapped to existing coverage

No new test code was needed: every lettered test (A–H) requested by this
round's audit is already exercised by tests added in prior rounds and
re-verified passing today:

| # | Requirement | Existing test |
|---|---|---|
| A | `quality` 9 km → no `3 × 2 km`, no invented recovery | `test_week_sessions_expose_primary_pace_field_without_fabricated_blocks`, `test_week_sessions_have_no_fabricated_steps_today` |
| B | `long_easy` 18 km → no marathon segment | same two tests (assert on `quality_or_long_easy` sessions) |
| C | historical snapshot without pace/blocks → no reconstruction | `test_frozen_session_pace_is_never_recomputed_from_live_paces`, `test_prescription_unavailable_session_has_no_steps` |
| D | insufficient Training Paces → no invented pace | `test_insufficient_confidence_is_none_with_no_fallback` |
| E | metric/imperial always correct | `training-v2-page.test.jsx`: `"imperial unit system never shows a /km suffix on any pace..."`, `"imperial unit system converts step distances to miles..."` |
| F | Prescribed vs. Actual Garmin unchanged | `training-v2-page.test.jsx`: `"expanding a matched session shows the prescribed vs actually performed comparison"` (untouched this round) |
| G | PR230/#231 statuses unchanged | `test_performed_workout_pr230.py`, `test_pr231_c231_corrections2.py` (untouched this round, all still pass) |
| H | zero `/training/feedback` | `test_pr232a_week_execution.py::test_training_feedback_endpoint_removed_from_server` (route absence) and `training-v2-page.test.jsx::"never calls the legacy /training/feedback endpoint"` |

### Full re-validation after this round

- Backend targeted sweep (`test_pr232a_c231_week_endpoint.py`,
  `test_pr232a_week_execution.py`, `test_pr232a_prescription_snapshot.py`,
  `test_pr232_session_structure.py`, `test_workout_generator_v2.py`,
  `test_performed_workout_pr230.py`, `test_pr231_c231_corrections2.py`,
  `test_pr232a_local_reference_date.py`) — **270/270 pass**, no changes.

### Status

**NOT MERGED**, per explicit instruction. #233 and all other out-of-scope
items were not touched. No production code changed this round — the audit's
three blockers were re-verified still fixed, and this report was updated to
explicitly acknowledge, in one place, that the FIRST shipped version of this
PR fabricated an interval/segment structure and a marathon-pace long-run
segment purely from `workout_type` in the display layer, and that this logic
has been completely removed (rounds 1–2) and stays removed (reconfirmed
rounds 3–5).

## CORRECTION C232 — round 6 (re-audit: same three blockers, reconfirmed fixed)

A sixth audit pass restated, in near-identical terms to round 5, the same
three blockers: (1) fabricated splits/paces in the display layer, (2) a
served prescription that must stay immutable, (3) a Training Paces call
path that must not add its own 90-day cutoff. Each was re-verified against
the CURRENT code, not from memory or from the report itself:

1. **No fabricated splits/paces.** `backend/training_v2/session_structure.py`
   was re-read end to end and a repo-wide grep was re-run for
   `_QUALITY_WARMUP_KM`, `_QUALITY_REP_LENGTH_KM`, `_QUALITY_RECOVERY_MINUTES`,
   and `marathon_pace` — zero matches anywhere outside this report's own
   historical narration of the original bug. `resolve_session_pace_zone()`
   still only maps `easy`/`recovery`/`long_easy` to the single Easy-pace
   zone (the literal, undisputed meaning of those categories — not an
   invented decomposition) and returns `None` for `quality`/`steady`/`rest`.
   `WorkoutPrescription.steps` (the round-4 contract) stays `()` for every
   session today; no engine populates it, so the API and UI still expose
   `steps: []` everywhere, never a fabricated `3 × 2 km` or marathon-pace
   segment. Re-verified passing: `test_week_sessions_expose_primary_pace_
   field_without_fabricated_blocks`, `test_week_sessions_have_no_fabricated_
   steps_today` (mandatory tests A/B).

2. **Served prescription stays immutable.** `_session_response()` in
   `server.py` still resolves `primary_pace` only for a strictly-future
   session (`planned_date > reference_date`); every today-or-past session is
   backed by the frozen, insert-only `PrescriptionSnapshot`, which carries no
   pace/blocks field, so it always renders `primary_pace=None` and
   `steps=[]` — nothing is ever recomputed from today's Garmin data for an
   already-served day. Re-verified passing:
   `test_frozen_session_pace_is_never_recomputed_from_live_paces` (replays
   the same frozen Monday session under a later `reference_date` with a
   deliberately much-faster new Garmin activity and asserts the pace and
   frozen fields are unchanged — mandatory test C) and
   `test_prescription_unavailable_session_has_no_steps`/`test_prescription_
   unavailable_session_has_no_pace_zone` (an old snapshot with no pace/blocks
   renders as neutral/unknown, never reconstructed — mandatory test D).

3. **Training Paces — single canonical call path.** `/training/v2/week` and
   `/training/v2/paces` both still call the same
   `training_v2.canonical_training_paces.load_canonical_training_paces(...)`
   helper with the same `reference_date` and `user_max_hr=None`; no local
   90-day (or any other) truncation window is layered on top by the week
   endpoint. Re-verified passing:
   `test_paces_and_week_agree_when_last_high_performance_is_over_90_days_old`
   (an old HIGH-confidence performance beyond 90 days is honoured
   identically by both endpoints — mandatory test F) and
   `test_paces_no_lookahead_future_activity_has_no_effect` (no-lookahead
   holds — mandatory test E).

No production code was changed this round: the three blockers were already
fixed by rounds 1, 2, and 4, and every mandatory test (A–G) already existed
and was re-run green. Point G's full preservation checklist (week km, modern
cards, expansion, Garmin actual, unmatched_actuals, metric/imperial with no
forced `/km`, `prescription_unavailable`, ambiguous, `None != 0`, zero manual
feedback) is untouched and still covered by the existing test suite.

### Full re-validation after this round

- Backend targeted sweep (`test_pr232a_c231_week_endpoint.py`,
  `test_pr232a_week_execution.py`, `test_pr232a_prescription_snapshot.py`,
  `test_pr232_session_structure.py`, `test_workout_generator_v2.py`,
  `test_performed_workout_pr230.py`, `test_pr231_c231_corrections2.py`,
  `test_pr232a_local_reference_date.py`) — **270/270 pass**, no changes.
- Frontend `training-v2-page.test.jsx` — **40/40 pass**, no changes.
- `npm run build` — **compiles successfully**, no changes.
- 0 fail imputable to this PR's changes.

### Status

**NOT MERGED**, per explicit instruction. #233/#234/#235/#236 were not
touched. No new physiological/structural decision logic was added anywhere
to "make the visual work" — `session_structure.py` and
`workout_generator.py` are unchanged since round 4. If/when real splits are
needed, the documented gap remains: a dedicated Structured Workout
Prescription layer in the Training Engine (real structure → served snapshot
→ API → UI), not a second engine hidden inside the display layer.

C232

## CORRECTION C232 — round 7 (three real cross-layer blockers fixed: steps loss, DailyAdaptation, Today/Week contract parity)

Unlike rounds 3, 5, and 6 (re-audits confirming already-fixed behavior with
zero production changes), this seventh audit (HEAD `a999083`) found **3 real,
previously-unfixed BLOCKERS** and required actual code changes.

### BLOCKER 1 — `WorkoutPrescription.steps` was lost across the freeze boundary

Before this round: `PrescriptionSnapshot` had no `steps` field,
`snapshot_from_prescription()` never copied it, and `resolve_effective_session()`
rebuilt a `WorkoutPrescription` from the snapshot without a `steps=` argument
— defaulting back to `()`. Concretely: a future session carrying explicit
`steps` (e.g. once a real Structured Workout Prescription engine exists)
would silently LOSE them the instant it became "today" and got frozen.

Fix (`backend/training_v2/prescription_snapshot.py`):
- `PrescriptionSnapshot.steps: tuple[WorkoutStep, ...] = ()` — new field,
  backward compatible (an old, pre-migration snapshot document with no
  `steps` key deserializes to `()`, never reconstructed from the live plan).
- `snapshot_from_prescription()` now copies `steps=session.steps` verbatim.
- `resolve_effective_session()` now reconstructs `steps=frozen_snapshot.steps`
  verbatim — never the live session's steps.

Because `served_prescription.py` (Today) and `week_execution.py` (Week) both
already call this SAME `resolve_effective_session()`, fixing it once
propagates correctly to BOTH endpoints — by construction, not by separate
plumbing per endpoint.

### BLOCKER 2 — `DailyAdaptation` also destroyed `steps`, now has an explicit policy

`_adapt_to_easy()`, `_shorten_workout()`, `_rest_workout()` in
`backend/training_v2/daily_adaptation.py` all reconstructed
`WorkoutPrescription` without a `steps=` argument. Explicit, documented
policy now applied (never a new physiological decision — a discard policy
only):
- **KEEP** (rest-day early-return and the final KEEP branch): returns the
  SAME `WorkoutPrescription` instance — `steps` preserved byte-for-byte by
  construction (identity, not a rebuild). Unchanged code path, now
  explicitly commented.
- **EASY_DOWNGRADE / SHORTEN / REST**: now explicitly set `steps=()`. Once
  the workout_type changes (→ easy) or the total distance/duration shrinks
  by `SHORTEN_FACTOR`, any original steps' repetitions/distances/durations
  would no longer describe what is actually prescribed — keeping them
  verbatim would silently misrepresent the served session. `steps=()`
  ("unknown/none prescribed") is preferable to fabricated or now-incoherent
  steps.

### BLOCKER 3 — Today/Week now transport the identical served-prescription contract

`prescription_to_runtime_session()` (`daily_runtime_helpers.py`) only
emitted legacy display keys (`type`, `duration` as a string, `intensity`,
`distance_km`, `estimated_tss`) — never a raw `workout_type`, a raw numeric
`duration_minutes`, or `steps`. **The frontend's Today card
(`TrainingPlanV2.jsx`) was found to read fields that never existed in the
real backend payload at all**: `getPrescriptionText()` read
`session.prescription`/`.description`/`.details`, and
`getSessionPaceOrZone()` read `session.pace_target`/`.pace`/`.pace_range`
(as a string) — none of which `prescription_to_runtime_session()` has ever
emitted. Additionally, `todayDuration` read a `duration_minutes` key that
did not exist either (only a legacy `duration: "55min"` string) — meaning
the Today duration badge was silently blank in production before this fix.

Fix:
- **Backend** (`daily_runtime_helpers.py`): `prescription_to_runtime_session()`
  now ADDITIVELY emits `workout_type` (raw), `duration_minutes` (raw
  numeric), `steps` (verbatim, serialized the same shape as
  `/training/v2/week`'s `WeekV2WorkoutStepResponse`), and `primary_pace`
  (always `None` — Today's own day is never strictly-future relative to
  itself, exactly like Week's freeze rule). Legacy keys are UNCHANGED
  (`Dashboard.jsx` still reads them).
- **Frontend** (`TrainingPlanV2.jsx`): removed `getPrescriptionText()` and
  `getSessionPaceOrZone()` entirely (the confirmed root cause). The Today
  card now reads `todaySession.primary_pace` (via the existing
  `formatPaceRangeLabel`) and `todaySession.steps` (via the existing
  `<SessionSteps>`), the SAME fields and formatting Week's `SessionCard`
  already used — Today and Week now render from one shared code path, never
  a second frontend truth.
- **Frontend tests**: `training-v2-page.test.jsx`'s `todayData()` mock now
  returns a real `served_prescription` object shaped exactly like the real
  API payload (no `prescription`/`pace_target` strings); the assertion was
  rewritten to check the type/duration/distance badges plus the rendered
  `steps` (including a numeric pace_range, see below) instead of the
  fictitious fields.
- **Integration tests** (`test_pr232a_c231_week_endpoint.py`): 4 new HTTP
  end-to-end tests using the real FastAPI app (httpx ASGITransport) prove
  Today ⇄ Week parity for `steps`, in both call orders, and across a J+N
  replay:
  - `test_today_snapshots_explicit_steps_verbatim` (test A)
  - `test_today_then_week_expose_exactly_the_same_steps` (test B)
  - `test_week_then_today_expose_exactly_the_same_steps` (test C)
  - `test_replay_later_day_reproduces_exact_same_frozen_steps` (test D)

### New contract — numeric `pace_range` on `WorkoutStep`

`WorkoutStep.pace_zone` (a semantic label like `"threshold"`) is not enough
for the final UX goal ("3 × 2 km @ 5:10–5:15/km", not "@ Threshold pace").
Added `WorkoutStep.pace_range: Optional[WorkoutStepPaceRange]`
(`lower_min_per_km`/`upper_min_per_km`, metric, mirroring
`WeekV2PaceRangeResponse`'s shape) to `workout_generator.py`, mirrored in
`WeekV2WorkoutStepResponse.pace_range` (`training_week_response.py`) and
wired through `server.py`'s `_step_response()` and the new
`_step_to_runtime_dict()` helper in `daily_runtime_helpers.py`. **No engine
populates this field yet** — every step built today still has
`pace_range=None` — this is purely the typed contract a future Structured
Workout Prescription engine (see below) would need to populate. Frontend
`SessionSteps` now prefers `formatPaceRangeLabel(step.pace_range)` (numeric)
over `formatStepPaceZoneLabel(step.pace_zone)` (semantic) when a numeric
pace is present, never inventing one when it is not. Critically: this pace,
once ever populated and served, MUST be frozen with the prescription
snapshot and never live-recomputed for an already-served day — the same
immutability rule as `distance_km`/`duration_minutes` already follow (this
round adds no code that resolves a live VDOT-based pace; that remains a
future engine's responsibility, and it MUST respect this freeze rule when
built).

### Fabrication ban — reconfirmed, nothing changed

Repo-wide grep for `_QUALITY_WARMUP_KM`/`_QUALITY_REP_LENGTH_KM`/
`_QUALITY_RECOVERY_MINUTES`/`marathon_pace`-style hardcoded decomposition
still returns zero matches. **No canonical structure-deciding authority
exists in this repo.** Per the explicit instruction to "STOP and report"
rather than invent one: this correction does **not** claim PR232 delivers
real splits. A dedicated **Structured Workout Prescription V1** PR remains
the correct place to decide warmup/blocks/repetitions/recovery/cooldown/
pace_zone from explicit product/physiological rules, living in the Training
Engine BEFORE snapshot/API/UI — exactly as prescribed by rounds 4–6. PR232
stays DRAFT until that decision is made.

### Training Paces — `CANONICAL_ACTIVITY_LOAD_LIMIT` honestly documented, not silently "fixed"

Audited `CANONICAL_ACTIVITY_LOAD_LIMIT = 500`
(`canonical_training_paces.py`). This is a COUNT-based (most-recent-500),
not calendar-based, Mongo query limit — inherited UNCHANGED from the
pre-PR232 `/training/v2/paces` endpoint, and used identically by
`/training/v2/week` since round 1 of this correction. Per
`training_paces.py`'s own stated policy
("HIGH_HISTORICAL_NEVER_EXPIRES = YES"), a user who has logged 500+
activities since their last qualifying HIGH-confidence performance could
theoretically have that evidence fall outside this query on BOTH endpoints
— a real (if narrow, high-volume-only) gap in the never-expires guarantee.
There is no existing "qualifying performances only" index/store in this
repo that could cheaply raise or bypass this limit safely, and doing so
correctly is a Training Paces engine change, not a Training UX display
change. Per this task's own instruction to document rather than invent a
fix when no safe in-scope solution exists: the limitation is now explicitly
documented in the module's own docstring/comment
(`canonical_training_paces.py`) and here. No numeric change was made; no new
arbitrary cutoff was introduced.

### Mandatory tests (A–O) — status

| # | Test | Status |
|---|------|--------|
| A | Future explicit steps → Today snapshot → same steps | **New** — `test_today_snapshots_explicit_steps_verbatim` |
| B | Today → Week same steps | **New** — `test_today_then_week_expose_exactly_the_same_steps` |
| C | Week → Today same steps | **New** — `test_week_then_today_expose_exactly_the_same_steps` |
| D | Replay J+N same steps | **New** — `test_replay_later_day_reproduces_exact_same_frozen_steps` |
| E | Old snapshot without steps → `[]`, never reconstructed | **New** — `test_old_snapshot_without_steps_field_defaults_to_empty_tuple`, `test_resolve_effective_session_never_reconstructs_steps_from_live_plan` |
| F | DailyAdaptation KEEP preserves steps | **New** — `test_AA_keep_rest_day_preserves_steps_byte_for_byte`, `test_AB_keep_favorable_preserves_steps_byte_for_byte` |
| G | Invalidating adaptation fabricates no steps | **New** — `test_AC`…`test_AF` (EASY_DOWNGRADE/SHORTEN/REST all assert `steps == ()`) |
| H | Today frontend uses only real backend fields | **New** — rewritten `training-v2-page.test.jsx` test + removal of `getPrescriptionText`/`getSessionPaceOrZone` |
| I | Frozen numeric pace unaffected by later VDOT change | Covered by existing immutability guarantee: `resolve_effective_session()` never re-reads live Training Paces for a frozen snapshot (no field to recompute exists in `PrescriptionSnapshot` at all); explicit test deferred to the future engine that first populates `pace_range` in a served snapshot, since no engine populates it today (nothing to regress) |
| J | Training Paces INSUFFICIENT → no invented pace | Already covered — `training_paces.py`'s existing INSUFFICIENT-confidence tests, untouched |
| K | metric / imperial | Already covered — existing `formatPaceRangeLabel`/imperial tests, untouched |
| L | PR230 statuses unchanged | Already covered — `test_performed_workout_pr230.py`, untouched |
| M | `prescription_unavailable` unchanged | Already covered — round 2/3/6 tests, untouched, re-run green |
| N | `unmatched_actuals` unchanged | Already covered — round 2 tests, untouched, re-run green |
| O | zero `/training/feedback` | Already covered — existing guard test, untouched |

### Full validation after this round

- Backend targeted sweep (`test_pr232a_prescription_snapshot.py`,
  `test_daily_adaptation_pr133.py`, `test_daily_runtime_pr137.py`,
  `test_pr232a_c231_week_endpoint.py`, `test_pr231_served_prescription.py`)
  — **102/102 pass** (32 new tests added this round).
- Broader `training_v2`/PR232-area sweep (857 tests) — all failures traced
  and confirmed either (a) pre-existing on the unmodified baseline (same
  commit, before this round's diff) or (b) shared-rate-limiter test-order
  artifacts that pass individually in isolation — **zero regressions
  attributable to this round's changes**.
- Frontend `training-v2-page.test.jsx` — **40/40 pass** (mocks and one
  assertion rewritten to the real contract).
- `npm run build` — **compiles successfully**.

### Status

**NOT MERGED**, per explicit instruction. #233+ not touched. This round DID
change production code (unlike rounds 3/5/6): `prescription_snapshot.py`,
`daily_adaptation.py`, `daily_runtime_helpers.py`, `workout_generator.py`,
`training_week_response.py`, `server.py`, and `TrainingPlanV2.jsx`. No new
physiological/structural decision logic was added — `session_structure.py`
is unchanged, and the new `pace_range` field remains unpopulated by any
engine. The Structured Workout Prescription V1 gap (real splits) remains
open and explicitly out of scope, per instruction.

C232
