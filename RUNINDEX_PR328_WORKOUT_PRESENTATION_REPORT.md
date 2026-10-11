# RUNINDEX — PR328 Workout Presentation

## Traçabilité

- Cible : `copilot/dev`.
- Base vérifiée via GitHub et clone : `dd06e0e4022e285117674378db730fd44f0e6a40`.
- #326 mergée le 11 octobre 2026 à 07:45:17 UTC ; #327 mergée à 10:55:02 UTC.
- HEAD de code validé : `872f1018e73b7d4b2c1815d35e54e8e873217b90`.
- Le commit suivant ajoute uniquement ce rapport. Son SHA final est indiqué dans la description de la PR, pour éviter une référence récursive au hash du document lui-même.
- Branche de travail : `copilot/workout-analysis-v2-update`. Aucun push sur la cible, merge ou déploiement.

## Diagnostic différentiel avant modification

`WorkoutDetail` affichait `signals.session_type` (« standard », classification historique de durée/volume) en concurrence avec les intervalles reconnus par `summary`. `signals.session_structure` existait déjà, indépendamment de l'intensité.

`_phase_observations()` produisait déjà les faits d'exécution et les réserves ; `_build_meaning()` y ajoutait les comparaisons historiques dans un texte unique. Les pages WorkoutDetail, DetailedAnalysis et SessionDetail consommaient ce texte. Coach Context V2 conserve l'objet canonique et le projette vers le LLM sans découper ce texte.

`advice.text` vient de `_build_advice()` : observation descriptive des derniers efforts comparables, ou observation générale existante. Son indicateur `available` gouverne l'affichage ; il ne constitue pas une nouvelle prescription. Sa provenance et son texte sont conservés.

Les références 14 jours sont des moyennes brutes ; les références similaires 180 jours portent déjà `comparable` et leurs réserves. Leurs calculs ne sont pas modifiés.

## Fichiers modifiés

- `backend/workout_analysis_v2.py`
- `backend/tests/test_workout_presentation_pr328.py`
- `frontend/src/lib/workoutAnalysis.js`
- `frontend/src/lib/i18n.js`
- `frontend/src/pages/WorkoutDetail.jsx`
- `frontend/src/pages/DetailedAnalysis.jsx`
- `frontend/src/pages/SessionDetail.jsx`
- `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
- `RUNINDEX_PR328_WORKOUT_PRESENTATION_REPORT.md`

Tous ces chemins sont relatifs à `/home/runner/work/sauvegarde260708/sauvegarde260708`.

## Contrats préservés et extension

| Contrat | Résultat |
| --- | --- |
| `summary.code/text` | Inchangé ; structure, durées et moyenne restent dans le résumé. |
| `meaning.code/text` | Texte historique conservé pour compatibilité, notamment Coach. |
| `meaning.observations` | Ajout : faits essentiels déjà produits par le backend, sans historique ni FC maximale. |
| `meaning.caveats` | Ajout : réserves de couverture et d'intensité issues du moteur existant. |
| `advice.code/text/available` | Inchangé ; observation distincte de la synthèse. |
| `signals.session_type` | Inchangé dans le payload ; ne concurrence plus une structure identifiée dans les pages. |
| `signals.session_structure` | Inchangé ; seuls les codes disponibles `intervals`/`continuous` guident la présentation de structure. |
| `phase_analysis` | Calculs, classification, durées, distances, allures, FC et régularité inchangés. |
| `comparison` | Objets et critères 14/180 jours inchangés. |
| `evidence.has_splits` | Inchangé ; libellé « Splits kilométriques ». |
| `phase_analysis.available` | Présence de phases, y compris inconnues. |
| `evidence.has_structured_phases` | Au moins une phase classifiée ; ce n'est pas la preuve d'intervalles. |

Les listes additives ont des valeurs par défaut indépendantes ; les anciens dictionnaires et les instances `AnalysisText` restent acceptés. Les trois pages partagent un sélecteur de présentation, sans moteur scientifique frontend, découpage par ponctuation ou regex. Les chaînes identiques de réserves sont dédupliquées intégralement.

Sans faits d'exécution essentiels, une observation prudente reprend les templates d'intensité existants, uniquement à partir du signal fiable ; sans signal fiable, l'intensité reste indéterminée.

## Avant/après sur fixtures synthétiques

- Fixture backend PR328 : quatre efforts de 240 s aux allures 288/282/271/291 s/km, récupérations de 180 s, FC 151/157/159/159 bpm. Sa dispersion calculée est **7,6 s/km**, pas une valeur remplacée pour reproduire une capture réelle.
- La fixture existante #326, également exécutée, utilise les distances 832,07/851,11/885,81/825,41 m : moyenne **4:43/km**, dispersion **7,7 s/km**.
- Avant : type « standard » visible et paragraphe comportant dispersion, extrêmes, FC maximale et historique.
- Après : « Structure : Intervalles » ; dispersion, efforts le plus rapide/le plus lent et évolution descriptive de FC, puis réserve concise. La phrase scientifique existante précise que cette évolution n'est pas une mesure de dérive cardiaque.
- Le maximum observé reste dans les cartes de phases/FC et dans le texte historique compatible ; il n'encombre plus la synthèse.
- Référence 14 jours : « Référence descriptive », valeurs repliables.
- Référence 180 jours non comparable : réserve toujours visible, détails repliables. Si `comparable === true`, détails ouverts par défaut et réserve de non-preuve de progrès conservée.
- Splits absents + phases présentes : « Splits kilométriques : Non », « Phases enregistrées : Oui », puis classification disponible ou non selon la preuve.
- Séances continues, sans phases, uniquement inconnues et mixtes : aucun intervalle déduit du titre ; niveaux de preuve séparés.
- Cartes d'échauffement, efforts, récupérations, retour au calme, métriques et limites conservées, sans refonte générale.

Aucune activité réelle n'a été lue ou modifiée ; aucun identifiant réel n'est ajouté aux nouvelles fixtures.

## Tests exécutés

Backend, depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend`, exécuté par l'agent backend :

```sh
python -m pytest tests/test_workout_presentation_pr328.py tests/test_workout_analysis_v2.py tests/test_workout_analysis_v2_unified.py tests/test_workout_analysis_v2_phases.py tests/test_coach_workout_access_pr325.py tests/test_coach_context_v2.py tests/test_mobile_workout_analysis.py -q --tb=short
```

**563 passed**, 14 avertissements de dépréciation existants, exit 0. Comprend les fixtures FR/EN/ES, couverture partielle, FC manquante, maximum seul, intensité fiable/non fiable, texte historique, comparaisons, round-trip, compatibilité des instances et propagation Coach, gardes FREE/TRIAL/PREMIUM.

Frontend, depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend` :

```sh
npm ci --legacy-peer-deps --no-audit --no-fund
CI=true npm test -- --watchAll=false --forceExit --runInBand --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/structured-workout-view.test.jsx src/__tests__/coach-page.test.jsx src/__tests__/chat-coach-subscription-status.test.jsx
npm run build
```

**308 passed**, 4 suites, exit 0 ; production **Compiled successfully**, exit 0. Tests dédiés : structure sans type contradictoire, consommateurs secondaires, références repliables/accessibles, référence fiable ouverte, preuves séparées, langues, réserve seule et déduplication. Les tests existants couvrent FREE, TRIAL/PREMIUM et transitions des droits. Logs réseau simulés et fallback d'URL attendus dans les tests.

Build final : JS principal 341,75 kB, CSS 15,12 kB gzip. Avertissement Browserslist ancien, non corrigé hors périmètre.

Les premières itérations frontend ont détecté une fermeture JSX mal placée, quatre assertions de visibilité à adapter aux zones repliables et un sélecteur de texte trop strict ; corrigés et commandes relancées avec succès.

`git diff --check` et `git diff dd06e0e4022e285117674378db730fd44f0e6a40 --check` : exit 0.

## Sécurité et revue

- Scan de secrets des huit fichiers de code/tests : aucun secret détecté.
- Validation parallèle sur le HEAD de code : CodeQL Python/JavaScript, **0 alerte**.
- La revue standard a échoué au chargement de son modèle malgré son statut de succès affiché ; elle n'est donc pas déclarée comme revue effective.
- Revue indépendante read-only : un risque de retour au texte historique lorsque seules des réserves existaient ; corrigé et testé, ainsi que le cas maximum seul.

## Limites et risques résiduels

- Aucun test visuel sur appareil physique ni validation de la séance réelle ; résultats fondés sur fixtures synthétiques et DOM.
- Le texte historique reste long pour les consommateurs externes qui continuent volontairement de lire `meaning.text` ; les trois pages auditées utilisent l'extension.
- Les réserves peuvent allonger la synthèse lorsque la couverture est partielle ; elles ne sont pas supprimées.
- Installation backend complète bloquée par une roue privée inaccessible ; dépendances nécessaires aux suites restaurées, sans changement de manifestes ni ajout d'outil.
- Aucun changement Training Today/Week, droits, ingestion Garmin/GCCLI, normalisation provider-neutral, Mongo/Redis, seuils ou algorithmes.
- Revue **C328 attendue** avant toute intégration.
