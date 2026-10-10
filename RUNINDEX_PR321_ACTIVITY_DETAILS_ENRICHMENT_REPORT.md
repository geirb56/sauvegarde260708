# RUNINDEX — PR321 — Enrichissement ciblé des activités

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
- Redis pending TTL existant 300 s, fiable at-least-once ; la réservation Mongo
  protège aussi contre expiration du pending, redelivery et requêtes concurrentes.
- Aucun nouveau schéma/index/collection ni migration ou suppression historique.

## 7. Tests GitHub : commandes et résultats exacts

Python 3.12.3 ; venv temporaire ; dépendances de test existantes restaurées,
sans modifier `requirements.txt` ni ajouter un outil au projet.
Depuis `backend/`, `PYTHONPATH=.` et `python` du venv :

| Commande `python -m pytest … -q` | Résultat |
| --- | --- |
| `tests/test_activity_details_pr321.py` | **46 passed, 1 warning**, 0.82 s |
| `tests/test_garmin_user_connection.py` (processus isolé) | **8 passed**, 0.60 s |
| `tests/test_garmin_queue_backfill_pr197.py tests/test_garmin_phased_sync_pr07a.py tests/test_garmin_deep_sync.py` | **39 passed**, 10.79 s |
| `tests/test_garmin_data_layer.py tests/test_garmin_activity_normalization_pr02.py tests/test_training_v2_domain_activity.py tests/test_performed_workout_pr230.py tests/test_mongo_garmin_boundary_pr137.py` | **181 passed, 1 failed**, 0.64 s |

Les deux workers `-n 2 --dist loadscope` viennent de `backend/pytest.ini`,
inchangé. **274 tests passés, un échec préexistant** sur ces exécutions finales.

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
