# RUNNER_PROFILE_PR07_REPORT

## Rôle exact de `RunnerProfile`

`RunnerProfile` est une couche métier pure et déterministe qui centralise les
caractéristiques durables ou semi-durables du coureur à partir de données
déclarées, de `TrainingHistory`, de `TrainingLoadSnapshot`, de
`GarminCapabilities` et de métriques physiologiques injectées explicitement.

Cette PR ne détermine aucun état de reprise, aucune fatigue, aucune surcharge,
aucune readiness et ne modifie aucune recommandation existante.

## Champs finaux

- `reference_date`
- `age`
- `sex`
- `primary_discipline`
- `experience_level`
- `typical_weekly_km`
- `typical_weekly_hours`
- `typical_runs_per_week`
- `typical_long_run_km`
- `typical_speed_kmh`
- `available_history_days`
- `profile_confidence`
- `vo2max`
- `vma_kmh`
- `max_hr`
- `resting_hr`
- `has_hrv`
- `has_vo2max`
- `has_training_readiness`
- `has_power`
- `has_running_dynamics`
- `preferred_days_per_week`
- `max_days_per_week`
- `preferred_long_run_day`
- `injury_constraints`
- `availability_constraints`

## Sources de données

- `user_profile`
  - âge
  - sexe
  - discipline
  - jours souhaités / maximum
  - jour préféré de sortie longue
  - contraintes de disponibilité
  - contraintes de blessure
  - FC max déclarée
  - éventuels volumes explicitement déclarés en secours
- `TrainingHistory`
  - `window_30d`
  - `window_90d` en secours uniquement
  - `available_history_days`
- `TrainingLoadSnapshot`
  - injecté explicitement pour garder l’interface pure et stable
  - non utilisé pour calculer un état dans cette PR
- `GarminCapabilities`
  - booléens de capacités observées
- `physiological_metrics`
  - `vo2max`
  - `vma_kmh`
  - `max_hr`
  - `resting_hr`

## Ordre de priorité des sources

- données personnelles et contraintes :
  - valeur déclarée valide
  - sinon absence / liste vide
- métriques d’entraînement :
  - valeur observée `TrainingHistory.window_30d`
  - sinon valeur observée `TrainingHistory.window_90d`
  - sinon valeur explicitement déclarée
  - sinon `None`
- physiologie :
  - valeur observée valide dans `physiological_metrics`
  - sinon valeur déclarée valide
  - sinon `None`

## Calcul des métriques habituelles

- `typical_weekly_km = window.distance_km * 7 / 30`
- `typical_weekly_hours = window.duration_hours * 7 / 30`
- `typical_runs_per_week = window.activity_count * 7 / 30`
- `typical_long_run_km = window.longest_run_km`
- `typical_speed_kmh = window.average_speed_kmh`

Règles appliquées :

- priorité à la fenêtre 30 jours
- fenêtre 90 jours uniquement en secours si la 30 jours ne fournit pas de
  donnée exploitable
- aucun fallback arbitraire
- aucun arrondi intermédiaire
- arrondi uniquement sur la sortie finale

## Définition de l’expérience

`experience_level` décrit uniquement la profondeur d’historique observable,
pas le niveau sportif réel :

- `unknown` : 0 jour exploitable
- `beginner` : 1 à 29 jours
- `developing` : 30 à 89 jours
- `established` : 90 à 364 jours
- `experienced` : 365 jours ou plus

## Définition de la confiance

- `none` : aucune donnée déclarée ni observée exploitable
- `low` : historique inférieur à 30 jours
- `medium` : historique de 30 à 89 jours
- `high` : historique d’au moins 90 jours

Cas explicite couvert :

- 0 jour + données déclarées valides => `low`
- 0 jour + aucune donnée déclarée exploitable => `none`

Les données déclarées seules ne produisent jamais `medium` ou `high`.

## Comportement sans historique

Sans historique exploitable :

- `experience_level = "unknown"`
- `typical_weekly_km = None`
- `typical_weekly_hours = None`
- `typical_runs_per_week = None`
- `typical_long_run_km = None`
- `typical_speed_kmh = None`
- `available_history_days = 0`
- `profile_confidence = "none"`

Sauf si une valeur correspondante est explicitement déclarée dans
`user_profile`.

## Comportement avec profil déclaré mais sans historique

Sans historique mais avec données déclarées exploitables :

- les champs déclarés valides sont conservés
- `experience_level = "unknown"`
- `profile_confidence = "low"`
- aucun volume par défaut n’est injecté

## Comportement sans physiologie

Si la physiologie est absente ou invalide :

- `vo2max = None`
- `vma_kmh = None`
- `max_hr = None`
- `resting_hr = None`

Aucune estimation implicite n’est créée.

## Capabilities reprises

Les booléens repris de manière déterministe :

- `has_hrv`
- `has_vo2max`
- `has_training_readiness`
- `has_power`
- `has_running_dynamics`

Si `garmin_capabilities` est absent, tous restent à `False`.

## Contraintes normalisées

- `preferred_days_per_week` validé dans `[1, 7]`
- `max_days_per_week` validé dans `[1, 7]`
- si `preferred_days_per_week > max_days_per_week`, la valeur préférée devient
  `None` sans correction silencieuse
- `preferred_long_run_day` conservé tel quel si non vide
- `injury_constraints` et `availability_constraints`
  - absentes => listes vides
  - présentes => chaînes nettoyées, sans interprétation métier

## Fichiers modifiés

- `backend/training_v2/runner_profile.py`
- `backend/training_v2/__init__.py`
- `backend/tests/test_runner_profile_pr07.py`
- `RUNNER_PROFILE_PR07_REPORT.md`

## Tests exécutés

À exécuter :

- `cd backend && python -m pytest tests/test_runner_profile_pr07.py -q`
- `cd backend && python -m pytest tests/test_training_history_pr05.py -q`
- `cd backend && python -m pytest tests/test_training_v2_training_load.py -q`
- `cd backend && python -m pytest tests/test_garmin_data_layer.py -q`
- `cd backend && python -m py_compile training_v2/runner_profile.py training_v2/__init__.py`

## Résultats exacts

- `python -m py_compile training_v2/runner_profile.py training_v2/__init__.py` ✅
- `python -m pytest tests/test_runner_profile_pr07.py -q` → `35 passed`
- `python -m pytest tests/test_training_history_pr05.py -q` → `53 passed`
- `python -m pytest tests/test_training_v2_training_load.py -q` → `50 passed`
- `python -m pytest tests/test_garmin_data_layer.py -q` → `13 passed`

## Risques résiduels

- la profondeur d’historique dépend de la sémantique déjà exposée par
  `TrainingHistory.available_history_days`
- les alias de discipline restent volontairement limités à un mapping explicite
- `TrainingLoadSnapshot` est injecté mais non exploité dans cette PR par design

## Confirmation de périmètre

Confirmation :

- aucun moteur existant n’a été modifié
- aucun score n’a été modifié
- aucune readiness n’a été modifiée
- aucun frontend n’a été modifié
- aucun endpoint n’a été modifié
