# GARMIN_DAILY_METRICS_PR03_REPORT.md

## Chemin actuel de collecte

- `backend/garmin/service.py`
  - `sync()` et `deep_sync()` appellent `provider.get_daily_metrics(user_id, days=30)`.
  - chaque document est persisté via `db.garmin_daily_metrics.update_one({...}, {"$set": {...m, user_id, synced_at}}, upsert=True)`.
- `backend/garmin/providers/gccli_provider.py`
  - `get_daily_metrics()` délègue à `GccliRunner.fetch_daily_metrics(days, account)`.
- `backend/garmin/runner.py`
  - commandes gccli déjà existantes uniquement:
    - `health hr <day>`
    - `health sleep <day>`
    - `health hrv <day>`
- Consommation
  - endpoint API inchangé: `backend/api/garmin.py` → `/api/garmin/daily-metrics` → `garmin_service.get_daily_metrics()`.

## Ancienne normalisation

Avant PR03, `GccliRunner.fetch_daily_metrics()` parsait manuellement les payloads HR/sommeil/HRV et assemblait directement:
- `resting_hr`
- `sleep_hours`
- `sleep_score`
- `hrv`

La normalisation n’utilisait pas `GarminDailyMetrics`.

## Nouvelle normalisation

PR03 fait de `GarminDailyMetrics` la source unique:
- `backend/garmin/runner.py`
  - collecte inchangée (`health hr`, `health sleep`, `health hrv` seulement)
  - normalisation via `GarminDailyMetrics.from_gccli(date=day, hr=..., sleep=..., hrv=...)`
  - document final basé sur `normalized.model_dump()`
  - ajout additif de `garmin_daily_metrics = normalized.model_dump()`
- `backend/garmin/data_layer.py`
  - `GarminDailyMetrics.from_gccli()` résout la date de manière déterministe à partir des payloads (`calendarDate` / `date` / `dailySleepDTO.calendarDate` / date de boucle)
  - aucune fabrication de valeur si donnée absente

## Champs historiques conservés

Conservés:
- `date`
- `resting_hr`
- `sleep_hours`
- `sleep_score`
- `hrv`

Ajout additif:
- `stress`
- `body_battery`
- `respiration`
- `garmin_daily_metrics`

## Sous-document `garmin_daily_metrics` ajouté

- Contenu: `normalized.model_dump()`
- Pas de duplication de payload brut volumineux
- Contrat endpoint non cassé (ajout additif)

## Absence de fallback

Règle appliquée: donnée absente Garmin => `None`.

Sémantique sommeil historique préservée:
- `sleepTimeSeconds` absent => `sleep_hours = None`
- `sleepTimeSeconds = null` => `sleep_hours = None`
- `sleepTimeSeconds = 0` => `sleep_hours = None`
- `sleepTimeSeconds > 0` => conversion en heures, arrondie à 1 décimale

Vérifié par tests PR03 pour:
- `resting_hr`
- `sleep_hours`
- `sleep_score`
- `hrv`
- `stress`
- `body_battery`
- `respiration`

## Absence de nouvelles commandes gccli

Aucune nouvelle commande ajoutée.

Toujours limité à:
- `health hr`
- `health sleep`
- `health hrv`

Tests PR03 incluent une assertion statique interdisant:
- `health stress`
- `health body-battery`
- `health respiration`
- `health training-readiness`
- `health training-status`
- `health max-metrics`
- `health race-predictions`

## Fichiers modifiés

- `backend/garmin/data_layer.py`
- `backend/garmin/runner.py`
- `backend/tests/test_garmin_daily_metrics_pr03.py`
- `GARMIN_DAILY_METRICS_PR03_REPORT.md`

## Tests exécutés

Depuis `backend/`:

- `python -m pytest tests/test_garmin_daily_metrics_pr03.py -q`
- `python -m pytest tests/test_garmin_data_layer.py -q`
- `python -m pytest tests/test_garmin_deep_sync.py -q`
- `python -m pytest tests/test_garmin_activity_normalization_pr02.py -q`
- `python -m py_compile garmin/data_layer.py garmin/runner.py garmin/service.py`

## Résultats exacts

- `tests/test_garmin_daily_metrics_pr03.py`: **11 passed**
- `tests/test_garmin_data_layer.py`: **13 passed**
- `tests/test_garmin_deep_sync.py`: **21 passed**
- `tests/test_garmin_activity_normalization_pr02.py`: **31 passed**
- `py_compile`: **OK**

Total pytest exécuté ici: **76 passed**.

## Risques résiduels

- `sleep_hours` reste arrondi à 1 décimale (comportement existant conservé).
- Les champs `stress` / `body_battery` / `respiration` restent à `None` tant que ces payloads ne sont pas fournis par le flux de collecte actuel (volontaire en PR03, sans nouvelle commande gccli).

## Confirmation de non-modification hors périmètre

Aucun changement sur:
- moteur métier (Training Engine, TrainingHistory, RunnerProfile, TrainingState, PlanGoal, WorkoutGenerator)
- scores RunIndex / Readiness
- frontend
- endpoints publics
- auth / queue / workers / Redis / index MongoDB

PR03 remplace uniquement la normalisation des métriques quotidiennes Garmin sur le flux existant.
