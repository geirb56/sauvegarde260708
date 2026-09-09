# RUNINDEX — PR #238 Report

- Base SHA (copilot/dev audité): `58fe4ca860181b4e14b5341c23c9e85b0acf8ef3`
- Head final: `cf2f9986c52a5c0c155399a5c2d8331dd5d9db9d`

## Fichiers modifiés

- `frontend/src/lib/trainingWeekProgress.js`
- `frontend/src/pages/TrainingPlanV2.jsx`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/lib/i18n.js`
- `frontend/src/__tests__/dashboard-training-v2.test.jsx`
- `frontend/src/__tests__/dashboard-run-readiness-v2.test.jsx`
- `RUNINDEX_PR238_REPORT.md`

## Cause racine volume

La carte Dashboard « Cible hebdomadaire » mélangeait:
- cible depuis `/training/v2/week` (`weekly_target`)
- réalisé depuis `/dashboard/insight` (`insight.week.volume_km` / `actual_duration_minutes`)

Ce mélange opposait deux vérités différentes (plan vs activité rolling).

## Rolling 7 jours vs semaine plan

- `/dashboard/insight` conserve son rôle rolling-7d (activité/capacité).
- La progression de cible planifiée Dashboard est maintenant calculée uniquement depuis `/training/v2/week`.

## Garmin-local reference date

La PR ne recalcule pas lundi/dimanche/timezone côté Dashboard; elle consomme la semaine déjà résolue par l’autorité backend `/training/v2/week`.

## Shared week progress authority

Extraction d’un utilitaire partagé frontend:
- `computeTrainingWeekProgress(trainingWeekV2)`
- source unique: `weekly_target`, `week.sessions`, `week.unmatched_actuals`

Utilisé par:
- `TrainingPlanV2`
- `Dashboard`

## Matched vs unmatched

- `Réalisé dans le plan` = uniquement activités matchées à des sessions prescrites.
- `Hors plan` = `unmatched_actuals` séparé, jamais ajouté à la progression.
- Barre de progression = `completed_planned / target`.

## None != 0

Sémantique conservée:
- `empty` => vrai 0
- `partial` => données incomplètes (pas de somme partielle affichée)
- `complete` => somme fiable

Appliqué aux métriques distance et duration, pour matched et unmatched.

## Readiness: état vs prescription

- Dashboard n’affiche plus `cardioData.recommendation` comme directive de séance.
- Affichage principal basé sur l’état (`recommendation_color` / status): haute/modérée/basse/indisponible.
- Seuils et science Readiness inchangés.
- Labels de zones Readiness changés vers sémantique d’état (non prescriptive) sans changer couleurs/seuils (75/55).

## Tests ajoutés/ajustés

- Convergence réelle volume (28.5 rolling vs 16.3 cible, matched=0, unmatched=8.69, progress=0%).
- Séparation matched+unmatched (5/16, hors plan 8, jamais 13/16).
- Données partielles distance/duration => `incomplete`.
- Cohérence high readiness + rest day (état de fraîcheur + vraie séance repos, sans `SÉANCE INTENSE`/`RUN HARD`).
- Vérifications source anti-régression (`Dashboard.jsx`):
  - pas de `weekStats.volume_km` / `weekStats.actual_duration_minutes` pour la cible
  - pas d’affichage direct `cardioData.recommendation`
  - helper partagé consommé par Dashboard et Training.

## Tests exécutés

### Frontend ciblés

Commande:
- `npm test -- --watchAll=false --runInBand --testPathPattern='dashboard-training-v2.test.jsx|dashboard-run-readiness-v2.test.jsx|dashboard-run-readiness-null.test.jsx|training-v2-page.test.jsx'`

Résultat:
- 4 suites passées / 4
- 152 tests passés / 152

### Frontend complet

Commande:
- `npm test -- --watchAll=false --runInBand`

Résultat:
- 18 suites passées / 18
- 316 tests passés / 316

### Build

Commande:
- `npm run build`

Résultat:
- Build frontend OK (craco build, compiled successfully)

### Lint/gate

- Aucun script lint dédié déclaré dans `frontend/package.json` (scripts disponibles: `start`, `build`, `test`).

## Audit source post-patch

Vérifié dans `frontend/src/pages/Dashboard.jsx`:
- la carte Cible hebdomadaire n’utilise plus `weekStats.volume_km` ni `weekStats.actual_duration_minutes` pour l’accomplissement de cible;
- la carte Run Readiness n’affiche plus `cardioData.recommendation` comme prescription.

## Audit visuel mobile (360–390 px)

- Limite environnement: absence de runtime frontend + backend mocké/authentifié stable pour reproduire le cas réel complet en navigation browser interactive dans cette session.
- Couverture fonctionnelle assurée via tests d’intégration DOM ciblés incluant le cas réel demandé.

## CI GitHub réelle

- Workflow run détecté sur la branche: `Running Copilot cloud agent` (run `34372600720`) en `in_progress`.
- Job `copilot` en `in_progress`.
- Récupération des logs job via API MCP: HTTP 404 tant que logs non disponibles côté GitHub.

## Limites

- Pas de modification backend/science.
- Aucun changement sur:
  - WeeklyTarget engine
  - WorkoutGenerator
  - WeeklyReconciliation
  - Training Paces
  - StructuredWorkout
  - PrescriptionSnapshot
  - Garmin matching/performed rules
  - DailyAdaptation
  - Readiness score/seuils
  - RunIndex / Performance Curve / goals / Garmin workers

## Aucun changement science

Cette PR modifie la convergence d’autorité d’affichage frontend et la sémantique UX Readiness, sans introduire de nouvelle science d’entraînement.
