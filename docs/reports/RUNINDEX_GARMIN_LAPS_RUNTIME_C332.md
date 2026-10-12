# RUNINDEX — Validation runtime C332 : acquisition & persistance des laps Garmin

> Validation runtime ciblée sur Emergent. Aucun changement de code, aucune PR, aucun push. Seules écritures = celles du parcours réel d'acquisition laps (#331/#332). Drift local `activity_day` préservé. Caches existants non effacés. Données Garmin sources non modifiées. WA V2 / Training V2 / Coach non touchés. Aucun secret/JWT/donnée personnelle exposé.

---

## 1. HEAD testé et environnement

| Élément | Valeur |
|---|---|
| HEAD local | `174ee2b` (merge local, parent canonique `70fd634` = PR #330/#331/#332) |
| Commits intégrés | #330 (audit conception), #331 (acquisition+persistance laps), #332 (fix perte de livraison + enqueue Redis atomique + dédup) |
| Backend / workers | backend + `garmin-sync/event/monitor/scheduler-worker` **RUNNING** |
| Redis runtime | `PING=True` (`/app/bin/redis-server` v7.0.15, port 6379) |
| MongoDB | `ping ok` |
| Job `ACTIVITY_LAPS` | **reconnu** (`jobs/queue.py`: `JOB_ACTIVITY_LAPS="ACTIVITY_LAPS"`, `TARGETED_JOB_TYPES`) |
| Routes | `POST`/`GET /api/garmin/activities/{activity_id}/laps` (montées, `/api` + `garmin_router`) |
| Activité cible | `24346252881` (Auray–Vannes) — propriétaire `da8505ef…` (anonymisé), `source=garmin` |

## 2. Snapshot avant / après

| Champ | AVANT | APRÈS |
|---|---|---|
| `activity_laps` | **None** | présent (`schema_version=1`, `status=complete`, `source=garmin`, `endpoint=splits`, 22 laps) |
| `activity_laps_fetch` | **None** | (statut porté par `activity_laps.status=complete`) |
| `activity_details` | présent, `status=no_data`, 0 phase | **inchangé** (`no_data`, 0 phase) |
| Phases existantes | 0 | **inchangé** (0) |
| `activity_day` (champ document) | absent (var de boucle `server.py`, pas un champ doc) | inchangé |
| Jobs Redis pour l'activité | aucun (queue/deferred/processing = 0/0/0) | aucun résiduel (0/0/0, pas de réservation) |

→ Cache laps **absent avant** → le scénario de **première acquisition est reproductible et a été réellement observé**.

## 3. Résultats GET et POST

| Étape | Appel | Résultat |
|---|---|---|
| GET initial | `GET …/laps` | HTTP 200 · `activity_laps=null`, `cache_current=false`, `fetch_status=not_requested` · **aucun GCCLI, aucune écriture, aucun job** (conforme au cache absent) |
| POST #1 | `POST …/laps` | **HTTP 202 `{"status":"queued"}`** |
| POST #2 (immédiat) | `POST …/laps` | **HTTP 202 `{"status":"running"}`** — pas de 2ᵉ acquisition |
| GET après traitement | `GET …/laps` | HTTP 200 · `fetch_status=complete`, `cache_current=true`, **22 laps**, `schema_version=1` |
| POST #3 (cache valide) | `POST …/laps` | **HTTP 202 `{"status":"cached"}`** — pas de nouvelle acquisition |

## 4. Nombre réel de commandes GCCLI

**1 seule** exécution GCCLI `activity splits` (worker), malgré **3 POST** au total.
Log worker : `sync_start type=ACTIVITY_LAPS attempt=1` → `sync_success … duration=0.31s status=complete`.
Compteur `sync_start type=ACTIVITY_LAPS` = **1** (aucun doublon).

## 5. Nombre de laps et distance cumulée

| Attendu (#331) | Observé | Verdict |
|---|---|---|
| 22 laps | **22** | ✅ |
| 21 laps ~1 km | **21** (995–1005 m) | ✅ |
| Dernier lap ~274,53 m | **274,53 m** (`lap_index=22`) | ✅ |
| Distance cumulée ~21,2745 km | **21 274,5 m = 21,2745 km** | ✅ |
| Ordre natif préservé | `lap_index` 1→22 séquentiel | ✅ |
| `schema_version=1`, cache `complete` | `schema_version=1`, `status=complete` | ✅ |
| Champs absents à `null` | `min_hr=null`, `trigger_mode=null` (tous laps) | ✅ |

Champs normalisés persistés : `lap_index`, `order`, `start_time_gmt`, `distance_m`, `duration_s`, `moving/elapsed_duration_s`, `average_speed_mps`, `average_moving_speed_mps`, `max_speed_mps`, `average_hr`, `max_hr`, `average_cadence_spm`, `max_cadence_spm`, `elevation_gain_m`, `elevation_loss_m`, `max/min_elevation_m`, `intensity_type`.

**Anomalie Garmin préservée (non corrigée)** : dernier lap `average_speed_mps=3.196` > `max_speed_mps=3.191` — conservée telle quelle. ✅
`intensity_type="ACTIVE"` **non interprété** comme zone physiologique. ✅

## 6. Temps d'attente et d'exécution

| Mesure | Valeur |
|---|---|
| Commande GCCLI `activity splits` | **0,31 s** (worker) |
| POST → prise en charge worker | quelques secondes (job pris à `attempt=1`) |
| POST → cache disponible | **< 7 s** (cache déjà `complete` au premier GET de contrôle) |

## 7. État Redis et Mongo (après)

- Redis : `queue=0`, `deferred=0`, `processing=0`, aucune réservation `pending`/`:activity_laps` résiduelle → job **ACK** et nettoyé, pas d'orphelin.
- Un pic transitoire `processing=1` observé pendant le test = sync de fond du compte legacy `default` (sans rapport), revenu à 0.
- Mongo : `activity_laps` persisté (v1, 22 laps) ; `activity_details`/phases inchangés ; aucune duplication de laps ; aucun événement `ACTIVITY_CREATED` artificiel.

## 8. Tests automatisés réellement exécutés

### 8.1 Cause de l'instabilité précédente — RÉSOLUE
Les instances `redis-server` isolées ne démarraient pas car le binaire `/app/bin/redis-server` requiert `liblzf.so.1` / `libjemalloc.so.2` présentes dans `/app/lib/` mais absentes du chemin de librairies du shell (le Redis runtime tournait déjà avec le bon `LD_LIBRARY_PATH`). **Correctif d'invocation uniquement** (pas de modif code) : `PATH=/app/bin:$PATH` + `LD_LIBRARY_PATH=/app/lib`. Après cela, chaque instance isolée démarre en < 1 s.

### 8.2 Résilience Redis — exécution séquentielle (un test à la fois, Redis isolé dédié, timeout borné)

| Scénario | Test | Résultat |
|---|---|---|
| Crash réservation Mongo → avant enqueue Redis, récupération après expiry | `test_mongo_reservation_crash_before_enqueue_recovers_after_expiry` | **PASS** (1) |
| Fencing — interruption ne laisse pas de pending sans livraison | `test_interruption_cannot_leave_redis_pending_without_delivery` | **PASS** (1) |
| Lease expiré — POST running expiré ne perd pas la livraison réservée | `test_expired_running_post_does_not_lose_the_reserved_delivery` | **PASS** (1) |
| Redelivery — worker interrompu | `test_interrupted_worker_redelivery` | **PASS** (3) |
| Orphelin / watchdog stale ne recrée pas de redelivery | `test_laps_stale_watchdog_cannot_recover_fresh_redelivery` | **PASS** (1) |
| Retry différé promu puis ACK | `test_worker_deferred_retry_promotes_and_acks` | **PASS** (1) |
| Pending stale ne peut ni refresh, ni release, ni exécuter | `test_stale_pending_cannot_refresh_release_or_execute` | **PASS** (2) |
| Stockage différé survit au redémarrage Redis | `test_laps_delayed_storage_survives_local_redis_restart` | **PASS** (1) |
| Échec d'enqueue ne libère que sa propre réservation | `test_enqueue_failure_releases_only_its_reservation` | **PASS** (1) |
| Dédup POST confirmée dans tous les états de livraison (queue/processing/delayed/unknown) | `test_post_dedup_confirms_pending_target_in_all_delivery_states` | **PASS** (4) |
| Lookup pending « fail-closed » pour livraison inconnue | `test_pending_lookup_fails_closed_for_unknown_delivery` | **PASS** (3) |
| Promotion vérifie type + suffixe pending correct | `test_promotion_checks_type_and_correct_pending_suffix` | **PASS** (1) |

**Total : 20 cas de résilience exécutés → 20 PASS, 0 FAIL, 0 NON EXÉCUTÉ.**

Exécution strictement séquentielle (une invocation `pytest` par scénario), sur Redis **isolés** (ports aléatoires 127.0.0.1, `--save ""`, tmp dir) — le **Redis runtime (6379) n'a jamais été touché** et est resté `PING=True`, queue propre, tout du long.

### 8.3 Tests fonctionnels
Non re-exécutés (déjà validés au runtime §3–§7 : 22 laps, persistance, idempotence). Les suites unit (`test_activity_laps_pr332.py` / `_queue_pr332.py`, hors Redis isolé) restent vertes.

## 9. Anomalies éventuelles

- **Aucune anomalie fonctionnelle** sur le parcours runtime (acquisition, persistance, idempotence, ACK, nettoyage, non-régression).
- **Aucune anomalie de résilience** : les 20 cas crash / lease / redelivery / fencing / orphelins passent.
- Anomalie **connue et attendue** (donnée Garmin) : dernier lap `avg_speed > max_speed` — correctement **préservée**, non corrigée.
- Limitation d'environnement précédente (spawn `redis-server`) **résolue** via `LD_LIBRARY_PATH=/app/lib` à l'invocation (pas de modif code).

## 10. Risques résiduels

1. Généralisation hors échantillon : un seul profil d'activité continue (22 laps) validé au runtime ; cas `lapDTOs` vide/null, laps manuels, multisport non observés en runtime réel (mais couverts par les tests unit).
2. `strideLength` non persisté (hors mapping actuel) et unité non confirmée — sans impact.
3. Le « HOLD runtime gate » upstream (commit `c9b7d45`) concerne l'activation de l'acquisition automatique différée — à lever désormais que la résilience est validée.

---

## Verdict : **PASS**

**Fonctionnel (runtime réel)** : première acquisition observée, **1 seule** commande GCCLI, persistance conforme #331 (**22 laps / 21,2745 km / schema_version=1 / complete**, champs normalisés, `null` préservés, anomalie Garmin conservée, `intensity_type` non interprété), **idempotence** (3 POST → 1 acquisition), **isolation/non-régression** (`activity_details`/phases/`activity_day` inchangés, Redis nettoyé).

**Résilience (tests automatisés, exécution séquentielle, Redis isolé)** : **20/20 PASS** — crash réservation→enqueue, lease expiré, redelivery, fencing, orphelins/watchdog, promotion différée, dédup multi-états, restart Redis. 0 FAIL, 0 NON EXÉCUTÉ. Redis runtime jamais touché.

La limitation précédente du harness (spawn `redis-server`) était un simple problème de `LD_LIBRARY_PATH`, résolu à l'invocation sans modifier le code applicatif.

**#332 est fonctionnellement et structurellement validée (fonctionnel + résilience).** La roadmap peut se poursuivre avec l'adaptation de la queue GCCLI et l'acquisition automatique différée des laps ; le « runtime gate » peut être levé.

*(STOP. Aucune PR, aucun code modifié, rien poussé.)*
