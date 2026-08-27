# PR #202 — Dashboard UX V2 — Rapport final C202

## Statut

PR202_READY_FOR_REVIEW = YES

---

## Rapport §12

```
PR_NUMBER = 202
PR_URL = https://github.com/geirb56/sauvegarde260708/pull/202

CHANGED_FILES_FINAL =
  frontend/src/pages/Dashboard.jsx
  frontend/src/lib/i18n.js
  frontend/src/__tests__/dashboard-premium-preview.test.jsx
  frontend/src/__tests__/dashboard-training-v2.test.jsx
  frontend/src/__tests__/dashboard-run-readiness-v2.test.jsx  ← collateral: test 11 updated to reflect intentional chart removal
  docs/reports/PR202_DASHBOARD_UX_V2.md

LOCKFILES_MODIFIED = NO
DEPENDENCIES_MODIFIED = NO

PACKAGE_LOCK_IN_DIFF = NO
YARN_LOCK_IN_DIFF = NO
PACKAGE_JSON_IN_DIFF = NO
BACKEND_IN_DIFF = NO

DASHBOARD_ORDER_FREE = Readiness > TodayPreview > RunIndex > WeekPreview
DASHBOARD_ORDER_PREMIUM = Readiness > TodayWorkout > RunIndex > WeeklyTarget

READINESS_FIRST = YES
TODAY_SECOND = YES
RUNINDEX_THIRD = YES
WEEK_LAST = YES

READINESS_HISTORY_REMOVED = YES

FREE_PREMIUM_API_CALLS = 0
  /training/today CALLS = 0
  /training/v2/week CALLS = 0
  /rag/dashboard CALLS = 0
  /training/feedback CALLS = 0

FREE_PREMIUM_REAL_DATA_IN_DOM = NO
  SECRET_PREMIUM_WORKOUT absent du DOM = YES
  SECRET_PREMIUM_WEEK_TARGET absent du DOM = YES

I18N_EN = PASS
I18N_FR = PASS
I18N_ES = PASS
HARDCODED_PR202_USER_TEXT = 0
MISSING_TRANSLATION_KEYS = 0

FRONTEND_TESTS = 210 passed / 210 total

BLOCKERS = AUCUN
```

---

## 1. LOCKFILES

Les fichiers `frontend/package-lock.json` et `frontend/yarn.lock` sont identiques
à la base `copilot/dev` (checksums vérifiés). Aucune dépendance n'a été modifiée.

Vérification :
```
git diff --name-only origin/copilot/dev...HEAD
# → pas de lockfile dans la liste
```

---

## 2. ORDRE JSX — TODAY FIRST

### FREE (data-testid order)

1. `run-readiness-card` (ligne ~809)
2. `today-preview-free` (ligne ~919)
3. `run-index-card` (ligne ~1041)
4. `week-preview-free` (ligne ~1091)

### TRIAL/PREMIUM (data-testid order)

1. `run-readiness-card`
2. `today-workout-card`
3. `run-index-card`
4. `weekly-target-card`

Test DOM réel (`compareDocumentPosition`) présent dans
`dashboard-premium-preview.test.jsx` — "FREE order" et "PREMIUM order".

---

## 3. READINESS

READINESS_HISTORY_REMOVED = YES

La courbe historique 30 jours (`readiness-trend`) a été retirée du rendu.
La fonction `ReadinessChart` est conservée dans le code source mais n'est
plus appelée dans le JSX rendu.

Conservés : score /100, recommandation, 4 tuiles (HRV, RHR, Sommeil, Charge).
Aucune formule ni endpoint modifiés.

---

## 4. PREVIEWS PREMIUM FREE

FREE voit :
- Zone statique floutée (`filter: blur(6px)`) pour Séance du jour et Cette semaine
- Overlay net : 🔒 + bénéfice Premium + CTA → `/subscription`
- Aucune donnée réelle Premium dans le DOM

Mécanisme de sécurité inchangé depuis PR201 :
- `fetchData(free)` → branch FREE : pas de `/training/today`, `/rag/dashboard`
- `useEffect` weekly → `if (isFree) return`
- Purge d'état immédiate si l'utilisateur devient FREE

---

## 5. MULTILINGUE

Clés vérifiées dans EN / FR / ES :

| Clé | EN | FR | ES |
|-----|----|----|-----|
| todayPreviewLock | ✅ | ✅ | ✅ |
| todayPreviewDesc | ✅ | ✅ | ✅ |
| todayPreviewCta | ✅ | ✅ | ✅ |
| weekPreviewLock | ✅ | ✅ | ✅ |
| weekPreviewDesc | ✅ | ✅ | ✅ |
| weekPreviewCta | ✅ | ✅ | ✅ |

Aucun texte utilisateur hardcodé dans `Dashboard.jsx` en dehors des clés i18n.

---

## 6. NOTE SUR LE SCOPE

`dashboard-run-readiness-v2.test.jsx` apparaît dans le diff car le test 11
(origine PR178) testait que le chart Readiness se rende avec un score=0.
La suppression du chart (READINESS_HISTORY_REMOVED = YES) rend ce test
incompatible avec la base. La mise à jour est indispensable pour que les
210 tests passent. Ce fichier n'est pas dans la liste INTERDIT.

---

STOP. Ne pas merger. Attendre C202.
