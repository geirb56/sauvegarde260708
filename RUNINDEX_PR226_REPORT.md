# RUNINDEX PR226 — Goal Truth Unification

## Objectif

Unifier la vérité des objectifs d'entraînement en corrigeant plusieurs incohérences
entre `training_cycles`, `user_goals`, et les consommateurs V2.

---

## Problèmes corrigés

### 1. Fallback SEMI → MAINTENANCE (`server.py` l.1383)

**Avant :**
```python
current_goal = plan_data.get("goal", "SEMI")
```
**Après :**
```python
current_goal = plan_data.get("goal", "MAINTENANCE")
```
Le fallback dynamique est désormais `MAINTENANCE` (continu, sans race_date inventée),
jamais `SEMI` qui forçait un cycle semi-marathon inexistant.

---

### 2. Suppression du `race_date` stale après changement d'objectif

**Problème :** appeler `/training/set-goal?goal=5K` après un MARATHON laissait
l'ancien `user_goals` en base, avec `race_date=2025-09-28` qui contaminait
les endpoints V2.

**Fix :** les deux endpoints de changement d'objectif appellent désormais
`db.user_goals.delete_many({"user_id": ...})` **après** avoir mis à jour
`training_cycles.goal`. Tout changement d'objectif invalide les métadonnées
de course précédentes.

Endpoints modifiés :
- `POST /training/set-goal`
- `POST /training-plan/set-goal`

---

### 3. MAINTENANCE sans race_date ni target_time

La suppression de `user_goals` à chaque changement garantit que
`MAINTENANCE` n'hérite jamais d'un `race_date` ou `target_time_minutes`
d'un objectif précédent.

Les endpoints V2 protègent déjà MAINTENANCE via :
```python
race_date=race_date_v2 if mapped_goal_type != GoalType.maintenance else None
```
La combinaison des deux couches est désormais hermétique.

---

### 4. ULTRA — distance obligatoire > 42,195 km

#### `POST /training/set-goal` (PR226)

Nouveau paramètre `distance_km: Optional[float] = Query(None)`.

- Sans `distance_km` → HTTP 400
- `distance_km <= 42.195` → HTTP 400
- `distance_km > 42.195` → stocké dans `training_cycles.ultra_distance_km`

Changement d'objectif non-ULTRA → `ultra_distance_km` remis à `None`.

#### `POST /user/goal` (PR226)

`UserGoalCreate` accepte un champ optionnel `distance_km: Optional[float]`.

Pour `distance_type == "ultra"` :
- Sans `distance_km` ou `distance_km <= 42.195` → HTTP 400
- `distance_km > 42.195` → utilisé tel quel (plus de hardcode `50.0`)

---

### 5. Fallback V2 : `training_cycles.ultra_distance_km`

Les deux endpoints V2 lisent désormais `ultra_distance_km` en fallback
quand `user_goals.distance_km` est absent :

```python
raw_dist = user_goal.get("distance_km") if user_goal else None
if not (isinstance(raw_dist, (int, float)) and not isinstance(raw_dist, bool) and raw_dist > ULTRA_MIN_DISTANCE_KM):
    raw_dist = cycle.get("ultra_distance_km") if cycle else None
```

Cela permet à l'onboarding de passer `distance_km` directement à `set-goal`
sans nécessiter un appel séparé à `user/goal`.

Endpoints concernés :
- `GET /training/week-plan` (V2)
- `GET /training/v2/cycle`

---

### 6. Onboarding Ultra — demande de distance

`Onboarding.jsx` affiche un champ de saisie de distance (km) dès que
l'utilisateur sélectionne `ULTRA`. Le bouton "Continuer" reste désactivé
tant que la valeur n'est pas > 42,195.

À la création du plan, la distance est passée via :
```
POST /training/set-goal?goal=ULTRA&distance_km=<valeur>
```

---

### 7. Settings — champ distance pour ULTRA

`Settings.jsx` affiche un champ `ultraDistanceKm` dans le formulaire de
paramètres de course quand `selectedGoalOption.value === "ULTRA"`.

La validation côté frontend bloque la sauvegarde si `distance_km <= 42.195`.
Le payload envoyé à `POST /user/goal` inclut `distance_km`.

---

## Audit consommateurs

| Consommateur | Lecture race_date | Protection MAINTENANCE | ULTRA distance |
|---|---|---|---|
| `GET /training/week-plan` | `user_goals.event_date` | oui (V2 builder) | fallback cycle ✓ |
| `GET /training/v2/cycle` | `user_goals.event_date` | oui (V2 builder) | fallback cycle ✓ |
| Coach / LLM | `training_plans.goal` (snapshot) | `MAINTENANCE` fallback ✓ | N/A |
| Dashboard | lit `/training/v2/cycle` | hérité | hérité |
| Settings | lit `/user/goal` + `/training/v2/cycle` | `hasRaceSettings: false` | champ distance ✓ |
| Onboarding | `set-goal` seulement | pas de user_goals | distance_km passé ✓ |

---

## Tests — `backend/tests/test_goal_truth_pr226.py`

| 1 | `test_goal_config_has_all_goals` | GOAL_CONFIG has 5K/10K/SEMI/MARATHON/ULTRA/MAINTENANCE | ✅ PASSED |
| 2 | `test_standard_goal_cycle_weeks[5K]` | cycle_weeks > 0 for 5K | ✅ PASSED |
| 3 | `test_standard_goal_cycle_weeks[10K]` | cycle_weeks > 0 for 10K | ✅ PASSED |
| 4 | `test_standard_goal_cycle_weeks[SEMI]` | cycle_weeks > 0 for SEMI | ✅ PASSED |
| 5 | `test_standard_goal_cycle_weeks[MARATHON]` | cycle_weeks > 0 for MARATHON | ✅ PASSED |
| 6 | `test_maintenance_has_no_race_date_in_plan_goal` | build_plan_goal(MAINTENANCE) → race_date=None | ✅ PASSED |
| 7 | `test_maintenance_has_no_target_time_in_plan_goal` | build_plan_goal(MAINTENANCE) → target_time=None | ✅ PASSED |
| 8 | `test_maintenance_has_no_target_distance_in_plan_goal` | build_plan_goal(MAINTENANCE) → distance=None | ✅ PASSED |
| 9 | `test_maintenance_rejects_race_date` | PlanGoal MAINTENANCE + race_date → ValueError | ✅ PASSED |
| 10 | `test_maintenance_rejects_target_time` | PlanGoal MAINTENANCE + target_time → ValueError | ✅ PASSED |
| 11 | `test_fallback_without_goal_is_maintenance_not_semi` | `plan_data.get("goal", "SEMI")` absent; `"MAINTENANCE"` present | ✅ PASSED |
| 12 | `test_set_goal_deletes_user_goals_in_source` | set_training_goal calls user_goals.delete_many | ✅ PASSED |
| 13 | `test_set_training_plan_goal_deletes_user_goals_in_source` | set_training_plan_goal calls user_goals.delete_many | ✅ PASSED |
| 14 | `test_ultra_without_distance_refused` | build_plan_goal(ultra) no distance → raises | ✅ PASSED |
| 15 | `test_ultra_exactly_marathon_refused` | distance=42.195 → raises | ✅ PASSED |
| 16 | `test_ultra_below_marathon_refused` | distance=40.0 → raises | ✅ PASSED |
| 17 | `test_ultra_with_valid_distance_accepted` | distance=50.0 → accepted, target_distance_km=50.0 | ✅ PASSED |
| 18 | `test_ultra_distance_propagated_exactly` | distance=170.0 → stored 170.0 (not 50.0) | ✅ PASSED |
| 19 | `test_set_goal_endpoint_validates_ultra_distance` | set_training_goal body checks ULTRA + 42.195 | ✅ PASSED |
| 20 | `test_set_goal_stores_ultra_distance_in_cycles` | training_cycles.ultra_distance_km present | ✅ PASSED |
| 21 | `test_user_goal_create_model_has_distance_km` | UserGoalCreate.distance_km field present | ✅ PASSED |
| 22 | `test_user_goal_endpoint_validates_ultra_distance` | set_user_goal body checks ultra + 42.195 | ✅ PASSED |
| 23 | `test_v2_endpoints_have_ultra_distance_fallback` | ultra_distance_km appears ≥3× in server.py | ✅ PASSED |

**Total: 23/23 PASSED**

---

## Runtime

DEFERRED TO FINAL RUNTIME GATE.

---

## C226

PR #226 — base: `copilot/dev`. NE PAS merger.
