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

## Modifications et validations

À compléter après l’implémentation et les contrôles de cette PR. Les résultats synthétiques de référence ne valent pas validation sur l’activité réelle `24671804067` ni sur le runtime Emergent.
