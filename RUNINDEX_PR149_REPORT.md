# RUNINDEX PR149 REPORT — Premier découplage V2 ciblé

## 1. HEAD copilot/dev

`9e6dbaf` — Merge pull request #148 (test-fallback-still-exists). PR #148 confirmed merged.

## 2. Contrat /training/week-plan AVANT

| Field | Source | Frontend? | LLM? | Legacy/V2 |
|-------|--------|-----------|-------|-----------|
| goal | db.training_goals | Yes | No | Legacy |
| current_week | computed (start_date, today) | Yes | No | Legacy |
| total_weeks | goal.cycle_weeks | Yes | No | Legacy |
| phase | determine_phase() | Yes | Yes (context) | Legacy |
| context | computed (km*10, weekly_km) | No | Yes | Legacy |
| debug_volume | computed | No | No | Display |
| plan | generate_cycle_week / fallback | Yes | Produced by | Legacy |
| generated_by | "llm" / "fallback" | Yes | No | Legacy |
| metadata | LLM metadata | No | No | Legacy |

## 3. Consumer Matrix

| Symbol | Responsibility | Consumer | V2 Equivalent | Migrated #149? |
|--------|---------------|----------|---------------|----------------|
| DEFAULT_WEEKLY_KM | fallback floor | fallback display | REMOVED in V2 | Superseded by V2 target |
| compute_current_weekly_km | 28d avg | context.weekly_km | TrainingHistory.window_28d | Kept (compat) |
| determine_phase | cycle phase | LLM + response | Periodization V2 | Kept (compat) |
| determine_target_load | pseudo-load | LLM context | NOT equivalent to V2 | Kept (LLM compat only) |
| resolve_reprise_plan | target_km + state | prescription | WeeklyTarget V2 | **REPLACED by V2** |
| generate_cycle_week | LLM plan | response.plan | Future PR | Kept |
| _generate_fallback_week_plan | fallback plan | response.plan | Future PR | Kept (receives V2 cap) |

## 4. Source db.workouts auditée

`db.workouts` contains normalized activity documents with fields: `user_id`, `date`, `distance_km`, `duration_minutes`, `activity_type`, `average_hr`, `start_time`, etc. These correspond to Garmin-synced activities (via Terra) stored as normalized documents — NOT raw Garmin API responses.

## 5. Frontière DomainActivity

The bridge module (`training_v2/week_plan_bridge.py`) converts raw `db.workouts` documents to DomainActivity-compatible dicts before feeding them into the V2 chain. No raw Mongo documents enter Training V2.

## 6. Choix: OPTION B

The V2 orchestration chain already exists in `coach_service.py`. PR149 extracts a reusable `build_weekly_target_from_workouts()` function that wires the same V2 builders without duplicating any formulas.

## 7. Scope réellement migré

**Weekly prescription source**: `resolve_reprise_plan` → `WeeklyTarget V2`

Specifically:
- `target_km_protected` now comes from `WeeklyTarget.target_km` (distance-based)
- `target_km_protected = None` for duration-based states (deep_reprise, no_history)
- `context["training_state"]` now comes from `WeeklyTarget.continuity_state`
- No invented km for duration-based runners

## 8. Legacy restant dans week-plan

| Component | Status | Rationale |
|-----------|--------|-----------|
| determine_phase | Legacy compat | Phase enum differs from V2; not worth migrating alone |
| determine_target_load | Legacy compat | Only consumed by LLM rendering |
| generate_cycle_week | Legacy | LLM generation — future dedicated PR |
| _generate_fallback_week_plan | Legacy | Receives V2 cap but templates remain legacy |
| compute_current_weekly_km | Legacy compat | Display metric |

## 9. WeeklyTarget V2 — comment utilisé

```
WeeklyTarget V2 decides → target_km_protected (or None)
                         → continuity_state
                         → target_duration_minutes (duration-based)

Legacy LLM receives V2 values via context dict (compat projection)
```

V2 decides → compat projects. Never: legacy decides → V2 decorative.

## 10. Duration-based semantics

- `deep_reprise` / `no_history` → `target_basis = "duration"`, `target_km = None`
- No km fabrication for duration-based states
- `target_duration_minutes` transported in context for awareness

## 11. Reprise semantics

- `resolve_reprise_plan` no longer decides `target_km_protected`
- `WeeklyTarget V2` is sole authority for the weekly prescription
- Legacy `resolve_reprise_plan` call **removed** from endpoint

## 12. target_load semantics

- `determine_target_load` returns pseudo-load units (km*10/phase-adjusted)
- It is NOT renamed or confused with V2 metrics
- Kept solely for LLM rendering compatibility
- Documented as "Legacy target_load for LLM rendering (NOT the prescription source)"

## 13. Fallback status

`_generate_fallback_week_plan` still uses legacy templates. It receives `target_km_protected` from V2 as a cap. When V2 prescribes duration-based (None), the fallback uses its own `weekly_km` with phase multiplier — this is an acknowledged legacy path, not a V2 path.

## 14. Fichiers modifiés

- `backend/training_v2/week_plan_bridge.py` — NEW: V2 orchestration bridge
- `backend/server.py` — MODIFIED: /training/week-plan endpoint migrated to V2 prescription
- `backend/tests/test_pr149_week_plan_v2.py` — NEW: 9 architecture tests

## 15. Tests

| Test | Status |
|------|--------|
| test_normal_runner_distance_based | PASS |
| test_target_load_is_independent_of_weekly_target | PASS |
| test_no_recent_activity_deep_reprise | PASS |
| test_no_history_no_invented_km | PASS |
| test_bridge_produces_valid_target_from_raw_docs | PASS |
| test_duration_based_target_km_is_none_not_zero | PASS |
| test_weekly_target_has_no_acwr_tss_fields | PASS |
| test_low_volume_marathon_stays_low | PASS |
| test_same_inputs_same_output | PASS |
| Existing WeeklyTarget V2 tests (57) | ALL PASS |

## 16. Risques

1. **LLM generate_cycle_week**: may not handle `target_km_protected=None` gracefully for duration-based states. Mitigation: `target_duration_minutes` added to context.
2. **Fallback path**: when V2 prescribes duration-based, fallback still uses `weekly_km` with DEFAULT_WEEKLY_KM possibility. Acceptable for now (acknowledged legacy path).
3. **Phase mismatch**: legacy `determine_phase` enums ≠ V2 `PeriodizationPhase` enums. Not migrated in this PR — documented compat.

## 17. Runtime requis

After merge, validate:
- `/training/week-plan` — target_km, target_basis, continuity_state, prescription_source
- `/training/plan` — unchanged (uses coach_service V2 independently)
- `/training/today` — unchanged
- `/training/full-cycle` — unchanged
- `/training/metrics` — unchanged
- `/run-index` — unchanged
- `/dashboard` — unchanged

## 18. Scope exact #150

Recommended scope for PR #150:
1. Migrate `_generate_fallback_week_plan` to consume WeeklyTarget V2 natively (duration-based templates)
2. Migrate legacy `determine_phase` → Periodization V2 as response field
3. Full `generate_cycle_week` migration (or replacement with WorkoutGenerator V2 + LLM enrichment)

---

## Verdict

**READY FOR MERGE INTO copilot/dev**

Formulation exacte:

> /training/week-plan weekly prescription migrated to WeeklyTarget V2;
> legacy rendering/LLM compatibility remains (generate_cycle_week, fallback templates, determine_phase).
