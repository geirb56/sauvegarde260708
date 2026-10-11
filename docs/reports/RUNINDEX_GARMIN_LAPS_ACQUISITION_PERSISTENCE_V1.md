# RUNINDEX — PR332 : Garmin Lap Acquisition & Persistence V1

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
  `busy` ou `already_requested` en cas de course concurrente.
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

Résultats et commandes exacts ajoutés après exécution avant livraison.
Premier essai avec le Python système : échec avant collecte
`No module named pytest` ; ce n'est pas un test réussi.

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
