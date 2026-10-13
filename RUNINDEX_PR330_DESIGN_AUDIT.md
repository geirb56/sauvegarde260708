# RUNINDEX — Audit de conception PR #330

**Garmin Lap Data Acquisition & Workout Analysis V2**  
**Mode : audit strictement en lecture seule**

## Périmètre et limites

Cet audit s’appuie sur le code et les rapports présents dans le dépôt. Aucun appel Garmin, accès en écriture Mongo, lancement de worker, backfill ou réimport n’a été effectué. Les constats runtime concernant les activités A et B sont ceux fournis dans la demande et n’ont pas été reproduits ici.

## 1. Architecture existante et provenance

### Acquisition et persistance

- La commande d’acquisition déjà implémentée est **`gccli activity typed-splits <id> -j`**, invoquée par `GccliRunner.fetch_activity_typed_splits()` avec un seul essai ; le runner ajoute `-j` à ses commandes JSON. ([`backend/garmin/runner.py:92-105,233-242`](backend/garmin/runner.py#L92-L105))
- `GccliProvider.get_activity_phases()` exige le compte Garmin associé à l’utilisateur, valide l’identifiant de l’activité retournée et transmet le payload au normaliseur `normalize_typed_splits()`. ([`backend/garmin/providers/gccli_provider.py:109-120`](backend/garmin/providers/gccli_provider.py#L109-L120))
- Le contrat `typed-splits` documenté dans le dépôt est `{activityId, activityUUID, splits}` ; les lignes observées ont notamment `type`, durée en secondes, distance en mètres, vitesse en m/s, FC en bpm, `messageIndex` et `startTimeGMT`. Le rapport C321 précise que ce contrat découle de l’audit Emergent fourni, et que les tests reconstruisent des payloads : ce ne sont pas des captures brutes présentes dans le dépôt. ([`backend/garmin/data_layer.py:16-18,186-269`](backend/garmin/data_layer.py#L16-L18), [`RUNINDEX_PR321_ACTIVITY_DETAILS_ENRICHMENT_REPORT.md:271-282`](RUNINDEX_PR321_ACTIVITY_DETAILS_ENRICHMENT_REPORT.md#L271-L282))
- La commande **`activity splits`** et son enveloppe `lapDTOs` ne sont pas intégrées au provider actuel. Le contexte fourni pour l’activité A rapporte 22 `lapDTOs`, mais le dépôt ne contient ni capture brute ni contrat vérifiable de cette réponse. Il ne faut donc pas transposer automatiquement le schéma `typed-splits` aux laps.
- Le résultat `typed-splits` est persisté dans `garmin_activities.activity_details`, avec version, statut, provenance, endpoint et phases. Le cache considère `complete` **et `no_data`** comme terminaux pour la version courante. ([`backend/garmin/activity_details.py:15,24-36,54-104`](backend/garmin/activity_details.py#L15-L36))
- La synchronisation des résumés reste distincte : `_ingest_activities()` retire les champs d’enrichissement connus puis fait un `$set` du résumé, sans remplacer le document. Si un nouveau sous-document lap est introduit, il faut aussi le protéger explicitement contre un écrasement accidentel par cette ingestion. ([`backend/garmin/service.py:558-580`](backend/garmin/service.py#L558-L580))

### Worker, API et autorisation

- L’enrichissement actuel est déclenché explicitement par les routes POST/GET `/activities/{activity_id}/phases`. Le POST met en file ; le GET consulte Mongo et renvoie l’état `activity_details`. ([`backend/api/garmin.py:152-190`](backend/api/garmin.py#L152-L190))
- La queue fournit livraison fiable au moins une fois, déduplication de job, traitement différé et watchdog. Le worker réutilise le verrou par utilisateur, la limite globale et les retries bornés. ([`backend/jobs/queue.py:19-30,166-218,240-326`](backend/jobs/queue.py#L19-L30), [`backend/workers/sync_worker.py:104-162,185-218`](backend/workers/sync_worker.py#L104-L162))
- La réservation Mongo est ciblée par `(user_id, external_id, source="garmin")`, utilise un jeton de clôture, un bail de 900 s et un délai de retry de 300 s. Le contrôle et la lecture du document sont limités au même utilisateur. ([`backend/garmin/activity_details.py:24-29,39-51,63-116`](backend/garmin/activity_details.py#L24-L51))
- L’ingestion et le GET V2 ne déclenchent pas eux-mêmes le fetch des phases. Aucun nouveau chemin d’acquisition ne doit être implicitement déclenché par un simple rendu d’écran. ([`backend/garmin/activity_details.py:39-51`](backend/garmin/activity_details.py#L39-L51), [`backend/workout_analysis_v2_service.py:253-305`](backend/workout_analysis_v2_service.py#L253-L305))

### Workout Analysis V2 et écrans

- Le service V2 charge d’abord le workout avec `id + user_id`, puis retrouve l’activité Garmin avec le même utilisateur. L’enrichissement est une copie en mémoire : il extrait déjà cadence moyenne, dénivelé, vitesse, FC et éventuellement `km_splits`, sans persister ces changements dans `workouts`. ([`backend/workout_analysis_v2_service.py:100-117,120-198,253-305`](backend/workout_analysis_v2_service.py#L100-L117))
- Le cache de phases V2 accepte exclusivement `activity_details` à la bonne version, `complete`, avec endpoint `typed-splits`. `no_data` ne fournit donc pas de phases à l’analyse. ([`backend/workout_analysis_v2_service.py:201-250`](backend/workout_analysis_v2_service.py#L201-L250))
- L’API d’analyse renvoie le contrat `WorkoutAnalysisV2Response`; elle utilise le loader ci-dessus et ne déclenche pas d’acquisition. ([`backend/server.py:2124-2146`](backend/server.py#L2124-L2146))
- L’analyse d’allure consomme `km_splits`; les observations de cadence et de dénivelé sont des faits descriptifs du moteur existant, pas des champs de premier niveau visibles dans le contrat d’analyse. ([`backend/workout_analysis_v2.py:730-737,1197-1205`](backend/workout_analysis_v2.py#L730-L737))
- Les trois écrans consomment déjà un composant partagé pour les phases et `WorkoutKilometerSplits`. Ce dernier exige `km` et `pace_min_km`, filtre les entrées invalides et les présente explicitement comme kilomètres : il n’est donc **pas** un composant générique pour des tours Garmin de longueur variable. ([`frontend/src/components/workout/WorkoutKilometerSplits.jsx:3-10,14-38`](frontend/src/components/workout/WorkoutKilometerSplits.jsx#L3-L10), [`frontend/src/pages/WorkoutDetail.jsx:239-245`](frontend/src/pages/WorkoutDetail.jsx#L239-L245), [`frontend/src/pages/SessionDetail.jsx:172-178`](frontend/src/pages/SessionDetail.jsx#L172-L178), [`frontend/src/pages/DetailedAnalysis.jsx:131-137`](frontend/src/pages/DetailedAnalysis.jsx#L131-L137))
- Les routes `/workouts/{id}` ne renvoient que le document produit `workouts`, scopé par utilisateur. Pour transporter des laps venant de `garmin_activities`, le passage par l’analyse V2 est cohérent : les trois écrans chargent déjà cette API. ([`backend/server.py:786-796,2124-2146`](backend/server.py#L786-L796))

## 2. Causes confirmées et hypothèses

### Confirmé par le code

1. `typed-splits` et des `lapDTOs` sont deux voies distinctes. Le normaliseur courant n’accepte qu’un objet racine avec `splits` et classe `INTERVAL_*`; il ne normalise pas les tours de la commande `activity splits`. ([`backend/garmin/data_layer.py:186-202`](backend/garmin/data_layer.py#L186-L202))
2. `no_data` de `typed-splits` est un cache négatif valable pour **cet endpoint et ce schéma**, pas une preuve que `activity splits` serait vide. Toutefois, réutiliser `activity_details._cached()` comme condition générale d’arrêt du nouveau fetch bloquerait les laps. ([`backend/garmin/activity_details.py:32-36,54-59`](backend/garmin/activity_details.py#L32-L36))
3. `WorkoutKilometerSplits` attend déjà des splits kilométriques normalisés, alors que les observations rapportées peuvent être manuelles, partielles ou de formats différents. Les transformer toutes en kilomètres créerait une sémantique incorrecte.
4. La couche V2 peut déjà enrichir cadence et dénivelé depuis l’activité Garmin, mais ces valeurs ne sont pas actuellement exposées comme métriques autonomes de l’API V2 ni présentées systématiquement sur les trois écrans. ([`backend/workout_analysis_v2_service.py:151-169`](backend/workout_analysis_v2_service.py#L151-L169), [`backend/workout_analysis_v2.py:1197-1205`](backend/workout_analysis_v2.py#L1197-L1205))

### Non vérifié dans ce mode

- La disponibilité des `lapDTOs` pour l’activité B, les champs exacts et les règles Garmin de génération des tours automatiques/manuels/partiels.
- Le nom et l’unité de chaque propriété de `lapDTOs` dans le payload réel de GCCLI v1.9.0. Ne pas coder un mapping sur la seule base des noms habituels Garmin.
- L’interprétation exacte de `lapTriggerMethod`, ou d’un indicateur analogue, s’il existe dans la réponse concernée. Ne pas inférer « manuel » d’un numéro ou de la distance.
- Les chiffres A/B du contexte restent des constats rapportés par la demande ; ils n’ont pas été reproduits par un accès runtime dans cet audit.

## 3. Contrat de données recommandé

Ajouter un cache **indépendant** de phases, par exemple `garmin_activities.activity_laps` et `activity_laps_fetch`. Ne pas placer les laps dans `activity_details.phases`, ni les recopier directement dans `workouts.km_splits`.

Contrat minimal proposé :

- Enveloppe de cache : `schema_version`, `source="garmin"`, `endpoint="activity-splits"`, `status`, `fetched_at`, `laps`.
- Statuts distincts : `complete`, `partial`, `no_data`, `failed`. Une réponse vide **reconnue** peut être `no_data`; une enveloppe absente ou malformée ne peut pas être mise en cache comme absence de données.
- Chaque tour conserve l’ordre reçu, son numéro natif si fourni, son type/mode de déclenchement uniquement si documenté, puis les mesures vraiment présentes.
- Unités normalisées indépendantes des noms natifs : distance en mètres, durée en secondes, vitesse en m/s, FC en bpm, cadence en spm, dénivelé positif en mètres. Les valeurs absentes ou invalides restent `null`; ne pas compléter par zéro.
- Conserver des laps de distance quelconque. Ne créer un `km_splits` que si une règle séparée, explicitement validée, prouve qu’il s’agit d’un kilomètre complet. Un dernier tour partiel demeure un tour partiel.
- Ne calculer ni type de séance, ni intensité, ni conclusion physiologique à partir des tours. Les `INTERVAL_*` structurés restent du domaine de `ActivityPhase`.

Avant d’implémenter le normaliseur, il faut une fixture brute anonymisée et validée de la réponse `activity splits`, ou une source de contrat équivalente. L’audit actuel ne peut pas confirmer ce payload sans violer les contraintes d’absence d’appel Garmin.

## 4. Stratégie de cache, concurrence et idempotence

- Utiliser une clé/cache et une version indépendants de `activity_details`. Une version ou absence de cache lap ne doit jamais dépendre du statut `no_data` de `typed-splits`.
- Réserver, lire et écrire le document avec `(user_id, external_id, source)`, sans upsert ; écrire sous un jeton de réservation pour empêcher un ancien job d’écraser le résultat d’un nouveau.
- Conserver la politique « réponses valides positives ou négatives cachées par version », mais laisser les erreurs techniques et payloads malformés retryables.
- Faire un remplacement idempotent du snapshot des laps reconnus au sein de la seule section lap. La livraison au moins une fois ne doit pas dupliquer des lignes. Ne pas dédupliquer les tours sur leur seule distance ou durée : des tours légitimement répétés pourraient coïncider.
- Réutiliser l’infrastructure queue/worker existante, mais isoler les états de fetch et protéger les champs lap des écritures de sync. Si un nouveau job type est introduit, lui donner une déduplication explicite et conserver verrou utilisateur, limite globale, watchdog, délai/retry et protection par bail.
- Une file au niveau utilisateur peut sérialiser plusieurs activités d’un même utilisateur ; cette propriété est à préserver ou à décrire explicitement, pas à contourner par des jobs concurrents.
- Pas de fetch massif, backfill, migration, ni appel automatique au simple GET V2. L’acquisition reste ciblée et déclenchée explicitement.

## 5. Risques et protections

- **Assimilation d’un lap à un kilomètre :** conserver un contrat `recorded_laps` distinct de `km_splits`; l’UI dit « tours enregistrés » et montre distance/durée observées.
- **Perte de nature de tour :** préserver l’ordre et les indicateurs natifs documentés; ne pas classifier automatique, manuel ou partiel par heuristique.
- **Fausse absence :** seuls les payloads reconnus et valides peuvent devenir `no_data`; erreur, mauvais wrapper ou réponse incohérente doivent échouer sans effacer d’ancien résultat.
- **Cache négatif typed-splits :** garder `activity_details` et `activity_laps` indépendants au niveau cache, réservation, statut et éligibilité aux retries.
- **Régression des phases :** ne pas élargir `_cached_activity_phases()` ni changer sa condition `endpoint == "typed-splits"` ; ne pas modifier le mapping des `INTERVAL_*`.
- **Fuite inter-utilisateur :** maintenir l’identité scoppée par `user_id` lors de l’enqueue, des lectures Mongo, des écritures et de la réponse V2.
- **Écrasement par sync :** ajouter la protection de champs lap au chemin d’ingestion si nécessaire; celui-ci reste le chemin qui met à jour les résumés.
- **Unités et valeurs invalides :** convertir depuis un schéma source confirmé; refuser booléens, infinis, valeurs négatives invalides et conversions ambigües.
- **Affichage trompeur :** les observations factuelles de cadence/dénivelé restent séparées des réserves physiologiques; aucune modification des catégories `long`/`standard`, de l’intensité ou des calculs existants.
- **Historique :** cache absent sur les activités anciennes signifie « pas encore acquis », pas « aucun lap ». Aucun réimport massif n’est requis.

## 6. Matrice de tests requise

| Cas | Vérifications |
|---|---|
| Course continue, tours kilométriques | ordre, unités, mesures, restitution des tours; pas de conversion implicite en `km_splits` |
| Course continue, tours manuels | indicateur natif conservé seulement s’il est présent; aucun reclassement arbitraire |
| Dernier tour partiel | distance réelle conservée; étiquette « partiel » seulement si étayée; pas de complétion à 1 km |
| Fractionné avec `INTERVAL_*` | phases `typed-splits` inchangées; laps non injectés dans `phase_analysis` |
| Activité sans détails | cache absent/état explicite, réponse compatible avec les activités historiques |
| Payload vide ou malformé | vide reconnu → `no_data`; enveloppe invalide → échec retryable, sans fausse absence |
| Cache `typed-splits=no_data` | demande lap encore possible et indépendante |
| Plusieurs formats de tours | adapter uniquement les formes documentées; données inconnues rejetées ou conservées sans inventer de sémantique |
| Requête répétée/redelivery/concurrence | pas de doublon de stockage, jeton obsolète sans effet, retry/bail corrects |
| Isolation et accès | activité d’un autre utilisateur introuvable; aucun cross-user dans queue, Mongo ou V2 |
| Trois écrans | mêmes tours, cadence et dénivelé sur `WorkoutDetail`, `SessionDetail`, `DetailedAnalysis`; champs absents omis |
| Non-régression | tests phases, km-splits, classifications, intensité et observations existants inchangés |

## 7. Découpage minimal des PR

**Recommandation : deux PR, pas une PR end-to-end.** Acquisition/persistance et transport/présentation sont deux responsabilités indépendantes, avec critères de validation différents. Les séparer évite de mêler une intégration GCCLI encore dépendante du contrat réel à une modification UI.

1. **PR acquisition/persistance** — ajouter le fetch ciblé, le contrat normalisé lap, son cache versionné et sa route/job dédiée; protéger sync, queue et isolation. Objectif vérifiable : un payload vérifié peut être récupéré et persisté de façon idempotente, sans changement de `typed-splits` ni réimport.
2. **PR restitution V2** — ajouter un champ additif de données observées à l’API V2, exposer cadence/dénivelé et laps cachés, puis présenter le même composant factuel sur les trois écrans. Objectif vérifiable : les données persistées apparaissent de façon cohérente, sans alimenter les moteurs ou classifications existants.

Si le contrat lap réel n’est pas validé, la PR acquisition ne doit pas être considérée prête à implémenter.

## 8. Critères d’acceptation

- Contrat de réponse `activity splits` validé par une fixture brute anonymisée, avec unités documentées.
- Laps récupérés uniquement sur activité/utilisateur existants et reliés par identité scoppée.
- Aucune transformation automatique en kilomètres, phases ou intensité.
- `typed-splits` et ses caches `complete`/`no_data` restent inchangés et indépendants.
- Cache négatif ou cache absent typed-splits ne bloque pas un fetch lap.
- Retries, réservation, concurrence et erreurs ne créent ni doublon ni faux `no_data`.
- Cadence moyenne et dénivelé déjà disponibles sont affichés comme observations factuelles.
- Les trois écrans partagent la restitution, et les données absentes/partielles restent explicites.
- Tests de non-régression des phases, splits existants, classes, intensités, observations et accès utilisateur réussis.
- Aucun changement Training V2, Coach, moteur physiologique, `activity_day`, historique, ou prescription.

## 9. Recommandation GO / NO-GO

**GO conditionnel pour l’architecture à deux PR ; NO-GO pour une PR unique et pour coder un normaliseur lap avant validation du payload.**

Le plus petit changement cohérent est un cache lap indépendant, ciblé et versionné, puis un transport additif dans l’API V2 et un rendu partagé. Cette séparation respecte les limites de `WorkoutKilometerSplits`, empêche `typed-splits=no_data` de masquer les laps et évite de reconstruire le moteur. Le contrat exact de `lapDTOs` demeure la dépendance bloquante; l’activité B n’a pas été vérifiée dans cet audit.

**Arrêt après le rapport. Aucune implémentation ni PR #330 n’est créée; validation explicite attendue avant toute suite.**
