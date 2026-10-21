# C356 — Workout Analysis UX V3

## Périmètre et traçabilité

- Base : `copilot/dev`, `ee0109efe6f614136bf7aee98e409b70d73858ef` (merge C355).
- Branche de livraison : `copilot/c356-workout-analysis-ux-v3`.
- HEAD du code validé et résultats définitifs : renseignés après les validations ci-dessous.
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

Validation finale des trois pages, suite complète, build et contrôles automatisés :
résultats à compléter après exécution.

## 7. Validation visuelle

Captures **réelles de Chromium local**, sur fixtures **synthétiques contractuelles** :
elles ne sont ni des captures de séances Garmin réelles ni une revalidation scientifique
de C355. Toutes les requêtes API sont interceptées ; les domaines externes sont bloqués.
Les polices externes bloquées peuvent provoquer une police de repli dans les captures.

- Desktop : **1440 × 1100**.
- Mobile : **390 × 844**.
- Trois exemples : fractionné, footing probable, séance tapis indéterminée.
- Avant : route `WorkoutDetail` ouverte pour chaque exemple et viewport.
- Après : les trois routes doivent être réellement ouvertes et les disclosures actionnés
  au clavier ; résultat final à compléter.

| Exemple | Avant desktop | Avant mobile | Après desktop | Après mobile |
| --- | --- | --- | --- | --- |
| Fractionné | [capture](assets/c356/before-intervals-desktop.png) | [capture](assets/c356/before-intervals-mobile.png) | [capture](assets/c356/after-intervals-desktop.png) | [capture](assets/c356/after-intervals-mobile.png) |
| Footing probable | [capture](assets/c356/before-probable-easy-desktop.png) | [capture](assets/c356/before-probable-easy-mobile.png) | [capture](assets/c356/after-probable-easy-desktop.png) | [capture](assets/c356/after-probable-easy-mobile.png) |
| Tapis indéterminé | [capture](assets/c356/before-unknown-treadmill-desktop.png) | [capture](assets/c356/before-unknown-treadmill-mobile.png) | [capture](assets/c356/after-unknown-treadmill-desktop.png) | [capture](assets/c356/after-unknown-treadmill-mobile.png) |

Les fichiers JSON associés consignent routes, largeur, débordement, titres, texte
effectivement rendu, requêtes interceptées, erreurs et HEAD Git au moment du passage.
Ils documentent une validation fonctionnelle/rendu navigateur, pas une appréciation
graphique humaine exhaustive.

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

**En attente des validations finales.** Aucun merge ni déploiement demandé/exécuté.
