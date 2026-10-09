# RUNINDEX — PR317 — Workout Analysis V2 / allures canoniques

## 1. Statut et révisions exactes

**Livraison : rapport de blocage uniquement. Aucun code applicatif modifié,
aucune PR créée, aucun merge.**

- Audit : 9 octobre 2026.
- Repository : `geirb56/sauvegarde260708`.
- Base demandée : `copilot/dev`.
- Base vérifiée par `git ls-remote origin refs/heads/copilot/dev` :
  `65524421948976502cd51f108d8e427d9bd67f29`.
- HEAD du code audité, avant ajout de ce rapport :
  `65524421948976502cd51f108d8e427d9bd67f29`.
- Branche de livraison :
  `copilot/copilotdev-d99b7f42-ec8e-42a9-a61e-da78918f1ae5`.
- Dernier commit applicatif audité : merge de #316.

Tous les chemins ci-dessous sont absolus. L'audit porte sur les contrats et
chemins de persistance du code à ce HEAD, **pas sur un inventaire de la base
MongoDB de production**. Aucun accès aux données utilisateur n'a été effectué.

## 2. Diagnostic préalable — lecture seule

### 2.1 Training Paces V2

Fichier :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/training_paces.py`

- `PaceValue`, lignes 198–209 : `min_per_km`, `km_per_hour`, `method`.
- `PaceRange`, lignes 212–225 : `lower` rapide et `upper` lente, deux `PaceValue`.
- `VdotEvidence`, lignes 228–237 : confiance, date de performance, ancienneté,
  distance, durée et poids.
- `VdotResult`, lignes 240–253 : référence VDOT, confiance, compteurs,
  concordance, raison et preuves.
- `TrainingPaces`, lignes 256–279 : `reference_date`, `vdot_result`,
  `confidence`, `easy`, `marathon`, `threshold`, `interval`, `repetition`,
  `reason`, `model_version`.
- E et I sont des plages ; M, T et R sont des valeurs ponctuelles. Les valeurs
  indisponibles restent `None`.
- `training_paces_to_api_dict`, lignes 835–881 : sérialisation des plages,
  valeurs, confiance, date et `race_references`. Les équivalents de course
  issus de Training Paces ne sont pas les prédictions de Performance Curve.

Le chargeur unique est `load_canonical_training_paces`, lignes 72–100 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/training_paces_authority.py`.
Il lit les 500 activités Garmin les plus récentes de l'utilisateur, les
convertit et appelle le calcul canonique existant. Il **ne lit pas un résultat
d'allures historiquement figé**.

`get_training_v2_paces`, lignes 4022–4060 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py`
détermine la date canonique actuelle, appelle ce chargeur et sérialise son
résultat. Aucun archivage de cette sortie n'est effectué dans ce chemin.

### 2.2 Performance Curve V2

Fichier :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/performance_model.py`

- `RacePrediction`, lignes 530–554 : distance, temps prédit numérique et
  affiché, allure affichée, confiance, source, qualité de source, ratio
  d'extrapolation, méthode, pente et contributeurs.
- `PerformanceEstimate`, lignes 557–564 : `has_data`, `predictions`,
  `athlete_profile`, `race_curve_diagnostics`, `model_version`.
- `predict_races`, ligne 1541 : autorité de calcul existante.

`get_race_predictions`, lignes 3290–3421 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py`
charge les activités de l'utilisateur et appelle `predict_races` avec la date
UTC courante. Les quatre distances sont 5 km, 10 km, semi et marathon.
La réponse expose notamment temps, allure affichée, confiance et diagnostics.
Elle n'est pas un contrat d'archive datée des prédictions effectivement
disponibles avant une séance.

Le chemin historique RunIndex ne constitue pas une autre autorité d'allures :
`build_snapshot_document_from_domain`, lignes 326–343 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/services/run_index_history.py`
archive le résultat de `calculate_run_index_from_domain`, pas un
`TrainingPaces` ou un `PerformanceEstimate`.

### 2.3 Données actuellement accessibles à Workout Analysis V2

`WorkoutAnalysisV2Response`, lignes 127–137 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py`
expose `workout`, `summary`, `signals`, `physiology`, `pacing`, `comparison`,
`meaning`, `advice`, `evidence`.

`load_scoped_workout_analysis_v2`, lignes 200–249 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2_service.py`

1. Lit la séance par **`id` et `user_id`**.
2. Recherche sa source Garmin avec un filtre utilisateur
   (`_fetch_garmin_activity`, lignes 99–116).
3. Enrichit FC, vitesse, cadence, dénivelé, zones, splits et analyses déjà
   présents (`enrich_workout_from_garmin_activity`, lignes 119–197).
4. Charge un historique borné de séances du même utilisateur.
5. Appelle `build_workout_analysis_v2` sans prescription ni référence canonique.

`comparison` comporte aujourd'hui des observations historiques de séances,
pas une référence Training Paces ni une comparaison prescrit/réalisé.

### 2.4 Prescriptions historiques : présence réelle mais contrat partiel

`PrescriptionSnapshot`, lignes 84–194 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/prescription_snapshot.py`
possède `user_id`, `prescription_id`, `planned_date`,
`served_reference_date`, `served_at` et `structured`.

**Les snapshots structurés contiennent bien des cibles numériques**, pas
seulement des lettres E/M/T/I/R :
`StructuredWorkoutStep`, lignes 325–352 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/structured_workout.py`
porte `pace_zone`, `pace_min_per_km`, `pace_min_per_km_min`,
`pace_min_per_km_max`, répétitions, durée, distance et récupération.

Ces valeurs sont récupérables sans recalcul **si un snapshot valide existe**.
En revanche, le snapshot ne contient ni la confiance Training Paces d'origine,
ni son jeu complet de références, ni les prédictions Performance Curve.
Un objectif prescrit ne doit donc pas être présenté comme une archive complète
du potentiel historique du coureur.

`persist_served_snapshot`, lignes 42–67 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/snapshot_persistence.py`
impose la cohérence des dates et utilise `$setOnInsert`.
Les snapshots legacy peuvent manquer de `structured`, de `served_at` ou de
provenance ; les valeurs manquantes ne sont pas reconstructibles silencieusement.

Le rapprochement existant est `build_performed_workouts`, ligne 726 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/performed_workout.py`.
Ses règles documentées, lignes 80–99, utilisent utilisateur, date locale
Garmin, type course, dimensions comparables, garde de déviation et ambiguïté.
Ce n'est **pas un lien d'identité enregistré entre activité et prescription**.
`completed_unverified` ne prouve pas la conformité d'allure.

Le pont `week_execution`, lignes 10–44 et 173–200 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/week_execution.py`
réutilise les snapshots existants, conserve les ambiguïtés et signale les jours
historiques sans prescription. Il ne donne pas une référence d'allure manquante.

### 2.5 Fractions rapides et données Garmin partielles

`GarminActivity`, lignes 83–177 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/data_layer.py`
expose des agrégats, `lap_count`, `has_splits` et `details_available`, mais pas
une séquence de fractions reliées aux étapes prescrites.

`GccliProvider._normalize`, lignes 219–270 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/providers/gccli_provider.py`
conserve des agrégats et un sous-document normalisé ; le `raw_payload` listé
ne contient ni fractions rapides ni lien de prescription.

L'enrichissement Workout Analysis peut reprendre des `km_splits` ou `splits`
déjà présents. Des splits kilométriques ne prouvent toutefois pas à eux seuls
les limites travail/récupération d'un « 3 × 8 minutes ».
Le code inspecté ne fournit pas de contrat de correspondance fiable
fraction observée / étape prescrite.

Cela n'empêche pas la description des allures observées. Cela interdit
d'utiliser l'allure globale, échauffement compris, comme conformité des fractions.
L'absence de segments impose l'indisponibilité de cette conformité ; ce n'est
pas, à elle seule, un motif de blocage de toute analyse continue.

### 2.6 Coach Context V2

Les deux consommateurs appellent le même service canonique :
`process_coach_message`, lignes 1870–1884, et `get_workout_analysis_v2`,
lignes 2081–2096 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py`.

`CoachWorkoutDetail.analysis`, ligne 78, et `_normalize_workout_detail`,
lignes 722–774 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/coach_context_v2.py`
embarquent l'analyse reçue, sans en reconstruire une autre.

`build_llm_coach_context`, lignes 321–368 du même fichier, projette les allures
pour l'affichage, bloque les interprétations non justifiées et distingue le
contexte d'entraînement actuel de la séance sélectionnée.
Cette distinction ne transforme pas des références actuelles en références
historiques.

`_has_trusted_zone_provenance`, lignes 781–787 de :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py`
reste `False`. Aucun déverrouillage physiologique n'a été effectué.

## 3. Faisabilité et architecture retenue

**La récupération des cibles prescrites figées est faisable partiellement.
La récupération des sorties historiques complètes avec leur confiance
d'origine n'est pas établie par les contrats de stockage inspectés.**

L'absence de prédiction de course historique, considérée isolément, n'est pas
un blocage : la mission autorise explicitement `unavailable`.
De même, une séance sans prescription ou sans fractions identifiables doit
rester analysable sans inventer de conformité.

Le problème est de livrer ici un raccordement historiquement justifié aux
autorités canoniques : leurs sorties complètes ne sont pas archivées par les
chemins inspectés, et la prescription seule ne conserve pas leur confiance.
Une extension retournant uniquement des références canoniques `unavailable`
et quelques cibles prescrites serait un **périmètre partiel**, pas une preuve
que les références historiques demandées ont été raccordées.

Conformément à la consigne de repli lorsque les données nécessaires ne sont
pas disponibles, cette livraison s'arrête au diagnostic. Aucun nouveau calcul,
aucun raccordement indépendant, aucune collection et aucun backfill ne sont créés.

Un périmètre limité aux prescriptions figées pourrait être validé séparément :
lecture utilisateur-scopée, provenance temporelle stricte, reprise du matching
existant sans supprimer ses ambiguïtés, cibles ponctuelles ou plages inchangées,
confiance canonique inconnue explicitement conservée comme inconnue.
Le raccordement complet nécessiterait une source historique reconnue conservant
valeurs, date effective, date de calcul, type, confiance et provenance. Son
éventuelle collecte prospective demande une décision distincte ; elle ne
récupérerait pas rétroactivement les références absentes.

## 4. Vérification explicite de l'absence de look-ahead

- Aucun appel supplémentaire aux calculateurs, aucune référence courante
  injectée dans l'analyse historique : **aucun look-ahead introduit**.
- `_collect_vdot_evidence`, lignes 504–517 de
  `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/training_v2/training_paces.py`
  exclut les performances d'un jour ultérieur. Cette garde à la journée ne
  prouve pas une disponibilité avant l'heure exacte de la séance.
- Le chargeur applique la limite des 500 activités récentes avant le filtre
  historique du calculateur : des activités plus récentes peuvent donc
  déplacer des preuves anciennes hors de la fenêtre chargée.
- Recalculer aujourd'hui avec `reference_date` passée ne prouve pas qu'une
  sortie existait alors : ingestion tardive, correction de données et règles
  courantes peuvent changer le résultat. `_ingest_activities`, lignes 558–576
  de `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/service.py`
  utilise un upsert avec `$set`, pas une archive versionnée des observations.
- Pour une prescription, `served_reference_date == planned_date` ne suffit pas
  à prouver « connue avant la séance ». Il faudrait aussi contrôler `served_at`
  contre un début d'activité comparable en UTC. Date locale seule, fuseau
  inconnu ou horodatage absent ne permettent pas cette conclusion.
- Une référence actuelle pourrait être présentée comme comparaison
  rétrospective actuelle, jamais comme potentiel connu à la date passée.
  Cette option n'est pas implémentée dans le rapport de blocage.

Ni M = LT1, ni semi = LT2, ni 10 km = VO2max, ni zones Garmin = domaines
physiologiques ne sont ajoutés. D1/D2/D3 reste hors périmètre.

## 5. Fichiers modifiés et justification

Un seul fichier ajouté :
`/home/runner/work/sauvegarde260708/sauvegarde260708/RUNINDEX_PR317_REPORT.md`.
Il fournit le rapport de blocage demandé.

Training Paces V2, Performance Curve V2, WorkoutGenerator, Workout Analysis V2,
Coach Context V2, schémas MongoDB et données utilisateur sont inchangés.
Aucune formule VDOT, VMA ou de prédiction n'a été ajoutée.

## 6. Tests, dépendances et résultats

Suites existantes identifiées :

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_analysis_v2.py` :
  contrat API, isolation utilisateur, déterminisme, données partielles,
  exclusion des séances futures, garde physiologique.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_training_paces_pr194.py` :
  autorité Training Paces, confiance, équivalents de course et calcul existant.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_performance_curve_contract_pr249.py` :
  contrat Performance Curve.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_prescription_snapshot_v2_pr235.py` :
  conservation des cibles ponctuelles et plages, valeurs absentes et snapshots
  legacy ; notamment lignes 394–426.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_coach_context_v2.py` :
  analyse canonique embarquée, cutoff temporel, projection des allures,
  enrichissement Garmin et isolation ; notamment lignes 1149–1204 et 1733–1881.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_performed_workout_pr230.py`
  et `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_pr232a_week_execution.py` :
  matching et pont prescription/exécution.

Configuration :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/pytest.ini:1–9`
impose `pytest-xdist` et `-n 2 --dist loadscope`.
Les dépendances backend existantes sont déclarées dans :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/requirements.txt`,
notamment FastAPI, Pydantic, Motor/PyMongo et pytest.
Aucune dépendance n'a été ajoutée ni modifiée.

Commande tentée depuis
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```text
python -m pytest tests/test_workout_analysis_v2.py tests/test_training_paces_pr194.py tests/test_performance_curve_contract_pr249.py tests/test_prescription_snapshot_v2_pr235.py tests/test_coach_context_v2.py
```

**Résultat : code de sortie 1, `/usr/bin/python: No module named pytest`.**
La collecte n'a pas commencé : aucun test exécuté, aucun résultat de réussite
revendiqué. C'est une limite de l'environnement local, pas un résultat de CI.

Tests non exécutés :

- Les cinq suites de la commande ci-dessus, faute de pytest.
- Les suites matching/pont, les autres suites backend et frontend.
- Les douze nouveaux scénarios PR317 : aucune implémentation ni nouveau test
  dans cette livraison de blocage. Les tests existants ne sont pas présentés
  comme une couverture du raccordement non réalisé.
- Build et lint : non lancés pour un ajout documentaire seul.

La validation automatisée du rapport est consignée lors de la livraison.

## 7. Exemple API avant / après

**Aucun changement d'API.** Projection illustrative des clés existantes,
sans données utilisateur ni métriques fabriquées :

```text
GET /api/coach/workout-analysis/{workout_id}
Avant : version, workout, summary, signals, physiology, pacing,
        comparison, meaning, advice, evidence
Après : exactement le même contrat
```

`planned_vs_actual`, `canonical_pace_reference`, `pace_deviation` et
`reference_provenance` **n'ont pas été ajoutés**. Aucun exemple fictif n'est
présenté comme réponse d'un raccordement livré. API et Coach partagent toujours
la même analyse canonique existante.

## 8. Risques résiduels et décision attendue

- Présence et qualité des snapshots par utilisateur non vérifiées en production.
- Confiance canonique et références Performance Curve historiques non
  récupérables via les contrats d'archive inspectés.
- Matching déterministe != lien d'identité certain ; garder les ambiguïtés.
- Splits kilométriques != fractions prescrites ; aucune conformité inventée.
- Horodatages legacy/local-only : pas de garantie « connu avant la séance ».
- Tests indisponibles dans l'interpréteur local ; aucune garantie issue d'une
  exécution de tests.

**STOP : rapport livré, aucune PR #317 ouverte, aucune modification fonctionnelle.
Attendre validation du diagnostic et d'un éventuel périmètre prescription-only
ou d'une source historique autorisée avant toute implémentation.**
