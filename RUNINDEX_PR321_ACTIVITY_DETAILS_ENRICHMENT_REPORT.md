# RUNINDEX — PR321 — Enrichissement ciblé des activités

> Les sections 1–9 ci-dessous sont le bilan historique de la première livraison.
> Leur contrat provisoire et la stratégie de différé sont remplacés par la section
> **C321 — Corrections après audit runtime Emergent**, en fin de rapport.
> Aucun de ces bilans n'est une validation runtime Garmin effectuée dans GitHub.

## 1. Références Git et périmètre

- Base canonique : `copilot/dev`.
- HEAD de départ vérifié par `git fetch origin copilot/dev` :
  `d755a80ad9e47ec7cd28e62c03fd28293e41f27c`.
- La branche de travail fournie par GitHub, `copilot/enrichir-activites-avec-tructures`,
  part exactement de ce HEAD (merge-base identique). Aucun merge/rebase effectué.
- Premier HEAD d'implémentation testé : `21db77cdc622e992ffb539738068e2ecbd6ef2c5`.
  La revue indépendante a ensuite conduit à préserver les jobs différés
  pendant un bail/cooldown ; les tests corrigés sont indiqués ci-dessous.
  Le commit documentaire ultérieur contient ce rapport ; le HEAD final est indiqué
  dans la description de PR, pour éviter une référence circulaire.
- Objectif unique : observation de phases structurées, sans nouveau moteur.
- Aucun déploiement, modification Emergent, appel Garmin réel ou écriture MongoDB réelle.
- « PR321 » est la référence du besoin ; le numéro GitHub est attribué par GitHub.

## 2. Audit architectural obligatoire

Documents lus : `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`,
`GARMIN_DATA_LAYER_PR01_REPORT.md`, `GARMIN_ACTIVITY_NORMALIZATION_PR02_REPORT.md`,
`GARMIN_PHASED_SYNC_PR07A_REPORT.md`. Les rapports historiques restent des preuves
datées, non une description garantie du code actuel.

Code inspecté : `backend/garmin/{runner.py,data_layer.py,service.py,domain_adapter.py,backfill.py}`,
`backend/garmin/providers/{base.py,gccli_provider.py}`,
`backend/workers/event_worker.py`, `backend/workout_analysis_v2_service.py`,
`backend/workout_analysis_v2.py`, `backend/training_v2/domain_activity.py`,
`backend/training_v2/performed_workout.py`, plus API, file et worker de synchronisation.

Constats et réponses aux six points de l'audit :

1. **Contrat historique** : les résumés normalisés possèdent `external_id`,
   `source`, mesures historiques, `raw_payload` et `garmin_activity`.
   Un sous-document frère `activity_details` évite tout changement de ce modèle.
2. **Non-écrasement** : `_ingest_activities` utilise déjà `$set`, pas un remplacement.
   Il ignore désormais explicitement les deux champs réservés à l'enrichissement,
   même si un fournisseur les inclut accidentellement. Les synchronisations
   complètes/incrémentales n'appellent jamais la récupération de phases.
3. **Infrastructure réutilisable** : HOME GCCLI par utilisateur et compte lié via
   la factory, erreurs `GccliError`, commandes sans shell, timeout borné,
   file Redis fiable, worker indépendant, verrou utilisateur, plafond global,
   watchdog et ACK existants. Aucun nouveau worker, service externe ou collection.
4. **Frontière métier** : `ActivityPhase` est un modèle neutre dans
   `backend/activity_phases.py`. Seul le connecteur connaît les champs natifs.
   Les adaptateurs DomainActivity/ObservedActivity et leurs consommateurs restent
   inchangés ; les phases ne sont pas injectées dans leurs algorithmes.
5. **Historique/fournisseurs** : seules les activités existantes identifiées par
   `(user_id, external_id, source=garmin)` sont enrichies, sans upsert. La méthode
   facultative de Provider retourne `None` pour un fournisseur non compatible.
   Les activités anciennes restent utilisables sans détails.
6. **Déclenchement** : POST explicite ciblé, GET Mongo-only ; aucune récupération
   à l'affichage, au backfill ou à la synchronisation automatique.

`garmin_activities` demeure l'autorité d'ingestion ; `workouts` est dérivé par
l'event worker/backfill. « Immutable » signifie ici absence de reconstruction
des observations par la couche produit : le code existant met déjà les résumés
à jour par upsert. L'ajout ne réémet pas `ACTIVITY_CREATED`, ne modifie pas
`workouts`, et n'invalide pas ses caches puisqu'aucun consommateur actuel de
ces phases n'y est ajouté. Le GET spécifique lit l'autorité persistée.

Workout Analysis V2 utilise `km_splits` pour ses analyses d'allure : les nouvelles
phases temporelles ne doivent pas alimenter cette propriété. Training reste
l'autorité de prescription, Garmin l'autorité de l'observation effectuée.

## 3. Choix et fichiers modifiés

- `backend/activity_phases.py` : contrat neutre des phases observées.
- `backend/garmin/data_layer.py` : normalisation pure, bornée, sans classification.
- `backend/garmin/runner.py` : commande ciblée et option d'un seul essai.
- `backend/garmin/providers/base.py` : capacité facultative rétrocompatible.
- `backend/garmin/providers/gccli_provider.py` : récupération liée au compte.
- `backend/garmin/activity_details.py` : cache, réservation atomique, persistance.
- `backend/garmin/service.py` : protection des champs d'enrichissement.
- `backend/jobs/queue.py` : job avec un seul identifiant d'activité.
- `backend/workers/sync_worker.py` : dispatch sous protections existantes.
- `backend/api/garmin.py` : POST/GET ciblés authentifiés.
- `backend/tests/test_activity_details_pr321.py` : tests synthétiques et doubles mémoire.
- Ce rapport.

Diff de première implémentation : 11 fichiers, 715 insertions, 7 suppressions,
avant la correction revue des jobs différés.
Diff consultable dans la PR ou par comparaison avec le SHA de base ci-dessus.
Aucun changement frontend, Training V2, Readiness, Score, Performance Curve,
Coach/RAG, algorithme Workout Analysis V2, `hr-zones` ou `activity details`.

## 4. Contrat des données ajoutées

Sous-document frère `activity_details` :

| Champ | Contrat |
| --- | --- |
| `schema_version` | `1`, version du contrat/cache |
| `status` | `complete` ou `no_data` après réponse reconnue |
| `source`, `endpoint` | `garmin`, `typed-splits` |
| `fetched_at` | timestamp UTC de récupération réussie |
| `phases` | liste dans l'ordre reçu ; aucune agrégation/réinterprétation |

Chaque phase : `order` (position zéro-indexée), `native_type`, `phase_type`,
`duration_s`, `distance_m`, `average_speed_mps`, `average_hr`, `max_hr`, `min_hr`,
`source`. Tous les nombres absents/invalides restent `None`; zéro reste zéro.
Pas d'allure inventée : la vitesse disponible est conservée.

Mapping limité : `INTERVAL_ACTIVE→effort`, `INTERVAL_RECOVERY→recovery`,
`WARMUP→warmup`, `COOLDOWN→cooldown`, autres chaînes→`unknown` avec type natif
conservé. Aucun VO₂max/LT1/LT2/Z5 déduit d'un nom de séance.

**Contrat d'entrée provisoire, non vérifié sur JSON réel** :
liste d'objets ou enveloppe `splitDTOs`, champs `splitType`, `duration`,
`distance`, `averageSpeed`, `averageHR`, `maxHR`, `minHR`.
Les unités reprennent celles déjà utilisées par les résumés Garmin ; leur
application aux typed-splits doit être vérifiée par Emergent.
L'audit GitHub n'a trouvé aucune fixture typed-splits vérifiée. Les tests
identifient explicitement toutes leurs données comme **synthétiques**.
Enveloppe inconnue, ligne invalide, plus de 1000 phases ou type natif dépassant
128 caractères : échec sans cache négatif. Une liste reconnue vide est `no_data`.
Les clés arbitraires/raw JSON ne sont pas persistées.

Sous-document technique distinct `activity_details_fetch` :
état `running`/`failed`/`complete`, bail UTC `next_attempt_at`, jeton de fencing
pendant la récupération, code d'erreur générique. Le GET ne divulgue pas le jeton,
les credentials, les sorties GCCLI ni l'état interne complet.

## 5. Récupération ciblée et protections

- `POST /api/garmin/activities/{activity_id}/phases` : réponse 202 avec
  `queued`, `already_queued`, `cached` ou `cooldown`.
- `GET` au même chemin : détails persistés ou `None`, `fetch_status`, `error_code`.
- Identité issue exclusivement de l'utilisateur authentifié ; portée Garmin
  et propriétaire vérifiés avant enqueue et de nouveau dans le worker.
- 404 pour activité inexistante/non possédée/non Garmin, 422 pour identifiant
  non numérique (1–30 caractères), 503 si la récupération ne peut être enqueued.
- Les routes héritent de la politique d'accès `/api/garmin/` existante.
- Un seul enrichissement en attente par utilisateur, sans liste/bulk/force.
  Deux activités du même utilisateur ne sont pas traitées simultanément ;
  un `already_queued` implique de réessayer explicitement après le job courant.
- Commande GCCLI : `activity typed-splits <id> -j`, un compte utilisateur requis.
  Un seul essai par commande ciblée ; la file est propriétaire des retries.
  Les retries des autres commandes restent inchangés.
- Timeout commande existant ≤60 s ; marge worker ciblée d'au moins 65 s.
  Verrou utilisateur Redis de 120 s et plafond global existants réutilisés.

## 6. Cache et persistance

- Mise à jour `$set` des seuls champs d'enrichissement, jamais d'upsert.
- Cache durable versionné pour `complete` **et** `no_data` ; pas de TTL positif,
  pas de bouton force-refresh dans cette PR.
- Réservation Mongo atomique de l'activité : bail de 900 s, jeton unique et
  re-vérification du cache dans le filtre de réservation.
- Chaque écriture terminale compare le jeton : un ancien job ne peut écraser
  la réservation d'un autre. Crash/annulation : reprise explicite après le bail.
- Erreur : détails antérieurs préservés, statut technique `failed`, délai
  de 300 s avant nouvelle tentative. Le retry de file pendant ce délai est
  différé par `not_before`, sans ACK ni consommation de tentative supplémentaire.
  Le même mécanisme conserve un job récupéré après crash jusqu'à expiration
  du bail. La file existante n'a pas de primitive delayed-job : le worker
  réenfile le job avec une pause bornée de 5 s, sans verrou utilisateur.
- Redis pending des autres jobs inchangé (300 s). Le job ciblé possède son
  propre pending de 1800 s, supérieur au bail de 900 s, rafraîchi lorsqu'il
  est traité/différé. Refresh/libération Lua compare atomiquement le job_id :
  un ancien job ne supprime jamais le pending d'un nouveau.
  Livraison fiable at-least-once ; la réservation Mongo
  protège aussi contre expiration du pending, redelivery et requêtes concurrentes.
- Aucun nouveau schéma/index/collection ni migration ou suppression historique.

## 7. Tests GitHub : commandes et résultats exacts

Python 3.12.3 ; venv temporaire ; dépendances de test existantes restaurées,
sans modifier `requirements.txt` ni ajouter un outil au projet.
Depuis `backend/`, `PYTHONPATH=.` et `python` du venv :

| Commande `python -m pytest … -q` | Résultat |
| --- | --- |
| `tests/test_activity_details_pr321.py` | **47 passed, 1 warning**, 0.80 s |
| `tests/test_garmin_user_connection.py` (processus isolé) | **8 passed**, 0.60 s |
| `tests/test_garmin_queue_backfill_pr197.py tests/test_garmin_phased_sync_pr07a.py tests/test_garmin_deep_sync.py` | **39 passed**, 10.75 s |
| `tests/test_garmin_data_layer.py tests/test_garmin_activity_normalization_pr02.py tests/test_training_v2_domain_activity.py tests/test_performed_workout_pr230.py tests/test_mongo_garmin_boundary_pr137.py` | **181 passed, 1 failed**, 0.64 s |

Les deux workers `-n 2 --dist loadscope` viennent de `backend/pytest.ini`,
inchangé. **275 tests passés, un échec préexistant** sur ces exécutions finales.

L'échec `test_g_server_uses_boundary` cherche dans `server.py` un appel exact
`build_recent_training_response(domain_activities...)` absent au HEAD de base.
`git show d755a80…:backend/server.py` ne trouve que l'import de cette fonction.
Ni `server.py` ni ce test n'ont été modifiés ; le problème reste hors périmètre.

Essai initial combinant cinq suites : 86 passed, 1 failed dans
`test_bootstrap_provider_still_uses_env_account`. Des tests existants remplacent
`config.secrets` dans `sys.modules`, alors que le provider déjà importé conserve
son binding : collision d'ordre de collecte. La suite isolée passe (8/8).
Aucun test existant édité pour masquer cette collision.
Premier essai avant restauration complète : 148 passed, 1 erreur de collecte
(`cryptography` absent), puis dépendance existante restaurée.

Couverture nouvelle : effort/récupération/échauffement/retour au calme,
types inconnus, absence/zero/NaN/inf/bool, enveloppes incompatibles, GCCLI
timeout/non-JSON/exit simulés, compte requis, isolation, cache vide/idempotence,
non-écrasement après sync sans événement créé, bail concurrent/fencing,
contrats DomainActivity/ObservedActivity inchangés, file bornée et panne Redis,
dispatch/ACK/verrou worker, API ASGI JWT requis, GET sans appel et 404/422/503.

Autres vérifications :
- `python -m flake8` des 11 fichiers Python changés,
  `--select=E9,F63,F7,F82` : exit 0.
- `python -m compileall -q` sur les modules changés : exit 0.
- Import `api.garmin` : OK ; `git diff --check` : exit 0.
- Scan de secrets des fichiers Python changés : aucun secret.
- CodeQL Python : **0 alerte**.
- Revue automatisée appelée, mais moteur indisponible (modèle absent du
  registre) malgré l'étiquette « Success » de l'outil : ce n'est pas une revue
  validée. Une revue indépendante supplémentaire a identifié l'ACK incorrect
  d'un job encore sous bail/cooldown. Corrigé par différé fiable et testé
  (pas d'ACK, pas de consommation des retries, conservation de `not_before`).
  Sa seconde passe a identifié l'expiration et la libération non possédée du
  pending partagé ; corrigées par TTL ciblé et comparaison Lua du job_id,
  avec test de protection contre suppression du pending d'un nouveau job.

## 8. Validations impossibles ici et risques résiduels

Non validés : login/token Garmin réel ; JSON de l'activité `24671804067` ;
Mongo/Redis en production ; watchdog multi-processus réel ; runtime Emergent ;
frontend ou rendu après déploiement. Pas de suite intégrale backend/frontend
ni promesse de connexion réelle.

Risques : enveloppe/type natif/unité réels différents du contrat provisoire
(échec fermé à ajuster après preuve) ; cache `no_data` durable jusqu'à changement
de version ; GET feed historique éventuellement ignorant ces nouveaux détails
(le GET spécifique est l'autorité) ; un job différé occupe brièvement un slot
local mais pas de slot global/verrou utilisateur ; limites/index/latence Mongo et comportement
des verrous existants à confirmer en runtime. Les détails ne sont pas encore
consommés par les moteurs ou le frontend : c'est volontaire.

## 9. Transmission à Emergent : gate runtime après revue et merge autorisé

1. Fournir le diff et ce rapport pour revue ; aucun merge automatique.
2. Emergent seul capture une réponse réelle anonymisée de
   `gccli activity typed-splits 24671804067 -j` avec compte correctement isolé.
3. Comparer enveloppe, `splitType`, métriques/unités et ordre à la normalisation ;
   confirmer les 29 splits, 4 efforts 240 s, 4 récupérations 180 s, échauffement
   et retour au calme annoncés par l'audit runtime précédent, sans les présumer.
4. Si divergence : ne pas considérer le gate validé ; fournir fixture vérifiée
   anonymisée et corriger le contrat dans une revue dédiée avant utilisation.
5. Contrôler POST ciblé→worker→Mongo, puis GET sans GCCLI ; redemander le même
   identifiant, simuler double POST/redelivery et vérifier un seul appel.
6. Contrôler isolation A/B avec même identifiant, compte absent/déconnecté,
   erreur/timeout, Redis indisponible, crash puis expiration du bail.
7. Rejouer sync résumés complète/incrémentale et backfill produit : détails
   conservés, aucun nouveau `ACTIVITY_CREATED` pour une activité existante,
   contrats et données historiques inchangés.
8. Vérifier latences, limites, index existants et tailles documentaires réelles ;
   aucun appel systématique aux détails ni collecte massive.
9. Faire constater explicitement la réussite/échec du gate runtime par Emergent.

## C321 — Corrections après audit runtime Emergent

### 1. Références et constats du contrat réel

- PR existante corrigée : **#321**, sans nouvelle PR, merge ou changement de branche.
- Base de PR : `copilot/dev` à `d755a80ad9e47ec7cd28e62c03fd28293e41f27c`.
- HEAD de départ de C321 : `c545f43d013e065e1ab8682cd21a23e0c4a0aecd`.
- HEAD du code C321 testé : `3cbbe9ed21e232874d001787c1d823b41fdf65cc`.
  Le commit documentaire suivant complète ce bilan ; son HEAD final sera
  communiqué dans un commentaire sur la même PR, sans référence circulaire.

Source : constats vérifiés reproduits dans la demande C321, issus de l'audit
Emergent de GCCLI v1.9.0 pour `activity typed-splits 24671804067 -j`.
`/app/RUNINDEX_PR321_GCCLI_RUNTIME_CONTRACT_AUDIT.md` n'a pas été lu depuis
GitHub, et aucun appel Garmin n'a été exécuté ici.

Contrat confirmé par cette source :
- racine `{activityId, activityUUID, splits}` ;
- `type` est le type natif, `duration` en secondes, `distance` en mètres,
  `averageSpeed` en m/s, `averageHR` et `maxHR` en bpm ;
- `messageIndex` et `startTimeGMT` apportent des informations d'ordre ;
- `minHR` est absent de la réponse observée ;
- 29 éléments : quatre efforts 240 s, quatre récupérations 180 s,
  échauffement/retour au calme, et 19 éléments RWD à exclure.

### 2. Hypothèses initiales invalidées

Le parseur initial acceptait `splitDTOs`/liste brute, lisait `splitType` et
mappait `WARMUP`/`COOLDOWN`. Aucun de ces noms n'était une preuve du JSON réel.
Il conservait l'ordre brut sans exploiter les temps et ne séparait pas RWD.
Les anciennes fixtures étaient bien synthétiques, mais ne vérifiaient donc
pas le contrat réel. Elles sont remplacées par des fixtures **reconstruites
d'après le contrat documenté**, pas présentées comme captures de l'activité.

### 3. Modifications exactes et cache

- `backend/garmin/data_layer.py` : exige une racine objet avec liste `splits`,
  lit `type`, conserve les unités confirmées, mappe les quatre `INTERVAL_*`,
  exclut uniquement `RWD_RUN`/`RWD_WALK`, conserve le type natif des éléments
  retenus et utilise la règle d'ordre ci-dessous.
- Enveloppe ou ligne incompatible : `ValueError`, jamais un faux succès vide.
  Une liste `splits` reconnue vide, ou ne contenant que RWD, n'a légitimement
  aucune phase structurée. Les types inconnus restent `unknown` sans prétendre
  qu'ils ont été observés dans l'audit.
- Mesures absentes/incompatibles, booléennes, négatives, non finies ou
  non représentables : `None`; zéro reste zéro. Pas de FC minimale calculée.
  `min_hr` déjà présent dans le modèle reste `None` quand la source est absente.
- `backend/activity_phases.py` : propriété de lecture `pace_sec_per_km`,
  `1000 / average_speed_mps` uniquement si vitesse positive/finie et résultat
  fini. **Pas de nouveau champ sérialisé/persisté**, pas de seconde autorité.
- `backend/garmin/activity_details.py` : version de cache **2**. Les caches
  `complete`/`no_data` v1 ne bloquent plus une récupération explicite correcte.
  Aucun backfill automatique, migration ni réécriture globale.
- `backend/garmin/activity_ids.py`, runner/provider et frontières API/file :
  normalisation décrite ci-dessous, vérification de l'identité dans la réponse.
- `backend/jobs/queue.py`, `backend/workers/sync_worker.py` : différé fiable
  sans recirculation dans la FIFO.
- `backend/tests/test_activity_details_pr321.py` : contrat reconstruit,
  identifiants, ordre, invalides, cache et différé.
- `backend/tests/test_activity_details_delayed_redis_c321.py` : vraies commandes
  Lua sur Redis **local isolé**, concurrence de promotion et redémarrage AOF.

Diff de code C321 au HEAD testé : 11 fichiers, 507 insertions, 53 suppressions.
La documentation constitue le douzième fichier du correctif.
Aucun moteur métier, consommateur Training/Workout Analysis, frontend,
modèle de prescription, collection Mongo ou identifiant stocké modifié.
Les phases ne sont pas converties en `km_splits`.

### 4. Règle d'ordonnancement déterministe

1. Pour les phases retenues, `startTimeGMT` ISO date-heure valide constitue
   la preuve temporelle principale. Les valeurs sans offset sont interprétées
   UTC conformément au nom GMT ; les offsets explicites sont normalisés UTC.
   Une date sans heure ou une valeur invalide est traitée comme temps absent.
2. Les phases datées sont triées par instant croissant. À instant égal,
   `messageIndex` entier non négatif valide départage, puis position originale.
3. Les phases sans temps exploitable sont placées après les phases datées,
   triées par `messageIndex` quand disponible ; les index absents/invalides
   suivent, dans leur ordre d'entrée. En l'absence de toute preuve, l'ordre
   d'entrée reste stable.
4. `order` est ensuite recalculé en positions consécutives à partir de zéro,
   **après** exclusion des RWD. Ni `lapIndexes`, ni durée cumulée, ni un nom
   de séance ne servent à inventer un instant ou une classification.

Les champs n'étant pas toujours présents, une chronologie complète ne peut
être prouvée pour une phase non datée. Le placement de repli est explicitement
documenté, stable, mais ne prétend pas retrouver un horaire absent.
Tests : liste de référence reconstruite inversée, timestamps/index contradictoires,
offsets équivalents, égalités, temps manquants/invalides et aucune clé d'ordre.

### 5. Stratégie d'identifiants et jointures historiques

Audit du code : `GccliProvider._normalize`/`GarminActivity.from_summary` stockent
déjà les IDs résumés comme chaînes. Les requêtes de détails restent strictement
`user_id + external_id + source=garmin`. C321 ne modifie aucun ID stocké.

`normalize_activity_id` convertit les **entiers** GCCLI en chaînes, accepte
les chaînes numériques existantes sans les réécrire, refuse booléens,
flottants, valeurs négatives, arguments CLI et préfixes.
Le runner transmet une chaîne à GCCLI. Le provider compare aussi
`activityId` de la réponse, après cette normalisation, à la cible demandée :
absence/mismatch/incompatibilité échouent avant toute persistance des phases.

`workout_analysis_v2_service._extract_garmin_external_id` constitue déjà
la conversion spécifique du workout `garmin-24671804067` vers la clé
`24671804067` quand `external_id` est absent/None.
Ses requêtes restent scoped par `user_id` ; son repli historique d'ID entier
reste inchangé. Ce pont est vérifié par tests, **pas modifié**.
Les endpoints de phases prennent un ID d'activité, pas un ID de workout :
`garmin-123` y reste invalide. Aucune conversion globale ou autre fournisseur
affecté ; aucune migration MongoDB.

### 6. Vérification et correction minimale Redis

**Défaut confirmé** : la réinsertion toutes les cinq secondes pouvait produire
environ 180 passages en FIFO pour un bail de 900 s et occuper des slots locaux
alors qu'aucun travail n'était prêt. La préservation du job ne suffisait pas.

Correction additive au worker/file existants :
- deux clés Redis techniques : sorted set `runindex:garmin:details:delayed`
  (score d'échéance, membre `job_id`) et hash associé des payloads ;
  aucune nouvelle collection, aucun nouveau worker/moteur ou fournisseur ;
- une transition Lua atomique retire le payload exact de PROCESSING et sa
  claim **uniquement s'il était encore présent**, puis conserve le payload
  et l'échéance dans le différé. Un double transfert n'altère pas le job ;
- aucun ACK, aucune consommation de tentative, aucun `sleep` ni
  réenfilage régulier dans la FIFO pendant le bail ;
- watchdog existant (30 s par défaut) : promotion Lua des jobs échus,
  **100 maximum par cycle**, atomiquement vers la FIFO puis suppression
  des enregistrements différés. Deux watchdogs ne promeuvent pas deux fois ;
- LPUSH conserve le sens FIFO existant : les jobs ordinaires déjà prêts
  passent avant les nouveaux jobs promus. Les jobs futurs ne prennent
  ni sémaphore worker durant leur attente, ni verrou utilisateur/slot global ;
- pending toujours protégé par comparaison du `job_id` ; lors du transfert
  sa durée est portée à au moins `échéance - maintenant + 1800 s`.
  Ainsi le pending couvre un bail 900 s **et** une marge de traitement.
  Ni refresh ni release d'un ancien job ne modifient celui d'un nouveau ;
- crash avant la transition : PROCESSING/watchdog existants récupèrent.
  Après transition : données différées persistées dans Redis ; la reprise
  locale AOF est testée. Pas de TTL sur les payloads différés qui perdrait
  silencieusement des jobs.

Les verrous existants, retries des autres types de job, limites globales et
primitives de synchronisation n'ont pas été reconstruits.

### 7. Tests C321 et résultats exacts

Python 3.12.3, pytest 9.1.1, configuration inchangée `-n 2 --dist loadscope`.
Les commandes suivantes sont exécutées depuis `backend/` avec `PYTHONPATH=.`
et `python` du venv de validation. Aucun compte Garmin ni MongoDB réel.

| Commande `python -m pytest … -q` | Résultat final |
| --- | --- |
| `tests/test_activity_details_pr321.py tests/test_activity_details_delayed_redis_c321.py` | **78 passed, 2 warnings**, 1.81 s |
| `tests/test_garmin_queue_backfill_pr197.py tests/test_garmin_phased_sync_pr07a.py tests/test_garmin_deep_sync.py` | **39 passed**, 11.09 s |
| `tests/test_garmin_user_connection.py` (isolé) | **8 passed**, 0.79 s |
| `tests/test_garmin_data_layer.py tests/test_garmin_activity_normalization_pr02.py tests/test_training_v2_domain_activity.py tests/test_performed_workout_pr230.py tests/test_mongo_garmin_boundary_pr137.py` | **181 passed, 1 failed**, 0.96 s |
| `tests/test_workout_analysis_v2.py` (isolé) | **168 passed, 14 warnings**, 2.34 s |

**474 tests réussis, un échec préexistant inchangé.** L'assertion
`test_g_server_uses_boundary` recherche toujours un appel textuel absent de
`server.py`. Vérifié à nouveau par `git show c545f43…:backend/server.py` :
seul l'import `build_recent_training_response` est présent.
Ni fichier ni test concernés ne sont modifiés ; aucune régression nouvelle
démontrée par les suites exécutées.

Un premier essai combiné donnait 181 passed, 1 failed, 1 erreur de collecte
(`pytest_asyncio` absent). Après restauration du plugin utilisé par les tests
existants, `email_validator` manquait encore au chargement du serveur.
Les dépendances existantes ASGI restaurées, la suite Workout Analysis V2
passe intégralement (168/168). Aucun requirements/outil de test projet ajouté.
Les warnings sont des dépréciations existantes de Starlette/Pydantic/FastAPI/passlib.

La suite ciblée couvre les quatre efforts/récupérations, warmup/cooldown et
19 RWD exclus sur 29 lignes reconstruites ; aucune fixture ne prétend être
une capture brute. Elle couvre aussi ID entier/chaîne/mismatch/prefix,
vitesse nulle/non finie/bool/texte/absente, allure non persistée,
temps/index manquants, rejet sans cache négatif, invalidation v1, isolation,
non-écrasement de résumés, events et non-ACK des différés.

Les **5 tests Redis intégration** utilisent un serveur local éphémère sur
loopback/port isolé, AOF `appendfsync always`, jamais `REDIS_URL` de production :
transfert atomique/idempotent et FIFO libre ; promotion concurrente exactement
une fois ; lot borné 100/101 ; ownership/TTL ; kill/restart avec survie du job.
`redis-server` 7.0.15 a été installé uniquement dans le sandbox pour exercer
le runtime Redis déjà utilisé par le projet. Sans binaire, ces tests se
signalent explicitement comme skipped, pas comme validés.

Autres vérifications : Flake8 des 11 fichiers Python changés
`--select=E9,F63,F7,F82`, `compileall`, `git diff --check` : exit 0.
Scan de secrets : aucun. CodeQL Python au HEAD de code C321 : **0 alerte**.
La revue automatisée a été appelée mais son moteur reste indisponible
(modèle absent du registre) malgré son libellé « Success » ; une revue
indépendante de code a été effectuée en complément : **aucun problème
significatif identifié** sur le diff C321.

### 8. Risques résiduels

- Le contrat et les unités sont maintenant ceux du constat Emergent fourni,
  mais GitHub ne possède toujours pas la capture JSON brute vérifiée.
- Sans timestamp, la chronologie est seulement un repli stable fondé sur
  l'index/ordre d'entrée ; ce n'est pas une reconstruction temporelle prouvée.
- Aucun MongoDB réel testé. Verrous/index/latences et clés Redis du runtime
  Emergent restent à contrôler, particulièrement support des scripts Lua
  multi-clés (comme dans les mécanismes Redis existants).
- La promotion peut intervenir jusqu'à un cycle watchdog après l'échéance ;
  un backlog réel prolonge naturellement l'attente. Pending TTL fini et cache
  versionné/fencing ne constituent pas une garantie de délai sous panne illimitée.
- Les métriques de queue historiques ne comptent pas encore les jobs parked
  dans le différé ; elles restent inchangées plutôt qu'élargies hors périmètre.
- La durabilité après redémarrage Redis dépend de sa configuration persistante.
  Elle est vérifiée en local avec AOF, pas présumée en production.
- Les phases ne sont pas injectées dans les algorithmes ou le frontend ;
  le GET dédié reste leur accès courant.

### 9. Éléments restant à valider par Emergent

1. Après revue et merge **explicitement autorisé**, rejouer le GET/POST ciblé
   de l'activité `24671804067` avec son compte isolé ; confirmer 10 phases
   structurées après exclusion des 19 RWD, les 4×240 s et 4×180 s et l'ordre.
2. Comparer directement au JSON brut `splits/type`, `messageIndex`,
   `startTimeGMT`, unités et mesures ; vérifier `min_hr=None` et l'allure
   dérivée à la lecture, sans champ d'allure supplémentaire dans Mongo.
3. Vérifier que `external_id` reste chaîne, `workouts.id` conserve `garmin-`,
   aucun changement des clés, events, résultats moteur ou prescriptions.
4. Rejouer sync résumés/full/incrémentale et isolation A/B, erreurs réelles
   simulées en runtime, cache version2 et GET sans nouvel appel GCCLI.
5. Sur Redis runtime, valider transfert/promotions/Lua/ownership, pending
   couvrant le bail, crash/restart et progression des jobs de sync ordinaires
   sans recirculation de 5 s ; contrôler persistance Redis réelle.
6. Consigner résultats et limites runtime dans Emergent. GitHub ne prétend
   avoir validé ni Garmin réel, ni production Mongo/Redis, ni rendu déployé.

**Livraison C321 : uniquement commits sur la branche actuelle de #321,
rapport et diff pour revue. Aucun merge, déploiement ou nouvelle PR.**

## C321 — Deuxième correction : chronologie et jobs différés

### Références et audit du tri initial

Base PR : `copilot/dev`, `d755a80ad9e47ec7cd28e62c03fd28293e41f27c`.
Départ de cette correction : `25d2048acf1f7ba3a7b3722a6f24a85efc993792`.
HEAD code testé : `38938ee22f2593800f74d8b79b086d32d0962974`.
Le commit documentaire ultérieur est identifié dans le commentaire de livraison.
Cette section remplace les règles de chronologie/promotion du bilan précédent.

Défaut démontré : une récupération `[effort daté, récupération non datée,
effort daté]` pouvait devenir `[effort, effort, récupération]`.
La simple présence d'un timestamp n'est pas une preuve de position pour les
éléments qui n'en possèdent pas.

### Règle chronologique définitive

- Après filtrage RWD sans réordonnancement, si **toutes** les phases retenues
  possèdent un `messageIndex` entier non négatif et **unique**, on considère
  le tri croissant des index. Il est adopté seulement si les timestamps
  disponibles ne décroissent pas dans cet ordre.
- Sinon, si **toutes** les phases retenues possèdent une date-heure valide,
  on considère leur tri UTC stable. Il est adopté seulement si les index
  disponibles ne décroissent pas dans cet ordre.
- Si index complets et temps se contredisent, aucune priorité arbitraire :
  ordre de réception. Si les preuves sont partielles, invalides ou ambiguës,
  ordre de réception également. Aucun sous-ensemble daté n'est extrait pour
  pousser les éléments non datés à la fin.
- Les timestamps égaux restent stables ; les index dupliqués ne permettent
  pas un tri par index. Sans temps complet corroborant un autre ordre,
  les duplications restent dans l'ordre reçu.
- Le filtrage enlève uniquement les RWD et ne permute pas les autres phases.
  Le tri éventuel intervient ensuite sur une preuve globale cohérente.
  `order` est recalculé ; aucune durée cumulée, `lapIndexes` ou mesure inventée.

L'ordre complet/cohérent est une règle prudente et déterministe, pas une
garantie de retrouver la chronologie physique en présence de données source
contradictoires. Le contrat `splits/type`, les types INTERVAL, la vitesse/allure,
les IDs et FC optionnelles restent inchangés.

### Audit des transitions Redis et défauts démontrés

1. Avant cette correction, la promotion vérifiait l'échéance mais pas le
   propriétaire du pending : après expiration et nouvelle demande, un ancien
   job pouvait redevenir runnable.
2. Le worker rafraîchissait le pending sans exploiter le résultat du compare :
   même un pending détenu par un autre job n'empêchait pas son appel fournisseur.
3. Un pending expiré sans remplaçant doit pouvoir être repris atomiquement,
   et non laisser l'ancien job en attente permanente.
4. Redis Lua n'annule pas les écritures antérieures lorsqu'une erreur
   WRONGTYPE survient au milieu du script : il faut vérifier les types et
   les payloads avant les transitions destructives.
5. La récupération d'un orphan details avait une fenêtre entre retrait
   PROCESSING et réinsertion : la réinsertion des details fait désormais
   partie d'un script Lua conditionné au succès du retrait.
   Deux watchdogs ne réenfilent donc pas le même orphan. Autres jobs inchangés.

### Correctifs et invariants

- Refresh pending atomique : reprendre s'il manque, renouveler si `job_id`
  correspond, refuser si un autre job est propriétaire. Release ne reprend
  jamais un pending absent et ne supprime jamais un autre propriétaire.
- Promotion atomique et bornée : reprendre uniquement pending absent ou
  identique ; un pending détenu par un nouveau job **interdit** la promotion.
  L'ancien job termine explicitement `superseded`, enregistré dans un hash
  technique d'issues à TTL 1800 s et dans les logs. Ni GCCLI ni nouvelle
  réinsertion ni suppression de la nouvelle réservation.
- Worker : contrôle initial et nouveau contrôle juste avant dispatch sous
  verrou utilisateur. Un job supplanté est ACKé uniquement comme issue
  terminale explicitement loguée, jamais comme enrichissement réussi.
- Les contrôles de types et payloads ont lieu avant les écritures Lua.
  Une erreur de déplacement/promotion garde la source récupérable ;
  les erreurs Redis dans le worker ne deviennent pas un ACK terminal.
- Les différés restent hors FIFO jusqu'à échéance, sans cycle de cinq secondes.
  Watchdog multiple, lots de 100, FIFO ordinaire et verrous existants conservés.
- Les redeliveries terminées retrouvent le cache Mongo ; un bail expiré peut
  être repris, son jeton empêche une écriture ancienne. Bail 900 s, timeout
  fournisseur ≤60 s et marge worker 65 s inchangés.
- Crash avant parking : PROCESSING persisté et reprise watchdog ; après
  parking : sorted set/hash persistés et reprise de promotion. Pending repris
  seulement s'il est absent, jamais s'il est déjà réattribué.

Fichiers modifiés : data_layer, jobs/queue, workers/sync_worker, les deux suites
de tests de détails et ce rapport. Aucun moteur, frontend, ID stocké,
collection Mongo, migration ou fonctionnalité produit ajouté.

### Tests exacts

Depuis `backend/`, `PYTHONPATH=.`, Python 3.12.3 du venv temporaire ;
`backend/pytest.ini` inchangé (`-n 2 --dist loadscope`) :

| Commande `python -m pytest … -q` | Résultat |
| --- | --- |
| `tests/test_activity_details_pr321.py tests/test_activity_details_delayed_redis_c321.py` | **92 passed, 2 warnings**, 2.40 s |
| `tests/test_garmin_queue_backfill_pr197.py tests/test_garmin_phased_sync_pr07a.py tests/test_garmin_deep_sync.py` | **39 passed**, 11.06 s |
| `tests/test_garmin_user_connection.py` | **8 passed**, 0.75 s |
| `tests/test_garmin_data_layer.py tests/test_garmin_activity_normalization_pr02.py tests/test_training_v2_domain_activity.py tests/test_performed_workout_pr230.py tests/test_mongo_garmin_boundary_pr137.py` | **181 passed, 1 failed**, 1.08 s |
| `tests/test_workout_analysis_v2.py` | **168 passed, 14 warnings**, 2.28 s |

**488 réussites, 1 échec préexistant** : assertion textuelle
`test_g_server_uses_boundary` sur un appel absent de server.py au départ
`25d2048…` (seul l'import existe), code/test inchangés.
Warnings : dépréciations existantes, aucune régression observée.
Premier passage ciblé : 90 réussites, 1 échec du test de lot qui fabriquait
101 propriétaires concurrents pour un seul utilisateur. Correction de
la fixture liée au nouvel invariant : 101 utilisateurs distincts ; lot
100 puis 1 vérifié. Aucun test hors périmètre modifié.

Couverture supplémentaire : preuves complètes index/temps, timestamps
incohérents, index manquants/dupliqués, phase intermédiaire sans temps, RWD
intercalé ; pending réellement expiré, nouveau propriétaire, promotion
interdite/issue explicite, watchdogs concurrents, crash avant/après parking,
WRONGTYPE avec source conservée, reprise de bail et redelivery cache.
Les tests Redis utilisent **réellement Redis 7.0.15 local isolé**, loopback,
AOF, ports éphémères ; aucune connexion Redis/Mongo de production.

`git diff --check`, Flake8 (`--select=E9,F63,F7,F82`) des cinq fichiers Python
changés : exit 0. Imports data_layer/queue/sync_worker : OK.
Scan secrets : aucun ; CodeQL Python : **0 alerte**.
Revue automatisée appelée mais moteur indisponible (modèle absent).
La revue indépendante a détecté une réinsertion orphan non conditionnée au
résultat du retrait : corrigée par Lua et test de deux watchdogs (une insertion).

### Risques résiduels et verdict

- Une source contradictoire ne démontre pas un ordre meilleur : réception
  conservée et aucun horaire fictif. Contrôle du JSON réel par Emergent requis.
- Atomicité Redis garantit absence d'interleaving, pas rollback général sur
  panne serveur/OOM. Précontrôles traitent les erreurs de type démontrées ;
  durabilité dépend de l'AOF/runtime. Une corruption persistante de clé exige
  diagnostic opérationnel, plutôt qu'effacement silencieux des jobs.
- Les issues `superseded` sont terminales, loguées et conservées temporairement,
  pas des activités enrichies. Aucun endpoint produit supplémentaire.
- Backlog, panne illimitée et changement du compte pendant un job restent des
  risques runtime ; verrous et fencing Mongo existants demeurent nécessaires.
- Redis multi-clés, watchdog, baux et isolation sur Emergent restent à valider.
  Aucun test Garmin réel, Mongo réel, merge ou déploiement effectué ici.

**Verdict : prête pour revue de merge, sous réserve d'acceptation de l'échec
préexistant documenté et de revue des risques opérationnels.** Ce verdict
n'autorise ni merge automatique ni déploiement ; validation d'intégration
dans Emergent reste une étape distincte après décision humaine.

### Réaudit final de la deuxième correction — 10 octobre 2026

Base exacte de #321 : `copilot/dev`,
`d755a80ad9e47ec7cd28e62c03fd28293e41f27c`.
HEAD au début de cette nouvelle intervention :
`2c52b5290a7156065ff600105ca3cae8fa592665`, branche actuelle
`copilot/enrichir-activites-avec-tructures`. Les résultats précédents ci-dessus
sont des preuves historiques, pas des tests exécutés dans cette intervention.

**Audit chronologique actualisé.** Le tri « présence de timestamp d'abord »
n'existe plus au HEAD de départ : les critères globaux complets/cohérents
décrits dans cette section sont déjà implémentés. Ils sont conservés, sans
refonte ni reconstruction temporelle. Les index entiers non négatifs complets
et uniques peuvent être non contigus ; les dates GMT sans timezone sont
interprétées en UTC, les dates avec offset sont comparées en UTC. Une date seule
ou invalide n'est pas une date-heure exploitable. Les timestamps égaux ne
permutent pas les lignes ex æquo. Une contradiction entre index et temps
conserve l'ordre reçu.

**Défaut de filtrage démontré.** L'exclusion ne couvrait que `RWD_RUN` et
`RWD_WALK`, contrairement à l'invariant `RWD_*`. Une ligne synthétique
`RWD_STAND` ou `RWD_UNKNOWN` entre deux intervalles restait une phase `unknown`.
Le filtre porte maintenant sur le préfixe `RWD_`. Aucune autre famille inconnue
n'est exclue. Le filtrage précède la recherche de preuve chronologique et
préserve exactement l'ordre relatif des lignes conservées.

Les 17 cas synthétiques supplémentaires couvrent temps complets/offsets,
index complets non contigus, temps partiels avec index complets, index
manquants/dupliqués, contradictions, dates invalides ou sans heure,
absence de preuve, stabilité/déterminisme et quatre variantes RWD intercalées.
Les `lapIndexes` et les durées volontairement contradictoires ne servent
jamais de référence d'ordre. Ces données ne sont pas des captures Garmin.

**Audit Redis actualisé et défauts supplémentaires démontrés.** La promotion
atomique vérifiant le propriétaire `job_id`, la reprise d'un pending absent et
la suppression compare-and-delete sont déjà présentes au HEAD de départ ;
elles ne sont pas réécrites. Le cache et le bail Mongo restent inchangés.

- Un watchdog pouvait lire une ancienne date de claim, puis retirer une
  livraison fraîche du même payload après reprise par un autre worker. Le
  script de récupération des details compare désormais le claim courant à la
  valeur observée avant tout retrait.
- L'adoption d'un claim absent pouvait écraser un claim frais ou recréer une
  entrée de claim après ACK. Elle devient atomique : payload encore dans
  PROCESSING et `HSETNX`. Les autres types de jobs restent inchangés.
- Les details en contention de verrou utilisateur ou de plafond global
  retournaient encore immédiatement dans le FIFO après 1 ou 2 secondes.
  Ils sont maintenant parqués jusqu'à au moins la cadence watchdog
  (30 s par défaut), sans sommeil artificiel, consommation d'essai ou ACK.
  Le pending est renouvelé par le mécanisme différé existant. Une sync Garmin
  conserve son verrou, les mêmes limites et son comportement historique.

**Tests de cette intervention.** Toutes les commandes pytest ci-dessous sont
exécutées depuis
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend`,
avec `PYTHONPATH=.`, `/usr/bin/python` 3.12.3 et la configuration xdist
inchangée `-n 2 --dist loadscope`.

| Commande exacte (hors préfixe `PYTHONPATH=.`) | Résultat |
| --- | --- |
| `python -m pytest tests/test_typed_splits_chronology_c321.py tests/test_garmin_data_layer.py tests/test_garmin_activity_normalization_pr02.py tests/test_training_v2_domain_activity.py tests/test_performed_workout_pr230.py tests/test_mongo_garmin_boundary_pr137.py -q` | **198 passed, 1 failed**, 0,83 s |
| `python -m pytest tests/test_workout_analysis_v2.py -q` — premier essai | **0 test exécuté, 1 erreur de collecte** : `pytest_asyncio` absent |
| `python -m pytest tests/test_workout_analysis_v2.py -q` — après restauration des dépendances de test existantes | **168 passed, 14 warnings**, 1,76 s |
| `python -m pytest tests/test_activity_details_pr321.py tests/test_activity_details_delayed_redis_c321.py -q` | **104 passed** |
| `python -m pytest tests/test_garmin_queue_backfill_pr197.py tests/test_garmin_phased_sync_pr07a.py tests/test_garmin_deep_sync.py -q` | **39 passed** |
| `python -m pytest tests/test_garmin_user_connection.py -q` | **8 passed** |
| `python -m pytest tests/test_garmin_queue_health_admin.py -q` | **14 passed** |

Pour les quatre dernières lignes, les commandes déléguées comportaient
également `TMPDIR="$PWD/../.queue-c321-runtime"` et, respectivement,
`--basetemp="$PWD/../.queue-c321-runtime/details-full"`,
`--basetemp="$PWD/../.queue-c321-runtime/garmin-isolated"`,
`--basetemp="$PWD/../.queue-c321-runtime/user-isolated"`,
`--basetemp="$PWD/../.queue-c321-runtime/admin-only"`.
Ce répertoire temporaire a été supprimé après arrêt des Redis de test.

**Essais intermédiaires et limites de traçabilité.** La démonstration avant
correctif, depuis la racine du dépôt, était :
`PYTHONPATH=backend TMPDIR="$PWD/.queue-c321-runtime" python -m pytest
-c backend/pytest.ini --basetemp="$PWD/.queue-c321-runtime/regression-before"
backend/tests/test_activity_details_delayed_redis_c321.py
-k 'stale_watchdog or missing_claim or backpressure' -q`.
Elle produisait **4 échecs** : watchdog sur claim redélivré, adoption écrasant
un claim frais et les deux contentions user-lock/global-cap. Ces quatre
régressions démontrées sont corrigées et passent dans la suite finale.

L'essai combiné depuis `backend` :
`TMPDIR="$PWD/../.queue-c321-runtime" python -m pytest
--basetemp="$PWD/../.queue-c321-runtime/full"
tests/test_activity_details_pr321.py
tests/test_activity_details_delayed_redis_c321.py
tests/test_garmin_queue_backfill_pr197.py
tests/test_garmin_phased_sync_pr07a.py tests/test_garmin_deep_sync.py
tests/test_garmin_user_connection.py tests/test_queue_health.py
tests/test_garmin_queue_health_admin.py -q`
a échoué ; **le résumé exact n'a pas été conservé par le spécialiste :
aucun nombre n'est inventé pour cette tentative**.
Le diagnostic avec les six fichiers Garmin/health de cette commande a donné
**46 passed, 2 failed, 6 errors** : pollution des stubs `config.secrets`
entre modules (bootstrap/admin), cinq fonctions de queue-health demandant un
argument `r` non défini comme fixture, et une fonction async non marquée.
Avec seulement les quatre fichiers Garmin, **46 passed, 1 failed**
(même assertion bootstrap liée à l'ordre des stubs).
Ces défauts de lancement/collection existent dans les tests inchangés ;
les suites unitaires isolées pertinentes passent comme indiqué ci-dessus.
`test_queue_health.py` est un script nécessitant son client explicite,
pas une suite pytest autonome ; ses six fonctions ont été appelées
séparément avec un Redis local isolé (**6 réussites supplémentaires,
hors total pytest**). La commande ad hoc complète est conservée dans la
trace de l'agent, pas présentée comme une commande pytest reproductible.

Le spécialiste a également signalé un premier lancement racine
(**13 passed, 4 failed, 1 erreur de collecte**, mauvais chemin de résolution
`config.secrets`), puis des sélections partielles réussies (**89**, **45** et
**30** passed). Les commandes des deux premières sélections n'ont pas été
conservées intégralement ; elles ne servent pas au verdict ni au total final.
La sélection finale de 30 était :
`TMPDIR="$PWD/../.queue-c321-runtime" python -m pytest
--basetemp="$PWD/../.queue-c321-runtime/queue-final"
tests/test_activity_details_delayed_redis_c321.py
tests/test_activity_details_pr321.py
-k 'delayed_redis_c321 or enqueue or worker or pending_ownership or expired_mongo_lease' -q`.

L'échec `test_g_server_uses_boundary` est l'assertion textuelle préexistante
sur `build_recent_training_response(domain_activities...)`. Le `git show`
de la base exacte confirme que seul l'import est présent ; aucun changement
de `server.py` ou du test. Il ne s'agit pas d'une régression de C321.
L'erreur de collecte était une dépendance absente du sandbox, corrigée par
installation des outils déjà utilisés par les tests existants ; aucun fichier
de dépendances projet modifié. Les warnings sont les dépréciations
Starlette/passlib/Pydantic/FastAPI existantes.

`python -m py_compile` des deux fichiers de chronologie ; depuis `backend`,
`python -m flake8 garmin/data_layer.py tests/test_typed_splits_chronology_c321.py
--select=E9,F63,F7,F82` et
`PYTHONPATH=. python -c 'import garmin.data_layer; print("data_layer import OK")'`
: exit 0.
Le spécialiste queue a également exécuté
`python -m flake8 jobs/queue.py workers/sync_worker.py
tests/test_activity_details_delayed_redis_c321.py --select=E9,F63,F7,F82` et
`python -c 'import jobs.queue, workers.sync_worker'` : exit 0.

**Bilan final : 531 tests pytest réussis, 1 échec préexistant** dans les
exécutions complètes finales ci-dessus (les essais partiels ne sont pas
additionnés). Les 104 tests details incluent **18 tests avec Redis 7.0.15
réel, local isolé sur loopback, ports éphémères et AOF**, pas un Redis de
production. Les autres contrôles de worker/provider/Mongo utilisent des
simulations ; les appels Redis de transition sont exécutés par de vrais
scripts Lua dans ces 18 tests, pas imités par un faux `eval`.

**Vérifications et livraison.** HEAD de code testé :
`6480a494a5c9a831894e0e3f5089e9a9c6523ead`. Les commits documentaires et
de nettoyage ultérieurs ne changent pas le code testé ; leurs SHA exacts sont
fournis dans le commentaire de livraison. Des artefacts Redis temporaires
ont été capturés pendant une validation concurrente ; ils ont été retirés
intégralement de l'arbre final et ne font pas partie du diff livré.
Le diff final depuis `2c52b529...` ne comporte que les trois fichiers
backend ciblés, les deux suites de tests details/chronologie et ce rapport.
`git diff --check` : exit 0 ; scan des six fichiers : aucun secret.
CodeQL Python au HEAD de code : **0 alerte**. La revue automatisée a été
appelée mais son moteur est indisponible (modèle absent du registre), malgré
son libellé « Success » ; une revue indépendante de la chronologie et une
revue indépendante du delta queue n'ont trouvé aucun défaut significatif.

**Risques opérationnels inchangés.** L'enqueue details reste `SET NX` puis
`LPUSH` : un crash entre ces opérations peut laisser une réservation sans
payload jusqu'à son TTL fini (1800 s). L'API ne confirme pas un job enfilé
avant le retour de `LPUSH`. Redis ne garantit pas de rollback Lua général sur
OOM, et la persistance effective dépend de la configuration runtime.
Le bail Mongo de 900 s et le timeout GCCLI borné à 60 s restent la protection
pour une activité ; aucun test MongoDB/Garmin réel n'est revendiqué.

**Verdict actualisé : prête pour revue humaine de merge**, avec l'échec
statique préexistant et les limites runtime ci-dessus explicitement soumis
au reviewer. Aucun merge, déploiement, nouveau produit, nouvelle PR ou test
Garmin réel depuis GitHub. L'intégration Emergent reste à valider séparément.
