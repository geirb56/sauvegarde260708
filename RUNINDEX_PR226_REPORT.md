# RUNINDEX PR226 — Goal Truth Unification (Final Patch)

## Objectif

Unifier la vérité des objectifs d'entraînement : `training_cycles` + `user_goals` → `PlanGoal V2`.
Résoudre les 3 blockers du patch final : resolver canonique, MAINTENANCE stricte, ULTRA/bridge/tests réels.

---

## Changements

### 1. Resolver canonique `_resolve_goal_v2` (`server.py`)

Nouvelle fonction asynchrone unique qui lit `training_cycles` + `user_goals` et retourne un
`_ResolvedGoal` immutable (goal_type, mapped_goal, cycle_start, race_date, target_time_sec,
target_distance_km, cycle_doc, user_goal_doc).

**Règles enforced :**
- Pas de cycle → HTTP 400
- Type inconnu → HTTP 400
- MAINTENANCE → race_date=None, target_time_sec=None toujours (jamais de métadonnées stale)
- ULTRA sans distance → HTTP 400
- user_goal.distance_type ≠ cycle.goal → HTTP 400 (cohérence)

**Utilisé dans :**
- `GET /training/v2/week`
- `GET /training/v2/cycle`
- `GET /training/week-plan`

Plus aucune logique de résolution dupliquée dans ces 3 endpoints.

---

### 2. MAINTENANCE stricte (`server.py`)

#### `POST /user/goal`
- Bloqué si `training_cycles.goal == MAINTENANCE` → HTTP 400 explicite.
- Validation de `event_date` AVANT `delete_many` : doit être ISO parseable et future.
- Tous les checks (MAINTENANCE, event_date, distance_type, ultra distance, cohérence) s'exécutent
  avant toute mutation DB.

#### `/v2/week`, `/v2/cycle`, `/week-plan`
- Via `_resolve_goal_v2` : `race_date=None`, `target_time_sec=None` systématiquement pour MAINTENANCE.
- Jamais de métadonnées de course exposées pour un cycle MAINTENANCE.

---

### 3. ULTRA propagation complète (`week_plan_bridge.py`)

`build_weekly_target_from_workouts` accepte maintenant `target_distance_km: Optional[float] = None`
(en plus de `build_weekly_plan_from_workouts` déjà mis à jour précédemment).

Les 3 endpoints passent `resolved.target_distance_km` au bridge.

---

### 4. Fallback SEMI → MAINTENANCE (`server.py`)

`plan_data.get("goal", "SEMI")` → `plan_data.get("goal", "MAINTENANCE")`.

---

### 5. Distances (`server.py`)

| Type | Avant | Après |
|---|---|---|
| semi | 21.1 | 21.0975 (= `DISTANCE_HALF_MARATHON_KM` V2) |
| ultra | 50.0 (hardcode) | Supprimé — distance explicite obligatoire |

---

### 6. Validation `event_date` (`server.py`)

`POST /user/goal` valide `event_date` avant toute mutation :
- doit être parseable ISO (YYYY-MM-DD)
- doit être une date future

---

### 7. `invalid goal` → `HTTPException(400)` (`server.py`)

Les deux endpoints `set-goal` retournaient `{"error": "Invalid goal"}` (HTTP 200).
Corrigé en `raise HTTPException(status_code=400, detail="Invalid goal")`.

---

## Audit consommateurs

| Consommateur | Resolver utilisé | MAINTENANCE OK | ULTRA distance |
|---|---|---|---|
| `GET /training/v2/week` | `_resolve_goal_v2` ✓ | race_date=None ✓ | propagé ✓ |
| `GET /training/v2/cycle` | `_resolve_goal_v2` ✓ | race_date=None ✓ | propagé ✓ |
| `GET /training/week-plan` | `_resolve_goal_v2` ✓ | race_date=None ✓ | propagé ✓ |
| `POST /user/goal` | validation inline | bloqué ✓ | rejeté sans mutation ✓ |

---

## Tests — `backend/tests/test_goal_truth_pr226.py`

**50 tests, 0 skips, 0 failures** (40 after initial patch + 10 added in final patch).

### Section A — Unitaires / source-inspection

| # | Test | Résultat |
|---|---|---|
| 1 | `test_goal_config_has_all_goals` | PASS |
| 2-5 | `test_standard_goal_cycle_weeks[5K/10K/SEMI/MARATHON]` | PASS |
| 6 | `test_maintenance_has_no_race_date` | PASS |
| 7 | `test_maintenance_has_no_target_time` | PASS |
| 8 | `test_maintenance_rejects_race_date` | PASS |
| 9 | `test_fallback_without_goal_is_maintenance` | PASS |
| 10 | `test_set_goal_deletes_user_goals` | PASS |
| 11 | `test_ultra_without_distance_rejected` | PASS |
| 12 | `test_ultra_exactly_42195_rejected` | PASS |
| 13 | `test_ultra_valid_distance_accepted` | PASS |
| 14 | `test_ultra_distance_propagated_exactly` | PASS |
| 15 | `test_user_goal_create_model_has_distance_km` | PASS |
| 16 | `test_canonical_resolver_exists` | PASS |
| 17 | `test_semi_distance_is_21_0975` | PASS |
| 18 | `test_ultra_not_in_distance_types` | PASS |
| 19 | `test_validate_ultra_distance_km_helper_exists` | PASS |
| 20 | `test_validate_ultra_rejects_none` | PASS |
| 21 | `test_validate_ultra_rejects_42195` | PASS |
| 22 | `test_validate_ultra_accepts_50` | PASS |
| 23 | `test_goal_to_distance_type_map` | PASS |
| 24 | `test_build_weekly_target_from_workouts_has_target_distance_param` | PASS |
| 25 | `test_invalid_goal_raises_http400` | PASS |
| 26 | `test_post_user_goal_blocks_maintenance` | PASS |
| 27 | `test_event_date_validated_in_post_user_goal` | PASS |

### Section B — _resolve_goal_v2 avec DB mockée

| # | Test | Résultat |
|---|---|---|
| 28 | `test_resolve_goal_10k_coherent` | PASS |
| 29 | `test_resolve_goal_10k_with_coherent_user_goal` | PASS |
| 30 | `test_resolve_goal_10k_incoherent_semi_rejected` | PASS |
| 31 | `test_resolve_goal_maintenance_race_date_always_none` | PASS |
| 32 | `test_resolve_goal_ultra_50km_ok` | PASS |
| 33 | `test_resolve_goal_ultra_no_distance_rejected` | PASS |
| 34 | `test_resolve_goal_no_cycle_rejected` | PASS |

### Section C — POST /user/goal avec handler réel

| # | Test | Scénario | Résultat |
|---|---|---|---|
| 35 | `test_post_user_goal_maintenance_cycle_blocked` | MAINTENANCE cycle → 400 | PASS |
| 36 | `test_post_user_goal_ultra_no_distance_no_mutation` | ULTRA sans dist → 400 + pas de delete | PASS |
| 37 | `test_post_user_goal_ultra_42195_exact_rejected` | dist=42.195 → 400 | PASS |
| 38 | `test_post_user_goal_10k_incoherent_semi_blocked` | 10K + semi → 400 + pas de delete | PASS |
| 39 | `test_post_user_goal_past_date_rejected` | event_date passée → 400 | PASS |
| 40 | `test_post_user_goal_ultra_100km_succeeds` | ULTRA 100 km → insert, success | PASS |

---

## Runtime

DEFERRED TO FINAL RUNTIME GATE.

---

## C226

PR #226 — base: `copilot/dev`. NE PAS merger.

---

## Patch supplémentaire (final)

### Corrections `_resolve_goal_v2`

1. **`start_date` absent ou invalide → HTTP 400**
   - `cycle.get("start_date")` retourne `None` → `raise HTTPException(400)`
   - Parse échoue (garbage string) → `raise HTTPException(400)`
   - Plus aucun fallback silencieux `cycle_start = None`

2. **`event_date` présente mais invalide → HTTP 400**
   - Si `rd_raw` est présent mais non parseable → `raise HTTPException(400, "event_date '...' is not a valid ISO date")`
   - Type inattendu → `raise HTTPException(400)`
   - Plus de `pass` silencieux dans le bloc sauf

### Correction `/training/week-plan`

- Suppression du `or today.date()` dans `build_periodization(cycle_anchor_date=...)`
- Suppression de la relecture de `resolved.cycle_doc.get("start_date")` brut
- `cycle_start_v2` (déjà validé dans `_resolve_goal_v2`) utilisé exclusivement via `resolved.cycle_start`

### Tests ajoutés — Section D et E (10 nouveaux tests, 0 skip)

| # | Test | Résultat |
|---|---|---|
| 41 | `test_resolve_goal_no_start_date_rejected` | PASS |
| 42 | `test_resolve_goal_invalid_start_date_rejected` | PASS |
| 43 | `test_resolve_goal_invalid_event_date_rejected` | PASS |
| 44 | `test_resolve_goal_none_start_date_rejected` | PASS |
| 45 | `test_get_training_v2_week_10k_coherent` | PASS |
| 46 | `test_get_training_v2_cycle_10k_coherent` | PASS |
| 47 | `test_get_training_v2_week_ultra_50km` | PASS |
| 48 | `test_get_training_v2_cycle_ultra_50km` | PASS |
| 49 | `test_get_training_v2_week_invalid_start_date_rejected` | PASS |
| 50 | `test_get_training_v2_week_invalid_event_date_rejected` | PASS |

**Total : 50 tests, 0 skip, 0 failure.**
