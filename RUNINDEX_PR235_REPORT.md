# RUNINDEX — PR #235 — PRESCRIPTION SNAPSHOT V2 — GARMIN-EXPORT-READY

## 0. Scope confirmation

- Base branch: `copilot/dev`.
- Starting head SHA (required): `7ea03a22a5ca902f04561b326b3d5de0cc4be688`.
- Working branch: `copilot/garmin-export-ready` (already existed at exactly this head — no
  new branch was needed; it tracks the required start point 1:1, confirmed via
  `git log` before any change was made).
- Head SHA after implementation: `45495245054debe1a86ba31c2b18d0f358f987c7`.
- **No** changes to the frontend (`frontend/` untouched).
- **No** changes to the #234 Structured Workout engine
  (`backend/training_v2/structured_workout.py` untouched — every extension lives in the
  snapshot/served-prescription/week-execution/server layers that already *call* the
  engine).
- **No** #236 work, **no** Garmin Training API / FIT integration, **no** merge performed.

## 1. Files modified

| File | Change |
|---|---|
| `backend/training_v2/prescription_snapshot.py` | Core #235 contract: extended `PrescriptionSnapshot` model, added `resolve_structured_status()`, updated `resolve_effective_session()`, updated `snapshot_from_prescription()`. |
| `backend/training_v2/served_prescription.py` | `get_or_create_served_prescription()` now accepts a lazy `structured_factory` + `served_at`; pre-checks Mongo before invoking the factory, guaranteeing at most one #234 engine call per day. |
| `backend/training_v2/week_execution.py` | Historical/today sessions now read `structured` from the frozen snapshot via `resolve_structured_status()`; only strictly-future sessions still call the engine live. |
| `backend/server.py` | `/training/today` and `/training/v2/week` wired to build the structured candidate lazily (factory closure) and freeze it in the same document as the parent. |
| `backend/tests/test_pr232a_c231_week_endpoint.py` | 3 pre-existing tests updated: historical days with a frozen V2 snapshot now assert `historical_frozen` + frozen structured (previously asserted `historical_unavailable`/`None`, which was the pre-#235, intentionally-to-be-replaced behavior). |
| `backend/tests/test_prescription_snapshot_v2_pr235.py` | **New.** 20 pure unit tests for the extended contract (serialization, state machine, immutability ×4, numeric paces, recovery/mixed-basis/known-zero, Garmin-export-ready contract, reason_codes freeze). |
| `backend/tests/test_pr235_today_idempotence.py` | **New.** 2 end-to-end tests proving the #234 engine is invoked at most once across two same-day `/training/today` calls, and the persisted snapshot document is untouched by the second call. |
| `RUNINDEX_PR235_REPORT.md` | This report. |

No other files were touched.

## 2. Snapshot V2 architecture

Pipeline (unchanged order, per spec §3):

```
WorkoutGenerator → DailyAdaptation (Today-only) → final served WorkoutPrescription
   → StructuredWorkoutPrescriptionEngine (#234) → PrescriptionSnapshot V2 (ONE document)
```

`PrescriptionSnapshot` (in `training_v2/prescription_snapshot.py`) is a single,
`frozen=True` Pydantic model persisted once per `(user_id, prescription_id)` and never
rewritten. #235 adds three fields to the existing #231 PARENT-only snapshot:

```python
class PrescriptionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    # ── PARENT (pre-existing, #231) ──
    user_id: str
    prescription_id: str
    planned_date: date
    day: str
    workout_type: str
    intensity_class: str
    distance_km: Optional[float] = None
    duration_minutes: Optional[int] = None
    modified_from_planned: Optional[bool] = None

    # ── #235 additions ──
    reason_codes: Tuple[str, ...] = ()          # parent reason_codes, now frozen
    served_at: Optional[datetime] = None        # wall-clock instant of first serve
    structured: Optional[StructuredWorkoutPrescription] = None  # frozen #234 view
```

`structured` reuses the #234 `StructuredWorkoutPrescription` model verbatim (no
duplication, no reshaping): `workout_type`, `target_basis`, `total_distance_km`,
`total_duration_minutes`, `steps` (each carrying `step_type`, `repetitions`,
`distance_m`, `duration_seconds`, `recovery`, `pace_zone`, `pace_min_per_km`,
`pace_min_per_km_min/max`, `reason_codes`), `steps_distance_km_sum`,
`steps_duration_seconds_sum`, the four invariant/closure flags
(`distance_invariant_applicable`, `distance_closes_total`,
`duration_invariant_applicable`, `duration_closes_total`), and its own
`reason_codes`. `StructuredWorkoutRecovery` carries `kind`, `duration_seconds`,
`distance_m`, `count`. All of this was already vendor-neutral by construction (#234
never referenced Garmin), so #235 does not introduce any new enum or vocabulary beyond
the module-level `structured_status` string constants below.

`prescription_snapshot.py` remains a pure, I/O-free module (enforced by the pre-existing
`test_module_has_no_io_dependencies` guard test): it never reads the clock and never
calls the #234 engine itself — both the `structured` payload and `served_at` are
supplied by the caller (`served_prescription.py` / `server.py`), which alone decides
*when* to compute them.

### `resolve_structured_status()` — the single state machine

```python
def resolve_structured_status(*, planned_date, reference_date, frozen_snapshot) -> str:
    if planned_date > reference_date:
        return "future_live"
    if planned_date == reference_date:
        return "today_served"
    if frozen_snapshot is not None and frozen_snapshot.structured is not None:
        return "historical_frozen"        # NEW in #235
    return "historical_unavailable"       # unchanged legacy behavior
```

This single function is now called by both `/training/today` (implicitly, via
`served_prescription.py`) and `/training/v2/week` (`week_execution.py`), which is what
guarantees Today/Week convergence (spec §8) — they can no longer diverge because they
share the exact same decision logic instead of two independent implementations.

## 3. Today — atomic/idempotent behavior (spec §6/§11)

`served_prescription.get_or_create_served_prescription()` now:

1. Does a cheap `find_one` **first**.
2. If a document already exists for `(user_id, prescription_id)`: returns it as-is.
   The caller-supplied `structured_factory()` is **never invoked** — the #234 engine is
   not called a second time, `modified_from_planned` is not recomputed.
3. Only on a genuine cache miss does it call `structured_factory()` (which wraps
   `build_structured_workout_prescription` in `server.py`), build the candidate snapshot
   (parent + `structured` + `served_at` in the same `snapshot_from_prescription()` call),
   and upsert via `$setOnInsert` (race-safe: a concurrent writer's payload wins if it
   landed first; the loser re-reads the winning document instead of using its own
   locally-built candidate).

`server.py`'s `/training/today` handler builds a `_structured_candidate_factory()`
closure over the already-adapted `WorkoutPrescription` and passes it (plus
`served_at=datetime.now(timezone.utc)`) into `get_or_create_served_prescription`; it
then reads `structured_prescription = served_result.structured` instead of always
calling the engine unconditionally as before.

**Verified by `test_pr235_today_idempotence.py`**: a counting wrapper around
`training_v2.structured_workout.build_structured_workout_prescription` shows the engine
call count is identical after the first and second same-day `/training/today` call, and
the persisted `training_prescription_snapshots` collection is byte-for-byte unchanged
after the second call.

## 4. Week — historical / today / future behavior (spec §7–9)

`week_execution.py`'s per-session loop now branches on `resolve_structured_status()`:

- **`historical_frozen`** (V2 snapshot, `planned_date < reference_date`): `structured`
  is read directly from `frozen.structured` — the #234 engine is **not** invoked.
- **`historical_unavailable`** (no snapshot, or a legacy pre-#235 parent-only snapshot):
  `structured` stays `None`. **Never backfilled** — no attempt is made to reconstruct a
  historical structure from current rules.
- **`today_served`**: reads `frozen.structured` if the day's snapshot already exists
  (created by an earlier Today/Week call this same day); otherwise falls through to the
  same lazy factory pattern used by `/training/today`, freezing it there if this is the
  very first serve of the day originating from a Week call.
- **`future_live`** (`planned_date > reference_date`): built live via the engine every
  time, exactly as before #235 — future sessions are explicitly *not* snapshotted (spec
  §9: "future = live").

## 5. Legacy compatibility (spec §12)

No migration, destructive or otherwise, was performed. All three new fields
(`reason_codes`, `served_at`, `structured`) default to backward-compatible, falsy values
(`()`, `None`, `None`), so any pre-#235 Mongo document missing these keys deserializes
cleanly via `PrescriptionSnapshot(**doc)`:

```python
legacy_doc = {"user_id": "u1", "prescription_id": "...", "planned_date": "2026-08-10",
              "day": "monday", "workout_type": "easy", "intensity_class": "low",
              "distance_km": 8.0, "duration_minutes": None}
snap = PrescriptionSnapshot(**legacy_doc)
assert snap.structured is None and snap.reason_codes == () and snap.served_at is None
```

Reading such a document yields `structured_status == "historical_unavailable"` — the
same string legacy consumers already relied on, so this is a purely additive change
w.r.t. #233.

## 6. Immutability guarantees (spec §2/§10) and how they are tested

The ABSOLUTE RULE ("a served session's snapshot is immutable") is enforced structurally:
once `structured` is populated on a `PrescriptionSnapshot` instance, nothing in the
codebase re-derives it from live inputs for a day that is `< reference_date` — the only
code path that can populate it is the one-time freeze at first-serve. Historical reads
are pure attribute access on the persisted document.

Four dedicated tests (`test_prescription_snapshot_v2_pr235.py`) directly demonstrate this
for each axis named in spec §10:

- **A — Training Paces change**: build a snapshot with VDOT 50 paces; then build a
  *live* structured view of the same session with VDOT 65 paces and confirm it differs
  from the frozen one (proving the change is real), while `snap.structured` itself stays
  byte-identical.
- **B — Goal change**: same pattern with `GoalType.five_k` → `GoalType.marathon`.
- **C — Phase change**: same pattern with `PeriodizationPhase.build` → `.taper`.
- **D — Engine-rule change**: monkeypatches
  `training_v2.structured_workout.build_structured_workout_prescription` to raise if
  called again, then asserts a historical re-read of `snap.structured` succeeds without
  ever invoking the (now-broken) engine — i.e. proves no code path re-calls the engine
  for an already-frozen day.

Two more existing (updated) tests in `test_pr232a_c231_week_endpoint.py`
(`test_c234_historical_structured_stays_none_after_goal_change`,
`test_c234_historical_structured_stays_none_after_training_paces_change` — names kept
for git-blame continuity, bodies updated) exercise the same guarantee end-to-end through
the real `/training/v2/week` HTTP handler and fake Mongo, confirming the wiring (not
just the pure model) is immutable too.

## 7. Numeric paces / recovery / mixed-basis semantics (spec §14–15)

- `test_numeric_pace_frozen_single_value_for_threshold_zone` /
  `..._range_for_easy_zone` / `test_missing_training_pace_remains_none_never_recomputed`
  assert the exact single-vs-range-vs-None discipline is frozen and survives a Mongo
  round-trip, never recomputed on read.
- `test_recovery_n_minus_1_and_mixed_basis_preserved_through_snapshot` asserts the #234
  `recovery.distance_m is None` (never fabricated), `distance_invariant_applicable is
  False` and `distance_closes_total is False` (mixed-basis, `DISTANCE_TOTAL_MIXED_BASIS`
  reason code present) are preserved exactly through a full Mongo round-trip.
- `test_known_zero_recovery_distance_distinct_from_unknown_after_round_trip` directly
  proves `None != 0` survives JSON/Mongo-shaped serialization for recovery distances.

None of these invariants are "corrected" or recomputed by the snapshot layer — they are
stored exactly as the #234 engine produced them at serve time.

## 8. Garmin-export-ready rationale (spec §17)

`test_garmin_export_ready_contract_reconstructs_executable_session_from_snapshot_alone`
builds a `quality 9km` session (goal `ten_k`, phase `build` — the same scenario used by
#234's own mixed-basis test), freezes it, reloads it through a Mongo-shaped
round-trip, and then reconstructs, from `snapshot.structured` **alone**:

- step sequence (`warmup` → `work` → `cooldown`, order-checked),
- duration basis per step (`distance` / `time` / `open`, derived from which of
  `distance_m` / `duration_seconds` is set),
- target type (`pace_single` / `pace_range` / `open`) and its numeric range,
- repetitions and full recovery detail (`kind`, `duration_seconds`, `distance_m`,
  `count`),

without calling Training Paces, PlanGoal, Periodization, or the Structured Workout
engine anywhere in the test body after the snapshot is built — demonstrating that a
future `GarminWorkoutCompiler(snapshot)` could be written as a pure adapter over this
contract. No Garmin-specific vocabulary (`garmin`, `fit_file`, `ConnectIQ`, …) appears in
the snapshot's own serialized form, confirmed by an explicit substring check in the test.

`#235` does **not** introduce a `GarminWorkoutCompiler`, any Garmin enum, or FIT
generation — only the vendor-neutral contract required to build one later, per spec §21.

## 9. Tests actually executed

```
cd backend && python -m pytest \
  tests/test_prescription_snapshot_v2_pr235.py \
  tests/test_pr235_today_idempotence.py \
  tests/test_pr232a_c231_week_endpoint.py \
  tests/test_pr231_c231_snapshot_adaptation.py \
  tests/test_pr232a_week_execution.py \
  tests/test_structured_workout_pr234.py \
  tests/test_pr231_served_prescription.py \
  tests/test_pr232a_prescription_snapshot.py \
  tests/test_daily_adaptation_pr133.py \
  tests/test_performed_workout_pr230.py \
  tests/test_pr231_c231_corrections2.py \
  tests/test_pr231_c231_corrections3.py \
  tests/test_pr231_c231_final_corrections.py \
  tests/test_pr231_external_id_boundary.py \
  tests/test_pr232a_local_reference_date.py \
  tests/test_training_paces_pr194.py \
  tests/test_workout_generator_v2.py \
  -q
```
Result: **483 passed, 0 failed**.

This covers: new #235 tests (22), existing #234 structured-workout suite (unmodified,
still green), existing week-endpoint / snapshot-adaptation / week-execution suites
(#231/#232A, 3 tests updated for the new intended `historical_frozen` behavior),
prescription-snapshot pure unit tests (#231, extended model), served-prescription
idempotence, DailyAdaptation (#133), performed-workout matching (#230), external-ID
boundary handling, local-reference-date handling (#232A), Training Paces (#194), and
WorkoutGenerator V2.

A full repository-wide baseline run was performed once before starting code changes
(299 failed / 2760 passed / 41 errors) to confirm which failures are pre-existing and
unrelated (network-dependent live-server tests, Redis-fixture tests, and xdist-parallel
rate-limiting flakiness) — none of those pre-existing failures are in files touched or
exercised by this change.

## 10. CI

No GitHub Actions workflow run was triggered or observed for this branch as part of this
session (the task instructions require investigating CI only "when users mention CI,
build, test, or workflow failures" — none were mentioned or discovered here). All
validation in this report was performed locally via `pytest`, matching the project's
documented backend test-runner convention (`python -m pytest`, `pytest.ini` enforces
`-n 2 --dist loadscope`).

## 11. Known limitations

- A rare legacy edge case exists: a parent-only (pre-#235) snapshot that was created for
  a day that is **still today** at read time (i.e., the app served that day before this
  deploy and has not yet rolled past midnight since). In this specific case, both
  `/training/today` and `/training/v2/week` fall back to building `structured` live,
  best-effort, on every such call — it is not persisted (insert-only snapshot semantics
  forbid rewriting an existing document). This is deliberately conservative (never
  invents/backfills a *historical* structure) but means that narrow window is not fully
  idempotent. It self-resolves the moment the day becomes historical (at which point the
  legacy parent-only doc simply reports `historical_unavailable`, per spec §12).
- The Garmin-export-ready contract test operates over one representative scenario
  (quality 9 km, mixed-basis, repeated work). It is not an exhaustive enumeration of
  every workout-type × goal × phase combination — that exhaustive coverage already exists
  in the (untouched) #234 suite; #235's contract test specifically demonstrates
  *reconstructability from the snapshot alone*, not #234 correctness.

## 12. Explicit confirmations

- ✅ No frontend files modified.
- ✅ No Garmin Training API / FIT integration added.
- ✅ No `GarminWorkoutCompiler` created.
- ✅ No #236 work performed.
- ✅ No merge performed — PR left open against `copilot/dev`, in **DRAFT**.

---

# C235 CORRECTIVE AUDIT

Corrective pass on PR #235 fixing 4 audited blockers, without reopening or
rearchitecting the already-validated #235 design.

- **Head before correction:** `7fcee2c87a0661dc32855eef0a52ae1773d2137a`
- **New head:** this commit (see PR diff).
- **Scope:** `backend/server.py`, `backend/training_v2/{today_prescription,
  served_prescription, prescription_snapshot, week_execution,
  training_week_response}.py`, plus new/updated tests. No frontend, no #234
  engine, no Garmin/FIT, no #236.

## C1. Today fast-path (blocker #1 — idempotence)

`GET /training/today` now does a cheap `find_one` on
`(user_id, prescription_id)` **before** ever calling
`resolve_today_final_prescription` (which bundles Readiness +
DailyAdaptation + Structured Workout):

- **Snapshot exists** → FAST PATH: read `parent` + `structured` +
  `adaptation_action`/`adaptation_reason_codes` directly from the frozen
  document (`PrescriptionSnapshot(**doc)` + `resolve_effective_session`).
  `resolve_today_final_prescription` (and therefore `build_daily_adaptation`
  and the #234 engine) is **never called**. A live readiness read
  (`training_v2.today_prescription.resolve_live_readiness`, a new pure
  helper factored out of `resolve_today_final_prescription`) remains
  available for the `readiness`/`fatigue` diagnostic blocks only — it never
  feeds into the served-prescription fields.
- **Snapshot absent** → SLOW PATH: unchanged pipeline (readiness →
  DailyAdaptation → Structured Workout → atomic
  `get_or_create_served_prescription`), now additionally freezing
  `adaptation_action`/`adaptation_reason_codes` at creation time.

**Proof the second Today never re-runs DailyAdaptation:** new test
`tests/test_pr235_c235_corrections.py::test_second_today_never_invokes_daily_adaptation`
patches `training_v2.today_prescription.build_daily_adaptation` with a
call-counter. First call → count == 1 (creates the snapshot). Second call →
count **stays at 1**. This test was verified to **fail on the pre-correction
head** (`7fcee2c`, count == 2), and **pass** on the corrected head.

## C2. Frozen serve metadata (blocker #2)

`PrescriptionSnapshot` gained two additive fields:
`adaptation_action: Optional[str] = None` and
`adaptation_reason_codes: Tuple[str, ...] = ()`, threaded through
`snapshot_from_prescription`, `get_or_create_served_prescription` (params +
`ServedPrescriptionResult`), and both call sites (`/training/today`,
`/training/v2/week`'s fallback-creation branch — which honestly records
`None`/`()` since no adaptation candidate is available there). Today's
response now derives `adaptation_action`, `adaptation_reason`, and
`adaptation_applied` **exclusively** from the winning snapshot's frozen
metadata (`served_result.adaptation_action` /
`served_result.adaptation_reason_codes`), never from a freshly recomputed
`adaptation_result` once a snapshot exists — including on the very call
that creates it, since a concurrent caller may have actually won the write.

## C3. reason_codes convergence (blocker #3)

Today's `"reason_codes"` field now reads `served_prescription.reason_codes`
(the effective, frozen parent — identical source Week already used via
`resolve_effective_session`), replacing the old
`list(adaptation_result.reason_codes)` (live). This single change fixes
convergence for both the creation call and every subsequent call.

**Test:**
`test_reason_codes_frozen_across_today_and_week_despite_live_drift` patches
`build_daily_adaptation` so any call beyond the first would (if it ever ran)
return a different reason code (`"LIVE_DRIFT_SHOULD_NEVER_LEAK"`). Asserts
Today (2nd call) and Week both keep the original, frozen reason codes and
never see the drifted value. Fails on `7fcee2c` (both leak the drift on the
second Today call and Week already diverges from Today on the first call
in the old code path is actually consistent then diverges after — see test
run for the exact failure output), passes on the corrected head.

## C4. Snapshot identity (prescription_id Today/Week)

`/training/today` now returns `"prescription_id"` (the existing
`week_execution.prescription_id_for(user_id, today, day_name.lower())`
value — no new identifier). `week_execution.SessionExecution` gained a
`prescription_id` field (populated for every session, including
`EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE` ones), threaded additively into
`WeekV2SessionResponse.prescription_id` via `/training/v2/week`'s
`_session_response`.

**Tests:** `test_today_and_week_expose_same_prescription_id_identity` and
`test_week_first_then_today_still_expose_same_prescription_id` assert
`Today.prescription_id == Week.sessions[today].prescription_id` (both
call orders), plus parent/structured convergence. Both fail (KeyError:
`prescription_id`) on `7fcee2c`, pass on the corrected head.

## C5. Concurrency — honest claim (blocker #4/#9)

The previous "structured_factory AT MOST ONCE globally per day" claim in
`served_prescription.py`'s docstrings was **false** under genuine
concurrency (two callers can both observe "not found" on the pre-check read
before either wins the `$setOnInsert`). Docstrings now state the honest
guarantee:

- `structured_factory` may run more than once concurrently (pure, no side
  effect beyond wasted CPU — a losing candidate is discarded, never
  persisted, never observed).
- The **final persisted document** is unique/atomic (unique index on
  `(user_id, prescription_id)` + `$setOnInsert`).
- Every caller (winner or loser) re-reads and converges on that **same**
  winning document before returning.
- Every subsequent (non-concurrent) call short-circuits on the cheap
  pre-check and never invokes the factory again.

**Test:** `test_concurrent_first_serve_converges_on_single_winning_snapshot`
injects a real `await asyncio.sleep(0)` yield point into the fake DB's
`find_one` (the existing fake DB has no genuine suspension points, so a
plain `asyncio.gather` never actually interleaves two callers — this was
verified by inspection before writing the test). With the yield point, two
concurrent `GET /training/today` calls are scheduled via `asyncio.gather`;
asserts: exactly one snapshot document persists, both responses' `parent` +
`structured` + `reason_codes` + `prescription_id` converge byte-for-byte,
and the structured-engine factory count is `>= 1` (never asserting "exactly
1", matching the corrected, honest claim).

## C6. Legacy Today (unchanged behaviour, documented)

The existing legacy edge case — a pre-#235 parent-only snapshot still
"today" — is preserved: the fast path rebuilds `structured` live,
best-effort, without persisting over the existing insert-only document
(mirrors `week_execution`'s identical `"today_served"` legacy handling).
This narrow window is not fully idempotent for `structured`; it self-heals
once the day becomes historical (`historical_unavailable`, unchanged). No
destructive rewrite of any historical snapshot was introduced.

## C7. Tests executed (this corrective pass)

New (all verified to fail on `7fcee2c`, pass on the corrected head):
- `tests/test_pr235_c235_corrections.py` (5 tests): second-Today-skips-
  DailyAdaptation, frozen-reason_codes-convergence, snapshot-identity
  (both call orders), concurrent-first-serve-convergence.

Re-run, all passing (no regressions vs. `7fcee2c` — a full-repo diff of
failing test names before/after this change is byte-for-byte identical,
confirming zero newly-introduced failures):
- `tests/test_pr235_today_idempotence.py`
- `tests/test_prescription_snapshot_v2_pr235.py`
- `tests/test_pr232a_c231_week_endpoint.py`
- `tests/test_pr231_served_prescription.py`
- `tests/test_pr232a_prescription_snapshot.py`
- `tests/test_pr232a_week_execution.py`
- `tests/test_pr231_c231_corrections2.py`
- `tests/test_pr231_c231_corrections3.py`
- `tests/test_pr231_c231_snapshot_adaptation.py`
- `tests/test_daily_adaptation_pr133.py`
- `tests/test_structured_workout_pr234.py`
- `tests/test_training_paces_pr194.py`
- `tests/test_pr232a_local_reference_date.py`
- `tests/test_performed_workout_pr230.py`
- `tests/test_pr231_external_id_boundary.py`
- `tests/test_handlers_pr228.py`
- `tests/test_workout_generator_v2.py`

A full repository-wide run (`pytest tests/`, `-n 2 --dist loadscope`) was
also performed before and after this change: **301 pre-existing failures**
in both cases, and a name-for-name diff of the two failure lists is
**empty** — confirming this corrective pass introduces zero regressions.
(Two additional flaky/order-dependent failures — `test_single_clock_in_today`
and a `test_race_day_...` rate-limit timeout — were independently reproduced
on the unmodified `7fcee2c` head and pass in isolation; they are pre-existing
test-infra flakiness, unrelated to this change.)

## C8. CI (real)

No GitHub Actions workflow run was triggered for this branch during this
corrective pass. As with the original #235 session, no CI failure was
reported or investigated (out of scope per task instructions — CI
investigation is only required when failures are mentioned).

## C9. Final confirmations (per corrective-audit §14)

- ✅ A snapshot Today existing can be read without calling DailyAdaptation
  (C1, test-verified).
- ✅ Today's prescription `reason_codes` no longer come from a live
  adaptation (C3, test-verified).
- ✅ Today + Week both expose `prescription_id` (C4, test-verified).
- ✅ Today + Week converge on parent + structured (C4, pre-existing +
  new tests).
- ✅ No historical structured snapshot is ever recomputed (unchanged from
  original #235 — C231/#235 historical-frozen semantics untouched).
- ✅ No Garmin-specific logic added.
- ✅ No frontend modification.
- ✅ No merge — PR stays in **DRAFT** against `copilot/dev`.

