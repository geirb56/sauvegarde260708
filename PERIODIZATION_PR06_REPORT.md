# PERIODIZATION_PR06_REPORT

## Principe fondamental

> **Periodization décrit le calendrier d'entraînement. Elle ne décide pas encore de la charge ni des séances.**

Periodization positionne le coureur dans son cycle d'entraînement à partir de `PlanGoal`, `TrainingState` (optionnel) et `reference_date`. Elle ne décide pas du volume, des séances, de l'allure ni des autorisations d'intensité. Ces responsabilités appartiennent aux couches PR07+.

---

## Responsabilité de Periodization

| Ce que Periodization fait | Ce que Periodization ne fait PAS |
|---|---|
| Détermine la phase calendrier | Décide du volume hebdomadaire |
| Identifie le mode (race_calendar / continuous) | Prescrit des séances |
| Calcule les dates de début/fin de phase | Calcule les allures |
| Fournit la semaine courante dans la phase | Autorise ou interdit l'intensité |
| Émet des reason codes stables | Recalcule TrainingState |
| Détecte course passée / course imminente | Modifie PlanGoal |

---

## Modes

### `race_calendar`

Activé quand `PlanGoal.race_date is not None` et `goal_type in {5k, 10k, half_marathon, marathon, ultra}`.

Le planning est calculé à partir de `race_plan_start_date` vers `race_date`.

**Pour une course future datée (`race_date > reference_date`), `race_plan_start_date` est OBLIGATOIRE.**
Le moteur ne remplace jamais silencieusement une date de début absente par `reference_date`.

### `continuous`

Activé pour :
- `maintenance`
- Tout objectif de distance (`5k`, `10k`, etc.) sans `race_date`

Cycle répété : `base → build → consolidation → base → ...`

Nécessite `cycle_anchor_date` injecté par l'appelant.

---

## Phases

### Mode `race_calendar`

| Phase | Description |
|---|---|
| `base` | Fondamentaux aérobies |
| `build` | Développement de la charge |
| `specific` | Entraînements spécifiques à la distance |
| `taper` | Récupération avant course |
| `race` | Jour de course (reference_date == race_date) |

### Mode `continuous`

| Phase | Description |
|---|---|
| `base` | Fondamentaux aérobies (4 semaines) |
| `build` | Développement (5 semaines) |
| `consolidation` | Intégration et récupération (3 semaines) |

---

## Taper par objectif (durées fixes)

| Objectif | Durée taper |
|---|---|
| 5k | 1 semaine (7 jours) |
| 10k | 1 semaine (7 jours) |
| half_marathon | 2 semaines (14 jours) |
| marathon | 2 semaines (14 jours) |
| ultra | 2 semaines (14 jours) |

Centralisé dans `TAPER_WEEKS` dans `periodization.py`.

**Important :** Ces durées positionnent le coureur dans le calendrier. Elles ne déclenchent pas elles-mêmes une réduction de volume ; cela appartient aux couches suivantes.

---

## Proportions base/build/specific

Appliquées aux jours disponibles AVANT le taper :

| Phase | Proportion |
|---|---|
| base | 30 % |
| build | 40 % |
| specific | 30 % (absorbe le reste pour garantir zéro jour perdu) |

Centralisé dans `PRE_TAPER_PROPORTIONS`.

Méthode de calcul :
```
pre_taper_days = total_days - taper_days
base_days      = floor(pre_taper_days × 0.30)
build_days     = floor(pre_taper_days × 0.40)
specific_days  = pre_taper_days − base_days − build_days  ← reste exact
```

Cette méthode garantit que `base + build + specific + taper == total` exactement.

---

## Validation de race_plan_start_date (course future datée)

Règle finale : `race_plan_start_date <= reference_date < race_date`

| Cas | Résultat |
|---|---|
| `race_plan_start_date is None` (course future) | `ValueError` |
| `race_plan_start_date > reference_date` | `ValueError` — le plan ne peut pas être considéré comme commencé avant sa date de début |
| `race_plan_start_date > race_date` | `ValueError` |
| `race_plan_start_date == reference_date` | Valide |
| `race_plan_start_date < reference_date` | Valide — le coureur est déjà dans son cycle |
| `reference_date == race_date` (jour de course) | `race_plan_start_date` non requis |
| `reference_date > race_date` (course passée) | `race_plan_start_date` non requis |

---

## Préparations courtes

Une durée courte entre le début du plan et la course n'est **pas** une erreur.

Exemples valides :
- début du plan = 1 septembre, course = 15 octobre
- début du plan = 10 octobre, course = 15 octobre

Periodization compresse les phases disponibles ; aucune durée minimale n'est imposée.
`SHORT_PREPARATION` est émis quand pertinent.

---



Si le temps disponible ne permet pas toutes les phases, les phases les plus éloignées de la course sont supprimées en premier :

```
Priorité (la plus haute = conservée en dernier) :
race > taper > specific > build > base
```

Exemples :
- 5 jours avant un 5k (taper=7j) → uniquement taper (pre_taper=0, pas de base/build/specific)
- 10 jours avant un 5k → base=0, build=1j, specific=2j, taper=7j (base supprimée)

Principe : on ne fabrique pas rétroactivement des semaines inexistantes.

---

## Cycles continus

### Durées (centralisées dans les constantes)

| Phase | Durée | Constante |
|---|---|---|
| base | 4 semaines | `CONTINUOUS_BASE_WEEKS = 4` |
| build | 5 semaines | `CONTINUOUS_BUILD_WEEKS = 5` |
| consolidation | 3 semaines | `CONTINUOUS_CONSOLIDATION_WEEKS = 3` |
| **total cycle** | **12 semaines** | `CONTINUOUS_CYCLE_LENGTH_WEEKS = 12` |

Le cycle se répète à l'infini : `base → build → consolidation → base → ...`

### Déterminisme

Le cycle est calculé uniquement à partir de `cycle_anchor_date` (injecté par l'appelant). Aucune date interne n'est inventée.

```python
position_in_cycle = (reference_date - cycle_anchor_date).days % (12 × 7)
```

---

## Maintenance

`maintenance` utilise le même cycle continu que les autres objectifs sans date :
`base → build → consolidation`

Un coureur en maintenance ne reste pas bloqué en `base` indéfiniment : il progresse à travers le cycle complet.

`build_periodization` exige `cycle_anchor_date` pour garantir le déterminisme.

---

## Objectifs sans date de course

Exemples valides :
- `goal_type = half_marathon, race_date = None`
- `goal_type = half_marathon, target_time_seconds = 6600, race_date = None`
- `goal_type = ultra, target_distance_km = 80.0, race_date = None`

Tous → `mode = continuous`, aucune date de course fictive créée.

Le `target_time_seconds` reste dans `PlanGoal` pour les couches futures.

---

## Course passée

Si `reference_date > race_date` :

```
mode  = continuous
phase = consolidation
reason_codes contient RACE_DATE_PASSED
```

Le `PlanGoal` n'est pas modifié. Une future couche demandera à l'utilisateur de définir son prochain objectif.

---

## Interaction avec TrainingState

`TrainingState` peut être transmis à `build_periodization` mais **n'influence jamais la phase calendrier**.

Exemples valides et non-contradictoires :
```
phase = build, continuity_state = partial_reprise   ← OK
phase = specific, load_state = high                  ← OK
phase = build, continuity_state = deep_reprise       ← OK
```

C'est `WeeklyTarget` / `WorkoutGenerator` (PR07+) qui adapteront la prescription en fonction de `TrainingState`.

---

## Reason codes

| Code | Signification |
|---|---|
| `RACE_CALENDAR` | Mode race_calendar activé |
| `CONTINUOUS_CYCLE` | Mode continuous activé |
| `PHASE_BASE` | Phase base |
| `PHASE_BUILD` | Phase build |
| `PHASE_SPECIFIC` | Phase specific |
| `PHASE_TAPER` | Phase taper |
| `PHASE_RACE` | Jour de course |
| `PHASE_CONSOLIDATION` | Phase consolidation (continuous) |
| `RACE_DATE_PASSED` | Course dépassée, basculement en continuous |
| `SHORT_PREPARATION` | Préparation courte : `(race_date - race_plan_start_date).days < taper_days + 7`. **`SHORT_PREPARATION` caractérise la durée initiale du plan entre `race_plan_start_date` et `race_date`. Il ne dépend pas de la proximité actuelle de la course.** `reference_date` sert uniquement à déterminer la phase actuelle. |
| `NO_RACE_DATE` | Objectif sans date de course |
| `MAINTENANCE_GOAL` | Objectif maintenance |

---

## Constantes retenues

```python
# Taper
TAPER_WEEKS = {
    GoalType.five_k:        1,
    GoalType.ten_k:         1,
    GoalType.half_marathon: 2,
    GoalType.marathon:      2,
    GoalType.ultra:         2,
}

# Proportions pré-taper
PRE_TAPER_PROPORTIONS = {
    "base":     0.30,
    "build":    0.40,
    "specific": 0.30,
}

# Cycle continu
CONTINUOUS_CYCLE_LENGTH_WEEKS  = 12
CONTINUOUS_BASE_WEEKS          = 4
CONTINUOUS_BUILD_WEEKS         = 5
CONTINUOUS_CONSOLIDATION_WEEKS = 3
```

---

## Frontières (boundaries)

Toutes testées explicitement avec `==` :

| Test | Frontière testée |
|---|---|
| test_09 | Dernier jour base / Premier jour build |
| test_10 | Dernier jour build / Premier jour specific |
| test_11 | Dernier jour specific / Premier jour taper |
| test_12 | Dernier jour taper / Jour de course |
| test_23 | Dernière semaine base (continuous) |
| test_24 | Première semaine build (continuous) |
| test_25 | Dernière semaine build (continuous) |
| test_26 | Première semaine consolidation (continuous) |
| test_27 | Dernière semaine consolidation (continuous) |
| test_28 | Retour en base au cycle suivant |

---

## Fichiers modifiés

| Fichier | Rôle |
|---|---|
| `backend/training_v2/periodization.py` | Nouveau module — couche métier pure |
| `backend/training_v2/__init__.py` | Export des symboles publics PR06 |
| `backend/tests/test_periodization_pr06.py` | 51 tests PR06 (38 originaux + 8 nouveaux race_plan_start_date + 3 nouveaux SP1/SP2/SP3 SHORT_PREPARATION) |
| `PERIODIZATION_PR06_REPORT.md` | Ce rapport |

---

## Tests exécutés

### Tests PR06 spécifiques

```
backend/tests/test_periodization_pr06.py — 51 tests
```

**Résultat : 51 passed**

### Non-régression

```
tests/test_plan_goal_pr05.py          — PR05 PlanGoal
tests/test_training_state_pr04.py     — PR04 TrainingState
tests/test_runner_profile_pr07.py     — PR07 RunnerProfile
tests/test_training_history_pr05.py   — PR05 History
tests/test_training_v2_training_load.py — TrainingLoad
tests/test_garmin_data_layer.py       — Garmin Data Layer
```

**Résultat : 231 passed**

---

## Résultats exacts des tests PR06

```
test_01_5k_race_calendar_mode                PASSED
test_02_marathon_far_race_coherent_phase     PASSED
test_03_ultra_with_date_same_phases          PASSED
test_04_no_race_date_continuous              PASSED
test_05_maintenance_continuous               PASSED
test_06_chrono_without_date_continuous       PASSED
test_07_reference_equals_race_date           PASSED
test_08_race_date_passed                     PASSED
test_09_exact_base_build_boundary            PASSED
test_10_exact_build_specific_boundary        PASSED
test_11_exact_specific_taper_boundary        PASSED
test_12_exact_taper_race_boundary            PASSED
test_13_short_prep_no_base                   PASSED
test_14_very_short_prep                      PASSED
test_15_taper_5k_duration                    PASSED
test_16_taper_10k_duration                   PASSED
test_17_taper_half_marathon_duration         PASSED
test_18_taper_marathon_duration              PASSED
test_19_taper_ultra_duration                 PASSED
test_20_no_week_lost                         PASSED
test_21_no_week_counted_twice                PASSED
test_22_continuous_week1_is_base             PASSED
test_23_continuous_last_week_base            PASSED
test_24_continuous_first_week_build          PASSED
test_25_continuous_last_week_build           PASSED
test_26_continuous_first_week_consolidation  PASSED
test_27_continuous_last_week_consolidation   PASSED
test_28_continuous_cycle_wraps_back_to_base  PASSED
test_29_determinism                          PASSED
test_30_model_immutable                      PASSED
test_31_no_datetime_now_or_date_today        PASSED
test_32_no_legacy_imports                    PASSED
test_33_partial_reprise_no_phase_change      PASSED
test_34_deep_reprise_no_phase_change         PASSED
test_35_high_load_no_phase_change            PASSED
test_36_maintenance_not_eternal_base         PASSED
test_37_ultra_without_date_continuous        PASSED
test_38_target_time_no_phase_influence       PASSED
test_py_compile_periodization                PASSED
test_py_compile_init                         PASSED
test_n1_future_race_no_plan_start_raises     PASSED
test_n2_plan_start_equals_reference_date_accepted PASSED
test_n3_plan_start_before_reference_date_accepted PASSED
test_n4_plan_start_after_reference_date_raises    PASSED
test_n5_plan_start_after_race_date_raises         PASSED
test_n6_5_days_before_5k_is_taper                 PASSED
test_n7_10_days_before_5k_first_day_is_build      PASSED
test_n8_phase_boundaries_fixed_across_reference_dates PASSED
test_sp1_normal_plan_short_preparation_stable_absent  PASSED
test_sp2_short_plan_short_preparation_stable_present  PASSED
test_sp3_long_plan_near_race_no_short_preparation     PASSED

51 passed in 0.55s
```
