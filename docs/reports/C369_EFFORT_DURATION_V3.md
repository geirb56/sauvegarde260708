# C369 — Durée individuelle des phases d’effort dans V3

## 1. HEAD et branche audités

- Audit : 24 octobre 2026, avant toute modification du dépôt.
- Branche canonique et cible de la PR : `copilot/dev`.
- HEAD distant vérifié par `git ls-remote origin refs/heads/copilot/dev` :
  `d9fc1f1bb36e0c20b2448edb6f87142c799ebc4d`.
- Base locale identique au HEAD canonique.
- Branche de travail : `copilot/c369-exposition-durees-efforts`.
- HEAD exact de l’implémentation et des tests :
  `6aec092d634a542ea44830c6a7d65a681563406d`.
- Ce rapport est ajouté ensuite dans un commit documentaire ; son SHA de livraison
  est indiqué dans la description de PR, sans prétendre être le HEAD testé ci-dessus.
- Racine du dépôt audité : `/home/runner/work/sauvegarde260708/sauvegarde260708`.

## 2. Confirmation effective de C368

GitHub confirme la PR #365 mergée vers `copilot/dev` le 24 octobre 2026.
Le HEAD canonique est précisément le merge de cette PR, avec pour parents
`5f081866dede6b5ccca3ef51dba677e6ef9e864b` et
`b565a1832f48fad9e5fc8b8128f30d59f4fd464d` (implémentation C368).
Le code présent contient les modèles, l’extracteur, les deux raccordements et
les tests `effort_pace_observations`, vérifiés directement.

Conventions C368 réutilisées : bloc additif dans l’entrée et la sortie V3,
`status` global, booléen `available` et motif par effort, comptages de couverture,
identifiants d’observation fondés sur `order`, unité, source, endpoint, méthode,
chemins de provenance et copie profonde vers la sortie.

Limites structurelles signalées, non corrigées hors périmètre :

- Les modèles V2/V3 ne constituent pas à eux seuls une preuve de validation du cache :
  leurs champs numériques ordinaires ne portent pas toutes les règles du loader.
  Le chemin de production passe par le loader existant ; le transfert contrôle
  aussi la source Garmin et réutilise le prédicat numérique V2.
- La distinction brut absent / brut rejeté est déjà perdue en amont de V2.
- C368 recopie les limitations V2, qui peuvent concerner la comparabilité des
  efforts, et pas seulement l’allure. C369 ne modifie pas C368 et ne copie pas
  ces limitations de régularité dans son nouveau bloc descriptif.

## 3. Provenance exacte et matrice préalable

| Élément | Source V2 | Contrat V3 avant C369 | Action |
|---|---|---|---|
| Durée individuelle | `phase_analysis.efforts[*].duration_s` | Absente | Copier une valeur V2 admissible, sans calcul |
| Ordre des efforts | Liste `efforts`, `order`, `effort_number` | Convention C368 | Conserver liste et numérotation, même incomplètes |
| Unité | `duration_s`, secondes | Unité explicite par observation C368 | `unit: "s"` ; aucune conversion |
| Disponibilité | Valeur positive finie ; zéro conservé en amont ; `None` ambigu | États C368 | Couverture globale et état/motif individuel |
| Provenance | Garmin typed-splits → cache contrôlé → V2 | Métadonnées C368 | Source, endpoint, méthode et chemins explicites |

Chemin observé dans le code :

1. `splits[*].duration` du payload typed-splits est normalisé sans conversion
   en `ActivityPhase.duration_s` :
   `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/data_layer.py:186-264`.
   Le normaliseur rejette booléens, valeurs non numériques, négatives ou non finies
   en les remplaçant par `None`. Le zéro est conservé.
2. Le cache `garmin_activities.activity_details` doit être complet, de version
   attendue, de source Garmin et d’endpoint typed-splits. Le lecteur vérifie
   également l’ordre et les mesures :
   `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2_service.py:211-263`.
   Un cache contenant directement une mesure numérique invalide est rejeté
   globalement, contrairement à une valeur brute déjà normalisée en `None`.
3. V2 copie `duration_s` sans recalcul dans chaque phase structurée, numérote
   les phases classées `effort` avant tout examen de disponibilité, puis
   construit la liste `efforts` :
   `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py:1852-1926`.
4. Le loader construit V2 une fois, puis fournit ce résultat à l’extraction V3 :
   `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_intelligence_v3_service.py:147-183`.
   C369 lit exclusivement ce résultat déjà disponible.
5. L’extracteur C369 contrôle l’admissibilité avec le prédicat V2
   `_valid_positive_number`, défini dans
   `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py:721-731`.
   Il n’introduit ni seuil physiologique, ni calcul de durée.

V2 ne possède pas d’identifiant indépendant d’effort dans ce modèle :
`order` et `effort_number` sont préservés ; l’identifiant d’observation V3
`recorded_effort_duration:{order}` suit la convention de nommage C368.
Il est local à la séance, pas un identifiant Garmin global.

## 4. Contrat V3 avant / après

Avant : `effort_pace_observations` existe, mais aucun bloc de durée individuelle.

Après : ajout de `effort_duration_observations` dans `WorkoutIntelligenceV3Input`
et `WorkoutIntelligenceV3`, avec une valeur par défaut indisponible pour les
anciens payloads.

- Global : `status` (`available`, `partial`, `unavailable`),
  `recorded_effort_count`, `available_duration_count`, `efforts`,
  `unavailable_reason`, `validity_conditions`, `limitations`.
- Par effort : `id`, `code: recorded_effort_duration`, `order`, `effort_number`,
  `duration_s`, `unit: s`, `available`, `unavailable_reason`, `source: garmin`,
  `endpoint: typed-splits`, `method: workout_analysis_v2._build_phase_analysis`,
  `source_paths`.
- Chemins individuels :
  `garmin_activities.activity_details.phases[order].duration_s` et
  `workout_analysis_v2.phase_analysis.efforts[index].duration_s`.
- Aucun arrondi, moyenne, dispersion, tendance ou score ajouté.
- Le statut global porte seulement sur les efforts enregistrés, pas sur
  la complétude de la séance entière ni sur la qualité du capteur.

**Effet public explicite :** le JSON V3 existant est enrichi d’un nouveau bloc.
Les routes et leurs enveloppes restent identiques. Les consommateurs connus
sélectionnent leurs champs ; un consommateur externe à validation stricte de
toutes les clés pourrait devoir accepter cette extension.

## 5. Fichiers modifiés

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_intelligence_v3_models.py`
  — modèles factuels et champs additifs.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_intelligence_v3.py`
  — transfert pur V2 → entrée V3 → copie profonde en sortie.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_intelligence_v3.py`
  — 25 cas C369 après paramétrisation.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/docs/reports/C369_EFFORT_DURATION_V3.md`
  — présent rapport.

Aucun changement du calcul V2, loader, acquisition, route, frontend, abonnement,
schéma persisté, prompt, règle d’admission ou activation du Coach hybride.
Aucune dépendance du dépôt ajoutée ou mise à jour.

## 6. Tests exécutés et résultats réels

Environnement isolé : Python 3.12.3, pytest 8.3.5, pytest-xdist 3.6.1,
Pydantic 2.13.4, FastAPI 0.110.1, httpx 0.28.1, flake8 7.3.0.
Les dépendances nécessaires aux tests ont été restaurées dans
`/tmp/c369-venv`, sans modifier les manifests. Ce n’est pas une reproduction
exacte de tout le fichier de dépendances : notamment Motor 3.7.1,
PyMongo 4.19.0, PyJWT 2.14.0 et cryptography 50.0.0 dans cet environnement.

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```bash
/tmp/c369-venv/bin/python -m pytest \
  tests/test_workout_intelligence_v3.py \
  tests/test_historical_max_hr_c367.py \
  tests/test_workout_analysis_v2_phases.py \
  tests/test_garmin_laps_analysis_c343.py \
  tests/test_narrative_coach_v3.py \
  tests/test_hybrid_coach_c359.py \
  tests/test_hybrid_coach_c362.py \
  tests/test_hybrid_coach_c364_audit.py \
  tests/test_hybrid_coach_c365.py \
  tests/test_workout_analysis_v2_facts.py -q
```

**Résultat : 1 050 réussis, 6 avertissements de dépréciation.**
La configuration existante `-n 2 --dist loadscope` est conservée.

```bash
/tmp/c369-venv/bin/python -m flake8 \
  workout_intelligence_v3.py workout_intelligence_v3_models.py \
  tests/test_workout_intelligence_v3.py --select=E9,F63,F7,F82
git diff --check
```

Résultat : les deux contrôles réussissent.
Scan des secrets des trois fichiers de code/tests et du rapport : aucun secret détecté.
CodeQL Python, après commit du code : aucune alerte.
Revue indépendante du diff : aucun problème significatif signalé.

Traçabilité des essais intermédiaires : le premier essai pré-modification
avait 119 réussites et un échec d’import FastAPI absent. Un premier nouveau
test utilisait un nom de fonction inexistant, corrigé vers
`build_narrative_context`. Le premier essai HTTP recevait 401, car le middleware
d’abonnement précédait la dépendance de route ; les autorités d’authentification
et d’accès sont désormais simulées explicitement dans le test. Les essais
complets suivants ont réussi. Aucun échec de production n’en est déduit.

| Exigence | Preuve synthétique |
|---|---|
| Quatre efforts valides, unités, provenance | `test_c369_four_durations_reuse_v2_without_new_reads` |
| Absence, zéro, négatif, non numérique, booléen, NaN, infini, disponibilité partielle | `test_c369_partial_durations_preserve_effort_identity` |
| Phases absentes, vides, cache invalide, aucun effort/durée exploitable | `test_c369_unavailable_durations_do_not_fallback_to_session` |
| Défense sur V2 hors chemin normal | `test_c369_defensively_rejects_invalid_v2_duration_without_recalculation` |
| Numéros non contigus et source non vérifiée | `test_c369_preserves_v2_order_numbering_and_rejects_unverified_sources` |
| Ordre normalisé différent de l’ordre de réception | `test_c369_recorded_order_comes_from_normalized_v2_not_arrival_order` |
| JSON, ancien contrat, non-mutation, absence de nouvelles conclusions/narration | `test_c369_additive_json_contract_nonmutation_and_no_new_conclusions` |
| Réponse HTTP réelle ASGI, blocs C368 et C369 | `test_c369_existing_http_response_serializes_both_observation_blocks` |
| Non-régression des allures et consommateurs backend connus | Suites C368/V3, V2, Narrative et Hybrid listées ci-dessus |
| Pas de nouveau chargement | Comparaison exacte des requêtes simulées avec extraction C369 neutralisée ; V2 construit une seule fois ; reconstruction des phases interdite dans le test d’extraction |

Toutes les nouvelles fixtures sont synthétiques. Les tests C369 de pipeline
interdisent les connexions réseau et les sous-processus. Le test ASGI ne lance
pas le lifespan, simule le loader et ne contacte ni MongoDB, ni Garmin, ni LLM.
Pas de validation sur données Garmin réelles, pas de suite exhaustive du dépôt,
pas de test/build frontend exécuté : son audit reste en lecture seule.

## 7. Analyse des valeurs absentes et invalides

- Positif fini fourni par V2 : valeur inchangée, `available: true`.
- `None` V2 : `duration_s: null`, `available: false`,
  `v2_phase_duration_missing_or_rejected_upstream`. Il serait faux de dire
  « certainement absent dans Garmin ».
- Zéro V2 : `duration_s: null`, `available: false`,
  `invalid_v2_phase_duration`. Le normaliseur/cache tolère zéro comme mesure
  enregistrée ; il n’est pas exploitable comme durée d’effort positive avec le
  prédicat V2 réutilisé ici. Zéro n’est jamais confondu avec `None`.
- Valeur brute négative/non numérique/non finie : déjà `None` après
  normalisation. C369 ne relit pas le brut pour retrouver le motif.
- Valeur invalide directement injectée dans V2 : rejet défensif avec motif
  `invalid_v2_phase_duration` ; ce n’est pas une nouvelle source admissible.
- Chaque effort reste présent même sans durée. Les suivants ne sont pas
  renumérotés. Aucune substitution par durée totale, allure, distance,
  récupération ou prescription.
- Sans phases validées ou avec une source non Garmin : bloc indisponible.

## 8. Compatibilité API et frontend — audit sans modification

Chemin identifié :

1. V2 déjà chargé → extraction V3 → copie profonde vers le modèle de sortie.
2. `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/narrative_coach_v3_models.py:23-24`
   étend l’enveloppe V3 avec la narration.
3. `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py:2157-2182`
   expose **GET `/api/coach/workout-intelligence/{workout_id}`**.
   C’est la route trouvée exposant explicitement ce contrat V3. La route V2
   `/api/coach/workout-analysis/{workout_id}` n’est pas enrichie par C369.
4. La sérialisation FastAPI/Pydantic conserve le modèle imbriqué complet :
   le test ASGI vérifie effectivement `effort_pace_observations` **et**
   `effort_duration_observations` dans le JSON HTTP synthétique.
   Il ne démontre pas leur présence dans un déploiement distant.
5. `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/hooks/useWorkoutIntelligence.js:18-20`
   reçoit la réponse complète dans son état.
   Les pages consommatrices sont :
   `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/WorkoutDetail.jsx`,
   `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/SessionDetail.jsx`,
   `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/DetailedAnalysis.jsx`.
6. `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/components/workout/NarrativeWorkoutAnalysis.jsx:19-69`
   sélectionne classification, intensité, historique et tendance ; il ne lit
   pas les blocs individuels C368/C369. La recherche dans le frontend ne trouve
   aucune référence directe à ces deux noms de champs.

**Distinction :** modèles présents ; réponse HTTP synthétique prouvée ;
réception de l’enveloppe dans React identifiée ; aucune consommation explicite
ni affichage dédié de ces blocs V3 dans le code audité.
L’affichage existant d’éventuelles données de phases V2 n’est pas un affichage
du nouveau contrat V3. Un affichage C369 nécessiterait une future PR dédiée.

**Déploiement effectif : inconnu.** Ni une configuration de production, ni
la présence du modèle, ni un test local ne prouve la révision réellement servie.
Aucun déploiement ni interrogation d’un environnement de production effectué.

## 9. Limites scientifiques

Une durée décrit une phase enregistrée, classée « effort » par V2.
Elle ne certifie ni une durée d’effort physiologique, ni l’exhaustivité de
l’enregistrement, ni une chronologie absolue, ni la précision du capteur.

Aucune conclusion nouvelle de régularité, exécution, conformité, fatigue,
progression, intensité physiologique ou comparaison historique. Les conclusions
existantes de V3 ne sont pas supprimées : le test compare tous les autres champs
avec un bloc C369 neutralisé, ainsi que le contexte narratif et son fallback.
Les allures C368, la science déterministe, Training, LT1/LT2/VMA, les prédictions,
le Coach hybride et son admission restent inchangés.

## 10. Risques résiduels

- Ambiguïté des `None` héritée du normaliseur ; non réparable par simple transfert.
- Cache invalide rejeté globalement par le loader existant.
- Exactitude des mesures et complétude de séance non garanties.
- Extension JSON additive pouvant affecter des consommateurs externes stricts
  inconnus ; aucune promesse de compatibilité universelle.
- Tests synthétiques et environnement partiellement restauré, pas de preuve
  de fonctionnement d’un déploiement ni de validation Garmin réelle.
- Contrôle advisory de préparation des tests : les versions déjà déclarées
  PyJWT 2.13.0, cryptography 49.0.0 et python-jose 3.5.0 ont des alertes de
  dépendances. PyJWT 2.14.0 et cryptography 50.0.0, sans alerte dans le contrôle,
  ont été utilisés uniquement dans l’environnement de test ; python-jose
  n’y a pas été installé. Aucun manifest ni correctif de dépendance hors
  périmètre n’est inclus dans C369. Ce constat n’est pas une conclusion
  d’exploitabilité du code de l’application.

## 11. Verdict

**GO pour revue de la PR C369**, sur le seul objectif du transfert factuel des
durées V2 admissibles. Les préconditions de provenance et de sémantique sont
établies dans le chemin existant ; les pertes d’information sont explicites.

Ce GO n’autorise ni merge automatique, ni déploiement, ni affichage frontend,
ni activation de `C359_HYBRID_COACH_ENABLED`, ni admission de nouvelles
conclusions dans le Coach.
