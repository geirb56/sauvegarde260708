# RUNINDEX — Fiabilisation de la concurrence GCCLI (#333)

> Les sections initiales ci-dessous décrivent le snapshot PR333 livré à
> `6de36fc84c0e76311aaf9bd14e3d12a8f6feb44c`. La section **Correction C333 avant
> merge** en fin de rapport prévaut pour l'audit courant, les preuves et le verdict.
> Les 385 tests initiaux n'établissaient pas une garantie stricte d'absence de
> chevauchement physique dans la fenêtre entre Redis et le lancement OS.

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

## Correction C333 avant merge — audit courant

### Références et causes racines vérifiées

- PR existante : #333, toujours draft ; aucun merge et aucun déploiement.
- Base d'intégration : `copilot/dev`,
  `70fd6344b10edf61ba9877731837689943d9c30e`.
- HEAD audité avant correction :
  `6de36fc84c0e76311aaf9bd14e3d12a8f6feb44c`.
- HEAD du code de production correctif :
  `df8f889720f279034c6b87038720de52d15b9fc2`.
- HEAD du snapshot code/tests définitif (405 tests) et de la validation CodeQL :
  `1479832417a880b2ee37f1448cea9826829d1de5`. Les commits ultérieurs ne
  changent que le rapport ; le HEAD de livraison est fourni sur la PR et dans
  la réponse finale.
- Les corrections restent sur `copilot/fiabilisation-limiteur-global-gcccli`,
  pas sur la branche d'intégration.

**Renouvellement dépendant de la boucle.** Dans le snapshot audité,
`sync_worker._renew_execution` attendait `asyncio.sleep(30)` puis une commande
Redis async. Il ne pouvait pas s'exécuter pendant un blocage de l'event loop.
Les appels synchrones aux providers dans `garmin/service.py` (VO2max, métriques
quotidiennes, pagination et synchronisation) sont bien présents dans le code ;
ils ne sont pas uniformément déplacés dans `asyncio.to_thread`. La vérification
synchrone par commande protège son propre prochain départ, mais ne renouvelle
pas les réservations d'autres jobs de la même boucle. Un tel renouvellement
périodique n'était donc pas une protection indépendante de l'exécution physique.

**Fenêtre Redis / OS.** `ExecutionLease.command` faisait un CAS de propriété
et construisait les arguments du gardien. Le runner appelait ensuite
`subprocess.run`, ou `pty.fork` suivi d'un `exec` pour le login. Redis ne participe
pas à cette création OS. Un propriétaire pouvait changer après la réponse Lua
et avant l'exécution effective. Le contrôle de durée monotone de la réponse
Redis ne couvre pas une suspension ultérieure. Ni le token, ni le TTL, ni GNU
`timeout` ne constituent un fencing accepté par Garmin avant sa première requête.

**Deux propriétés différentes.** L'admission Lua et le release à token peuvent
rester corrects alors qu'un processus ancien tourne encore. Un ZSET de cardinal
8 ne prouve pas qu'il existe au plus 8 exécutions physiques ; une expiration
forcée, une perte de clés ou une suspension après le dernier contrôle peut
séparer ces deux observations. Les nouveaux tests doivent mesurer ces propriétés
séparément, avec des enfants réels et pas seulement des mocks d'admission.

### Modifications ciblées et justification

1. Le worker démarre un **thread de renouvellement par exécution admise**, après
   acquisition des deux réservations. Ce thread appartient au worker existant :
   ce n'est ni un nouveau service ni un consommateur de queue. Il utilise le
   client Redis synchrone et le même Lua de comparaison des deux propriétaires,
   à une cadence calculée à partir des TTL (30 s avec les valeurs actuelles).
   Le renouvellement n'attend plus le scheduling de la boucle asyncio.
2. Le Lua n'est pas changé : si le membre global est déjà expiré/absent, ou si
   le verrou utilisateur est absent/différent, rien n'est renouvelé. L'exécution
   est arrêtée pour ses commandes futures. Une erreur Redis n'est pas traitée
   comme une autorisation implicite.
3. La création paresseuse du client synchrone est protégée contre les appels
   simultanés du runner et du thread. Les timeouts socket/connexion sont courts
   et les retries Redis implicites désactivés ; on ne reprend pas une commande
   après perte de son contrôle de propriété.
4. Le `finally` arrête les futurs départs, attend les commandes enregistrées,
   signale l'arrêt du thread et attend sa fin **avant** release et fermeture du
   client. Les libérations restent conditionnées au token, indépendantes et
   protégées contre les annulations répétées. Une réponse de renouvellement en
   retard ne peut donc pas rétablir une réservation après son cleanup normal.
5. Un dernier CAS est ajouté dans le runner après la construction des arguments,
   immédiatement avant `subprocess.run` ou `pty.fork`. Il refuse le départ si un
   remplacement/une expiration est observable à cet instant ; il réduit la
   fenêtre précédente sans prétendre rendre Redis et le lancement OS atomiques.
6. Les commandes physiques gardent le timeout indépendant introduit par PR333,
   et le drainage garde son enregistrement de threads/processus réels.

Les TTL, le défaut de capacité globale 8, les commandes Garmin, le nombre de
tentatives et les backoffs ne sont pas changés. Queue/claims/watchdog/delayed,
réservations pending et persistance C332 ne sont pas reconstruits. Le nouveau
thread ajoute une faible consommation mémoire et des commandes Redis
périodiques ; aucun chiffre de performance non mesuré n'est revendiqué.

### Limite stricte et mécanisme de fencing nécessaire

Une deuxième vérification ne prouve pas la propriété « jamais de chevauchement » :
un processus peut encore être suspendu juste **après son dernier CAS**, ou juste
avant que le gardien ne démarre. Redis peut alors recycler la réservation,
accepter son successeur, puis l'ancien processus reprendre son spawn.
Un thread indépendant corrige le blocage asyncio tant que le processus et ses
threads sont schedulés ; il ne corrige pas le gel complet du worker, un changement
d'autorité Redis ou une expiration imposée pendant une commande déjà en cours.
Le gardien borne l'exécution après son lancement mais ne l'empêche pas de partir.

Pour une garantie stricte, une autorité d'exécution non contournable doit accepter
un **epoch monotone de fencing** pour chaque propriétaire et slot, et rejeter
les epochs obsolètes au moment où elle exécute la commande. Le transfert d'un slot
doit attendre la terminaison et le reap du processus précédent, pas seulement la
disparition de son TTL. Cette autorité doit arbitrer l'ensemble des workers :
un mutex local à une machine Railway ou un nouveau compteur Redis n'est pas
suffisant entre instances. Si elle est externe à Garmin, elle doit contrôler
tous les lancements/enfants et refuser de transférer une capacité dont l'arrêt
ancien n'est pas établi, même pendant une partition. Un simple jeton transmis
à GCCLI que Garmin ne vérifie pas ne fournit pas ce fencing.

Ce mécanisme implique une décision d'architecture hors de la correction ciblée ;
il est **proposé, pas implémenté**. Aucune nouvelle queue/service n'est ajoutée
pour contourner le périmètre demandé. Le verdict de merge devra refléter la
fenêtre résiduelle démontrée, indépendamment du succès des tests Redis.

### Contraintes Railway / Redis

- Conserver les TTL actuels et les timeouts GCCLI existants ; ne pas accepter
  une commande dont la deadline dépasse la fenêtre de réservation. Une marge
  fixe ne constitue pas une mesure des pires suspensions d'ordonnancement Railway.
- Vérifier la présence de GNU coreutils `timeout`, la création de groupes de
  processus et l'absence d'échappement/daemonisation de GCCLI. Le fichier
  `deploy/railway/Dockerfile.worker` utilise `python:3.11-slim` et
  `workers.run_all`, mais l'image déployée n'a pas été construite ni testée ici.
- Les threads de renouvellement sont indépendants de l'event loop, pas du
  processus OS, du GIL, de la résolution DNS, du gel du conteneur ou d'un arrêt
  d'instance Railway. Les timeouts socket sans retry bornent l'I/O réseau
  habituelle ; ils ne prouvent pas une borne globale sous gel OS ou DNS bloqué.
- Drain complet des anciennes versions avant activation ; ne jamais intervenir
  sur le compteur legacy ou les réservations d'un worker encore vivant pour
  « débloquer » artificiellement l'admission.
- Redis doit être une autorité unique cohérente, sans éviction/FLUSH/perte de clés
  actives ou failover perdant leurs écritures ; un refus de communication reste
  un refus d'autorisation, pas un mode dégradé sans limite.
- Les scripts Lua existants utilisent plusieurs clés sans hash tag commun :
  ils requièrent un Redis compatible avec ces EVAL atomiques. Un véritable Redis
  Cluster multi-shard pourrait répondre `CROSSSLOT`. Aucun support Cluster ni
  changement de nommage n'est introduit dans C333 ; valider cette compatibilité
  dans la configuration Railway/Redis effective plutôt que l'inférer d'une URL.
- Aucun test, restart, merge ou déploiement ne vise le Redis/Garmin/Mongo runtime.

### Scénario critique reproduit : compteur correct, exécutions en chevauchement

Le nouveau test
`test_post_final_cas_pause_can_still_overlap_replacement_even_with_renewal`
dans `backend/tests/test_gccli_concurrency_c333.py` n'est ni un `xfail` ni une
assertion retirée. Il **attend et mesure** le contre-exemple suivant :

1. L'ancien détenteur passe le dernier CAS puis attend à l'entrée de l'implémentation
   réelle de `subprocess.run`, avant création du PID.
2. Sur le Redis isolé, sa réservation globale est rendue expirée et son verrou
   utilisateur retiré ; le successeur acquiert les deux réservations.
3. Le thread de renouvellement ancien détecte la perte de propriété et interdit
   les futurs appels de commande. Le successeur lance un enfant réel.
4. L'ancien appel, déjà au-delà du dernier contrôle, reprend son spawn. Les
   timestamps monotones écrits par les deux enfants montrent un chevauchement.
5. L'admission Redis compte **1** détenteur et les deux enfants tournent pour le
   même utilisateur. Le cleanup ancien n'efface toujours pas le successeur.

La mutation de réservation est imposée **dans le test isolé**, pas effectuée en
production. Elle modélise le handover devenu possible après expiration pendant
une suspension post-CAS. Avec le processus et ses threads schedulés normalement,
le nouveau renouvellement réduit fortement ce cas ; il ne supprime pas la
fenêtre logique démontrée. Le résultat positif de ce test signifie que la
reproduction du risque réussit, **pas** que l'exclusion physique est garantie.

Un second cas,
`test_sigstop_after_final_cas_pauses_renewal_and_allows_physical_overlap_after_real_expiry`,
utilise plusieurs processus et un véritable `SIGSTOP`/`SIGCONT` : le gel arrête
**aussi** le thread indépendant, les deux réservations expirent naturellement
dans Redis, un successeur est admis, puis l'ancien processus reprend après le
dernier CAS. Les enfants réels écrivent leurs intervalles d'activité séparément
du compteur Redis. Les TTL sont raccourcis uniquement dans ce test (12 s) en
conservant la marge de sécurité du code pour une commande inférieure à 1 s ;
les TTL de production ne sont pas modifiés. Ce cas n'exige pas une suppression
manuelle de clés pour mettre en évidence la fenêtre post-CAS.

La variante PTY du premier test démontre la même fenêtre dans le chemin
d'authentification. Redis est échantillonné pendant que les deux PIDs sont
effectivement vivants, avant et après la lecture du compteur : le résultat
**2 processus / 1 détenteur** n'est pas seulement déduit d'intervalles terminés.
Des cas distincts d'expiration durant une commande déjà lancée démontrent aussi
que l'ancien processus n'est pas tué immédiatement par la perte de renouvellement ;
le refus de son prochain appel et la sécurité de son release restent intacts.

### Résultats de validation C333

- **405 tests passent** dans les groupes isolés existants : **289** tests
  concurrence/livraison/C333 et **116** tests runner/provider.
- **20 cas C333** supplémentaires ; les **42 cas PR333** restent couverts.
  Aucun skip ni xfail. Les tests de reproduction du chevauchement passent parce
  qu'ils établissent le contre-exemple, non parce qu'ils prouvent une exclusion.
- Capacité par défaut : **10 processus workers concurrents**, 8 admissions,
  maximum physique mesuré séparément à **8** en conditions saines. Configuration
  réduite : 5 workers, 2 admissions et maximum physique **2**. Ces résultats
  conditionnels ne réfutent pas les contre-exemples après perte de réservation.
- Blocage de l'event loop : un enfant réel bloque la boucle au-delà de plusieurs
  périodes de renouvellement ; les leases sont raccourcies **après** son départ,
  puis sauvées par des CAS provenant du thread, sans intervention de la boucle.
- Perte de réservations : expiry globale et véritable expiration utilisateur
  par PEXPIRE, remplacement de propriétaire, refus de résurrection et release
  tardif ; jamais de renouvellement d'un détenteur déjà expiré/remplacé.
- Perte Redis réelle : `CLIENT PAUSE ALL` sur le serveur isolé pendant une
  commande réelle, timeout socket puis récupération. Le détenteur arrêté ne
  redémarre pas, même si son Lua en attente a pu finir après perte de la réponse.
  Le successeur et le cleanup ancien sont testés séparément.
- Crash SIGKILL, annulations répétées, annulation directe de la tâche interne,
  shutdown/drainage et join d'un renouvellement en cours : suites PR333/C333.
- Flake8 fatal-error et vérification whitespace : propres.

Commandes finales exécutées depuis `backend/`, configuration
`-n 2 --dist loadscope` inchangée :

```text
python -m pytest tests/test_gccli_concurrency_pr333.py tests/test_activity_laps_pr332.py tests/test_activity_laps_queue_pr332.py tests/test_activity_details_pr321.py tests/test_activity_details_delayed_redis_c321.py tests/test_garmin_queue_backfill_pr197.py tests/test_gccli_concurrency_c333.py --basetemp=.pytest_cache/c333-regression -q --tb=short
# 289 passed, 7 warnings in 44.87s
python -m pytest tests/test_garmin_daily_metrics_pr03.py tests/test_garmin_vo2max_pr195.py tests/test_garmin_deep_sync.py --basetemp=.pytest_cache/c333-runner -q --tb=short
# 116 passed in 1.07s
python -m flake8 sync/execution_lease.py workers/sync_worker.py garmin/runner.py tests/test_gccli_concurrency_pr333.py tests/test_gccli_concurrency_c333.py tests/test_activity_laps_queue_pr332.py --select=E9,F63,F7,F82
git diff --check
# exit 0, sans sortie
```

Les 7 avertissements comprennent les dépréciations existantes et deux
avertissements Python liés au fork PTY dans un processus multithreadé. Le chemin
PTY existant est conservé et couvert ; cela reste un point de compatibilité
runtime Python à examiner, pas une validation de l'image Railway.

Les assertions de queue/ACK/watchdog, déduplication, réservations details/laps,
backoffs et persistance C332 sont conservées dans les groupes de régression.
Les modules Garmin métier, Mongo/historique, frontend, abonnement et tous les
moteurs physiologiques sont inchangés. Aucun drift local n'est réécrit.

Un essai groupant les dix suites dans **un seul processus de collection pytest**
a rencontré une pollution préexistante des stubs du module `feed` entre tests.
Les groupes d'exécution séparés utilisés par le rapport PR333 initial passent.
Cette tentative échouée est conservée dans les résultats ; aucun test étranger
au périmètre n'est réécrit pour la masquer.
L'essai commun arrêté avec `-x -o faulthandler_timeout=30` rapporte
**2 failed, 104 passed, 3 warnings** : deux tests de routes authentifiées échouent
à importer `api/garmin.py:30` avec
`ModuleNotFoundError: No module named 'feed.sse'; 'feed' is not a package`.
`test_garmin_deep_sync.py` crée à la collection des stubs globaux `feed` et
`config` sans restauration ; l'audit indépendant confirme ce comportement
préexistant. Le périmètre C333 ne le corrige pas.

Comme précédemment, aucun test destructif runtime, suite backend entière, image
Docker/Railway, benchmark ou essai Garmin distant n'est exécuté. Les preuves
concernent le sandbox, un Redis loopback par fixture et des commandes simulées.

La review spécialisée read-only de la correction ne trouve aucun problème
significatif supplémentaire ; elle ne conclut pas à un PASS physique.
La validation CodeQL Python sur le code correctif commité indique **0 alerte**.
L'outil de review automatisée reste indisponible pour cause de modèle absent ;
son affichage « succès / aucun commentaire » n'est pas une validation effective.

### Verdict courant

**BLOCKED pour une garantie stricte d'absence de chevauchement physique.**

La correction indépendante de l'event loop et le refus des changements observés
avant le dernier CAS ne suffisent pas à clôturer le risque après ce CAS.
La sûreté du bookkeeping Redis et l'absence de corruption par cleanup tardif
sont des propriétés distinctes, conservées ; elles ne justifient pas un PASS
global. La décision de merge nécessite soit le mécanisme de fencing décrit
ci-dessus, soit une acceptation explicite d'une garantie moins forte par l'audit
utilisateur. Aucun merge ni déploiement n'est proposé automatiquement.

## Finalisation locale C333 — 14 octobre 2026

### Références et périmètre

- Base distante `copilot/dev` vérifiée :
  `70fd6344b10edf61ba9877731837689943d9c30e`.
- HEAD distant de la PR existante #333, branche
  `copilot/fiabilisation-limiteur-global-gcccli`, et HEAD local avant modification :
  `5f672601e9e735eb599c1af8c7157eac3b580f5d`.
- Les deux anciens commits inaccessibles ne sont ni récupérés ni reconstruits.
  Cette finalisation part exclusivement du HEAD distant vérifié.
- Seuls `deploy/railway/Dockerfile.worker` et ce rapport sont modifiés.
  Aucun changement de code métier, de tests, de dépendances Python ni de drift
  Emergent, notamment `activity_day`. Aucune écriture sur la base d'intégration,
  aucune nouvelle PR, aucun merge, push, déploiement ou accès runtime.
- Le SHA final local est fourni dans la réponse de finalisation ; ce rapport
  fait partie de ce commit et ne peut contenir son propre SHA.

### Contrôles du code existant

L'audit confirme, sans réimplémentation :

- `sync/execution_lease.py:105-144` renouvelle les leases dans un thread dédié
  via un client Redis synchrone, indépendamment de l'event loop asyncio.
- `sync/execution_lease.py:146-164` vérifie les deux propriétaires par CAS Lua ;
  `garmin/runner.py:107-120` et `:210-213` appellent ce dernier contrôle
  immédiatement avant `subprocess.run` et `pty.fork`.
- Le nettoyage worker conserve drainage, arrêt/join du renouvellement puis
  libération conditionnée aux tokens. Les retries et la queue sont inchangés.

### Modification Railway et construction exacte

`coreutils` est maintenant explicitement demandé par l'installation apt du
Dockerfile worker. Les URLs privées, le hash de la wheel et la commande pip
d'origine restent inchangés.

Commande exécutée depuis le checkout local :

```text
docker build --progress=plain -f deploy/railway/Dockerfile.worker -t runindex-c333-final-local:check .
```

Résultat : **échec, exit 1**, à l'étape pip, `Dockerfile.worker:17-20`.
La couche apt réussit et indique `coreutils 9.7-3`, déjà présent et désormais
marqué explicitement installé. Le téléchargement de la wheel privée litellm
échoue avec `[Errno -5] No address associated with hostname` pour
`customer-assets.emergentagent.com`.
Les contrôles de résolution applicative du sandbox échouent aussi pour
`d33sy5i8bnduwe.cloudfront.net`, alors que `pypi.org` résout.
Ce résultat n'affirme pas que ces domaines sont globalement inexistants.
Aucun remplacement d'artefact privé, changement DNS/hosts, téléchargement via
IP ou retrait de dépendance n'est utilisé.

**L'image worker complète n'a pas été créée et GNU timeout n'y est donc pas
validé.** Une sonde indépendante, sans réseau, dans la seule image de base
`python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`
confirme GNU timeout 9.7 et la terminaison SIGKILL de commandes Python simulées,
en subprocess et PTY (terminal maintenu ouvert jusqu'au reap). Cette preuve
limitée ne remplace pas un build ni une validation du worker complet.

### Tests frais et limites

Le code Python et les tests sont identiques au HEAD distant ci-dessus.
Les deux groupes canoniques séparés de la section précédente sont réexécutés
avec `python -m pytest`, `-n 2 --dist loadscope` conservé, caches et basetemp
sous `/tmp`, sans écrire dans le checkout :

```text
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_gccli_concurrency_pr333.py tests/test_activity_laps_pr332.py tests/test_activity_laps_queue_pr332.py tests/test_activity_details_pr321.py tests/test_activity_details_delayed_redis_c321.py tests/test_garmin_queue_backfill_pr197.py tests/test_gccli_concurrency_c333.py -q --tb=short -n2 --dist loadscope -o cache_dir=/tmp/c333-final-local-cache --basetemp=/tmp/c333-final-local-temp
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_garmin_daily_metrics_pr03.py tests/test_garmin_vo2max_pr195.py tests/test_garmin_deep_sync.py -q --tb=short -n2 --dist loadscope -o cache_dir=/tmp/c333-final-runner-cache --basetemp=/tmp/c333-final-runner-temp
```

- Sept suites PR333/C333, laps PR332, details et queue : **289 passed,
  7 warnings, 45.67 s**.
- Trois suites runner/daily metrics/VO2max/deep sync : **116 passed, 2.49 s**.
- Total : **405 passed**. Redis isolés en loopback uniquement ; aucun Redis,
  Garmin, Mongo ni Railway de production utilisé. Les tests n'ajoutent aucun
  changement au checkout. Les avertissements comprennent ceux du fork PTY
  multithreadé déjà décrits dans la section historique.

Les tests de chevauchement restent des reproductions réussies du risque :
**deux commandes physiques pour un détenteur Redis** sont possibles après
le dernier CAS, notamment lorsque le processus entier est suspendu et que
ses leases expirent. Le thread résout le blocage de l'event loop, pas une
suspension de processus ni l'atomicité entre Redis et le lancement OS.
**BLOCKED demeure le verdict pour une garantie physique stricte** ; aucun
nouveau fencing distribué n'est ajouté.

Les workflows GitHub consultés sont des exécutions d'agents, pas une preuve
de construction de l'image Railway. Les résultats ci-dessus sont ceux du
sandbox et ne constituent pas une validation de production.
