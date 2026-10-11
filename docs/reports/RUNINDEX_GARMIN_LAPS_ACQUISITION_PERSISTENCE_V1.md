# RUNINDEX — PR332 : Garmin Lap Acquisition & Persistence V1

## P332 — Correction ciblée avant merge (2026-10-11)

### Références et verdict

- PR existante : #332, toujours draft, aucun merge/nouvelle PR.
- Base PR : `copilot/dev` / `6c2f986074a9f84def0b9ad73e097d0e16406d06`.
- Head audité avant correction : `ee5a9cc9f1476a73582ddbbb463f475bb2668d38`.
- Head corrigé exact : publié dans le commentaire de livraison de #332.
- Git initial propre. Aucun drift local préexistant ; `activity_day` inchangé.
- **Verdict : HOLD** jusqu'à validation runtime Emergent et audit C332.
  Les tests locaux ne valident pas Mongo production, les workers Railway ou
  le payload réel complet ; la fixture ne contient toujours que deux exemples.

### Diagnostic factuel A — Cohérence Mongo / Redis

1. Interruption après réservation Mongo, avant tout enqueue Redis :
   `queued` reste jusqu'au bail de 900 s. Une demande avant expiration retourne
   `queued` même si aucune livraison n'existe ; après expiration GET expose
   `retryable_error/lease_expired` et POST reprend la réservation.
   Test déterministe par cancellation et expiration contrôlée : réussi avant
   correction. Pas de changement de cette politique bornée, ni réparation GET.
2. Anomalie distincte reproduite : Redis réservait le pending dans Lua puis
   faisait LPUSH hors Lua. Une cancellation entre les deux laissait un pending
   sans livraison, bloquant jusqu'au TTL 1800 s. Le test d'invariant a échoué
   avant correction. **Correctif** limité aux laps : SET NX et LPUSH dans le
   même script Lua ; prévalidation des types de clés avant tout write, car Lua
   est atomique mais n'annule pas les écritures en cas d'erreur de script.
   Aucun stockage/queue supplémentaire, legacy typed-splits inchangé.

### Diagnostic factuel B — Lease, fencing, redelivery, redémarrage

Le fencing Mongo empêchait déjà l'écriture d'un ancien token après nouvelle
acquisition. Les tests existants couvrent worker interrompu, bail expiré,
nouveau résultat puis ancienne terminaison, reprise watchdog et Redis AOF.

**Anomalie reproduite au niveau worker réel + Redis local** :
un POST après expiration du `running` remplace le token Mongo par `queued`,
mais Redis retourne `already_queued` pour la livraison encore exécutée.
L'ancienne écriture est refusée ; le fetch retournait pourtant un succès
`superseded`. Le worker ACKait alors l'unique livraison et libérait pending,
laissant Mongo queued sans travail. Échec observé : aucun job différé (0 au
lieu de 1).

**Correctif minimal** : après écriture refusée, relire le document utilisateur.
Si le nouveau cache est valide ou l'activité supprimée, succès terminal
`superseded` conservé. Sinon retourner le contrat interne existant `deferred` :
immédiat si queued, sinon au prochain bail/cooldown. Le worker existant parque
alors la même livraison sans consommer un retry, puis reprend. Aucune nouvelle
logique de worker ni transmission des tokens Mongo à Redis nécessaire :
les pending Redis sont déjà protégés par leur propre job-id.

Ajouts : cycle cancellation Mongo→expiration→POST, interruption Redis,
wrong-type Redis sans réservation partielle, POST sur running expiré→ancienne
terminaison refusée→déférence→nouveau cache, worker disparu→watchdog→nouveau
traitement→livraison dupliquée utilisant le cache (un seul appel provider).
Le redémarrage worker est simulé par abandon/reprise de la livraison ; pas
un test de déploiement Railway ni de SIGKILL production.

### Diagnostic factuel C — Contrat API sans rupture

Aucune route, HTTP status ou forme de réponse publique modifiée.

| Notion | Contrat |
|---|---|
| Résultat POST | `queued` nouvelle réservation ou demande déjà réservée ; `already_queued` même cible confirmée dans Redis ; `running` en cours ; `busy` autre cible/slot inconnu ; `cooldown` délai temporaire ; `cached` cache versionné valide |
| État GET | `fetch_status` : `not_requested`, `queued`, `running`, `complete`, `empty`, `retryable_error` |
| Disponibilité | `cache_current` indique la validité versionnée ; `activity_laps` peut contenir un ancien cache pendant un retry, ne pas le confondre avec un résultat courant |
| Retry | `error_code` + `next_attempt_at` ; failed ou bail expiré → `retryable_error` ; retry déclenché uniquement par POST/queue déjà autorisée |

`already_queued`, `busy`, `cooldown` sont des résultats de demande, pas des
statuts finaux de cache. `complete` et `empty` décrivent un cache reconnu ;
`empty` n'est jamais déduit d'une erreur. `deferred` reste interne worker.
POST conserve HTTP 202 pour ces réponses ; 404 inaccessible, 422 ID invalide,
503 indisponibilité queue. GET reste exclusivement Mongo, sans writes/Redis.

### Diagnostic factuel D — Intégrité et périmètre

Laps sur `garmin_activities` uniquement. Writer laps ne touche ni phases,
ni `activity_details`, ni `activity_day`. Ingestion suivante utilise `$set`
en excluant les deux sous-documents laps ; tests de préservation conservés.
Cache valide évite provider/GCCLI en POST, GET et redelivery. Aucun backfill,
automatisation d'acquisition, priorité de jobs ou calcul physiologique ajouté.
`intensity_type` reste une valeur source opaque, sans conversion en zone.

La stratégie future (queue GCCLI/worker Railway existants, enrichissement
différé et priorité des syncs principales, moteurs canoniques) n'est pas
implémentée dans ce correctif.

### Fichiers corrigés et tests réellement exécutés

- `backend/jobs/queue.py` : enqueue laps atomique et validation des types.
- `backend/garmin/activity_laps.py` : différer une livraison fenced lorsque
  le cache courant n'est pas encore disponible.
- `backend/tests/test_activity_laps_queue_pr332.py` : cinq tests ciblés,
  adaptation du point d'injection de panne de l'enqueue passé dans Lua.
- Ce rapport : diagnostic et protocole runtime.

Depuis `backend/` (`/home/runner/work/sauvegarde260708/sauvegarde260708/backend`) :

1. `python -m pytest tests/test_activity_laps_queue_pr332.py -k
   'mongo_reservation_crash or expired_running_post' -q` avant correctif :
   **1 passed, 1 failed** (perte de livraison démontrée).
2. `python -m pytest tests/test_activity_laps_queue_pr332.py -k
   'interruption_cannot' -q` avant correctif : **1 failed**
   (pending sans livraison démontré).
3. `python -m pytest tests/test_activity_laps_pr332.py
   tests/test_activity_laps_queue_pr332.py tests/test_activity_details_pr321.py
   tests/test_activity_details_delayed_redis_c321.py
   tests/test_typed_splits_chronology_c321.py
   tests/test_garmin_queue_backfill_pr197.py -q` :
   **244 passed**, 3 avertissements de dépréciation, 18,33 s.
4. `python -m pytest tests/test_garmin_activity_normalization_pr02.py
   tests/test_garmin_data_layer.py tests/test_garmin_daily_metrics_pr03.py
   tests/test_garmin_phased_sync_pr07a.py tests/test_garmin_deep_sync.py -q` :
   **96 passed**, 0,88 s.
5. `python -m pytest tests/test_garmin_user_connection.py -q` :
   **8 passed**, 0,74 s.
6. Tentative supplémentaire du groupe (3) avec `test_reliable_queue.py`
   avant l'atomicité Redis finale : **241 passed, 3 erreurs** (fixture `r`
   inexistante dans ce module prévu pour un runner manuel).
   Ce module n'a pas été modifié ni exécuté contre des services externes.

Premiers essais : pytest absent, incompatibilité PyOpenSSL système puis deux
tests skipped faute de redis-server. Runtime restauré hors dépôt et Redis
local installé avant les reproductions effectives ci-dessus. Aucun skip
dans les 244 tests finaux. Versions test : Python 3.12.3, pytest 9.1.1,
xdist 3.8.0, Redis client 8.1.0/server 7.0.15, Motor 3.7.1,
PyMongo 4.18.3, FastAPI 0.143.0, HTTPX 0.28.1. Pas de dépendance du dépôt
changée ; versions déployées exactes à revalider.

### Procédure reproductible Emergent — cible 24346252881

À exécuter avec les accès existants et autorisation explicite ; **non exécutée
par Copilot**. Ne pas afficher JWT, compte Garmin, user-id, HOME personnel,
GPS ou payload brut dans le rapport public.

1. Relever SHA backend **et** worker Railway ; vérifier version identique et
   queue existante. Authentifier le propriétaire dans la session existante ;
   vérifier le document par user/source/external_id `24346252881`.
2. En lecture seule conserver une comparaison privée des sous-documents
   `activity_details`, `activity_day` et résumé ; ne publier que
   « identiques/non identiques ». Relever cache laps version/statut/fetched_at.
3. GET `/api/garmin/activities/24346252881/laps` avec cette authentification.
   Observer les logs existants : **aucune commande GCCLI** et aucune write.
   Sans authentification → 401/403 ; autre utilisateur → 404.
4. Si cache déjà valide, vérifier directement 22 laps, dernier lap
   `lap_index=22`, `order=21`, `distance_m≈274.53`, sans purger/refetch.
   Sinon POST cette route une fois et répéter immédiatement : un seul job
   autorisé, GET queued/running. Attendre l'exécution du worker existant,
   sans lancer une commande GCCLI manuelle en parallèle.
5. Après complete, attendre **22 laps** et dernier environ **274,53 m**
   pour cette activité précise (référence #331, pas généralisation).
   Vérifier index/ordre et valeurs : maxSpeed 3.191 et averageSpeed 3.196
   du dernier lap conservés. Ne pas attendre 22 depuis la fixture locale
   de deux exemples ni inventer des laps manquants.
6. Vérifier absence des champs GPS/strideLength/connectIQ/lengthDTOs,
   source Garmin/endpoint splits/version 1 ; comparer données existantes
   privées avant/après : aucun effacement phases/local day/résumé.
7. Refaire POST (attendu `cached`) et plusieurs GET : fetched_at et laps
   inchangés, **zéro acquisition supplémentaire** dans les logs.
8. Sur la prochaine sync ordinaire déjà autorisée, comparer encore les
   données existantes/laps. Ne pas déclencher un réimport ou backfill.
9. Pannes/concurrence dans un environnement isolé seulement : reproduire
   arrêt avant enqueue, interruption worker, expiration de bail, POST
   concurrent et redelivery ; contrôler reprise et anciennes écritures
   refusées. Ne pas modifier leases/tokens/queue de production pour tester.
10. Publier SHA exacts, statuts, compte d'appels (sans identité), nombre de
    laps, distance finale et booléens de préservation. Si 22/274,53 diffèrent,
    conserver la source, diagnostiquer et garder **HOLD**, pas corriger les
    valeurs pour satisfaire l'attendu.

### Risques résiduels

Mongo/Redis restent deux systèmes sans transaction commune : interruption
avant enqueue laisse queued jusqu'à 900 s (pas un blocage illimité).
Crash serveur Redis/durabilité dépend de l'AOF/config déployée ; l'atomicité
Lua ne constitue pas une garantie de persistance production.
Lookup de contention linéaire inchangé. Les limites/verrous/watchdog hérités
ne sont pas refactorisés. Mongo et provider simulés, Redis local réel :
tests locaux ≠ validation de production. Aucun appel Garmin réel ni Mongo
production, aucun enrichissement automatique/backfill. Audit C332 requis.

---

## Références exactes et préconditions

- Base : `copilot/dev`, `6c2f986074a9f84def0b9ad73e097d0e16406d06`.
- Branche head : `copilot/garmin-lap-acquisition-persistence-v1`.
- Le SHA head exact est donné dans la description finale de la PR (un rapport
  commité ne peut contenir son propre SHA).
- #330 et #331 vérifiées mergées dans `copilot/dev` via GitHub et l'historique
  Git ; base locale identique au head de cette branche au précontrôle.
- État Git initial propre : aucune modification préexistante locale.
- Fixture et rapport #331 présents et lus. La fixture fournit **deux exemples**,
  pas les 22 laps bruts. Les tests reconstruisent une enveloppe contenant ces
  deux exemples avec leurs index originaux 1/22 et ordres 0/21.
- Rapport historique #331 utilisé comme preuve de payload, non comme état
  actuel du code. Ses suggestions `min_hr`/`trigger_mode`/`stride_length` ne
  sont pas reprises dans le contrat V1.

## Architecture et fichiers

Flux : POST JWT → vérification `(user_id, source=garmin, external_id)` →
réservation Mongo `queued` → **queue Redis existante** → **sync_worker
existant** → provider HOME/compte du propriétaire → `gccli activity splits
<id> -j` → normalisation → écriture Mongo conditionnelle.

GET JWT → vérification de propriété → lecture Mongo uniquement. Aucun appel
Redis, provider ou Garmin ; aucune écriture depuis GET.

- `backend/garmin/activity_laps.py` : contrat, validation, réservation et cache.
- `backend/garmin/runner.py` : commande `activity splits`, une tentative.
- `backend/garmin/providers/base.py` et `gccli_provider.py` : capacité ciblée.
- `backend/jobs/queue.py` : type `ACTIVITY_LAPS`, réutilisation des primitives
  fiables et du stockage différé existants.
- `backend/workers/sync_worker.py` : dispatch et protections ciblées partagées.
- `backend/api/garmin.py` : POST/GET authentifiés.
- `backend/garmin/service.py` : exclusion des champs d'enrichissement du `$set`
  des syncs, même si un provider les fournit.
- `backend/tests/test_activity_laps_pr332.py` : contrat, API et Mongo simulée.
- `backend/tests/test_activity_laps_queue_pr332.py` : queue/worker et Redis local.
- Ce rapport.

Aucune nouvelle collection, queue indépendante, dépendance applicative ou
processus worker. Aucun changement frontend, WA V2, Training V2, Coach,
classification ou entitlement.

## Contrat normalisé définitif

`activity_laps` contient `schema_version=1`, `source="garmin"`,
`endpoint="splits"`, `status="complete"|"empty"`, `fetched_at` UTC et `laps`.
Chaque lap contient exactement les champs suivants :

| Source Garmin | Cible |
|---|---|
| lapIndex | lap_index |
| messageIndex | order |
| startTimeGMT | start_time_gmt |
| distance | distance_m |
| duration | duration_s |
| movingDuration | moving_duration_s |
| elapsedDuration | elapsed_duration_s |
| averageSpeed | average_speed_mps |
| averageMovingSpeed | average_moving_speed_mps |
| maxSpeed | max_speed_mps |
| averageHR | average_hr |
| maxHR | max_hr |
| averageRunCadence | average_cadence_spm |
| maxRunCadence | max_cadence_spm |
| elevationGain | elevation_gain_m |
| elevationLoss | elevation_loss_m |
| maxElevation | max_elevation_m |
| minElevation | min_elevation_m |
| intensityType | intensity_type |

Les champs métriques/heure/intensité manquants ou explicitement nuls restent
`null`. Index et ordre sont requis pour identifier les laps sans en inventer.
Les valeurs sources sont conservées, sans arrondi, cadence doublée, conversion
de distance en kilomètres ou correction de vitesse. `intensity_type` est une
chaîne native opaque, pas une intensité physiologique.

Exclusions par allowlist : GPS, connectIQMeasurement, lengthDTOs, eventDTOs,
strideLength, min_hr, trigger_mode, calories et tout champ brut non requis.

### Règles défensives non établies par l'échantillon #331

- Enveloppe objet avec `activityId` **int positif** égal à la cible.
  `lapDTOs` doit être une liste ; `[]` est un succès vide reconnu.
  `null`, clé absente, type incorrect, stdout vide/non JSON : erreur,
  **jamais** cache négatif. `eventDTOs` facultatif, liste s'il est présent.
- Maximum 1000 laps par enveloppe, erreur au-delà, aucune troncature.
- Chaque lap est un objet, `lapIndex` entier positif et `messageIndex` entier
  non négatif ; booléens/floats refusés pour ces identifiants.
- Les deux index sont strictement croissants dans l'ordre reçu. Doublons,
  inversion ou contradiction entre index et ordre : erreur. Les trous sont
  acceptés : pas de renumérotation ni obligation de séquence contiguë.
- Si un lap fournit `activityId`, il doit être le même entier natif.
- Mesures : uniquement int/float JSON finis, pas booléen ou chaîne numérique.
  Valeurs négatives refusées sauf altitudes absolues min/max, qui peuvent être
  sous le niveau de la mer. Zéro est conservé. Toute valeur invalide invalide
  l'enveloppe entière, plutôt que perdre silencieusement un lap.
- Heure fournie : ISO avec `T`, UTC explicite ou GMT sans timezone tel
  qu'observé ; offset non UTC refusé. Chronologie non décroissante entre les
  heures disponibles. Chaîne source conservée. Pas d'heure inventée.
- Intensité fournie : chaîne non vide, maximum 64 caractères, aucune liste
  fermée de valeurs supposées.
- Pas de cohérence physiologique ni de comparaison max/moyenne. La petite
  inversion réelle `maxSpeed=3.191 < averageSpeed=3.196` reste inchangée.

### Identifiants et isolation

Entrées API/queue : entier positif, chaîne numérique ou `garmin-<numérique>`
normalisés en chaîne décimale sans zéros initiaux (maximum 30 chiffres).
Enveloppe Garmin : entier natif requis. Les clés Mongo existantes ne sont
jamais migrées ; recherche de `external_id` canonique chaîne seulement.
Les anciens documents stockés autrement ne sont pas implicitement rattachés.
Aucun user_id déduit de l'ID Garmin ; chaque requête et écriture est filtrée
sur le propriétaire JWT/job et `source="garmin"`.

## API et états

- `POST /api/garmin/activities/{activity_id}/laps` : HTTP 202, acquisition
  ciblée. Statuts `queued`, `already_queued`, `running`, `cached`, `cooldown`,
  ou `busy`. Une course de réservation relit Mongo pour rendre l'état courant.
- `GET /api/garmin/activities/{activity_id}/laps` : HTTP 200,
  `activity_laps`, `cache_current`, `fetch_status`, `error_code`,
  `next_attempt_at`. États `not_requested`, `queued`, `running`, `complete`,
  `empty`, `retryable_error`.
- Authentification requise ; 404 pour activité absente/inaccessible, 422 pour
  ID invalide ; POST 503 si queue indisponible.

La réservation Mongo `queued` précède l'enqueue : une tâche en attente
n'est pas annoncée `not_requested` par GET après un POST réussi. Si le slot
par utilisateur appartient à une autre activité, POST indique `busy`, pas
un faux succès ciblé ; une erreur technique minimale est stockée.
La résolution d'un job Redis préexistant a lieu au POST seulement.
Un état queued/running dont le bail a expiré est exposé comme erreur
récupérable `lease_expired`, sans que GET déclenche une récupération.

## Cache, concurrence et idempotence

- Stockage indépendant `garmin_activities.activity_laps` /
  `activity_laps_fetch`, distinct de `activity_details` et de `no_data`.
- Cache positif et négatif valides tant que `schema_version=1`. Pas de TTL
  des résultats : activité historique supposée stable. Évolution du contrat
  via bump de version ; pas de refresh forcé/backfill en V1.
- Reservation atomique Mongo par activité/utilisateur, token UUID et bail
  900 s (même constante que l'infrastructure #321).
- Une réservation queued peut être prise par le worker ; un running non
  expiré ne peut pas être repris. Les résultats/erreurs sont conditionnés au
  token : un worker remplacé ne peut écraser le nouveau résultat.
- Échec : ancien cache conservé, `activity_laps_fetch=failed`, code générique
  sans stdout/stderr/payload personnel, prochain essai après 300 s.
- Un seul slot laps Redis par utilisateur, distinct du slot typed-splits.
  Les limites globales et le verrou d'exécution par utilisateur restent
  communs aux syncs et enrichissements.
- FIFO fiable BLMOVE → processing → ACK ; redelivery et watchdog existants.
  Les jobs différés utilisent les zset/hash déjà présents pour #321, sans
  deuxième système. Relivraison après succès utilise le cache, sans refetch.
- Retries du worker bornés par `SYNC_MAX_RETRIES` (défaut 3) ; commande
  GCCLI à tentative unique, timeout ≤60 s ; marge worker ciblée ≥65 s.
  Déférence jusqu'au bail/cooldown sans consommer un nouvel essai.
- Syncs ultérieures utilisent `$set` de résumé sans remplacer l'enrichissement.
  Aucune écriture de `activity_day`, phases ou champs locaux par le pipeline laps.

## Tests exécutés

Premier essai avec le Python système : échec avant collecte
`No module named pytest` ; ce n'est pas un test réussi.

Depuis `backend/`, avec `python -m pytest` et les deux workers configurés :

- `tests/test_activity_laps_pr332.py -q` : **60 passed**, 2 avertissements
  de dépréciation Starlette/Pydantic ; réexécuté après corrections de cooldown
  et ajout de la concurrence POST.
- `tests/test_garmin_activity_normalization_pr02.py tests/test_garmin_data_layer.py
  tests/test_garmin_daily_metrics_pr03.py tests/test_garmin_phased_sync_pr07a.py
  tests/test_garmin_deep_sync.py -q` : **96 passed**.
- `tests/test_garmin_user_connection.py -q` : **8 passed**.
- Essai groupé initial des neuf modules Garmin (les cinq précédents plus
  user_connection, queue_backfill_pr197, queue_health_admin et
  vo2max_history_endpoint) : **103 passed, 1 failed, 3 erreurs de collecte**.
  Import Redis pollué par les stubs de tests, dépendance `email_validator`
  absente pour les modules important `server`, et bootstrap global échouant
  dans le groupe (8/8 réussis en isolation). Aucune modification des tests
  existants ni prétention que ce groupe est vert.
- `git diff --check` : réussi.
- Lint tenté : `python -m flake8 --select=E9,F63,F7,F82` sur les fichiers
  Python du contrat/provider/API/persistance/tests laps : non exécuté,
  environnement sans module `flake8`. Aucun nouveau linter ajouté.

Validation de l'agent queue depuis la racine :

`TMPDIR="$PWD/.test-runtime" PYTHONPATH=backend python -m pytest -q
--basetemp="$PWD/.test-runtime/pytest"
backend/tests/test_activity_laps_queue_pr332.py
backend/tests/test_activity_details_pr321.py
backend/tests/test_activity_details_delayed_redis_c321.py
backend/tests/test_garmin_queue_backfill_pr197.py
backend/tests/test_typed_splits_chronology_c321.py` :
**164 passed**, un avertissement existant. Redis local isolé, pas de Mongo
réel ni Garmin.

Après réconciliation de cible et normalisation d'ID, même commande cinq
modules : **174 passed**, un avertissement existant.
Après finalisation de la réservation/lookup laps dans un seul appel Lua et
ajout des tests d'intégration POST + vrai Redis local + Mongo simulée :

`TMPDIR="$PWD/.test-runtime" PYTHONPATH=backend /usr/bin/python -m pytest -q
--basetemp="$PWD/.test-runtime/queue-only-pytest"
backend/tests/test_activity_laps_queue_pr332.py` : **38 passed** (4,92 s).
Ces derniers tests couvrent aussi queued/processing/delayed/slot inconnu,
POST répété, autre cible busy et réconciliation de bail expiré.

Le runtime Python de test a été restauré hors fichiers suivis ; aucune
dépendance du dépôt changée. Principales versions réellement utilisées :
Python 3.12.3, pytest 9.1.1, xdist 3.8.0, Redis client 8.1.0, Motor 3.7.1,
PyMongo 4.18.2, FastAPI 0.110.1, HTTPX 0.28.1. Cela diffère de certaines
versions épinglées du déploiement : non-régression runtime exacte à confirmer
dans Emergent. Les artefacts de test ne sont pas suivis/commités.

Validation automatique exécutée sur les commits d'implémentation :
**CodeQL Python : 0 alerte**. Revue automatique demandée mais **indisponible**
(modèle configuré non présent dans le registre) : ne constitue pas une revue
réussie malgré le libellé de succès retourné par l'outil. Revue indépendante
rubber-duck effectuée ; corrections du cooldown, relecture CAS et
réconciliation même cible/autre cible intégrées. Audit C332 toujours requis.
Scans de secrets : aucun secret détecté dans les fichiers modifiés.
Dernière validation du head `77125166cb6f98919006e9042159f8df62392b68` :
revue automatique toujours indisponible et **CodeQL interrompu par timeout**.
Les 0 alertes précédentes concernent les commits antérieurs, pas une analyse
finale terminée de ce head. Revalidation sécurité complète requise lors de
l'audit C332 ; aucun succès final CodeQL revendiqué.

## Risques résiduels et limites

- Payload validé sur une seule activité : autres profils/multisport et
  champs particuliers peuvent échouer volontairement en mode fail-closed.
- Cadence/altitudes et certaines vitesses conservent les unités inférées
  du rapport #331 ; aucune nouvelle preuve d'unité produite.
- Mongo et Redis ne partagent pas de transaction : crash entre réservation
  Mongo et enqueue laisse `queued` jusqu'à expiration, puis POST permet
  reprise. GET expose l'expiration, ne tente jamais de réparer.
- Un job queued durablement plus longtemps que le bail peut être exposé
  expiré alors qu'il reste dans Redis ; POST réconcilie sans fetch Garmin.
- Pas de TTL/refresh de cache : modifications ultérieures côté Garmin ne
  sont pas automatiquement détectées en V1.
- Mongo simulée dans les tests : comportement atomique réel et déploiement
  distribué doivent être audités dans Emergent après merge autorisé.
- Limites Redis/per-user/global et watchdog hérités de #321, pas remplacés.
- La réconciliation POST d'un slot occupé inspecte les livraisons de la queue,
  processing et stockage différé ; coût linéaire des listes en cas de contention.
  GET n'effectue jamais cette inspection.
- Aucun appel Garmin réel ni écriture Mongo de production depuis Copilot.

## Protocole runtime Emergent après merge autorisé

**Attendre audit C332 et autorisation ; ne pas merger automatiquement.**

1. Vérifier SHA base/head/merge et version backend/worker identique, routes
   présentes et services Redis/Mongo disponibles ; aucun nouveau worker.
2. Sur une activité déjà détenue par l'utilisateur connecté, relever en
   lecture seule les caches laps/phases, `activity_day`, queue et sessions.
   Ne pas importer/backfiller d'autres activités.
3. GET laps avant POST : pas d'exécution GCCLI, pas d'écriture, état initial
   exact. Vérifier 401/403 sans JWT et 404 avec un autre utilisateur.
4. POST de la cible autorisée ; répéter immédiatement. Vérifier un seul
   job ciblé et GET `queued`/`running` sans fetch depuis GET. Tester aussi
   une autre cible : résultat `busy` si le slot est occupé.
5. Autoriser une seule acquisition réelle `activity splits` par le worker
   existant, HOME/compte correct. Vérifier enveloppe, normalisation et
   persistance de l'ensemble réellement reçu (ne pas attendre deux laps
   ou supposer 22 pour toute activité).
6. Vérifier les unités/valeurs sans correction, index/ordre natifs, absence
   GPS/strideLength/champs exclus et diagnostics sans secrets. Vérifier
   phases, WA V2, Training/Coach et `activity_day` inchangés.
7. GET/POST après succès : cache courant, aucune nouvelle commande.
   Cache vide uniquement sur enveloppe réellement valide vide, jamais sur
   erreur/session indisponible ; ne pas fabriquer un cas réel vide.
8. En environnement de validation isolé uniquement, simuler crash, lease
   expiré, doublon de livraison et échec ; observer retries bornés,
   déférence, reprise et refus d'écriture d'un ancien token.
9. Une sync ordinaire autorisée ultérieure ne doit pas supprimer les laps
   ni phases/local day. Aucun reimport massif, aucun backfill.
10. Publier preuves exactes SHA, commandes, appels, états et tests réellement
    exécutés. Ne pas présenter les scénarios non exécutés comme réussis.
