# RUNINDEX — PR324 — Workout Detail : restitution des phases structurées

## Audit préalable en lecture seule — 10 octobre 2026

### Références et périmètre

- Dépôt : `geirb56/sauvegarde260708`.
- Branche d’intégration cible : `copilot/dev`.
- HEAD initial de l’audit et de la branche de travail : `2e9dfacae2d3c69f6e0273145cfdad86883f9acf`, merge de la PR #323.
- La tête GitHub de `copilot/dev` observée pendant l’audit est également `2e9dfacae2d3c69f6e0273145cfdad86883f9acf`.
- L’audit ci-dessous a précédé toute modification de l’interface ou des tests.
- Aucun accès MongoDB Emergent, appel Garmin/GCCLI, merge ou déploiement n’a été effectué.

### Fichiers et historique examinés

Code et tests actuels :

- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/WorkoutDetail.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/DetailedAnalysis.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/lib/workoutAnalysis.js`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/lib/i18n.js`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/lib/i18n.test.js`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2_service.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/context/SubscriptionContext.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`

Les métadonnées et fichiers des PR #318, #319, #320 et #322 ont aussi été retrouvés sur GitHub. Les rapports historiques #318, #322 et #323 présents dans le dépôt ont été consultés. #318 a établi la hiérarchie mobile de Workout Detail et ses traductions/tests ; #319 a étendu le contrat éditorial V2 ; #320 a adapté ses consommateurs frontend ; #322 a ajouté `phase_analysis` au contrat V2 sans modifier les champs et calculs préexistants. #323 a corrigé le fallback d’allure de phase en présence d’une durée ou distance explicitement nulle.

### Chargement, contrat et données optionnelles

- Workout Detail effectue séparément `GET /workouts/{id}` et `GET /coach/workout-analysis/{id}?language={lang}` dans son effet React. Il ne fait pas d’appel spécifique pour les phases.
- La route backend d’analyse renvoie `WorkoutAnalysisV2Response` et exige l’authentification. Le service charge le workout dans le périmètre de l’utilisateur. Aucun contrôle d’abonnement propre à cette route n’a été trouvé dans le gestionnaire examiné.
- Le contrat backend réel expose `phase_analysis` avec une valeur par défaut compatible avec les réponses antérieures. Il contient `available`, `analysis_type`, `phases`, `efforts`, `recoveries`, `effort_statistics`, `recovery_statistics`, `effort_regularity`, `missing_data` et `limitations`.
- Le frontend est en JavaScript sans type frontend dédié à ce schéma. Le backend rend les nombres de phases facultatifs/nullable, les tableaux ont des valeurs par défaut vides et les statistiques/régularité ont des valeurs par défaut. Les mesures à afficher sont notamment `duration_s`, `distance_m`, `pace_sec_per_km`, `average_hr` et `max_hr`; les valeurs manquantes restent nulles, pas des zéros de remplacement.
- Chaque phase expose aussi un ordre, un `phase_type` neutralisé (`effort`, `recovery`, `warmup`, `cooldown` ou `unknown`) et des numéros facultatifs. `native_type` et `source` sont des champs techniques qui ne sont pas nécessaires à la compréhension par l’utilisateur.
- `effort_regularity` est descriptif : `available`, `comparable_effort_count`, `pace_sample_count`, `partial_comparison`, dispersion, évolution premier–dernier et évolution des FC moyennes peuvent être absents ou partiels. Une seule répétition ou `available=false` ne justifie aucun jugement de régularité.
- Les limitations de phases sont des codes internes, contrairement aux limitations générales d’analyse qui disposent déjà de textes localisés. Les codes de phase ne doivent pas être affichés directement.

### Insertion UI, composants et comportements à préserver

- Workout Detail a déjà une hiérarchie visible pour le résumé, les points clés, l’allure/splits, la réponse cardiaque, l’historique et le conseil, puis des détails techniques repliables. Les composants `Card`/`CardContent` et les tokens Tailwind de la page sont réutilisables.
- `SplitsChart` visualise des fractions kilométriques, pas des phases structurées ; le détourner confondrait les deux contrats. La phase doit être intégrée comme une section distincte après le résumé de séance et avant les sections de pacing/splits existantes.
- L’ordre métier est disponible dans `phase_analysis.phases`. L’association d’une récupération à un effort n’est justifiée que si leur position chronologique établit directement cette relation ; le frontend ne doit pas fabriquer une alternance ou déduire une séance depuis son titre.
- Lorsque `phase_analysis.available` est faux, la section de phases doit être entièrement absente. Le résumé et les sections standard actuels restent intacts. Une ancienne réponse sans le champ doit suivre ce même chemin.
- Pendant le chargement et en cas d’erreur de l’analyse, les états standard existants restent l’autorité. L’échec de l’analyse ne doit pas devenir une erreur de phases distincte. Les splits valides restent accessibles même si l’analyse est en chargement ou indisponible.
- La page utilise actuellement un conteneur `max-w-3xl`, `min-w-0`, du texte sécable, des cartes compactes, une grille responsive et des contrôles tactiles. Les tests DOM ne constituent pas une validation visuelle réelle sur Android.

### Droits d’accès observés

- Workout Detail ne consomme pas `SubscriptionContext` et ne masque pas conditionnellement Workout Analysis V2 selon `FREE`, `TRIAL` ou `PREMIUM`. La requête d’analyse existante est faite sans contrôle de plan dans cette page.
- Le nouveau rendu doit donc rester dans le même périmètre d’accès que les données déjà renvoyées à cette page, sans introduire de nouveau contrôle, endpoint ou règle d’abonnement. Les droits effectifs de la route restent déterminés par les contrôles backend existants ; cette PR frontend ne les redéfinit pas.

## Composants réutilisés

- La section s’intègre dans `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/WorkoutDetail.jsx`, sous le résumé de séance et avant les points clés existants.
- Elle reprend les composants `Card`/`CardContent`, les classes Tailwind et le formateur d’allure `formatPaceDisplay` déjà utilisés dans Workout Detail.
- `SplitsChart` est laissé inchangé : les splits kilométriques restent affichés dans la section de pacing et ne sont ni recalculés ni confondus avec des phases.
- Aucune bibliothèque, aucun composant graphique ou endpoint supplémentaire n’a été ajouté.

## Modifications effectuées

- Ajout d’une section autonome d’efforts/récupérations, rendue uniquement lorsque `phase_analysis.available === true`.
- Résumé : nombre d’efforts et de récupérations, temps total et distance des efforts, allure moyenne des efforts quand calculable.
- Détail : les phases sont triées selon `order`; chaque effort comprend durée, distance, allure et FC moyenne/maximale disponibles. Les récupérations consécutives immédiates sont rattachées au détail de cet effort. Une récupération sans lien direct reste une ligne distincte; les échauffements, retours au calme et types inconnus demeurent visibles dans leur position chronologique avec un libellé neutre. Aucun `native_type` fournisseur n’est rendu.
- Régularité : visible uniquement lorsque `effort_regularity.available === true`; le nombre comparable, la dispersion, l’évolution premier–dernier et l’évolution de FC moyenne sont affichés uniquement s’ils sont disponibles. `partial_comparison` reçoit une réserve explicite. Le texte décrit les mesures et ne porte aucun jugement de performance.
- Valeurs facultatives/non finies : omissions pour les indicateurs non calculables ou libellé traduit « Non enregistré » dans une répétition. `missing_data` et `limitations` sont rendus sous forme d’explications localisées, jamais sous forme de codes internes.
- Aucune modification de la classification historique `signals.session_type`, des calculs Workout Analysis V2, de la collecte ou d’un domaine backend.

Fichiers modifiés :

- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/WorkoutDetail.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/lib/i18n.js`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/__tests__/workout-analysis-v2-pages.test.jsx`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/RUNINDEX_PR324_WORKOUT_DETAIL_PHASES_UX_REPORT.md`

## Contrat API consommé

Le seul contrat lu est `analysis.phase_analysis`, reçu dans la réponse existante de `GET /coach/workout-analysis/{workout_id}?language={lang}`. Le frontend consomme `available`, `phases`, `efforts`, `recoveries`, les statistiques, la régularité, les valeurs manquantes et les limitations. L’unité d’allure est `pace_sec_per_km` (convertie vers le formateur existant en min/km); durées en secondes, distances en mètres et FC observées sont utilisées telles que fournies. `source`, `analysis_type` et `native_type` ne servent pas à reclasser les phases ou à afficher des données fournisseur.

## Comportement avec et sans phases

- `available=true` : section structurée, incluant aussi les cas partiels et les phases non-effort/récupération.
- `available=false`, champ absent (ancienne réponse), analyse en chargement ou erreur : aucune section de phases, aucun message d’erreur additionnel. Les sections standard gardent leur comportement.
- Les splits kilométriques fonctionnent indépendamment : ils restent visibles avec des phases et leur état vide reste inchangé sans splits.
- Les fixtures de cette PR sont synthétiques et sans donnée personnelle. Les valeurs de référence fournies dans le besoin servent uniquement à ces fixtures; l’activité `24671804067` n’a pas été interrogée et n’est pas déclarée validée.

## Gating et traductions

- La page n’utilise pas `SubscriptionContext` et n’avait pas de gate Workout Analysis V2. Le rendu ajouté ne crée ni entitlement, ni règle, ni endpoint et ne masque pas l’accès préexistant.
- Des tests utilisent le `SubscriptionProvider` actuel avec états `FREE`, `TRIAL` et `PREMIUM`; la section demeure au niveau d’accès existant dans les trois états.
- Libellés de phase, mesures manquantes, limites, comparabilité et régularité ajoutés dans le dictionnaire i18n existant FR/EN/ES. Le test de parité i18n vérifie les clés et les placeholders d’interpolation des trois langues.

## Tests et contrôles exécutés

Base : `copilot/dev` à `2e9dfacae2d3c69f6e0273145cfdad86883f9acf`.
HEAD code/tests avant l’ajout documentaire final : `a2635fa3cf0f37eb7e8786932f81a4a012cd1145`.
HEAD de validation parallèle CodeQL : `547d78b5304a571f6b2bdefab2a2092c8cdb910d` (rapport d’audit déjà inclus).

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend` :

| Commande | Résultat |
|---|---|
| `CI=true npm test -- --watchAll=false --runInBand --forceExit --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx src/lib/i18n.test.js` | **2 suites réussies, 242 tests réussis, 0 échec** |
| `CI=true npm test -- --watchAll=false --runInBand --forceExit` | **34 suites : 33 réussies, 1 échouée; 795 tests réussis, 1 échoué** |
| `npm run build` | **Réussite** — compilation de production réussie |

L’unique échec de la suite frontend complète est dans le test hors périmètre `src/__tests__/progress-v2-migration.test.jsx`, assertion historique `predictions.predictions?.map` sur le texte source de `Progress.jsx`. Aucun fichier Progress ni code de cette page n’est modifié par cette PR. Le build signale aussi la base Browserslist/caniuse-lite datée; aucune dépendance n’a été modifiée. Un avertissement existant concernant l’absence de `REACT_APP_BACKEND_URL` apparaît dans les tests.

`git diff --check` a réussi. Le scan de secrets des trois fichiers source/test modifiés n’a détecté aucun secret. Aucun script lint n’est déclaré dans `frontend/package.json`; aucun lint ad hoc n’a été ajouté. La vérification 360 px est un test DOM statique des classes de retour à la ligne/conteneur, pas une validation de rendu visuel réel.

`parallel_validation` : CodeQL JavaScript **0 alerte**. La tâche Code Review n’a retourné aucun commentaire, mais son propre résultat indique que le modèle demandé est indisponible dans le registre; cette exécution n’est donc pas présentée comme une revue indépendante complète. Le HEAD de livraison final contiendra la présente mise à jour documentaire, sans changement du code/test validé au HEAD parallèle ci-dessus.

## Risques résiduels

- Sans données runtime Emergent, la présence et les valeurs du contrat dans l’environnement déployé ne sont pas vérifiées.
- Les classes responsive sont testées dans le DOM, mais l’absence de débordement réel et la lisibilité tactile doivent être confirmées visuellement sur Android aux largeurs 360/390 px.
- Les phases inconnues ou mesures manquantes restent descriptives; les fixtures synthétiques ne remplacent pas l’examen par les réviseurs des données autorisées.
- Le test de suite complète existant hors périmètre demeure en échec décrit ci-dessus.

## Vérifications runtime à effectuer dans Emergent

1. Sur une activité structurée autorisée, confirmer l’ordre des phases, les nombres d’efforts/récupérations, les unités, les valeurs nulles et la correspondance de récupération uniquement pour les phases directement successives.
2. Vérifier une phase inconnue, une récupération absente, des FC/allures manquantes, une régularité indisponible/partielle, ainsi que l’affichage combiné ou absent des splits.
3. Vérifier qu’une activité sans phases et une ancienne réponse API conservent exactement le rendu standard et que `session_type=standard` n’est pas modifié.
4. Confirmer les droits effectifs `FREE`/`TRIAL`/`PREMIUM` de l’API existante; cette PR ne les redéfinit pas.
5. Parcourir FR/EN/ES et contrôler l’interface réelle sur Android à 360 px et 390 px, sans débordement horizontal.
6. Ne lancer aucun enrichissement fournisseur lors de cette vérification; attendre la revue C324 avant toute décision de merge ou déploiement.

La PR demande uniquement l’intégration de l’affichage frontend. Aucun merge ni déploiement n’a été effectué.

## C324 — Finalisation du gating après PR #325

### Références exactes et audit préalable en lecture seule

- Branche de base GitHub `copilot/dev` : `626a0f9d979122b15c93efd650c0597089a794e8`.
- PR #325 : intégrée dans ce HEAD par le merge commit `626a0f9d979122b15c93efd650c0597089a794e8`; le head #325 était `e23b820dfdc11a5f1a115d3ef9fd10499dfe01ce`.
- PR #324 au début de cette correction : `b2a97833e9a23c845da5c13306f5b29bd624968a`. HEAD de validation du code et des tests de gating : `b3eb5140ba848f5dd132a757427e992dd9f426e6`. L’actualisation documentaire ci-dessous ne change pas le code testé.
- Le merge de `copilot/dev` dans la branche #324 a été fait sans conflit. Les fichiers backend modifiés par #325 ne recoupent aucun des fichiers frontend de #324. Le diff de correction par rapport à `copilot/dev` ne contient que des fichiers frontend et ce rapport.
- Audit effectué avant l’édition de cette correction. Aucune modification du backend #325, des calculs V2, du contrat des phases, de Garmin/GCCLI, du Coach FREE, de Training V2 ou de Readiness.

### Droit observé et chemins concernés

- `SubscriptionContext` dans `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/context/SubscriptionContext.jsx` tire les droits de `/user/features`; `hasFeature(feature)` lit seulement `feature_access` et renvoie `false` si le droit manque. L’état `loading` est initialement vrai. Une erreur de récupération met en place des droits fail-closed; `/subscription/info` ne décide pas de l’accès.
- Le seul contrôle employé dans ces pages est `!loading && hasFeature("coach_workout_analysis") === true`. Cet entitlement canonique est true pour TRIAL actif et PREMIUM et false pour FREE, TRIAL expiré, chargement, réponse sans entitlement ou échec.
- Consommateurs frontend directs de `GET /coach/workout-analysis/{id}` repérés : `WorkoutDetail.jsx`, `DetailedAnalysis.jsx`, `SessionDetail.jsx`. L’ancienne route `/coach/detailed-analysis/{id}` n’est pas consommée et reste retirée.
- La protection additionnelle backend est déjà livrée par #325 : dans `server.py`, `_coach_access()` consulte `UserAccess.can("coach_workout_analysis")`, fail-closed; le handler du Coach n’injecte l’analyse de séance que si l’accès est vrai. Les tests `backend/tests/test_coach_workout_access_pr325.py` couvrent le refus FREE/d’échec d’accès, l’accès TRIAL/PREMIUM et la suppression du détail V2 dans le contexte FREE. La route directe V2 reste protégée par le middleware d’accès PREMIUM et le chargement de workout reste user-scoped. Aucun droit du Coach FREE n’a été changé par cette correction.
- Les faits de séance et splits viennent de `GET /workouts/{id}` et demeurent accessibles. Les résumés, interprétations, signaux, pacing/physiology dérivés, phases, régularité, comparaisons, observations, preuves et limitations venant de V2 sont protégés.

### Correctifs frontend

- **Workout Detail :** chargement des faits de séance séparé de celui de V2; appel V2 conditionné à la résolution positive de l’entitlement. Pendant le chargement des droits, après refus ou erreur, aucun appel V2 ni rendu de données V2. Le résultat analysé est masqué dès que `canAccessAnalysis` devient faux; le changement de dépendance annule le chargement précédent. La réactivation autorisée lance une nouvelle requête. Les fallbacks pour allure, vitesse et FC ne réutilisent pas de valeur V2 quand l’accès est refusé; les valeurs factuelles du workout et les splits restent visibles. Une invitation discrète localisée pointe vers `/subscription`.
- **Detailed Analysis :** même gate; aucune requête ni aucun ancien contenu lorsque le droit manque; l’accès refusé présente l’invitation et un retour vers la séance.
- **Session Detail :** chargement des faits indépendant; seule la section d’analyse et ses limitations dépendent du droit. Les requêtes d’analyse sont annulées/ignorées si l’accès change; les faits de séance restent visibles à FREE.
- La logique partagée ne réimplémente aucun palier. Les libellés de l’invitation sont disponibles en FR/EN/ES. Aucun changement de design général ou de navigation.

### Tests et non-régression

Sur `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend` :

| Commande | Résultat |
|---|---|
| `CI=true npm test -- --watchAll=false --runInBand --forceExit --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/subscription-context-authority.test.jsx src/lib/i18n.test.js` | **3 suites réussies, 256 tests réussis, 0 échec** |
| `CI=true npm test -- --watchAll=false --runInBand --forceExit` | **34 suites : 33 réussies, 1 échouée; 806 tests réussis, 1 échoué** |
| `npm run build` | **Réussite**, compilation production réussie |
| `git diff --check origin/copilot/dev...HEAD` | **Réussite** |

Couverture ajoutée/actualisée : assertions réseau d’absence de requête V2 FREE sur les trois pages; faits/splits FREE; TRIAL/PREMIUM; TRIAL expiré; entitlement inconnu et chargement; downgrade immédiat et réactivation; entitlement réel fourni par `SubscriptionContext`; maintien des phases disponibles/indisponibles, comparabilité partielle, données manquantes, réponse legacy, langues FR/EN/ES et layout mobile 360 px. La suite conserve également les tests existants du comportement Coach; aucun code/droit du Coach FREE n’a été changé.

### Test historique Progress

Commande sur la base actuelle `626a0f9d979122b15c93efd650c0597089a794e8` dans le worktree `/home/runner/work/sauvegarde260708-base-current/frontend` :

`CI=true npm test -- --watchAll=false --runInBand --forceExit --runTestsByPath src/__tests__/progress-v2-migration.test.jsx`

- **Base actuelle :** 1 suite échouée, 10 tests réussis / 11; l’assertion ligne 73 exige le texte historique `predictions.predictions?.map`.
- **Tête #324 :** la même assertion échoue dans la suite complète (**806/807**). `Progress.jsx` et `progress-v2-migration.test.jsx` ne diffèrent pas entre la base et la tête #324.
- **Classification :** échec préexistant, non causé par #324; assertion de test obsolète par rapport au code qui valide `Array.isArray(predictions?.predictions)` puis rend `predictions.predictions.map`. Le rendu des prédictions est toujours présent. Progress n’a pas été modifié.

### Limites et vérifications Emergent restantes

- Le build avertit que la base Browserslist/caniuse-lite a sept mois; aucune dépendance n’a été changée. Les tests affichent aussi l’avertissement existant `REACT_APP_BACKEND_URL` absent avec fallback.
- Aucun runtime Emergent ni appareil Android n’est accessible dans cette validation locale. Dans Emergent, vérifier avec des comptes FREE, TRIAL actif, PREMIUM et TRIAL expiré : absence de requête réseau V2 en FREE/chargement/erreur; rechargement et retrait instantané du détail lors d’un changement de droit; faits/splits toujours visibles; navigation `/workout/:id/analysis` et `/sessions/:id`; appels Coach FREE refusés pour l’analyse personnalisée mais Coach général/quota inchangé. Confirmer les traductions et le rendu sans débordement à 360/390 px.
- La revue Code Review/CodeQL de la correction doit être consignée après son exécution. Aucune fusion ni aucun déploiement n’a été effectué; attendre la nouvelle revue C324.
