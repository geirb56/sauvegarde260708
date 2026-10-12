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

| Suite | Résultat |
|---|---|
| `test_activity_laps_pr332.py` (unit, hors Redis isolé) | **passés** (inclus dans 68 passed du run normal) |
| `test_activity_laps_queue_pr332.py` (unit, hors Redis isolé) | **passés** |
| Tests d'intégration Redis isolés (fixture `local_redis`) | **PARTIELS** — un lot a démarré (**72 passed**) mais la suite complète n'a **pas** pu être menée à terme : le spawn répété de `redis-server` isolé devient instable sous charge dans ce harness (« Isolated Redis did not start », timeout du run). |

**Important** : les 35 tests précédemment « skipped » (absence de `redis-server` au PATH) **ne sont pas déclarés réussis**. En exposant `/app/bin` au PATH, une partie de l'intégration Redis isolée s'est exécutée (72 passés) **sans toucher** le Redis runtime (instances isolées sur ports aléatoires), mais la couverture **crash / lease expiré / redelivery** n'a **pas** pu être confirmée intégralement (erreurs de démarrage des instances isolées = limitation d'environnement, **aucun échec applicatif démontré**). Le Redis runtime est resté sain tout du long.

## 9. Anomalies éventuelles

- **Aucune anomalie fonctionnelle** sur le parcours runtime (acquisition, persistance, idempotence, ACK, nettoyage, non-régression).
- Anomalie **connue et attendue** (donnée Garmin) : dernier lap `avg_speed > max_speed` — correctement **préservée**, non corrigée.
- Limitation **d'environnement** : instabilité de spawn de `redis-server` isolé pour la suite d'intégration Redis (ne reflète pas un défaut de #332).

## 10. Risques résiduels

1. Couverture automatisée **crash/lease/redelivery** non confirmée intégralement dans ce harness (nécessiterait un Redis de test stable dédié ou une exécution séquencée des instances isolées).
2. Généralisation hors échantillon : un seul profil d'activité continue (22 laps) validé au runtime ; cas `lapDTOs` vide/null, laps manuels, multisport non observés.
3. `strideLength` non persisté (hors mapping actuel) et unité non confirmée — sans impact sur ce test.
4. Le « HOLD runtime gate » documenté upstream (commit `c9b7d45`) concerne l'activation de l'acquisition automatique différée — hors périmètre de cette validation.

---

## Verdict : **PASS PARTIEL**

**Validé par observation runtime réelle** : première acquisition déclenchée (cache absent au départ), **1 seule** commande GCCLI `activity splits`, persistance Mongo conforme au contrat #331 (**22 laps, 21,2745 km, schema_version=1, complete**, champs normalisés, `null` préservés, anomalie Garmin conservée, `intensity_type` non interprété), **idempotence** (3 POST → 1 acquisition ; `queued`→`running`→`cached` ; aucune duplication), **isolation/non-régression** (`activity_details`/phases/`activity_day` inchangés, Redis nettoyé, pas d'orphelin), Redis runtime sain.

**Pourquoi PARTIEL et non PASS complet** : la couverture **automatisée** des scénarios Redis de résilience (crash, lease expiré, redelivery) n'a **pas** pu être exécutée intégralement de façon fiable dans ce harness (instabilité de spawn des instances `redis-server` isolées) — **aucune anomalie démontrée**, mais couverture incomplète explicitement signalée. Ces scénarios restent à confirmer sur un Redis de test dédié stable avant de lever le « runtime gate » et de passer à l'acquisition automatique différée.

*(STOP. Aucune PR, aucun code modifié, rien poussé.)*
