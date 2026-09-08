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
