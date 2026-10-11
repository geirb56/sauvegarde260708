# RUNINDEX PR329 — Workout Analysis V2 : simplification UX

## Références et état de l’audit

- Base canonique : `copilot/dev` à `13f4881b2afa74ffa027160015b00af4c1b8fd4a`.
- Base de comparaison canonique : `copilot/dev` / `13f4881b2afa74ffa027160015b00af4c1b8fd4a`.
- Le rapport a été actualisé après l’audit C329. Les fichiers Progress concernés sont identiques entre cette base et la branche PR.
- Les PR #318, #324 et #328 étaient intégrées à cette base.
- Audit réalisé en lecture seule avant toute modification, sur les trois pages, les helpers et traductions frontend, les tests concernés, le contrat de `backend/workout_analysis_v2.py` et le raccordement `backend/coach_context_v2.py`.

### Diagnostic initial

- `WorkoutDetail` répétait les faits de séance dans plusieurs cartes : métriques principales, synthèse d’allure, splits kilométriques, réponse/zones cardiaques, comparaisons récentes à 14 jours et sorties similaires à 180 jours. Des détails avancés exposaient preuves, versions, couverture et limitations internes.
- `DetailedAnalysis` et `SessionDetail` présentaient des faits et observations qui divergeaient de l’écran principal; certaines vues secondaires conservaient des métriques ou détails techniques sans conclusion historique défendable.
- L’indisponibilité d’intensité et les avertissements de couverture/comparabilité étaient visibles, même lorsqu’ils ne changeaient pas la compréhension de la séance.
- Les références historiques fournissaient fenêtres, effectifs et écarts bruts, mais pas toujours des critères suffisants de structure et de comparabilité pour conclure à une progression ou à une exécution plus régulière.
- Le contrat V2 fournit déjà `phase_analysis` (phases, ordre, efforts/récupérations et régularité), ainsi que les champs internes d’analyse, preuves, limitations et comparaison. Le composant Coach consomme l’analyse canonique via `coach_context_v2.py`.
- `WorkoutAnalysisMeaning.observations` est une liste de chaînes non typées. Le producteur `_phase_observations()` construit les observations pour `meaning.structured_phases` dans un ordre connu : dispersion d’allure (si la régularité est disponible), extrêmes d’allure, puis évolution factuelle de FC. Pour les codes non structurés sans intensité, le producteur peut concaténer un constat et une réserve physiologique dans une même chaîne; sans type de preuve ni séparation de phrase dans le contrat, l’interface ne tente pas de la découper.
- L’accès frontend repose sur `coach_workout_analysis`. Les pages conservent les faits de séance et affichent l’avis d’accès lorsque l’utilisateur n’est pas autorisé; l’écran d’analyse secondaire est protégé. Le parcours Coach transmet l’identifiant de séance.

## Changements livrés

- Nouveau `WorkoutPhaseAnalysis` partagé par les trois écrans. Il lit uniquement `phase_analysis`, garde l’ordre enregistré, associe une récupération seulement si elle suit immédiatement l’effort, replie les récupérations et omet les valeurs absentes. Il conserve les phases inconnues et affiche les autres phases de façon neutre.
- Remplacement des cartes détaillées par un résumé compact (nombre d’efforts/récupérations, allure moyenne disponible, régularité disponible) et des lignes d’effort (numéro, durée, allure, FC moyenne disponible). Les phases d’échauffement, de retour au calme et autres restent synthétiques.
- Alignement de `WorkoutDetail`, `DetailedAnalysis` et `SessionDetail` sur les faits principaux, la structure, une conclusion existante si elle est étayée, puis l’observation Coach distincte. La sélection de conclusion ne crée pas d’interprétation côté React; l’observation redondante sur la dispersion est supprimée lorsque la régularité est déjà présentée.
- Sélection des conclusions : `meaning.structured_phases` n’est éligible que si `phase_analysis.effort_regularity.available === true`; le premier fait existant est alors la dispersion mesurée produite par le backend. Les conclusions de classification physiologique ne sont éligibles que si `signals.intensity.available === true`, que le code est reconnu (`low`, `moderate`, `high`, `very_high`) et que `meaning.code` est un code de classification correspondant. Une phrase factuelle non structurée concaténée à une réserve n’est pas découpée ou affichée. Le Coach reste alimenté par son contrat canonique inchangé; la chaîne Coach structurée qui concatène la réserve est masquée à l’écran si l’intensité n’est pas disponible.
- Les splits kilométriques sont réintroduits via `WorkoutKilometerSplits`, un `<details>` replié par défaut avec une liste source-ordonnée de lignes compactes (kilomètre, allure/vitesse, FC enregistrée si disponible), sans graphique. Les entrées invalides et absentes sont omises; aucun panneau vide n’est rendu. Les valeurs utilisent le système d’unités sélectionné; un type cyclisme convertit l’allure enregistrée en vitesse pour l’affichage.
- Les panneaux historiques à 14/180 jours, zones cardiaques, détails avancés, preuves et diagnostics restent masqués. Les contrats et champs internes restent inchangés.
- Une classification physiologique apparaît uniquement lorsqu’elle est explicitement disponible. Aucune mention « intensité indisponible » ni valeur de substitution n’est affichée.
- Le formatage reste adapté au sport : allure de course si valide, sinon vitesse enregistrée utilisable; vitesse pour le vélo. Les métriques absentes ne sont pas remplacées par des données inventées.
- Le bouton Coach conserve l’accès sur les trois pages et navigue vers `/coach?analyze=<id exact>`. Le chargement d’analyse ne déclenche pas le LLM.

### Fichiers modifiés par PR #329 (incluant le correctif C329)

1. `frontend/src/components/workout/WorkoutPhaseAnalysis.jsx` — nouveau composant commun des phases compactes.
2. `frontend/src/components/workout/WorkoutKilometerSplits.jsx` — nouveau composant commun compact pour les splits repliés.
3. `frontend/src/lib/workoutAnalysis.js` — sélection prudente des conclusions et observations distinctes.
4. `frontend/src/lib/i18n.js` — libellés FR/EN/ES des splits.
5. `frontend/src/pages/WorkoutDetail.jsx` — hiérarchie simplifiée, splits factuels et accès préservé.
6. `frontend/src/pages/DetailedAnalysis.jsx` — vue alignée, chargement des splits de l’activité existante et navigation Coach.
7. `frontend/src/pages/SessionDetail.jsx` — vue alignée et splits factuels.
8. `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx` — non-régression conclusions, phases, splits, unités, accès et Coach; assertions de présentation historique/avancée adaptées.
9. `RUNINDEX_PR329_WORKOUT_UX_SIMPLIFICATION_REPORT.md` — ce rapport d’audit et checklist runtime.

## Validation et limites

- Calculs backend : **aucune modification** de `backend/workout_analysis_v2.py` ni de `backend/coach_context_v2.py`; aucune modification de Training V2, des prescriptions, de l’ingestion, des quotas, des gardes backend ou des dépendances.
- Tests ciblés : `npx craco test --watchAll=false --forceExit --runTestsByPath src/__tests__/workout-analysis-v2-pages.test.jsx --silent` — **281 tests réussis sur 281**.
- Tests frontend complets : `npx craco test --watchAll=false --forceExit --silent` — **33 suites réussies sur 34; 837 tests réussis sur 838**. L’unique échec reste `src/__tests__/progress-v2-migration.test.jsx`, test « predictions list rendering preserved ».
- Comparaison Progress : test exécuté à la base `13f4881b2afa74ffa027160015b00af4c1b8fd4a` et sur le code corrigé au commit `829ef7e319481e3a607c9122d54ca105e081dc61` : **10/11 réussis aux deux révisions**, même assertion échouée ligne 73. Le test exige littéralement `predictions.predictions?.map`; `frontend/src/pages/Progress.jsx` emploie déjà la forme protégée `Array.isArray(predictions?.predictions) ? predictions.predictions.map(...)`. Les deux fichiers Progress sont inchangés entre base et PR (`git diff` vide). L’échec est donc préexistant, indépendant de PR329, et dû à une assertion textuelle obsolète; aucun correctif Progress n’a été apporté.
- Build : `npm run build` — **réussi** (`Compiled successfully`). L’avertissement Browserslist signale une base `caniuse-lite` ancienne.
- `git diff --check` : réussi.
- Validation runtime Emergent : **non exécutée**. Jest et le build ne prouvent pas le rendu de l’activité réelle.
- Justification de sûreté : la régularité d’allure est une mesure calculée à partir des phases comparables (cohorte de durées/distances et dispersion des allures) dans le moteur existant; elle ne dépend pas de LT1/LT2. Aucun seuil de zone générique n’est utilisé. Le frontend consomme uniquement ces observations factuelles et les codes d’intensité déjà fournis; il ne calcule ni seuils physiologiques ni conclusion scientifique.
- Exemple visuel compact : « Splits kilométriques enregistrés · 2 » reste replié; à l’ouverture, deux lignes `Km 2 · 5:30 /km · 149 bpm` et `Km 1 · 6:00 /km` suivent l’ordre source, sans barres ni graphe. Les splits invalides sont omis.
- Risques restants : le contrat n’identifie pas individuellement les observations et certaines phrases non structurées concatènent une réserve; elles sont donc omises plutôt que découpées par texte. La récupération des splits de la route secondaire peut échouer indépendamment de l’analyse, auquel cas le panneau est omis. L’affichage réel mobile, l’activité cible et les droits Coach restent à vérifier sur Emergent.

## Checklist de validation Emergent — à exécuter après revue et merge autorisé

- [ ] Activité Garmin réelle `garmin-24671804067`, séance du 10 octobre 2026, 4 × 4 min : quatre efforts visibles et ordonnés.
- [ ] Récupérations lisibles, repliées par défaut, uniquement associées aux phases adjacentes observées.
- [ ] Lecture immédiate des faits; aucun avertissement technique, chiffre historique non démontré ou texte redondant.
- [ ] Vérifier les trois écrans : `WorkoutDetail`, `DetailedAnalysis`, `SessionDetail`.
- [ ] Vérifier l’affichage mobile à 360 px et 390 px sans débordement.
- [ ] Vérifier la navigation Coach avec l’identifiant exact et les droits FREE/TRIAL/PREMIUM.
- [ ] Vérifier une séance continue et une séance sans phases.
- [ ] Consigner le résultat réel séparément; ne pas déduire la réussite des tests Jest ou du build.
