# RUNINDEX — Fiabilisation de la concurrence GCCLI (#333)

## Références et périmètre

- Repository : `geirb56/sauvegarde260708`.
- Base exacte : `copilot/dev`, `70fd6344b10edf61ba9877731837689943d9c30e`
  (merge de #332, vérifié contre la référence distante avant modification).
- HEAD initial audité : `70fd6344b10edf61ba9877731837689943d9c30e`.
- HEAD code/tests validé : `32de7817ff0c8829364ebeec34d64fc14de8f931`.
  Les commits ultérieurs de rapport ne changent pas ce snapshot de code/tests ;
  le SHA HEAD de livraison est fourni dans la description de PR et la réponse finale.
- Branche de livraison : `copilot/fiabilisation-limiteur-global-gcccli`.
- Objectif unique : sécuriser les deux réservations de concurrence existantes.
  Aucune nouvelle queue, aucun worker/service supplémentaire, aucun merge.

## Audit préalable : risques confirmés

Lecture intégrale du limiteur, du worker et des primitives de queue, puis du
runner GCCLI et des tests de livraison details/laps.

1. L'ancien compteur `runindex:garmin:global_active` expirait 300 secondes après
   son premier `INCR`, indépendamment de la durée des jobs et sans renouvellement.
   Une nouvelle génération de compteur pouvait admettre de nouveaux jobs ; les
   anciens `DECR` affectaient alors des détenteurs différents.
2. `SET sync_lock:{user_id} 1 NX EX 120` était suivi d'un `DEL` inconditionnel,
   aussi bien en cas de saturation globale que dans le `finally`. Après expiration,
   un ancien worker pouvait supprimer le verrou d'un nouveau.
3. L'acquisition globale était hors du bloc de nettoyage : une erreur Redis
   après l'acquisition utilisateur conservait le verrou jusqu'à son expiration.
   Une erreur de libération globale pouvait également empêcher le `DEL` utilisateur.
4. `asyncio.wait_for` n'arrête pas un thread `asyncio.to_thread`. Details/laps
   utilisent ces threads : libérer la capacité immédiatement après annulation
   pouvait laisser un véritable processus GCCLI tourner.
5. Les autres chemins service/provider comportent des appels synchrones :
   ils peuvent bloquer l'event loop. Un heartbeat asyncio seul ne constitue donc
   pas une preuve de renouvellement pendant leurs commandes.
6. `subprocess.run(timeout=...)` dépend de la survie du parent Python pour tuer
   son enfant. Après `SIGKILL` du worker, ce timeout Python n'est plus un garant.

Les seuls appels de slots de production étaient ceux de `process_job` ;
`scheduler_worker` consulte seulement `global_active_count`. Les verrous
utilisateur étaient acquis/libérés dans ce worker. Les réservations pending
details/laps utilisent déjà des scripts Lua conditionnés à leur job ID ; elles
ne sont pas les verrous de concurrence et conservent leur protocole #332.

## Architecture avant / après

| Protection | Avant | Après |
| --- | --- | --- |
| Capacité globale | Compteur INCR/DECR, TTL commun | ZSET `runindex:garmin:global_leases`, token unique par livraison, échéance individuelle |
| Admission | Compteur sans identité | Lua atomique : Redis TIME, purge des propriétaires expirés, vérification de capacité, ajout |
| Capacité par défaut | `GARMIN_GLOBAL_MAX_SYNCS=8` | Configuration et défaut 8 conservés |
| Libération globale | DECR anonyme | ZREM du seul token du détenteur |
| Verrou utilisateur | Valeur `1`, DEL inconditionnel | SET NX EX 120 avec token UUID, compare-and-release Lua |
| Renouvellement | Aucun | CAS atomique des deux réservations ; ne recrée jamais un propriétaire expiré |
| Crash pendant GCCLI | Deadline dépendant du worker | GNU `timeout` indépendant, groupe de processus distinct pour les commandes JSON/auth-status |
| Timeout / annulation thread | Coroutine annulée, thread encore actif | Arrêt des commandes futures, drainage de l'exécution physique avant libération |
| Queue / retries | BLMOVE, processing, ACK, watchdog, delayed | Structures et politique inchangées |

Le ZSET n'expire pas collectivement : chaque membre porte sa date de recyclage
Redis. Un crash sans libération restitue la capacité lors de la prochaine
admission/lecture après 300 secondes ; le verrou utilisateur expire après
120 secondes. Une libération tardive ne retire que l'ancien membre et ne peut
ni décrémenter un autre propriétaire ni supprimer son verrou.

## Exécution réelle, expirations et renouvellement

- Un nouveau UUID est créé **par livraison**, pas par job ID : une redelivery
  du même job ne réutilise pas son ancien propriétaire.
- Le worker renouvelle les deux réservations toutes les 30 secondes.
- Avant **chaque commande physique**, y compris chaque retry inline, le runner
  vérifie et renouvelle synchroniquement les deux propriétaires par le même Lua.
  Le contexte est transmis aux threads par `ContextVar` / `asyncio.to_thread`.
  Cette vérification couvre aussi auth-status et le login PTY.
- La borne GCCLI existante (15–60 secondes) est conservée. La commande est
  enveloppée par `timeout --signal=KILL --kill-after=5`. Son délai indépendant
  est inférieur aux leases utilisateur (120 s) et globale (300 s), avec marge.
  Le timeout extérieur Python laisse 5 secondes au gardien indépendant.
- Une commande dont la borne ne tient pas dans la fenêtre de lease est refusée.
  Un délai anormal de réponse Redis est aussi contrôlé par horloge monotone
  avant lancement. L'absence de `timeout` provoque un refus fermé, sans GCCLI.
- Si un vieux worker reprend **après expiration**, son prochain CAS échoue :
  aucun nouveau processus n'est lancé, même si Redis est à nouveau disponible.
  Le processus déjà lancé dispose de sa propre deadline, indépendante du worker.
  Recycler un membre expiré n'est donc pas, à lui seul, la stratégie de sûreté.
- Perte de propriétaire ou erreur Redis : arrêt irréversible des commandes de
  cette exécution et absence d'ACK ; le watchdog conserve sa voie de récupération.
  Aucun retry fournisseur supplémentaire n'est ajouté.
- Timeout/annulation : la coroutine de travail est shieldée, les commandes
  futures sont interdites et le travail en cours est drainé. Les commandes
  physiques sont aussi enregistrées sous un verrou de thread : une annulation
  directe de la tâche interne lors du shutdown ne permet pas de libérer les
  réservations avant la fin du processus déjà lancé.
- Nettoyage dans le `finally` externe, y compris acquisition ambiguë/échouée ;
  libérations indépendantes, bornées et shieldées contre des annulations répétées.
  Une erreur de cleanup laisse expirer uniquement les réservations concernées.

### Interactions avec livraison et timeouts

BLMOVE/processing/claims, ACK, backoffs et `MAX_RETRIES` sont conservés.
Le watchdog peut toujours redélivrer un job long après `ORPHAN_TIMEOUT` :
le token utilisateur empêche une deuxième exécution simultanée ; details/laps
gardent leur parking delayed sans consommation d'une tentative en cas de
saturation. Leur timeout worker reste `max(JOB_TIMEOUT, 65)`.

Pour les appels synchrones historiques des autres services, le timeout asyncio
du job n'est **pas** une borne stricte de durée totale : l'event loop peut rester
bloquée par un appel/retry fournisseur. Cette limite préexistante n'est pas
masquée par le heartbeat. La sûreté physique repose alors sur le CAS synchrone
par commande et le gardien indépendant, non sur la disponibilité du timer asyncio.
Le drainage peut retarder le retour d'une annulation ou d'un timeout ; il ne
libère pas prématurément une capacité encore utilisée.

## Fichiers modifiés

- `backend/sync/rate_limiter.py` : slots identifiés, admission/renouvellement Lua,
  comptage des leases.
- `backend/sync/execution_lease.py` : contexte de propriétaire, fencing fermé,
  enregistrement/drainage de l'exécution réelle.
- `backend/jobs/queue.py` : primitives de verrou utilisateur à token ; primitives
  de livraison et réservations #332 inchangées.
- `backend/workers/sync_worker.py` : intégration, renouvellement et cleanup.
- `backend/garmin/runner.py` : garde de lancement et deadline indépendante,
  y compris authentification.
- `backend/tests/test_gccli_concurrency_pr333.py` : tests ciblés Redis/processus.
- Tests existants directement couplés au contrat de slots/nettoyage :
  `test_sync_scheduler.py`, `test_activity_details_pr321.py`,
  `test_activity_details_delayed_redis_c321.py`,
  `test_activity_laps_queue_pr332.py`, `test_garmin_queue_backfill_pr197.py`.
- Le présent rapport.

## Validation

**385 tests passent** : 269 concurrence/livraison/enrichissements et
116 régressions runner/provider ; 5 avertissements de dépréciation existants.
Le nouveau module comporte 42 cas paramétrés. Aucun test destructif n'utilise
le Redis runtime : le fixture lance son propre Redis sur un port loopback dédié.
Les substituts GCCLI sont des processus locaux, sans compte Garmin ni Mongo runtime.

Commandes exécutées depuis `backend/`, avec la configuration existante
`-n 2 --dist loadscope` :

```text
python -m pytest tests/test_gccli_concurrency_pr333.py tests/test_activity_laps_pr332.py tests/test_activity_laps_queue_pr332.py tests/test_activity_details_pr321.py tests/test_activity_details_delayed_redis_c321.py tests/test_garmin_queue_backfill_pr197.py --basetemp=.pytest_cache/pr333-regression -q --tb=short
# 269 passed
python -m pytest tests/test_garmin_daily_metrics_pr03.py tests/test_garmin_vo2max_pr195.py tests/test_garmin_deep_sync.py --basetemp=.pytest_cache/pr333-runner -q --tb=short
# 116 passed
python -m flake8 garmin/runner.py jobs/queue.py sync/rate_limiter.py sync/execution_lease.py workers/sync_worker.py tests/test_gccli_concurrency_pr333.py tests/test_activity_details_delayed_redis_c321.py tests/test_activity_details_pr321.py tests/test_activity_laps_queue_pr332.py tests/test_garmin_queue_backfill_pr197.py tests/test_sync_scheduler.py --select=E9,F63,F7,F82
# aucun défaut bloquant
git diff --check
git diff --cached --check
# propres
```

Couverture ciblée : admission/release normales, saturation, 30 admissions
concurrentes, expiry/recyclage, cleanup tardif, identités utilisateur, CAS de
renouvellement et refus de résurrection, indisponibilité Redis et reprise,
retry inline fenced, tokens distincts en redelivery, exécutions multi-utilisateurs,
backpressure details/laps, erreurs acquisition/release, annulation répétée,
annulation directe de la tâche interne, timeout avec véritable thread/commande,
et `SIGKILL` du worker avec terminaison indépendante de son enfant.
Le test manuel du cap du scheduler est également appelé avec Redis isolé.

Les premières exécutions ont révélé des mocks/tests couplés à l'ancien contrat
de libération et des fenêtres d'attente de fixture ; ces tests ont été adaptés,
sans retirer les assertions de livraison ni modifier les retries de production.
Les résultats ci-dessus sont ceux des exécutions finales.

Non exécutés : Redis/Garmin/Mongo de production, tests destructifs runtime
`test_reliable_queue.py` / `test_realtime_sync_pipeline.py`, suite backend entière,
frontend/build Docker et benchmark de charge. Raisons : isolation requise,
absence de comptes/services runtime dédiés à ces essais et périmètre exclusivement
concurrence backend. Aucune réussite runtime distante n'est revendiquée.
Les dépendances de test existantes ont été installées dans le sandbox ; les
manifests de dépendances et images du projet ne sont pas modifiés.

Validation automatisée après commit du code/tests : **CodeQL Python, 0 alerte**.
Le scanner de secrets ne détecte aucun secret dans les 12 fichiers modifiés.
L'outil de review automatisée est indisponible (modèle
`capi-prod-claude-sonnet-4.6` absent de son registre) : son statut « succès /
aucun commentaire » n'est donc pas revendiqué comme une review effective.
Une revue de conception indépendante a été réalisée ; ses observations sur
le blocage historique de l'event loop, le drain de migration et le refus fermé
des pannes Redis sont consignées ci-dessous.
Une seconde review read-only du diff final par l'agent spécialisé `code-review`
ne trouve aucun problème significatif ; elle ne remplace pas l'audit utilisateur.

## Risques résiduels et gates de déploiement

1. **Drain obligatoire des anciens workers avant activation.** Pas de rollout
   mixte garanti : l'ancienne version n'applique pas le fencing physique et son
   compteur anonyme peut expirer pendant son exécution. La nouvelle admission
   respecte le compteur legacy non nul sans jamais le modifier. Si ce compteur
   est exceptionnellement non nul sans TTL, vérifier l'arrêt des anciens workers
   avant intervention opérateur ; aucune suppression automatique dangereuse.
2. Vérifier GNU coreutils `timeout` dans l'image runtime. Les images worker
   actuelles sont Debian `python:3.11-slim` ; le code refuse de dégrader la sûreté
   si l'exécutable manque. Un test local ne vaut pas une validation Railway.
3. Redis doit préserver les réservations : pas de FLUSH, éviction des clés de
   concurrence ou failover perdant des écritures pendant les exécutions actives.
   Des tokens ne compensent pas la disparition de l'autorité d'admission.
4. La garantie physique suppose une progression normale des horloges/schedulers
   OS et que GCCLI ne daemonise pas en échappant au groupe du gardien. Une
   suspension arbitrairement longue entre CAS et spawn, le gel du gardien OS,
   un changement brutal d'horloge Redis ou une perte de ses données ne permettent
   pas une preuve absolue avec Redis seul ; Garmin ne fournit pas de fencing token
   côté serveur. Ces limites doivent être acceptées à l'audit, pas dissimulées
   derrière une augmentation de TTL.
5. L'event loop bloquée par les chemins synchrones historiques et l'at-least-once
   (pas exactly-once) restent des propriétés existantes. Un accès Mongo bloqué
   peut prolonger le drainage ; aucun nouveau processus GCCLI ne peut partir une
   fois l'exécution arrêtée. Un job synchrone peut aussi affamer le renouvellement
   asyncio des jobs frères : leurs leases expirées sont refusées à la reprise,
   avec récupération par watchdog plutôt qu'exécution non protégée. Cette
   limitation de disponibilité sous charge doit être vérifiée au runtime ;
   les frontières de threads des services existants ne sont pas reconstruites ici.

## Performances et non-régression

Coût ajouté : un Lua synchrone par commande/retry GCCLI, un renouvellement
périodique par job, une connexion Redis synchrone créée paresseusement et fermée
au cleanup, et un petit processus gardien par commande. Aucun benchmark de
latence/charge n'a été exécuté ; aucune métrique de performance n'est inventée.
La capacité peut rester réservée jusqu'à expiration après crash ou panne Redis :
la sûreté est privilégiée à l'admission immédiate.

Les moteurs physiologiques, Workout Analysis V2, prédictions, allures, plans,
Coach IA, schéma Mongo, abonnement, backfills et déclenchements automatiques
ne sont pas modifiés. Le drift `activity_day` est intact. La règle future des
365 jours est hors périmètre et n'est pas implémentée.

Les suites #332 dédiées passent ; leurs contrats restent dans les mêmes
modules : routes et POST-only, ciblage et réservations indépendantes details/laps,
normalisation, persistance Mongo fenced, refus du superseded, recovery des
reservations expirées, parking/promotions atomiques et ACK seulement après
traitement réussi ou échec terminal existant.

**Livraison sans merge automatique. Audit utilisateur requis avant merge.**
