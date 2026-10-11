# RUNINDEX PR329 — Workout Analysis V2 : simplification UX

## Références et état de l’audit

- Base canonique : `copilot/dev` à `13f4881b2afa74ffa027160015b00af4c1b8fd4a`.
- Tête du code audité avant l’ajout de ce rapport : `7e008bbe1566024d4d1b5aa06a63a3f54ffcbe2d`.
- Les PR #318, #324 et #328 étaient intégrées à cette base.
- Audit réalisé en lecture seule avant toute modification, sur les trois pages, les helpers et traductions frontend, les tests concernés, le contrat de `backend/workout_analysis_v2.py` et le raccordement `backend/coach_context_v2.py`.

### Diagnostic initial

- `WorkoutDetail` répétait les faits de séance dans plusieurs cartes : métriques principales, synthèse d’allure, splits kilométriques, réponse/zones cardiaques, comparaisons récentes à 14 jours et sorties similaires à 180 jours. Des détails avancés exposaient preuves, versions, couverture et limitations internes.
- `DetailedAnalysis` et `SessionDetail` présentaient des faits et observations qui divergeaient de l’écran principal; certaines vues secondaires conservaient des métriques ou détails techniques sans conclusion historique défendable.
- L’indisponibilité d’intensité et les avertissements de couverture/comparabilité étaient visibles, même lorsqu’ils ne changeaient pas la compréhension de la séance.
- Les références historiques fournissaient fenêtres, effectifs et écarts bruts, mais pas toujours des critères suffisants de structure et de comparabilité pour conclure à une progression ou à une exécution plus régulière.
- Le contrat V2 fournit déjà `phase_analysis` (phases, ordre, efforts/récupérations et régularité), ainsi que les champs internes d’analyse, preuves, limitations et comparaison. Le composant Coach consomme l’analyse canonique via `coach_context_v2.py`.
- L’accès frontend repose sur `coach_workout_analysis`. Les pages conservent les faits de séance et affichent l’avis d’accès lorsque l’utilisateur n’est pas autorisé; l’écran d’analyse secondaire est protégé. Le parcours Coach transmet l’identifiant de séance.

## Changements livrés

- Nouveau `WorkoutPhaseAnalysis` partagé par les trois écrans. Il lit uniquement `phase_analysis`, garde l’ordre enregistré, associe une récupération seulement si elle suit immédiatement l’effort, replie les récupérations et omet les valeurs absentes. Il conserve les phases inconnues et affiche les autres phases de façon neutre.
- Remplacement des cartes détaillées par un résumé compact (nombre d’efforts/récupérations, allure moyenne disponible, régularité disponible) et des lignes d’effort (numéro, durée, allure, FC moyenne disponible). Les phases d’échauffement, de retour au calme et autres restent synthétiques.
- Alignement de `WorkoutDetail`, `DetailedAnalysis` et `SessionDetail` sur les faits principaux, la structure, une conclusion existante si elle est étayée, puis l’observation Coach distincte. La sélection de conclusion ne crée pas d’interprétation côté React; l’observation redondante sur la dispersion est supprimée lorsque la régularité est déjà présentée.
- Suppression des panneaux historiques, splits kilométriques, zones cardiaques, détails avancés, preuves et diagnostics du parcours utilisateur de ces trois pages. Les contrats et champs internes restent inchangés.
- Une classification physiologique apparaît uniquement lorsqu’elle est explicitement disponible. Aucune mention « intensité indisponible » ni valeur de substitution n’est affichée.
- Le formatage reste adapté au sport : allure de course si valide, sinon vitesse enregistrée utilisable; vitesse pour le vélo. Les métriques absentes ne sont pas remplacées par des données inventées.
- Le bouton Coach conserve l’accès sur les trois pages et navigue vers `/coach?analyze=<id exact>`. Le chargement d’analyse ne déclenche pas le LLM.

### Fichiers modifiés

1. `frontend/src/components/workout/WorkoutPhaseAnalysis.jsx` — nouveau composant commun des phases compactes.
2. `frontend/src/lib/workoutAnalysis.js` — sélection prudente de la conclusion et suppression des observations redondantes.
3. `frontend/src/pages/WorkoutDetail.jsx` — hiérarchie de séance simplifiée, diagnostics/historique masqués, accès et sport conservés.
4. `frontend/src/pages/DetailedAnalysis.jsx` — vue secondaire alignée et navigation Coach conservée.
5. `frontend/src/pages/SessionDetail.jsx` — vue de session alignée, diagnostics/historique masqués.
6. `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx` — couverture des phases, des trois écrans, de l’accès et de la navigation; adaptation des assertions qui ne vérifiaient que l’ancienne présentation historique/avancée.
7. `RUNINDEX_PR329_WORKOUT_UX_SIMPLIFICATION_REPORT.md` — présent rapport et checklist runtime.

## Validation et limites

- Calculs backend : **aucune modification** de `backend/workout_analysis_v2.py` ni de `backend/coach_context_v2.py`; aucune modification de Training V2, des prescriptions, de l’ingestion, des quotas, des gardes backend ou des dépendances.
- Tests ciblés : `npx craco test --watchAll=false --forceExit --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx --silent` — **267 tests réussis sur 267**.
- Tests frontend complets : `npx craco test --watchAll=false --forceExit --silent` — **33 suites réussies sur 34; 823 tests réussis sur 824**. L’échec restant est `src/__tests__/progress-v2-migration.test.jsx` (« predictions list rendering preserved »), qui vérifie un fragment structurel de Progress; aucun fichier Progress n’est modifié par cette PR.
- Build : `npm run build` — **réussi** (`Compiled successfully`). L’avertissement Browserslist indique uniquement une base `caniuse-lite` ancienne.
- `git diff --check` : réussi.
- Validation runtime Emergent : **non exécutée**. Jest et le build ne prouvent pas le rendu de l’activité réelle.
- Risques restants : rendu réel/mobile, exactitude de l’appariement des données source sur l’activité cible, et vérification manuelle des droits Coach à confirmer en runtime. L’échec de test Progress est hors périmètre et reste à traiter séparément.

## Checklist de validation Emergent — à exécuter après revue et merge autorisé

- [ ] Activité Garmin réelle `garmin-24671804067`, séance du 10 octobre 2026, 4 × 4 min : quatre efforts visibles et ordonnés.
- [ ] Récupérations lisibles, repliées par défaut, uniquement associées aux phases adjacentes observées.
- [ ] Lecture immédiate des faits; aucun avertissement technique, chiffre historique non démontré ou texte redondant.
- [ ] Vérifier les trois écrans : `WorkoutDetail`, `DetailedAnalysis`, `SessionDetail`.
- [ ] Vérifier l’affichage mobile à 360 px et 390 px sans débordement.
- [ ] Vérifier la navigation Coach avec l’identifiant exact et les droits FREE/TRIAL/PREMIUM.
- [ ] Vérifier une séance continue et une séance sans phases.
- [ ] Consigner le résultat réel séparément; ne pas déduire la réussite des tests Jest ou du build.
