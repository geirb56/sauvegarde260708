# RUNNER_PROFILE_PR07_REPORT

## Rôle exact de `RunnerProfile`
- Centraliser un profil V2 pur, stable, explicite et déterministe.
- Décrire uniquement des caractéristiques durables ou semi-durables du coureur.
- Exclure toute décision de reprise, fatigue, surcharge, readiness ou recommandation.

## Sources de données
- `TrainingHistory` pour les métriques observées d’historique et de volume.
- `TrainingLoadSnapshot` injecté explicitement pour garder la dépendance visible, sans logique readiness dans cette PR.
- `user_profile` pour les données déclarées et contraintes utilisateur.
- `GarminCapabilities` pour recopier les capacités observées.
- `physiological_metrics` pour les métriques physiologiques facultatives.

## Ordre de priorité des sources
- Données personnelles et contraintes : valeur déclarée valide, sinon absence.
- Métriques d’entraînement : valeur observée `TrainingHistory`, sinon valeur utilisateur explicitement déclarée, sinon `None`.
- Physiologie : valeur présente et valide, sinon `None` ; `max_hr` peut venir du profil utilisateur en repli déclaré.

## Calcul des métriques habituelles
- Priorité à la fenêtre `window_30d`.
- `typical_weekly_km = distance_km * 7 / days`
- `typical_weekly_hours = duration_hours * 7 / days`
- `typical_runs_per_week = activity_count * 7 / days`
- Aucun volume par défaut n’est injecté.
- Aucun arrondi intermédiaire n’est appliqué ; l’arrondi se fait uniquement sur la sortie.
- `typical_long_run_km` reprend `longest_run_km` observé.
- `typical_speed_kmh` reprend `average_speed_kmh` observé quand disponible.

## Définition de l’expérience
- `unknown` : 0 jour exploitable.
- `beginner` : 1 à 29 jours.
- `developing` : 30 à 89 jours.
- `established` : 90 à 364 jours.
- `experienced` : 365 jours ou plus.
- Cette classification décrit uniquement la profondeur d’historique observée, pas le niveau sportif réel.

## Définition de la confiance
- `none` : 0 jour d’historique exploitable.
- `low` : 1 à 29 jours.
- `medium` : 30 à 89 jours.
- `high` : 90 jours ou plus.
- Aucune valeur par défaut n’augmente artificiellement la confiance.

## Comportement sans historique
- `experience_level = "unknown"`
- `typical_weekly_km = None`
- `typical_weekly_hours = None`
- `typical_runs_per_week = None`
- `typical_long_run_km = None`
- `typical_speed_kmh = None`
- `available_history_days = 0`
- `profile_confidence = "none"`
- Aucun fallback de type `20 km` n’est utilisé.

## Comportement sans physiologie
- `vo2max = None`
- `vma_kmh = None`
- `max_hr = None`
- `resting_hr = None`
- Aucune estimation implicite n’est créée.

## Capabilities reprises
- `has_hrv`
- `has_vo2max`
- `has_training_readiness`
- `has_power`
- `has_running_dynamics`
- En absence de `GarminCapabilities`, toutes ces valeurs restent à `False`.

## Contraintes normalisées
- `preferred_days_per_week` et `max_days_per_week` sont validés entre 1 et 7.
- Si `preferred_days_per_week > max_days_per_week`, `preferred_days_per_week` devient `None`.
- `preferred_long_run_day` est normalisé de façon stable.
- `injury_constraints` et `availability_constraints` deviennent des listes vides si absentes.
- Aucune interprétation métier ou médicale n’est ajoutée.

## Fichiers modifiés
- `backend/training_v2/runner_profile.py`
- `backend/training_v2/__init__.py`
- `backend/tests/test_runner_profile_pr07.py`
- `RUNNER_PROFILE_PR07_REPORT.md`

## Tests exécutés
- `cd backend && python -m pytest tests/test_runner_profile_pr07.py -q`
- `cd backend && python -m pytest tests/test_training_history_pr05.py -q`
- `cd backend && python -m pytest tests/test_training_v2_training_load.py -q`
- `cd backend && python -m pytest tests/test_garmin_data_layer.py -q`
- `cd backend && python -m py_compile training_v2/runner_profile.py training_v2/__init__.py`

## Résultats exacts
- `python -m pytest tests/test_runner_profile_pr07.py -q` → `27 passed in 0.50s`
- `python -m pytest tests/test_training_history_pr05.py -q` → `53 passed in 1.03s`
- `python -m pytest tests/test_training_v2_training_load.py -q` → `50 passed in 1.12s`
- `python -m pytest tests/test_garmin_data_layer.py -q` → `13 passed in 1.09s`
- `python -m py_compile training_v2/runner_profile.py training_v2/__init__.py` → succès

## Risques résiduels
- Le profil reste dépendant du niveau d’agrégation déjà fourni par `TrainingHistory`.
- Les alias de champs déclaratifs couvrent les formes attendues les plus probables, mais pourront être étendus si de nouveaux formats d’entrée apparaissent.

## Confirmation de périmètre
- Aucun moteur existant n’a été modifié.
- Aucun score, readiness, frontend ou endpoint n’a été modifié.
