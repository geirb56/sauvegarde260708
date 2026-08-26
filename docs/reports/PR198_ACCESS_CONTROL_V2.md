# PR198 — ACCESS CONTROL V2 — FREE / TRIAL / PREMIUM

## ALIGNEMENT FRONTEND ↔ BACKEND

---

BACKEND_SINGLE_SOURCE_OF_TRUTH = YES
`backend/access_control.py` remains the only authority for subscription tiers and feature permissions. No route handler or frontend component reconstructs access policy independently.

FRONTEND_USES_CANONICAL_ACCESS = YES
`SubscriptionContext.jsx` now calls `/api/user/features` (backed by `UserAccess.to_api_dict()`) as the primary source for all access flags (`isFree`, `hasPremiumAccess`, `hasFeature`). `/api/subscription/info` is retained for display-only fields (label, badge).

SUBSCRIPTION_DUPLICATION_REMOVED = YES
The hardcoded `features` dict previously returned by `/subscription/info` (from `subscription_manager.FEATURES`) is no longer used for access decisions in the frontend. All access flows through `feature_access` from the canonical endpoint.

---

FREE_RUNINDEX = YES — `run_index` is in `FREE_FEATURES`; `/api/run-index` route is `FREE`.

FREE_READINESS = YES — `dashboard_insight`, `basic_stats` are in `FREE_FEATURES`; `/api/dashboard/insight` and `/api/stats` routes are `FREE`.

FREE_VO2MAX = DENIED — `/api/garmin/` prefix is `PREMIUM`; `garmin_sync` is a `PREMIUM_FEATURE`; `can("garmin_sync") = False` for FREE.

FREE_PROGRESS = PAYWALL — `Progress.jsx` now waits for `subLoading=false` before any API call; when `isFree=true`, only `/api/stats` and `/api/run-index` (both FREE) are called; the Paywall component is rendered immediately.

FREE_TRAINING = PAYWALL — `TrainingPlanV2.jsx` already gated behind `if (subLoading || isFree) return` (pre-existing correct behavior, unchanged).

TRIAL_EQUALS_PREMIUM = YES — `has_premium_access` is `True` for both `Tier.TRIAL` and `Tier.PREMIUM`; `can()` returns identical results for all features; verified by `TestTrialEqualsPremium`.

---

FREE_PROGRESS_PREMIUM_API_CALLS = 0
Verified: `Progress.jsx` guards the entire premium fetch block behind `if (isFree) { /* free-only calls */ return; }`. Endpoints `/training/race-predictions`, `/training/v2/cycle`, `/garmin/vo2max-history`, `/garmin/daily-metrics` are never called for FREE users.

FREE_TRAINING_PREMIUM_API_CALLS = 0
Pre-existing guard in `TrainingPlanV2.jsx`: `if (subLoading || isFree) return;` before any premium API call. Unchanged.

FAIL_CLOSED = YES
- Backend: DB error → `FREE` returned (no premium access). Unknown feature → `False`. Unknown route → `PREMIUM`. Expired trial/premium → `FREE`.
- Frontend: `/user/features` fetch failure → `FAIL_CLOSED_STATE` applied (`plan: "free"`, `has_premium_access: false`). `Promise.allSettled` used so display failure does not affect access.

---

FILES_CHANGED = 3
- `frontend/src/context/SubscriptionContext.jsx` — evolved to canonical `/user/features` contract; exposes `hasPremiumAccess`.
- `frontend/src/pages/Progress.jsx` — gated premium API calls behind subscription status check; added `[isFree, subLoading]` deps.
- `backend/tests/test_pr198_access_control_v2.py` — 56 new unit tests (no DB / no server).

TEST_RESULTS = 56/56 PASSED (unit, no live server required)

BLOCKERS = NONE

PR198_READY_FOR_REVIEW = YES
