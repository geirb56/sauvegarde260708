# PR #202 — Dashboard UX V2 — Rapport final C202

## Statut

PR202_READY_FOR_REVIEW = YES

---

## 1. LOCKFILES

LOCKFILES_MODIFIED = NO
DEPENDENCIES_MODIFIED = NO

Les fichiers `frontend/package-lock.json` et `frontend/yarn.lock` ont été restaurés
exactement depuis la base `copilot/dev`. Aucun package n'a été modifié.

Commande de vérification :
```
git diff --name-only origin/copilot/dev...HEAD
```
Résultat : lockfiles absents du diff.

---

## 2. HIÉRARCHIE DASHBOARD — TODAY FIRST

### Ordre final FREE

DASHBOARD_ORDER_FREE = Readiness > TodayPreview > RunIndex > WeekPreview

READINESS_FIRST = YES
TODAY_SECOND = YES
RUNINDEX_THIRD = YES
WEEK_LAST = YES

Blocs JSX dans `Dashboard.jsx` :
1. `run-readiness-card` (Run Readiness — toujours premier)
2. `today-preview-free` (zone floutée statique — FREE uniquement)
3. `run-index-card` (RunIndex — troisième, FREE et PREMIUM)
4. `week-preview-free` (zone floutée statique — FREE uniquement)

### Ordre final TRIAL/PREMIUM

DASHBOARD_ORDER_PREMIUM = Readiness > TodayWorkout > RunIndex > WeeklyTarget

Blocs JSX :
1. `run-readiness-card`
2. `today-workout-card` (vraie séance du jour)
3. `run-index-card`
4. `weekly-target-card` (vrai weekly target V2)

---

## 3. READINESS

READINESS_HISTORY_REMOVED = YES

La courbe historique Readiness 30 jours (`readiness-trend`) a été retirée du Dashboard.

Conservés :
- Score /100
- Recommandation
- 4 tuiles : HRV, RHR, Sommeil, Charge d'entraînement
- Aucun calcul modifié

---

## 4. SÉANCE DU JOUR

FREE : zone statique floutée (`today-preview-free`) — aucun fetch Premium.
TRIAL/PREMIUM : vraie séance du jour (`today-workout-card`).

Règles de sécurité inchangées :
- /training/today = jamais appelé en FREE
- Aucune donnée Premium dans le DOM en FREE
- Placeholder statique uniquement

---

## 5. RUNINDEX

RunIndex déplacé en 3e position (après séance / preview séance).
RunIndex reste visible pour tous (FREE + PREMIUM).

Conservés : score /1000, confiance, 4 piliers.

---

## 6. CETTE SEMAINE

Dernier bloc dans les deux cas.
FREE : `week-preview-free` statique + overlay 🔒 + CTA → /subscription.
TRIAL/PREMIUM : `weekly-target-card` (vrai weekly target V2).

---

## 7. MULTILINGUE

MULTILINGUE_EN_FR_ES = YES
MISSING_TRANSLATION_KEYS = 0
HARDCODED_PR202_USER_TEXT = 0

Clés ajoutées dans EN / FR / ES :
- `todayPreviewLock`
- `todayPreviewDesc`
- `todayPreviewCta`
- `weekPreviewLock`
- `weekPreviewDesc`
- `weekPreviewCta`

---

## 8. TESTS

FRONTEND_TESTS = 210 passed / 210 total

Fichiers modifiés :
- `dashboard-premium-preview.test.jsx` — ajout des tests d'ordre DOM (FREE + PREMIUM),
  suppression de la courbe d'historique (`readiness-trend`).
- `dashboard-training-v2.test.jsx` — correction des tests 8–10c et 12 (usage de `isFree: false`
  pour les assertions sur les vraies cartes PREMIUM).
- `dashboard-run-readiness-v2.test.jsx` — Test 11 mis à jour :
  `READINESS_HISTORY_ON_DASHBOARD = NO` (chart n'est plus rendu).

Tests d'ordre DOM prouvant la hiérarchie :
- FREE : `run-readiness-card` < `today-preview-free` < `run-index-card` < `week-preview-free`
- PREMIUM : `run-readiness-card` < `today-workout-card` < `run-index-card` < `weekly-target-card`

Tests de sécurité FREE :
- FREE_PREMIUM_API_CALLS = 0 (/training/today, /training/v2/week, /rag/dashboard)
- FREE_PREMIUM_REAL_DATA_IN_DOM = NO (SECRET_PREMIUM_WORKOUT, SECRET_PREMIUM_WEEK_TARGET absents)

---

## 9. BLOCKERS

BLOCKERS = AUCUN

---

## 10. FICHIERS MODIFIÉS DANS PR202 (diff vs copilot/dev)

```
frontend/src/pages/Dashboard.jsx
frontend/src/lib/i18n.js
frontend/src/__tests__/dashboard-premium-preview.test.jsx
frontend/src/__tests__/dashboard-training-v2.test.jsx
frontend/src/__tests__/dashboard-run-readiness-v2.test.jsx
docs/reports/PR202_DASHBOARD_UX_V2.md
```

---

STOP. Ne pas merger. Attendre C202.
