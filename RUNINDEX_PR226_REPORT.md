# RUNINDEX PR226 — Goal Truth Unification (+ Patch)

## Objectif

Unifier la vérité des objectifs d'entraînement en corrigeant plusieurs incohérences
entre `training_cycles`, `user_goals`, et les consommateurs V2.

---

## Problèmes corrigés

### 1. Fallback SEMI → MAINTENANCE (`server.py`)

**Avant :** `plan_data.get("goal", "SEMI")`  
**Après :** `plan_data.get("goal", "MAINTENANCE")`

Le fallback dynamique est désormais `MAINTENANCE` (continu, sans race_date inventée),
jamais `SEMI` qui forçait un cycle semi-marathon inexistant.

---

### 2. Suppression du `race_date` stale après changement d'objectif

Tout appel à `/training/set-goal` ou `/training-plan/set-goal` déclenche
`db.user_goals.delete_many({"user_id": ...})` **après** mutation de `training_cycles`.

Tout changement d'objectif invalide les métadonnées de course précédentes.

---

### 3. Validation avant mutation — `POST /user/goal` (PATCH)

**Avant :** `delete_many` s'exécutait avant toute validation → un payload invalide
pouvait effacer un goal valide.

**Après :** toute validation (distance_type, ultra distance, cohérence avec cycle)
s'exécute AVANT `delete_many` / `insert_one`. Un payload invalide → 400 sans aucune mutation.

---

### 4. Cohérence `user_goal.distance_type` ↔ `training_cycles.goal` (PATCH)

`POST /user/goal` vérifie désormais que `distance_type` correspond au cycle actif :

| `training_cycles.goal` | `distance_type` attendu |
|---|---|
| 5K | 5k |
| 10K | 10k |
| SEMI | semi |
| MARATHON | marathon |
| ULTRA | ultra |

Incompatibilité → HTTP 400, aucune mutation.

---

### 5. MAINTENANCE sans race_date ni target_time

La suppression de `user_goals` à chaque changement garantit que MAINTENANCE
n'hérite jamais d'un `race_date` ou `target_time` d'un objectif précédent.

---

### 6. ULTRA — distance obligatoire > 42,195 km

#### Helper canonique `_validate_ultra_distance_km` (server.py)

Point unique pour la validation de la distance ultra. Toute modification du seuil
ou du message d'erreur se fait en un seul endroit.

#### `POST /training/set-goal` + `POST /training-plan/set-goal`
- Sans `distance_km` → HTTP 400, **aucune mutation** (training_cycles non créé)
- `distance_km <= 42.195` → HTTP 400
- `distance_km > 42.195` → stocké dans `training_cycles.ultra_distance_km`

#### `POST /user/goal`
- `distance_type == "ultra"` sans `distance_km > 42.195` → HTTP 400
- Validation avant `delete_many` (atomic write)

---

### 7. Distances

`DISTANCE_TYPES` aligné sur les constantes V2 :

| Type | Avant | Après |
|---|---|---|
| semi | 21.1 | 21.0975 (= `DISTANCE_HALF_MARATHON_KM`) |
| ultra | 50.0 (hardcode) | **supprimé** — distance explicite obligatoire |

---

### 8. `target_distance_km` propagé au bridge V2 (PATCH)

`week_plan_bridge._build_weekly_context_from_workouts` et
`build_weekly_plan_from_workouts` acceptent maintenant `target_distance_km: Optional[float]`.

Le paramètre est transmis à `build_plan_goal()` pour les goals ULTRA.

Endpoints mis à jour :
- `GET /training/week-plan` — passe `target_distance_km_v2`
- `GET /training/v2/week` — résout et passe `target_distance_km_v2`

---

### 9. Fallback V2 : `training_cycles.ultra_distance_km`

Les deux endpoints V2 lisent `ultra_distance_km` en fallback
quand `user_goals.distance_km` est absent :

```python
raw_dist = user_goal.get("distance_km") if user_goal else None
if not (isinstance(raw_dist, (int, float)) and not isinstance(raw_dist, bool) and raw_dist > ULTRA_MIN_DISTANCE_KM):
    raw_dist = cycle.get("ultra_distance_km") if cycle else None
```

---

### 10. Onboarding — distance ULTRA avant création du plan

`Onboarding.jsx` affiche un champ de saisie dès que `ULTRA` est sélectionné.
Le bouton « Continuer » reste désactivé tant que `distance_km <= 42.195`.
La distance est envoyée via `set-goal?goal=ULTRA&distance_km=<valeur>`.

---

### 11. Settings — distance ULTRA requise avant appel set-goal (PATCH)

`Settings.jsx` :
- Un champ `pendingUltraDistance` est visible en permanence dans le bloc « Changer d'objectif ».
- Cliquer sur ULTRA sans distance valide → message d'erreur, **aucun appel API**.
- Distance valide → `set-goal?goal=ULTRA&distance_km=<valeur>` envoyé.
- Le formulaire de race settings affiche aussi un champ `ultraDistanceKm` pour `POST /user/goal`.

---

## Audit consommateurs

| Consommateur | Lecture race_date | Protection MAINTENANCE | ULTRA distance |
|---|---|---|---|
| `GET /training/week-plan` | `user_goals.event_date` | oui (V2 builder) | propagé via bridge ✓ |
| `GET /training/v2/week` | `user_goals.event_date` | oui (V2 builder) | résolu + propagé ✓ |
| `GET /training/v2/cycle` | `user_goals.event_date` | oui (V2 builder) | fallback cycle ✓ |
| Coach / LLM | `training_plans.goal` (snapshot) | `MAINTENANCE` fallback ✓ | N/A |
| Dashboard | lit `/training/v2/cycle` | hérité | hérité |
| Settings | lit `/user/goal` + `/training/v2/cycle` | `hasRaceSettings: false` | distance inline ✓ |
| Onboarding | `set-goal` seulement | pas de user_goals | `distance_km` passé ✓ |

---

## Tests — `backend/tests/test_goal_truth_pr226.py`

### Tests unitaires (source-level + plan_goal)

| # | Test | Scénario | Résultat |
|---|---|---|---|
| 1 | `test_goal_config_has_all_goals` | GOAL_CONFIG complet | PASS |
| 2-5 | `test_standard_goal_cycle_weeks[5K/10K/SEMI/MARATHON]` | cycle_weeks correct | PASS |
| 6 | `test_maintenance_has_no_race_date_in_plan_goal` | PlanGoal MAINTENANCE | PASS |
| 7 | `test_maintenance_has_no_target_time_in_plan_goal` | PlanGoal MAINTENANCE | PASS |
| 8 | `test_maintenance_has_no_target_distance_in_plan_goal` | PlanGoal MAINTENANCE | PASS |
| 9 | `test_maintenance_rejects_race_date` | ValueError si race_date | PASS |
| 10 | `test_maintenance_rejects_target_time` | ValueError si target_time | PASS |
| 11 | `test_fallback_without_goal_is_maintenance_not_semi` | code source | PASS |
| 12 | `test_set_goal_deletes_user_goals_in_source` | code source | PASS |
| 13 | `test_set_training_plan_goal_deletes_user_goals_in_source` | code source | PASS |
| 14 | `test_ultra_without_distance_refused` | ValueError | PASS |
| 15 | `test_ultra_exactly_marathon_refused` | ValueError 42.195 | PASS |
| 16 | `test_ultra_below_marathon_refused` | ValueError < 42.195 | PASS |
| 17 | `test_ultra_with_valid_distance_accepted` | 50.0 km OK | PASS |
| 18 | `test_ultra_distance_propagated_exactly` | 170.0 km non écrasé | PASS |
| 19 | `test_set_goal_endpoint_validates_ultra_distance` | code source | PASS |
| 20 | `test_set_goal_stores_ultra_distance_in_cycles` | code source | PASS |
| 21 | `test_user_goal_create_model_has_distance_km` | modèle | PASS |
| 22 | `test_user_goal_endpoint_validates_ultra_distance` | helper + code source | PASS |
| 23 | `test_v2_endpoints_have_ultra_distance_fallback` | ≥3 occurrences | PASS |

### Tests HTTP (skippés si email-validator absent)

| # | Test | Scénario | Résultat |
|---|---|---|---|
| 24 | `test_http_10k_goal_set_correctly` | 10K → training_cycles.goal=10K | SKIP (no email-validator) |
| 25 | `test_http_incoherent_goal_distance_type_rejected` | 10K + semi → 400 | SKIP |
| 26 | `test_http_ultra_50km_set_goal_succeeds` | ULTRA 50 km → cycle OK | SKIP |
| 27 | `test_http_ultra_no_distance_rejected_no_mutation` | ULTRA sans dist → 400, no cycle | SKIP |
| 28 | `test_http_maintenance_clears_race_metadata` | MAINTENANCE → user_goals vide | SKIP |
| 29 | `test_http_user_goal_ultra_valid` | ultra 100 km + cycle ULTRA → OK | SKIP |

---

## Runtime

DEFERRED TO FINAL RUNTIME GATE.

---

## C226

PR #226 — base: `copilot/dev`. NE PAS merger.
