# C356 — Workout Analysis UX V3

## Périmètre et traçabilité

- Base : `copilot/dev`, `ee0109efe6f614136bf7aee98e409b70d73858ef` (merge C355).
- Branche de livraison : `copilot/c356-workout-analysis-ux-v3`.
- HEAD d'intégration soumis à la revue et à CodeQL : `bb66a394d12e35eb442b7fb119bbdac597865eb4`.
- HEAD du code validé par les tests définitifs : renseigné après leur exécution.
- Frontend uniquement, hors présent rapport et fixtures/tests de présentation.
- Aucun changement des moteurs V2/V3, de prescription, des seuils, des abonnements ou des données.
- Aucun accès MongoDB, appel Garmin/GCCLI, déploiement ou merge.
- Arbre de travail initial propre ; aucune modification locale préexistante à préserver.

## 1. Diagnostic préalable (lecture seule)

Lecture des trois pages, des composants phases/splits, des helpers d'analyse, des contextes
de langue/abonnement, des traductions FR/EN/ES et des contrats/handlers backend réels.

| Point | État avant C356 |
| --- | --- |
| Coach actuel | `WorkoutDetail` privilégie `session_synthesis` V2, puis Coach Language V1. `SessionDetail` et `DetailedAnalysis` affichent les conclusions V1, puis faits et observations. |
| Emplacement V3 | Remplacer la zone de commentaire dans chacune des trois pages existantes, sans nouvelle route. |
| Redondances | Synthèse/conclusions, « sens », classification/intensité et observation Coach sont répartis dans plusieurs sections ; les phases sont développées avant les principaux enseignements. |
| Réutilisable | `WorkoutPhaseAnalysis`, `WorkoutKilometerSplits`, notice d'accès, métriques primaires, traductions et helpers de fallback existants. |
| Contrat non consommé | Aucun appel frontend à `/coach/workout-intelligence/{id}` : ni `narrative_coach_v3`, ni classification V3, comparaison historique V3 ou tendance V3. |
| Accès | Les trois pages utilisent `hasFeature("coach_workout_analysis")`. `/user/features` est l'autorité fail-closed ; V2 et V3 vérifient aussi l'accès et le propriétaire côté serveur. |
| Risques | Différences de fallback entre pages, réponses tardives après navigation/changement de langue, affichage Premium après révocation, perte des splits/phases et transformation d'un diagnostic probable en certitude. |

Les échanges conversationnels `Coach.jsx`/`ChatCoach.jsx` ne constituent pas la nouvelle
analyse de séance et ne sont pas refondus dans cette PR.

## 2. Architecture UX retenue

1. **Coach** : titre, analyse, interprétation, recommandation seulement si fournie, puis
   première limitation importante. Les phrases backend restent intactes.
2. **Preuves** : liste compacte de données contractuelles : type avec qualification
   « probable », efforts/récupérations, intensité personnelle seulement si étayée,
   références historiques, tendance suffisamment fiable et dispersion mesurée.
3. **Détails progressifs** : disclosure natif, composants phases et splits conservés,
   écarts historiques détaillés et limitations complémentaires. Pas de disclosure vide.

Une narrative valide remplace toutes les zones de commentaire legacy de la page :
pas de synthèse V2 ou de second Coach V1 à côté du récit V3. Les chiffres factuels des
phases restent consultables dans les détails. `generation_mode` et `evidence_refs` ne
sont jamais affichés.

## 3. Composants créés ou réutilisés

- `NarrativeWorkoutAnalysis` : présentation commune aux trois routes existantes.
- `useWorkoutIntelligence` : lecture V3 indépendante de V2, annulable et indexée par
  séance/langue, uniquement lorsque le droit existant est confirmé.
- `analysisFormat` : formatage `Intl.NumberFormat` centralisé des valeurs structurées ;
  `null`, valeurs absentes/non finies et zéro restent distincts.
- Réutilisation des composants phases, splits, métriques, notices d'accès et fallback.
- Aucune bibliothèque ajoutée, aucune nouvelle couleur décorative.

## 4. Fichiers modifiés

Chemins relatifs à la racine du dépôt :

- `frontend/src/pages/{WorkoutDetail,SessionDetail,DetailedAnalysis}.jsx`
- `frontend/src/components/workout/NarrativeWorkoutAnalysis.jsx`
- `frontend/src/components/workout/{WorkoutPhaseAnalysis,WorkoutKilometerSplits}.jsx`
- `frontend/src/hooks/useWorkoutIntelligence.js`
- `frontend/src/lib/{analysisFormat,i18n}.js`
- `frontend/src/utils/units.js`
- `frontend/src/__tests__/{analysis-format.test.js,workout-analysis-v3-pages.test.jsx}`
- `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx` : attentes adaptées uniquement
  au nouvel appel V3 et aux séparateurs décimaux localisés ; assertions métier conservées.
- `tests/e2e/c356-narrative-coach.spec.ts`
- `tests/fixtures/c356-workouts.ts`
- `docs/reports/assets/c356/*` : captures et mesures de navigateur.
- Le présent rapport.

## 5. Gestion des états

| État | Comportement |
| --- | --- |
| Narrative disponible | Un Coach V3 ; anciennes conclusions masquées, détails conservés. |
| Narrative absente/incomplète/mauvaise langue/mode `none` | Présentation legacy existante ; aucun conseil inventé. |
| Données insuffisantes | Incertitude du récit et type indéterminé ; pas de zone ni de tendance déduite. |
| Erreur V3 | Message discret localisé ; V2 et séance restent disponibles indépendamment. |
| Erreur V2 | V3 ne dépend pas du succès V2 ; détails disponibles conservés depuis la séance. |
| FREE ou droits en chargement | Aucun appel V3 ni commentaire Premium ; gating existant inchangé. |
| TRIAL/PREMIUM | Même feature flag canonique ; aucune décision locale fondée sur le nom du plan. |
| Changement séance/langue/droits | Annulation et masquage des données hors contexte ; pas de réutilisation d'un récit d'une autre séance/langue. |

## 6. Tests exécutés et résultats

Première validation des modifications partagées, avant intégration des pages :

- `CI=true npm test -- --watchAll=false --forceExit --runInBand --runTestsByPath src/utils/units.test.js src/__tests__/workout-analysis-v2-pages.test.jsx`
  depuis `frontend/` : **637 tests réussis, 2 suites**.
- `CI=true npm test -- --watchAll=false --forceExit --runInBand --runTestsByPath src/__tests__/analysis-format.test.js`
  depuis `frontend/` : **18 tests réussis**.

Validation de l'intégration, depuis `frontend/` :

| Commande | Résultat |
| --- | --- |
| `CI=true npm test -- --watchAll=false --runInBand --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/workout-analysis-v3-pages.test.jsx` | **765/765 tests**, 2/2 suites |
| `CI=true npm test -- --watchAll=false --forceExit --runInBand` | **1 392/1 392 tests**, 37/37 suites, 59,437 s |
| `npm run build` | **Compilation de production réussie** |
| `git diff --check` | Aucun problème d'espacement |

Le fichier V3 contient **138 cas** : les trois pages en FR/EN/ES, fractionné avec/sans
dispersion démontrée, footing probable et référence relative sans zone physiologique,
type indéterminé, tendance fiable/faible confiance, historique insuffisant,
narrative absente/incomplète/mauvaise langue, erreurs V2/V3 indépendantes, accès
FREE/en chargement/TRIAL/PREMIUM/révoqué, absence de doublons, phases/splits accessibles,
conservation des métriques et réponses tardives après navigation/changement de langue.
Les tests numériques couvrent aussi les valeurs non finies, `null`, zéro et les phrases
backend non retouchées. Le test de formatage a finalement **19 cas** dans la suite complète.

Les premiers passages V2 après intégration ont révélé des attentes obsolètes de nombre
d'appels et de séparateurs décimaux ; elles ont été adaptées aux seuls changements C356.
La précision fixe existante des unités a été préservée. Aucun test sans rapport supprimé
ni aucune assertion métier affaiblie.

- `parallel_validation` sur `bb66a394d12e35eb442b7fb119bbdac597865eb4` :
  **CodeQL JavaScript : 0 alerte**. L'outil de revue intégré est **indisponible**
  (`autofind` absent) : son statut « Success » ne prouve pas une revue exécutée.
  Revue indépendante du diff par agent read-only effectuée en complément :
  **aucun problème significatif identifié**.

## 7. Validation visuelle

Captures **réelles de Chromium local**, sur fixtures **synthétiques contractuelles** :
elles ne sont ni des captures de séances Garmin réelles ni une revalidation scientifique
de C355. Toutes les requêtes API sont interceptées ; les domaines externes sont bloqués.
Les polices externes bloquées peuvent provoquer une police de repli dans les captures.

- Desktop : **1440 × 1100**.
- Mobile : **390 × 844**.
- Trois exemples : fractionné, footing probable, séance tapis indéterminée.
- Avant : route `WorkoutDetail` ouverte pour chaque exemple et viewport.
- Après : les trois routes réellement ouvertes et les disclosures actionnés au clavier ;
  **18 visites effectives**, titres Coach/preuves vérifiés, détails repliés
  initialement et actionnables au clavier, aucune section de détails vide sur le tapis.

Depuis `tests/` :

- `C356_STAGE=before npx playwright test e2e/c356-narrative-coach.spec.ts --project=chromium --retries=0` :
  **6/6 tests réussis** (30,4 s).
- `C356_STAGE=after npx playwright test e2e/c356-narrative-coach.spec.ts --project=chromium --retries=0` :
  **6/6 tests réussis** (dernier passage : 14,7 s), réexécutés après les ajustements
  de largeur/détails et les gardes de contexte.
- **12 PNG + 12 JSON**, aucun débordement horizontal, aucune erreur de page et aucun
  endpoint API inattendu dans les passages enregistrés.
- Titres Coach initialement dans le viewport sur les **18 visites** (`toBeInViewport`),
  avant ouverture des détails et à défilement nul ; largeurs Coach : **736 px desktop /
  358 px mobile**. Les mesures initiales sont distinctes des défilements dus au clavier.

| Exemple | Avant desktop | Avant mobile | Après desktop | Après mobile |
| --- | --- | --- | --- | --- |
| Fractionné | [capture](assets/c356/before-intervals-desktop.png) | [capture](assets/c356/before-intervals-mobile.png) | [capture](assets/c356/after-intervals-desktop.png) | [capture](assets/c356/after-intervals-mobile.png) |
| Footing probable | [capture](assets/c356/before-probable-easy-desktop.png) | [capture](assets/c356/before-probable-easy-mobile.png) | [capture](assets/c356/after-probable-easy-desktop.png) | [capture](assets/c356/after-probable-easy-mobile.png) |
| Tapis indéterminé | [capture](assets/c356/before-unknown-treadmill-desktop.png) | [capture](assets/c356/before-unknown-treadmill-mobile.png) | [capture](assets/c356/after-unknown-treadmill-desktop.png) | [capture](assets/c356/after-unknown-treadmill-mobile.png) |

Les fichiers JSON associés consignent routes, largeur, débordement, titres, texte
effectivement rendu, requêtes interceptées, erreurs et HEAD Git au moment du passage.
Ils documentent une validation fonctionnelle/rendu navigateur, pas une appréciation
graphique humaine exhaustive.
Le navigateur de capture a réellement ouvert les pages. L'outil de consultation
interactive des images était indisponible (« Transport closed ») : aucune approbation
graphique humaine exhaustive n'est revendiquée. Les captures restent à examiner.

## 8. Problèmes backend restant à corriger — C357

- Le catalogue C355 utilise notamment `:g` pour certaines valeurs intégrées au texte :
  dispersion (`backend/narrative_coach_v3.py:191-198`), écarts d'allure et tendances
  (`:348-385`). Il peut conserver des décimales trop précises et un point en FR/ES.
  Corriger l'arrondi et la localisation **dans le catalogue**, pas avec une regex frontend.
- Certaines phrases françaises utilisent « Votre/vos » (ex. `:385`) alors que l'ancien
  Coach tutoie. Uniformiser le catalogue backend vers le tutoiement en C357.
  C356 n'effectue aucun remplacement « vous → tu » et n'affiche pas les deux Coach ensemble.
- Aucun LLM n'est activé par C356 ; les fixtures ne démontrent pas son fonctionnement.

## 9. Risques de régression

- Deux lectures autorisées (V2 et V3) par page : charge/latence supérieure, mais erreurs
  indépendantes et absence de couplage de disponibilité.
- Changements de langue/droits pendant une réponse : cas à couvrir explicitement.
- Fallback historique conservé, donc hiérarchie ancienne lorsque C355 n'est pas disponible.
- Métriques structurées localisées/arrondies pour affichage seulement ; aucune donnée
  backend, classification, seuil ou prescription recalculée côté frontend.
- Validation réelle authentifiée sur les séances Garmin citées à effectuer par le
  propriétaire avant décision de merge ; ce sandbox n'en fournit pas les données.

## 10. Verdict

**GO conditionnel** pour revue de la PR brouillon : tests, build et contrôles de sécurité
réussis. Conditions avant merge : revue humaine des captures, essai authentifié sur
les séances Garmin réelles citées et acceptation des limites rédactionnelles C357.
L'outil de revue intégré indisponible est explicitement compensé par une revue read-only
indépendante, sans être présenté comme un succès de cet outil.

**STOP : aucun merge ni déploiement exécuté.**
