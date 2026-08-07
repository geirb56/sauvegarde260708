# PLAN_GOAL_PR05_REPORT

## Déclaration fondamentale

**"PlanGoal décrit l'intention utilisateur. Il ne décide pas de la faisabilité sportive ni de la stratégie d'entraînement."**

---

## Responsabilité exacte de PlanGoal

PlanGoal est la couche métier pure qui représente ce que l'utilisateur veut préparer, sans décider comment l'entraînement doit être construit.

PlanGoal décrit. Il ne prescrit pas.

PlanGoal ne calcule **pas** :
- volume hebdomadaire cible
- progression
- périodisation
- nombre de séances
- sortie longue
- intensité
- séance
- faisabilité de l'objectif

Ces responsabilités appartiennent aux PR06+.

---

## Objectifs supportés

| Identifiant métier | Libellé produit    |
|--------------------|--------------------|
| `maintenance`      | Maintien en forme  |
| `5k`               | 5 km               |
| `10k`              | 10 km              |
| `half_marathon`    | Semi-marathon      |
| `marathon`         | Marathon           |
| `ultra`            | Ultra              |

Les libellés UI traduits ne figurent pas dans le modèle métier.

---

## Maintenance

`maintenance` est un objectif de premier rang. Ce n'est ni une absence d'objectif, ni un fallback technique, ni une préparation de course fictive.

Pour `maintenance` :
```
race_date             = None
target_time_seconds   = None
target_distance_km    = None
```

Aucune course ou performance n'est inventée. Toute tentative de fournir `race_date`, `target_time_seconds`, ou `target_distance_km` à un objectif `maintenance` produit une `ValidationError`.

---

## Distances canoniques

Centralisées dans `plan_goal.py` — jamais dispersées :

| Objectif       | Distance canonique |
|----------------|--------------------|
| `5k`           | 5.0 km             |
| `10k`          | 10.0 km            |
| `half_marathon`| 21.0975 km         |
| `marathon`     | 42.195 km          |

Pour ces quatre objectifs, `target_distance_km` est **entièrement dérivé du `goal_type`** — l'appelant ne doit pas fournir `target_distance_km`. Toute tentative de le fournir (même avec la valeur correcte) produit une `ValueError`.

```python
# Correct
build_plan_goal(goal_type="10k")  # → target_distance_km = 10.0

# Refusé — même si la valeur est correcte
build_plan_goal(goal_type="10k", target_distance_km=10.0)  # ValueError
```

## Contrat final par objectif

| Objectif       | `target_distance_km`                        |
|----------------|---------------------------------------------|
| `maintenance`  | Interdit — toujours `None`                  |
| `5k`           | Dérivé automatiquement : `5.0`              |
| `10k`          | Dérivé automatiquement : `10.0`             |
| `half_marathon`| Dérivé automatiquement : `21.0975`          |
| `marathon`     | Dérivé automatiquement : `42.195`           |
| `ultra`        | Fourni obligatoirement par l'appelant (> 42.195) |

---

## Ultra

`ultra` est un type d'objectif explicite.

- La distance doit être fournie (`target_distance_km > 42.195`).
- Un Ultra de 50 km et un Ultra de 100 km sont distinguables.
- Aucune distance par défaut n'est inventée.
- Ultra sans distance → `ValidationError`.
- Ultra ≤ 42.195 km → `ValidationError`.
- `race_date` et `target_time_seconds` restent optionnels.
- Le dénivelé / D+ est hors périmètre de PR05.

---

## Date de course optionnelle

Pour `5k`, `10k`, `half_marathon`, `marathon`, `ultra` : `race_date` est optionnelle.

Combinaisons toutes valides :
- objectif seul
- objectif + chrono
- objectif + date de course
- objectif + chrono + date de course

---

## Chrono optionnel

`target_time_seconds: Optional[int]` — stocké en secondes (unité canonique déterministe).

Exemples :
- 10 km en 45 min → 2700
- semi en 1h50 → 6600
- marathon en 4h → 14400

Un chrono peut exister même si `race_date = None`.

### PlanGoal ne juge pas le chrono

PlanGoal accepte structurellement tout chrono strictement positif, y compris un objectif extrêmement ambitieux (marathon en 2h30 → 9000 s). La faisabilité sportive sera évaluée dans une couche ultérieure.

---

## Provenance

| Valeur      | Signification                                                   |
|-------------|-----------------------------------------------------------------|
| `"user"`    | Objectif explicitement choisi par l'utilisateur                 |
| `"default"` | Aucune information utilisateur ; RunIndex a construit un objectif par défaut |

L'objectif par défaut est `maintenance` avec `created_from = "default"`. Cela ne signifie pas que `maintenance` est un fallback métier — uniquement que la provenance de ce choix particulier est `"default"`.

---

## Validations structurelles

| Règle                                        | Comportement                                 |
|----------------------------------------------|----------------------------------------------|
| `maintenance` + chrono                       | `ValidationError`                            |
| `maintenance` + `race_date`                  | `ValidationError`                            |
| `maintenance` + `target_distance_km`         | `ValidationError`                            |
| Standard + `target_distance_km` fourni       | `ValueError` (même valeur correcte)          |
| `ultra` sans distance                        | `ValidationError`                            |
| `ultra` avec distance ≤ 42.195               | `ValidationError`                            |
| `target_time_seconds = 0`                    | `ValidationError`                            |
| `target_time_seconds < 0`                    | `ValidationError`                            |
| `created_from` hors `{"user", "default"}`   | `ValidationError`                            |

---

## Ce que PlanGoal refuse volontairement de décider

- Si un chrono est réaliste, trop ambitieux ou trop facile
- Si le chrono est compatible avec la VMA, le VO2max ou l'historique
- Si l'objectif est compatible avec `RunnerProfile`
- Le volume hebdomadaire cible
- La progression ou la périodisation
- Le nombre de séances ou la sortie longue
- La faisabilité de l'objectif

---

## Indépendance

PlanGoal ne dépend pas de :
- `TrainingState`
- `TrainingLoad`
- `TrainingHistory`
- `RunnerProfile`
- `training_engine`
- `training_load_engine`
- `llm_coach`
- `coach_service`
- `datetime.now()`
- MongoDB / Redis / API / LLM / Garmin

---

## Fichiers modifiés

| Fichier                                      | Action   |
|----------------------------------------------|----------|
| `backend/training_v2/plan_goal.py`           | Créé     |
| `backend/training_v2/__init__.py`            | Mis à jour (ajout de `GoalType`, `PlanGoal`, `build_plan_goal`) |
| `backend/tests/test_plan_goal_pr05.py`       | Créé     |
| `PLAN_GOAL_PR05_REPORT.md`                   | Créé     |

Aucun fichier legacy modifié. Aucun fichier frontend modifié.

---

## Tests exécutés

### PR05 — PlanGoal (34 tests)

```
tests/test_plan_goal_pr05.py::test_01_maintenance_valid_no_extras          PASSED
tests/test_plan_goal_pr05.py::test_02_maintenance_refuses_chrono           PASSED
tests/test_plan_goal_pr05.py::test_03_maintenance_refuses_race_date        PASSED
tests/test_plan_goal_pr05.py::test_04_maintenance_refuses_target_distance  PASSED
tests/test_plan_goal_pr05.py::test_05_5k_canonical_distance                PASSED
tests/test_plan_goal_pr05.py::test_06_10k_canonical_distance               PASSED
tests/test_plan_goal_pr05.py::test_07_half_marathon_canonical_distance     PASSED
tests/test_plan_goal_pr05.py::test_08_marathon_canonical_distance          PASSED
tests/test_plan_goal_pr05.py::test_08b_standard_rejects_caller_distance_5k     PASSED
tests/test_plan_goal_pr05.py::test_08b_standard_rejects_caller_distance_10k    PASSED
tests/test_plan_goal_pr05.py::test_08b_standard_rejects_caller_distance_half   PASSED
tests/test_plan_goal_pr05.py::test_08b_standard_rejects_caller_distance_marathon PASSED
tests/test_plan_goal_pr05.py::test_08b_standard_rejects_wrong_distance_10k    PASSED
tests/test_plan_goal_pr05.py::test_09_chrono_without_race_date             PASSED
tests/test_plan_goal_pr05.py::test_10_date_without_chrono                  PASSED
tests/test_plan_goal_pr05.py::test_11_date_and_chrono                      PASSED
tests/test_plan_goal_pr05.py::test_12_neither_date_nor_chrono              PASSED
tests/test_plan_goal_pr05.py::test_13_ultra_50km                           PASSED
tests/test_plan_goal_pr05.py::test_14_ultra_100km                          PASSED
tests/test_plan_goal_pr05.py::test_15_ultra_exactly_marathon_refused       PASSED
tests/test_plan_goal_pr05.py::test_16_ultra_below_marathon_refused         PASSED
tests/test_plan_goal_pr05.py::test_17_ultra_no_distance_refused            PASSED
tests/test_plan_goal_pr05.py::test_18_ultra_without_chrono                 PASSED
tests/test_plan_goal_pr05.py::test_19_ultra_without_date                   PASSED
tests/test_plan_goal_pr05.py::test_20_zero_chrono_refused                  PASSED
tests/test_plan_goal_pr05.py::test_21_negative_chrono_refused              PASSED
tests/test_plan_goal_pr05.py::test_22_ambitious_chrono_accepted            PASSED
tests/test_plan_goal_pr05.py::test_23_provenance_user                      PASSED
tests/test_plan_goal_pr05.py::test_24_default_maintenance                  PASSED
tests/test_plan_goal_pr05.py::test_25_model_immutable                      PASSED
tests/test_plan_goal_pr05.py::test_26_deterministic                        PASSED
tests/test_plan_goal_pr05.py::test_27_no_legacy_imports                    PASSED
tests/test_plan_goal_pr05.py::test_nr_py_compile_plan_goal                 PASSED
tests/test_plan_goal_pr05.py::test_nr_exports                              PASSED

34 passed in 0.46s
```

### Non-régression (197 tests)

```
tests/test_training_state_pr04.py       — PASSED (toutes)
tests/test_runner_profile_pr07.py       — PASSED (toutes)
tests/test_training_history_pr05.py     — PASSED (toutes)
tests/test_training_v2_training_load.py — PASSED (toutes)
tests/test_garmin_data_layer.py         — PASSED (toutes)

197 passed in 0.79s
```

Total session : 231 passed (34 PR05 + 197 non-régression) ✅

Aucun comportement existant modifié.
