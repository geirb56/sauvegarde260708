# RUNINDEX — C346 · Audit Coach Judgment V1

**Audit en lecture seule — 19 octobre 2026**

## Références et périmètre vérifiés

- Dépôt : `geirb56/sauvegarde260708`.
- Branche canonique : `copilot/dev`.
- Base canonique vérifiée : `copilot/dev@6c9072fcd24ee4f1b47cff9ca84ae0e6c70a26f8`.
- Branche d’audit : `copilot/audit-coach-judgment-v1`.
- HEAD audité : `6c9072fcd24ee4f1b47cff9ca84ae0e6c70a26f8`.
- Arbre de travail propre au début de l’audit.
- C345 : PR #345 confirmée fusionnée dans la base auditée.
- C344 : PR #344 encore ouverte, en brouillon et non fusionnée lors de la vérification; head `108cd007cb11ce833cd3dc0e64fa449fb11d884d`, base de cette PR `1426de94323472139b1b64320c6557d02185df6b`. Ses statuts de comparabilité par métrique ne sont donc pas le contrat de la base auditée.
- Tests : **aucun exécuté**, conformément au périmètre strictement en lecture seule.
- Aucune lecture de MongoDB ou Redis runtime, synchronisation, acquisition Garmin, écriture, appel LLM ou backfill n’a été effectué.

Le code, les tests et les rapports historiques ont été consultés. Les rapports antérieurs et les fixtures synthétiques sont des éléments de contexte, pas une preuve d’état runtime.

## 1. Architecture actuelle

Flux observé dans le code :

`Garmin → garmin_activities → workouts dérivé → Workout Analysis V2 → Coach Language V1 → API → WorkoutDetail`

- `garmin_activities` est la source d’ingestion; `workouts` est une projection produit/UI reconstruisible (`backend/workers/event_worker.py`).
- Le service d’analyse charge le workout par `id + user_id`, recherche l’activité Garmin correspondante par identifiant et utilisateur, puis lit les phases déjà mises en cache. Il ne déclenche pas d’acquisition (`backend/workout_analysis_v2_service.py`).
- Workout Analysis V2 rassemble métriques, comparaisons, limitations, phases et observations factuelles avec preuves numériques.
- Coach Language V1 est ajouté au contrat V2 et consomme les phases, comparaisons et observations validées. Le GET `/coach/workout-analysis/{workout_id}` renvoie l’analyse déterministe sans appel LLM (`backend/server.py`).
- Le chat Coach utilise l’analyse sélectionnée dans un contexte plus large, puis appelle le LLM et persiste la conversation. Ses instructions interdisent les prescriptions et inférences non prouvées, mais n’assurent ni déterminisme ni identité de conclusion avec Coach Language.
- Le contexte Coach comprend aussi Training V2, données actuelles et historique borné. Les contrôles FREE/TRIAL/PREMIUM protègent l’analyse personnalisée.

**Conclusion d’architecture :** le Coach déterministe et le Coach LLM peuvent partager l’analyse canonique, mais leurs contextes et garanties diffèrent. Une divergence de formulation ou de jugement reste possible; le prompt seul ne remplace pas une validation structurée.

## 2. Inventaire des données réellement disponibles

| Donnée | Contrat présent | Provenance et limites |
|---|---|---|
| Distance, durée, allure et FC globales | Oui, selon les champs persistés | Résumé Garmin et projection `workouts`; une valeur absente reste absente |
| Phases typées | Oui, si cache Garmin schema v2 `complete` et valide | Ordre, type, durée, distance, vitesse et FC moyenne/max/min; chaque métrique peut manquer |
| Splits kilométriques | Oui, si valides et persistés | Contrat distinct des phases; adaptateur avec règles strictes de validation |
| Récupérations | Mesures de phase possibles | Ne démontrent pas l’intensité ni la qualité physiologique de récupération |
| Séries temporelles HR/allure seconde par seconde | Non démontrées dans le chemin audité | L’analyse consomme des phases/splits agrégés, pas une série continue documentée |
| Prescription structurée | Oui, si snapshot structuré enregistré | Étapes, répétitions, récupération et cible de pace éventuelle |
| Historique | Partiel | Coach Context : 30 jours, maximum 30 activités; Workout Analysis : fenêtre de 180 jours, candidats bornés à 200 puis maximum 5 références |

La présence d’un champ dans le modèle ou une fixture ne prouve pas qu’il existe pour une activité donnée.

## 3. Audit des prescriptions

Training V2 sait produire des prescriptions structurées : étapes, répétitions, durée ou distance par répétition, récupérations et cible de pace lorsque les Training Paces sont disponibles. Les récupérations sont intégrées au bloc; leur nombre correspond aux intervalles entre répétitions et leur distance n’est pas inventée (`backend/training_v2/structured_workout.py`).

Les prescriptions servies peuvent être gelées dans des snapshots immuables, indexés par utilisateur et `prescription_id` (date et jour). En revanche, l’absence de snapshot historique signifie prescription **indisponible** : le plan actuel ne doit pas servir à reconstruire le passé (`backend/training_v2/prescription_snapshot.py`, `week_execution.py`).

Training V2 possède aussi un rapprochement déterministe entre prescriptions et activités Garmin. Il exige notamment l’utilisateur, le type de course, la date locale prévue et des dimensions comparables; il laisse les cas ambigus sans attribution. Ses tolérances agrégées sont des règles techniques, pas des seuils d’exécution par bloc (`backend/training_v2/performed_workout.py`).

**Blocage :** l’analyse d’une activité ne consomme ni ce rapprochement ni le snapshot correspondant. Aucun lien historique persistant activité–prescription et effectivement lu par Coach Analysis n’a été démontré. La date seule ne suffit pas.

| Critère | Donnée disponible | Provenance | Fiabilité | Jugement possible |
|---|---|---|---|---|
| Type et volume prescrits | Oui, si snapshot retrouvé | Prescription servie | Bonne pour un snapshot faisant autorité | Comparaison agrégée de type/durée/distance |
| Objectif historique | Pas toujours figé | Goal/plan distinct | Insuffisante si le plan a évolué | Abstention sans source datée |
| Répétitions, durées et récupérations | Oui, si structure gelée | Snapshot structuré | Bonne pour les champs enregistrés | Par bloc si phases réellement alignables |
| Allure cible | Parfois | Training Paces dans la structure | Dépend de leur disponibilité et du snapshot | Cible explicite seulement |
| Tolérance d’exécution | Comparaison agrégée disponible | Moteur `performed_workout` | Règle générale, pas calibrée par bloc | Écart agrégé, pas conformité des intervalles |
| Association activité–prescription | Matching séparé possible | Ledger Training V2 | Non utilisable si absent ou ambigu | Uniquement si association confirmée |

### Jugements d’exécution

**Démontré :** Training V2 peut rapprocher une activité à une prescription dans son périmètre agrégé lorsque ses entrées sont fiables.

**Manquant dans l’analyse :** joindre cette ligne à l’activité sélectionnée, puis aligner chaque phase observée avec l’étape prescrite correspondante. Des efforts observés ne sont pas automatiquement les blocs du plan.

Le jugement P0 est donc conditionnel : activité exacte rattachée à une ligne `matched` non ambiguë, snapshot réellement servi présent, structure gelée et phases complètes et alignables. Hors de ce sous-ensemble, abstention.

## 4. Réponse à l’effort

Avec un cache de phases complet et valide, le moteur calcule une cohorte selon la durée ou la distance, puis des moyennes, dispersions, extrêmes et évolutions de FC. Les allures incohérentes sont écartées; les limites et données manquantes sont exposées (`backend/workout_analysis_v2.py`).

Cela peut justifier des constats bornés : efforts mesurés comparables en durée/distance, étendue d’allure, efforts le plus rapide/lent, valeurs HR entre efforts comparables, ou splits observés sur une sortie continue quand leur validation le permet.

Cela ne permet pas d’affirmer LT1/LT2, dérive physiologique, lactate, VO₂max sollicitée, fatigue, surentraînement ou cause d’une hausse de FC. La FC entre répétitions est une évolution mesurée, pas une dérive cardiaque.

**Point de vigilance :** `physiology.hr_drift` peut recopier une valeur entrante `hr_analysis.hr_drift`, mais aucun producteur runtime fiable n’a été établi. Les tests empêchent sa promotion en fait utilisateur; cette donnée ne doit pas devenir une preuve de dérive sans provenance et définition vérifiées.

## 5. Comparaisons historiques

Workout Analysis recherche des activités de même sport sur 180 jours et sélectionne des références de distance comparable. Le contrat courant utilise une comparabilité globale, avec limitations d’effectif et de nature de séance. Les différences insuffisamment défendables doivent rester descriptives.

Cette sélection n’établit pas que deux séances ont une structure comparable : durées d’effort, nombre de répétitions et récupérations ne sont pas des critères suffisants de la recherche similaire. Le contexte récent du Coach est encore plus borné (30 jours, maximum 30).

C344 proposerait des statuts de comparabilité séparés pour allure et FC, mais elle n’est pas fusionnée dans la base auditée et ne résout pas à elle seule la comparabilité des structures. Pas de conclusion de progrès/régression à partir de simples moyennes lorsque les séances ne sont pas comparables.

## 6. Étude de cas — 10 octobre 2026

**Les données réelles de `garmin-24671804067` n’ont pas été revérifiées.** Les valeurs 4 × 4 min, allures 4:48, 4:42, 4:31, 4:51/km et FC moyennes 151, 157, 159, 159 bpm figurent dans les rapports existants comme données de référence synthétiques. Le rapport PR322 précise qu’il ne s’agit pas d’une lecture MongoDB runtime.

Sous réserve que les mêmes phases soient confirmées par une lecture réelle autorisée :

1. Le moteur peut décrire les quatre efforts ordonnés, leurs durées, allures et FC, si ces champs sont présents et valides.
2. Il ne peut pas établir si l’activité respecte la prescription sans retrouver la prescription réellement servie.
3. Aucune preuve runtime ne démontre que le snapshot du 10 octobre est retrouvable.
4. Si les quatre durées sont réellement de 240 s et les allures valides, ces efforts sont comparables selon le critère technique de durée (tolérance 20 %). Cela ne prouve ni une cible commune ni l’intention prescrite.
5. Un constat utile serait l’étendue d’allure et la série de FC entre répétitions, avec la source et la couverture.
6. Il serait abusif d’appeler la troisième répétition « trop rapide », de conclure à une bonne/mauvaise exécution, à une dérive, à une fatigue ou à une cause physiologique.
7. Amélioration minimale : valider les phases réelles; joindre un snapshot via matching confirmé et non ambigu; comparer les blocs uniquement si leur alignement est explicite. Sinon, proposer le constat P1 ou s’abstenir.

Un descriptif de l’écart entre première et dernière répétition reformule les métriques, mais ne juge pas la conformité à l’entraînement.

## 7. État des trois autres séances

Les activités `garmin-24617769451` (05/10), `garmin-24701222152` (12/10) et `garmin-24737607543` (15/10) n’ont pas de documents runtime vérifiés dans cet audit. Leur état d’enrichissement est **inconnu**, non « enrichi » ou « non enrichi ».

C345 sélectionne au plus une activité par synchronisation et deux acquisitions ciblées au maximum. Son curseur mémorise les tentatives/résultats de demandes, pas l’achèvement de l’enrichissement. Son merge ne prouve donc pas l’état des quatre IDs de cette étude.

| Séance | Données runtime vérifiées | Observations/jugements possibles | Abstention |
|---|---|---|---|
| 05/10 — `garmin-24617769451` | Aucune | Aucun jugement spécifique à l’activité | Oui |
| 12/10 — `garmin-24701222152` | Aucune | Aucun jugement spécifique à l’activité | Oui |
| 15/10 — `garmin-24737607543` | Aucune | Aucun jugement spécifique à l’activité | Oui |

## 8. Garde-fous

**Déjà présents**

- Calculs déterministes, observations structurées, valeurs finies et preuves numériques.
- Localisation FR/EN/ES.
- Provenance, ordre, métriques facultatives et limitations pour les phases.
- Intensité indisponible sans provenance de zones fiable.
- Instructions LLM interdisant d’inventer prescription, seuil et causalité.
- Accès à l’analyse personnalisée protégé pour FREE/TRIAL/PREMIUM; Coach général soumis aux règles de quota existantes.

**À renforcer pour Judgment V1**

- Relation traçable entre activité et prescription effectivement servie, incluant provenance et statut du matching.
- Alignement et comparaison par bloc prescrit.
- Comparabilité historique qui inclut structure et récupérations.
- Contrat de jugement distinguant verdict, preuves, limites et abstention.
- Confiance fondée sur des critères vérifiables (couverture, qualité, accord des sources), pas sur un score arbitraire.
- Encadrement des sorties LLM afin qu’elles ne transforment pas des métriques descriptives en jugement contradictoire.
- Exclusion de `hr_drift` comme preuve tant que son origine et sa définition ne sont pas établies.

La proposition `judgment_type / verdict / evidence / confidence / limitations / message_key` est adaptée à évaluer, non à implémenter durant cet audit. Le message doit être déterministe et localisé; les preuves devraient référencer explicitement les métriques, phases, snapshot et provenance.

## 9. Architecture minimale recommandée

### P1 — Régularité observée (première bêta recommandée)

- **Nécessaire :** phases réellement acquises et valides; ordre, durée/distance et allure.
- **Disponible :** calcul de cohortes comparables et faits d’allure.
- **Manquant :** validation runtime de la couverture et seuil produit validé pour qualifier un résultat de régulier/irrégulier.
- **Algorithme minimal :** exposer le nombre d’efforts comparables, l’axe de comparaison, dispersion/étendue et données manquantes. Ne pas appeler cela réussite/échec sans seuil justifié.
- **Garde-fous et abstention :** abstention avec moins de deux allures valides, phases inconnues/incohérentes ou cohorte partielle insuffisante.
- **Tests :** ordre, cohorte partielle, valeurs absentes, FC entre efforts sans dérive, FR/EN/ES et absence de données runtime.
- **Fichiers candidats :** `backend/workout_analysis_v2.py`, `backend/coach_language.py`, tests V2; présentation éventuelle dans `frontend/src/lib/workoutAnalysis.js`.
- **Risque :** faire passer un seuil descriptif pour une note d’entraînement.

### P0 — Exécution par rapport à la prescription (conditionnel)

- **Nécessaire :** activité exacte; matching unique confirmé; snapshot servi; structure gelée; phases complètes alignables; cibles réellement prescrites.
- **Disponible :** snapshots structurés et moteur de rapprochement séparés.
- **Manquant :** lien consommé par l’analyse et comparaison prescrite/réalisée par bloc.
- **Algorithme minimal :** refuser les associations absentes/ambiguës; comparer uniquement les dimensions présentes des deux côtés avec tolérances explicites.
- **Garde-fous et abstention :** snapshot historique absent, prescription live/reconstruite, structure indisponible, phases partielles ou mauvais alignement ⇒ aucune conclusion d’exécution.
- **Tests :** même jour mais activité différente, matching ambigu, snapshot absent, phases partielles et cible de pace indisponible.
- **Fichiers candidats :** `backend/training_v2/performed_workout.py`, `week_execution.py`, `prescription_snapshot.py`, `workout_analysis_v2_service.py`, `coach_context_v2.py` et tests associés.
- **Risque :** faux jugement si les phases réalisées sont associées aux mauvais blocs.

### P2 — Comparaison historique structurée (à différer)

- **Nécessaire :** plusieurs activités antérieures, même nature et structures comparables; durées d’efforts et récupérations vérifiables.
- **Disponible :** recherche historique bornée et métriques de séance.
- **Manquant :** critères historiques fondés sur les structures complètes et couverture garantie.
- **Algorithme minimal :** cohortes séparées par métrique, parmi des structures comparables, avec effectif, fenêtre et limites affichés.
- **Garde-fous et abstention :** structures/types différents, nature inconnue, échantillon petit ou mesures incompatibles ⇒ pas de conclusion de progression.
- **Tests :** footing vs fractionné, récupérations/durées différentes, course vs entraînement, données manquantes et cohortes par métrique.
- **Fichiers candidats :** `backend/workout_analysis_v2.py`, `workout_analysis_v2_service.py`, `coach_language.py` et tests.
- **Risque :** faux progrès/régression de séances de même distance mais d’objectif différent.

**Ordre recommandé : P1, puis P0 uniquement sur associations vérifiées, enfin P2.** P0 ne doit pas être imposé à toute séance tant que le lien snapshot–activité n’est pas fiable.

## 10. Découpage en PR indépendantes

1. **P1 — Régularité observée :** observations de phases, preuve, couverture et abstention; aucune cible supposée.
2. **P0 — Lien prescription–activité :** raccordement via matching confirmé à un snapshot réellement servi; comparaison par bloc si l’alignement est vérifiable.
3. **P2 — Historique comparable :** critères structurels, durées et récupérations avant tout vocabulaire de progression.

Chaque PR devra tester absences, ambiguïtés, limites, localisation FR/EN/ES et droits FREE/TRIAL/PREMIUM. Aucun snapshot historique ne doit être reconstruit rétroactivement.

## 11. Critères GO/NO-GO bêta

**GO limité** pour un P1 descriptif seulement si les phases sont présentes, valides et traçables, et si l’interface présente une observation mesurée plutôt qu’une réussite d’entraînement.

**GO P0** uniquement pour une activité rattachée à un snapshot servi et à une seule activité confirmée; l’abstention doit être testée sur matching ambigu, snapshot absent et structure historique indisponible.

**NO-GO** pour juger globalement l’adhérence au plan, la progression entre séances hétérogènes ou une interprétation physiologique non prouvée. Les activités de l’étude n’ont pas été vérifiées en runtime.

| Capacité | Possible aujourd’hui | Blocage | Priorité bêta |
|---|---|---|---|
| Prescription vs exécution | Matching agrégé possible séparément dans Training V2 | Aucun lien consommé par l’analyse; relation historique et blocs non garantis | P0 conditionnel |
| Régularité des répétitions | Descriptif si phases réelles valides | Couverture runtime non vérifiée; seuil de verdict non justifié | **P1 recommandé en premier** |
| FC entre efforts | Valeurs de phase comparables | N’établit ni dérive ni cause | P1 descriptif |
| Progression historique | Écarts métriques limités | Structures et objectifs insuffisamment comparables | P2 différé |
| Seuils, fatigue, surentraînement, causalité HR | Non démontrés | Preuves insuffisantes | Interdit |
| Enrichissement des quatre activités nommées | Non vérifiable dans cet audit | Documents runtime non consultés | Abstention |

## État de livraison

Audit uniquement. Aucun code, test, appel runtime, commit, PR ou merge n’a été effectué dans le cadre de l’audit. Ce rapport consigne les constats observés au HEAD indiqué et ne valide pas l’état des données en production.
