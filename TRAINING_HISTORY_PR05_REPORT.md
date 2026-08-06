# TRAINING_HISTORY_PR05_REPORT.md

## Rôle exact de TrainingHistory

`TrainingHistory` est une couche métier pure qui transforme une liste
d'activités Garmin normalisées en historique d'entraînement exploitable
sur trois fenêtres glissantes : **7 jours**, **30 jours**, **90 jours**.

Elle répond de manière déterministe aux questions suivantes :
- Combien de kilomètres ont été courus sur 7 / 30 / 90 jours ?
- Combien de séances ?
- Quelle durée totale ?
- Quelle vitesse moyenne (pondérée par la durée) ?
- Quelle sortie la plus longue ?
- Depuis combien de jours le coureur n'a-t-il pas couru ?
- Dispose-t-on de suffisamment d'historique ?

Cette couche deviendra l'entrée de `RunnerProfile`, `TrainingState`,
`PlanGoal` et `WorkoutGenerator` dans les PR suivantes.

---

## Formats d'entrée acceptés

La fonction principale est :

```python
build_training_history(activities, reference_date)
```

ou via la méthode de classe :

```python
TrainingHistory.from_activities(activities, reference_date=date(...))
```

Chaque activité peut être :

1. **Un dict avec sous-document `garmin_activity`** (convention PR02) :
   - Champs utilisés depuis `garmin_activity` : `activity_type`, `start_time`,
     `distance_m` (mètres), `duration_s` (secondes).

2. **Un dict avec champs plats** (compatibilité historique) :
   - `activity_type`, `start_time`, `distance` (mètres), `duration` (secondes).

3. **Un objet Pydantic** exposant les attributs `activity_type`, `start_time`,
   `distance_m` / `distance`, `duration_s` / `duration`.

**Priorité** : le sous-document `garmin_activity` est toujours consulté en
premier. Les champs plats ne sont utilisés qu'en son absence.

---

## Activités retenues et exclues

### Retenues

| `activity_type`     |
|---------------------|
| `running`           |
| `trail_running`     |
| `treadmill_running` |

### Exclues (liste non exhaustive)

`cycling`, `walking`, `swimming`, `strength_training`, et tout autre type
non listé ci-dessus. Un `activity_type` absent (`None` ou manquant) est
également exclu — aucun type n'est fabriqué.

---

## Convention des fenêtres 7 / 30 / 90

Les fenêtres sont **glissantes** et **inclusives des deux côtés**.

Une fenêtre de N jours se termine à `reference_date` :

```
window_start = reference_date - timedelta(days=N-1)
window_end   = reference_date
```

Exemples avec `reference_date = 2026-08-06` :

| Fenêtre | Début       | Fin         |
|---------|-------------|-------------|
| 7 jours | 2026-07-31  | 2026-08-06  |
| 30 jours| 2026-07-08  | 2026-08-06  |
| 90 jours| 2026-05-09  | 2026-08-06  |

Les activités strictement postérieures à `reference_date` sont ignorées.

---

## Unités

| Grandeur        | Source Garmin    | Conversion             | Champ de sortie           |
|-----------------|------------------|------------------------|---------------------------|
| Distance        | mètres           | `distance_km = m / 1000` | `distance_km`           |
| Durée           | secondes         | `duration_hours = s / 3600` | `duration_hours`     |
| Vitesse moyenne | calculée         | `distance_km / duration_hours` | `average_speed_kmh` |
| Plus longue sortie | mètres via km | même conversion        | `longest_run_km`          |

Arrondi appliqué **uniquement** dans les champs finaux, à **2 décimales**.
Aucun arrondi intermédiaire sur chaque activité avant la somme.

Valeurs invalides exclues du calcul :
- distance : `None`, `0`, négative, non numérique
- durée : `None`, `0`, négative, non numérique

---

## Calcul de la vitesse moyenne

La vitesse est **pondérée par la durée**, calculée à partir des totaux :

```
average_speed_kmh = total_distance_km / total_duration_hours
```

Si la durée totale est nulle ou absente : `average_speed_kmh = None`.

La moyenne simple des vitesses individuelles de chaque séance est **interdite**.

### Exemple de vérification

| Séance | Distance | Durée   | Vitesse individuelle |
|--------|----------|---------|----------------------|
| A      | 10 km    | 1 h     | 10 km/h              |
| B      | 5 km     | 0,25 h  | 20 km/h              |

- Moyenne simple incorrecte : (10 + 20) / 2 = **15 km/h**
- Calcul pondéré correct : 15 km / 1,25 h = **12 km/h** ✓

---

## Comportement sans historique

Lorsqu'aucune activité de course valide n'est présente :

```
window_7d.distance_km  = 0.0
window_30d.distance_km = 0.0
window_90d.distance_km = 0.0

activity_count         = 0
duration_hours         = 0.0
average_speed_kmh      = None
longest_run_km         = None

has_any_running_history = False
has_7d_history          = False
has_30d_history         = False
has_90d_history         = False

days_since_last_run    = None
last_run_date          = None
available_history_days = 0
```

Aucun fallback, aucun volume fictif, aucun profil moyen injecté.
La décision « mode reprise » est déléguée à `TrainingState` (PR future).

---

## Indicateurs de disponibilité

| Indicateur              | Sémantique                                              |
|-------------------------|---------------------------------------------------------|
| `has_any_running_history` | Au moins une activité de course valide               |
| `has_7d_history`        | `available_history_days >= 7` ET au moins une course   |
| `has_30d_history`       | `available_history_days >= 30` ET au moins une course  |
| `has_90d_history`       | `available_history_days >= 90` ET au moins une course  |

`available_history_days` = nombre de jours entre la **première** activité de
course valide et `reference_date`. Il mesure la **profondeur** de l'historique,
non le nombre de jours actifs.

---

## Fichiers ajoutés

| Fichier                                              | Rôle                              |
|------------------------------------------------------|-----------------------------------|
| `backend/training_v2/__init__.py`                    | Point d'entrée du module          |
| `backend/training_v2/training_history.py`            | Logique métier pure (PR05)        |
| `backend/tests/test_training_history_pr05.py`        | Suite de tests (41 cas)           |
| `TRAINING_HISTORY_PR05_REPORT.md`                    | Ce rapport                        |

Aucun fichier existant n'a été modifié.

---

## Tests exécutés

```
cd backend
python -m pytest tests/test_training_history_pr05.py -q
```

### Résultats

```
41 passed in 0.48s
```

### Couverture des cas de test

| # | Cas                                  | Résultat |
|---|--------------------------------------|----------|
| 1 | Historique vide                      | ✅ PASS  |
| 2 | Filtrage des types d'activité        | ✅ PASS  |
| 3 | Fenêtres J-2 / J-10 / J-45 / J-100  | ✅ PASS  |
| 4 | Limites inclusives (J-6/7/29/30/89/90) | ✅ PASS |
| 5 | Activité future ignorée              | ✅ PASS  |
| 6 | Distances et durées invalides        | ✅ PASS  |
| 7 | Vitesse moyenne pondérée             | ✅ PASS  |
| 8 | Sortie la plus longue                | ✅ PASS  |
| 9 | Dernière course et jours écoulés     | ✅ PASS  |
| 10 | Profondeur d'historique             | ✅ PASS  |
| 11 | Compatibilité formats (flat / sub-doc) | ✅ PASS |
| 12 | Arrondi des distances et vitesses    | ✅ PASS  |

### Non-régression

```
python -m pytest tests/test_garmin_data_layer.py -q                   → 77 passed
python -m pytest tests/test_garmin_activity_normalization_pr02.py -q  → inclus ci-dessus
python -m pytest tests/test_garmin_daily_metrics_pr03.py -q           → inclus ci-dessus
python -m pytest tests/test_garmin_deep_sync.py -q                    → inclus ci-dessus
```

Note : `test_garmin_capabilities_pr04.py` échoue avec
`ModuleNotFoundError: No module named 'redis'` — erreur **pré-existante**
d'environnement (absence du package Redis dans l'environnement de test CI),
sans rapport avec PR05.

---

## Risques résiduels

| Risque                                       | Niveau | Mitigation                                        |
|----------------------------------------------|--------|---------------------------------------------------|
| Activités dont `start_time` est mal formaté  | Faible | `_parse_date` retourne `None` sans lever d'exception |
| Distances en km plutôt qu'en mètres dans les anciens champs plats | Moyen | Documenté — la source doit toujours être en mètres |
| Fuseau horaire (UTC vs local)                | Faible | Seule la date (YYYY-MM-DD) est utilisée, non l'heure |
| Fenêtres et fuseaux horaires extrêmes        | Faible | `reference_date` est fourni explicitement par l'appelant |

---

## Confirmation d'intégrité

✅ `training_engine.py` — **non modifié**
✅ `llm_coach.py` — **non modifié**
✅ `compute_current_weekly_km` / `compute_target_km` — **non modifiés**
✅ Resume guard — **non modifié**
✅ RunIndex Score / Readiness — **non modifiés**
✅ Synchronisation Garmin / Data Layer — **non modifiés**
✅ Frontend — **non modifié**
✅ Endpoints API publics — **non modifiés**
✅ MongoDB — **non modifié**
✅ Workers / Queue / Redis — **non modifiés**

PR05 est **purement additive**. Aucune fonctionnalité existante n'a été
touchée, supprimée ou branchée sur le nouveau module.
