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

## 10. Validation finale — commandes exactes et résultats exacts

### 10.1 Garmin non-régression PR07A

Commande exécutée :

`cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest -q tests/test_garmin_data_layer.py tests/test_garmin_activity_normalization_pr02.py tests/test_garmin_capabilities_pr04.py tests/test_garmin_session_store.py tests/test_run_index_engine.py tests/test_run_index_history_service.py tests/test_garmin_daily_metrics_pr03.py tests/test_garmin_deep_sync.py tests/test_garmin_phased_sync_pr07a.py`

Résultat exact :

- `129 passed in 1.10s`
- tests exécutés : `129`
- tests passés : `129`
- tests skipped : `0`
- échecs non liés : `0`

### 10.2 Queue / Redis — commande pytest minimale demandée

Commande exécutée :

`cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && REDIS_URL=redis://localhost:6379/0 python -m pytest -q tests/test_reliable_queue.py tests/test_queue_health.py`

Résultat exact :

- `1 failed, 8 errors in 0.58s`
- tests exécutés : `9`
- tests passés : `0`
- tests skipped : `0`
- échecs non liés :
  - fichiers `tests/test_reliable_queue.py` et `tests/test_queue_health.py` écrits en mode script avec fonction `main()` et paramètre `r` non fourni comme fixture pytest (`fixture 'r' not found`)

### 10.3 Queue / Redis — suites existantes exécutables localement

Commande exécutée :

`cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && REDIS_URL=redis://localhost:6379/0 python -m tests.test_queue_health`

Résultat exact :

- `RESULT: ALL PASSED ✅`
- checks exécutés : `6`
- checks passés : `6`
- checks skipped : `0`
- échecs non liés : `0`

Commande exécutée :

`cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && REDIS_URL=redis://localhost:6379/0 python -m tests.test_reliable_queue`

Résultat exact :

- `RESULT: 1 TEST(S) FAILED ❌`
- checks exécutés : `3`
- checks passés : `2`
- checks failed : `1`
- checks skipped : `0`
- échec non lié :
  - `test_redis_restart_durability` échoue sur `sudo supervisorctl restart redis` car `supervisorctl` n'est pas disponible dans cet environnement ; les 2 autres checks (`worker kill -9` recovery, `ACK` cleanup) passent

### 10.4 Worker / orchestration — suites existantes directement liées

Commande exécutée :

`cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && REDIS_URL=redis://localhost:6379/0 python -m tests.test_sync_scheduler`

Résultat exact :

- `RESULT: ALL PASSED ✅`
- checks exécutés : `5`
- checks passés : `5`
- checks skipped : `0`
- échecs non liés : `0`

Commande exécutée :

`cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest -q tests/test_realtime_sync_pipeline.py`

Résultat exact :

- `14 failed in 1.78s`
- tests exécutés : `14`
- tests passés : `0`
- tests skipped : `0`
- échecs non liés :
  - dépendance hardcodée `/app/bin/redis-cli` absente dans cet environnement
  - `REACT_APP_BACKEND_URL` non défini ; le test tombe sur `https://charge-load.preview.emergentagent.com`, non résolu ici

### 10.5 py_compile

Commande exécutée :

`cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m py_compile garmin/service.py garmin/sync_progress.py jobs/queue.py workers/sync_worker.py services/run_index_history.py garmin/runner.py garmin/providers/base.py garmin/providers/gccli_provider.py`

Résultat exact :

- succès
- sortie standard : vide
- erreurs : `0`

### 10.6 Vérifications explicites

1. `refresh_run_index_after_garmin_sync()` n'est plus relancé par le worker :
   - confirmé par `backend/workers/sync_worker.py` (`_run_job()` délègue uniquement à `garmin_service.sync()` / `incremental_sync()`)
   - la suite PR07A passe toujours avec la nouvelle orchestration (`129/129`)
2. `partial_success` reste traité comme succès :
   - `tests/test_garmin_phased_sync_pr07a.py::test_metrics_failure_after_run_index_returns_partial_success` confirme `success=True` et `status=partial_success`
   - le worker ACKe toujours tout résultat `success=True`
3. une vraie erreur `success=False` garde le chemin retry / requeue :
   - `tests/test_garmin_phased_sync_pr07a.py::test_activity_failure_stays_failed_before_run_index` confirme `success=False`
   - le branchement worker `if not result.get("success"): raise ...` est inchangé
4. le `pending key` est toujours supprimé après succès :
   - suppression toujours présente dans `backend/workers/sync_worker.py` (`redis.delete(f"{PENDING_PREFIX}{user_id}")`)
   - aucun test d'intégration exécutable localement n'a pu le revalider, `tests/test_realtime_sync_pipeline.py` étant bloqué par l'environnement
5. locks / rate limits existants restent inchangés :
   - `tests.test_sync_scheduler` passe (`cooldown`, `global concurrency cap`)
   - le lock utilisateur existe toujours inchangé dans `backend/workers/sync_worker.py`
6. la reliable queue conserve l'at-least-once delivery :
   - `tests.test_reliable_queue` valide encore le recovery après kill -9 et le cleanup après ACK
   - le check de durabilité après restart Redis est bloqué par l'absence de `supervisorctl`, pas par le code applicatif

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
