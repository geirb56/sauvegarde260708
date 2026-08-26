# PR201 — Access Control Frontend V2 — Rapport

BASE_BRANCH = copilot/dev
BASE_SHA = 5a3f1f8328c6f923907517c2e70fde7e54f79141
HEAD_SHA = 58ad914d3fcf5641c93b66f3f418a124b815c412

FILES_CHANGED = 5
LINES_ADDED = 449
LINES_REMOVED = 48

UNAUTHORIZED_FILES_CHANGED = 0
BACKEND_MODIFIED = NO
LOCKFILES_MODIFIED = NO
DEPENDENCIES_MODIFIED = NO

FRONTEND_CANONICAL_ACCESS = /api/user/features
FAIL_CLOSED = YES (hasPremiumAccess=false, isFree=true si /user/features indisponible)
TRIAL_EQUALS_PREMIUM = YES (tous deux has_premium_access=true → même chemin fonctionnel)

FREE_DASHBOARD_INSIGHT_CALLS = 1
FREE_DASHBOARD_RUN_INDEX_CALLS = 1
FREE_DASHBOARD_RAG_CALLS = 0
FREE_DASHBOARD_TRAINING_TODAY_CALLS = 0
FREE_DASHBOARD_TRAINING_WEEK_CALLS = 0

FREE_READINESS_SOURCE = /run-index metrics.run_readiness

FREE_PROGRESS_DATA_API_CALLS = 0
FREE_PROGRESS_PAYWALL = YES (décidé avant tout fetch)

TRIAL_ACCESS = hasPremiumAccess=true (trial_active=true)
PREMIUM_ACCESS = hasPremiumAccess=true (trial_active=false)

FRONTEND_TESTS = frontend/src/__tests__/access-control-v2.test.jsx (créé, node_modules absent — yarn install requis pour exécution)
FRONTEND_BUILD = node_modules absent — yarn install requis

BLOCKERS = Aucun — node_modules non installés dans le sandbox (conformément à l'interdiction de modifier les lockfiles)

---

## Changements effectués

### SubscriptionContext.jsx
- Remplace `/subscription/info` comme autorité des droits par `/api/user/features`
- Fetch parallèle : `/user/features` (autorité) + `/subscription/info` (affichage/billing)
- `hasPremiumAccess` = `features.has_premium_access` (exposé dans le contexte)
- `isFree` = `!hasPremiumAccess`
- `isTrial` = `features.trial_active`
- `isPremium` = `hasPremiumAccess && !isTrial`
- Fail closed : si `/user/features` indisponible → `hasPremiumAccess=false`, `isFree=true`
- TRIAL et PREMIUM suivent le même chemin fonctionnel Premium (`hasPremiumAccess=true`)
- `/subscription/info` conservé pour `statusLabel`, `statusBadge`, `statusBadgeColor`

### Dashboard.jsx
- Attente de la résolution subscription avant tout fetch (`subLoading` gardé)
- FREE : appelle uniquement `/dashboard/insight` + `/run-index` (inchangé)
- TRIAL/PREMIUM : comportement complet actuel (`/rag/dashboard`, `/training/today`, `/training/v2/week`)
- Aucun calcul modifié, aucun redesign

### Progress.jsx
- Guard `subLoading` et `isFree` avant tout fetch de données
- FREE : `setLoading(false)` immédiat → Paywall rendu avant tout appel
- Run-index history fetch également gardé (`subLoading || isFree`)
- TRIAL/PREMIUM : comportement complet inchangé

### access-control-v2.test.jsx (nouveau)
- Tests avec mock axios et rendu réel des composants
- Scénarios : FREE dashboard, FREE progress, fail closed, TRIAL, PREMIUM
