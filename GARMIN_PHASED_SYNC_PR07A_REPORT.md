# GARMIN_PHASED_SYNC_PR07A_REPORT

## 1. Architecture avant

Pipeline unique existant :

1. enqueue `/api/garmin/sync`
2. worker `backend/workers/sync_worker.py`
3. `backend/garmin/service.py`
4. fetch activités Garmin
5. persist `garmin_activities`
6. fetch daily metrics 30 jours
7. persist `garmin_daily_metrics`
8. `refresh_run_index_after_garmin_sync()`
   - rebuild workouts Garmin dérivés
   - snapshot RunIndex du jour
   - backfill historique RunIndex
9. ACK du job

Conséquence : le RunIndex courant attendait la fin des daily metrics longues.

## 2. Architecture après

Le pipeline Garmin reste **unique**.

Nouvel ordre :

1. `queued`
2. `activities_fetching`
3. fetch activités Garmin
4. persist `garmin_activities`
5. `activities_ready`
6. `refresh_today_run_index_after_garmin_activities()`
7. `run_index_ready`
8. `metrics_7d_fetching`
9. fetch daily metrics J-1 → J-7
10. `readiness_ready` ou `readiness_unavailable`
11. `enriching`
12. fetch daily metrics J-8 → J-30
13. backfill historique RunIndex
14. `complete` ou `partial_success`

Le worker reste unique, la queue Redis reste unique, et `/api/garmin/sync` continue d'utiliser ce pipeline.

## 3. Fichiers modifiés

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/providers/base.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/providers/gccli_provider.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/runner.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/service.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/sync_progress.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/jobs/queue.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/services/run_index_history.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workers/sync_worker.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_garmin_deep_sync.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_garmin_phased_sync_pr07a.py`

## 4. Contrat des phases

Redis status key : `runindex:garmin:sync_status:{user_id}`

Champs stables :

- `status`
- `phase`
- `updated_at`
- `activities_status`
- `activities_count`
- `run_index_status`
- `daily_metrics_status`
- `readiness_status`
- `error_code`

Phases stables exposées :

- `queued`
- `activities_fetching`
- `activities_ready`
- `run_index_ready`
- `metrics_7d_fetching`
- `readiness_ready`
- `readiness_unavailable`
- `enriching`
- `complete`
- `partial_success`
- `failed`

## 5. Contrat `daily_metrics_status`

- `pending` : récupération non terminée
- `ready` : données physiologiques réelles utilisables présentes
- `no_usable_data` : réponse Garmin normale mais aucune physio réelle exploitable
- `failed` : erreur technique réelle sur la phase metrics

## 6. Comportement sans HRV

Absence de HRV ne déclenche pas `failed`.

Si sommeil et/ou resting HR réels sont présents, la sync peut produire :

- `daily_metrics_status = ready`
- `readiness_status = ready`

La formule Readiness n'a pas été dupliquée ni modifiée.

## 7. Comportement `partial_success`

Cas couvert : activités et RunIndex prêts, puis échec technique metrics.

Résultat backend :

- `status = partial_success`
- `activities_status = ready`
- `run_index_status = ready`
- `daily_metrics_status = failed`
- `readiness_status = unavailable` si l'échec arrive avant readiness
- `readiness_status = ready` si l'échec arrive pendant l'enrichissement après readiness 7j

Le job n'est plus considéré comme échec global si la première valeur produit existe déjà.

## 8. Retry retenu

Aucun second pipeline n'a été ajouté.

Le retry ciblé est assuré par **reprise du pipeline unique** :

- un état Redis `run_index_status=ready` + `daily_metrics_status=failed/pending` permet à un nouveau `/api/garmin/sync` de reprendre à `metrics_7d` ou `metrics_enrichment`
- les activités ne sont pas refetchées dans ce cas
- la queue/worker existants sont conservés

## 9. Tests ajoutés

Nouveau fichier :

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_garmin_phased_sync_pr07a.py`

Couverture ciblée :

- ordre des phases
- disponibilité rapide du RunIndex
- fenêtre 7 jours exacte
- enrichissement J-8 → J-30 sans refetch inutile J-1 → J-7
- appareil sans HRV
- absence de physio exploitable
- `partial_success`
- erreur activités avant RunIndex
- reprise ciblée metrics-only
- maintien de l'incremental sync
- isolation/sanitation Redis progress

## 10. Résultats exacts

Commande validée :

`cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest -q tests/test_garmin_data_layer.py tests/test_garmin_activity_normalization_pr02.py tests/test_garmin_capabilities_pr04.py tests/test_garmin_session_store.py tests/test_run_index_engine.py tests/test_run_index_history_service.py tests/test_garmin_daily_metrics_pr03.py tests/test_garmin_deep_sync.py tests/test_garmin_phased_sync_pr07a.py`

Résultat :

- `129 passed in 0.67s`

## 11. Benchmark avant/après

Benchmark réel Garmin **non exécuté** dans cet environnement.

Aucun chiffre après implémentation n'est inventé dans ce rapport.

## 12. Limitations restantes

- le benchmark warm/cold réel reste à exécuter sur environnement Garmin disponible
- l'exposition frontend/SSE de cette progression n'est pas incluse ici
- la reprise ciblée se base sur l'état Redis éphémère, conformément au périmètre demandé

## 13. Points laissés explicitement à PR07B / PR07C / PR07D

- **PR07B** : exposition frontend/SSE/progression UI
- **PR07C** : itérations éventuelles sur retry UX / surfacing produit
- **PR07D** : benchmark réel complémentaire et optimisations additionnelles si nécessaires
