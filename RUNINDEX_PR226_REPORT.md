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

| # | Test | Scénario | Résultat attendu |
|---|---|---|---|
| 1 | `test_standard_goals_set_correctly[5K]` | POST set-goal?goal=5K | goal=5K dans training_cycles |
| 2 | `test_standard_goals_set_correctly[10K]` | POST set-goal?goal=10K | goal=10K dans training_cycles |
| 3 | `test_standard_goals_set_correctly[SEMI]` | POST set-goal?goal=SEMI | goal=SEMI dans training_cycles |
| 4 | `test_standard_goals_set_correctly[MARATHON]` | POST set-goal?goal=MARATHON | goal=MARATHON dans training_cycles |
| 5 | `test_maintenance_clears_race_date_and_target_time` | user_goals pré-existant → set-goal MAINTENANCE | user_goals supprimé |
| 6 | `test_no_stale_race_date_after_goal_change` | user_goals MARATHON → set-goal 5K | user_goals supprimé |
| 7 | `test_fallback_without_goal_is_maintenance` | inspection du code source | `plan_data.get("goal", "MAINTENANCE")` présent |
| 8 | `test_ultra_without_distance_rejected_set_goal` | POST set-goal?goal=ULTRA (sans distance_km) | HTTP 400 |
| 9 | `test_ultra_with_invalid_distance_rejected` | distance_km=42.195 et 40.0 | HTTP 400 |
| 10 | `test_ultra_with_valid_distance_propagated` | POST set-goal?goal=ULTRA&distance_km=50 | cycle.ultra_distance_km=50.0 |
| 11 | `test_ultra_user_goal_without_distance_rejected` | POST /user/goal ultra sans distance_km | HTTP 400 |
| 12 | `test_ultra_user_goal_with_valid_distance_accepted` | POST /user/goal ultra distance_km=100 | user_goals.distance_km=100.0 |
| 13 | `test_ultra_distance_preserved_not_overwritten_by_default` | distance_km=170 | stocké 170.0 (pas 50.0) |
| 14 | `test_maintenance_has_no_race_date_in_plan_goal` | build_plan_goal(MAINTENANCE) | race_date=None, distance=None |

---

## Runtime

DEFERRED TO FINAL RUNTIME GATE.

---

## C226

PR #226 — base: `copilot/dev`. NE PAS merger.
