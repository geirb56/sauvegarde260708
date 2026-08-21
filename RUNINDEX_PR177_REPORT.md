# RUNINDEX PR #177 — BASCULE FRONTEND TRAINING V2

## Metadata

| Field | Value |
|-------|-------|
| BASE_BRANCH | copilot/dev |
| HEAD_START | 7047ca2cef5026b62e0025de531427fd9d72edd0 |
| HEAD_FINAL | (set after push) |

## Routes canoniques

| Field | Value |
|-------|-------|
| TRAINING_CANONICAL_ROUTE | /training |
| TRAINING_WEEK_AUTHORITY | /api/training/v2/week |
| TRAINING_CYCLE_AUTHORITY | /api/training/v2/cycle |
| TRAINING_TODAY_AUTHORITY | /api/training/today |

## Scan statique — appels legacy depuis /training

| Endpoint | Count |
|----------|-------|
| TRAINING_LEGACY_PLAN_CALLS | 0 |
| TRAINING_LEGACY_FULL_CYCLE_CALLS | 0 |
| TRAINING_LEGACY_METRICS_CALLS | 0 |
| TRAINING_LEGACY_REFRESH_CALLS | 0 |

Vérifié par test automatisé (test 6 — "never calls forbidden legacy training endpoints").

## Prescription future

| Field | Value |
|-------|-------|
| FUTURE_PRESCRIPTION_INVENTED | NO |

Le Cycle V2 n'affiche que : `week_number`, `start_date`, `end_date`, `phase`, `is_current`.
Aucun `sessions`, `target_km`, `target_duration_minutes`, `estimated_tss`, `long_run`, `pace`, `zones`, `intensity`.

## Progress.jsx — statut full-cycle

| Field | Value |
|-------|-------|
| PROGRESS_FULL_CYCLE_STATUS | LEFT_LEGACY_WITH_EXACT_REASON |

**Raison exacte** : `Progress.jsx` utilise `fullCycle?.goal` (ligne 636–654) pour mettre en évidence la distance cible dans les prédictions de course (`pred.distance === fullCycle?.goal`). Le contrat `GET /training/v2/cycle` ne fournit pas de champ `goal` — il expose uniquement `cycle.mode`, `cycle.status`, `cycle.start_date`, `cycle.end_date`, `cycle.current_week`, `cycle.total_weeks`, `cycle.days_to_race` et `weeks[]`. La migration serait une invention de données. Le consumer legacy reste donc temporairement, sans aucune réécriture générale de Progress.

## Périmètre hors-scope

| Field | Value |
|-------|-------|
| READINESS_MODIFIED | NO |
| RUNINDEX_MODIFIED | NO |
| COACH_MODIFIED | NO |
| BACKEND_MODIFIED | NO |
| LOCKFILES_MODIFIED | NO |

## Fichiers modifiés

- `frontend/src/App.js` — `/training` → `TrainingPlanV2`; `/training-v2` → `<Navigate to="/training" replace />`
- `frontend/src/pages/TrainingPlanV2.jsx` — ajout Cycle V2 (`GET /training/v2/cycle`); paywall `returnPath` corrigé; composants `CycleSection`/`CycleWeekRow` extraits au niveau module
- `frontend/src/lib/i18n.js` — traductions cycle/phases ajoutées EN/FR/ES
- `frontend/src/__tests__/training-v2-page.test.jsx` — 15 tests PR #177 implémentés

`TrainingPlan.jsx` — laissé physiquement présent, NON routé.

## Tests

| Résultat | Count |
|----------|-------|
| passed | 92 |
| failed | 0 |
| skipped | 0 |
| errors | 0 |

Tests couverts (15 tests PR #177) :
1. ✅ /training rend le composant V2
2. ✅ /training-v2 redirige vers /training
3. ✅ FREE → Paywall, aucun appel API
4. ✅ TRIAL/PREMIUM → /training/v2/week appelé
5. ✅ TRIAL/PREMIUM → /training/v2/cycle appelé
6. ✅ Aucun appel endpoint legacy depuis /training
7. ✅ Duration basis — durée native, aucun faux km
8. ✅ Distance basis — UnitContext metric + imperial
9. ✅ estimated_tss=null → aucun "0 TSS"
10. ✅ estimated_tss=0 → "0 TSS" autorisé
11. ✅ Cycle — total_weeks affiché, semaine courante identifiable
12. ✅ Phases base/build/specific/taper/race/consolidation supportées
13. ✅ Aucune prescription future inventée dans cycle weeks
14. ✅ Aucun changement Coach
15. ✅ Aucun changement backend

Tests #173/#174 frontend : ✅ verts (92 total, 0 failed)

## Verdict

**READY FOR MERGE INTO copilot/dev**
