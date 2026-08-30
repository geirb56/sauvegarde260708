# RUNINDEX — PR #222 REPORT

## Base SHA réel
- Base branch: `copilot/dev`
- Base SHA: `75a2d2b14f7b6dd4d9ce52d88801cad8df6b2e1d`
- Verification: `origin/copilot/dev` currently points to merge commit `Merge pull request #221 from geirb56/copilot/221-unique-server-authority`.

## Head SHA
- Head SHA: `PENDING_FINAL_COMMIT`

## Anciens appels `/subscription/start-trial` trouvés
- `frontend/src/pages/Subscription.jsx` (legacy Trial CTA calling `POST /api/subscription/start-trial` on the base branch)
- Remaining source calls under `frontend/src/`: none
- Guard assertions kept in tests only: `frontend/src/__tests__/subscription-trial-handoff.test.jsx`

## Fichiers frontend modifiés
- `frontend/src/pages/Subscription.jsx`
- `frontend/src/context/SubscriptionContext.jsx`
- `frontend/src/pages/Onboarding.jsx`
- `frontend/src/pages/Settings.jsx`
- `frontend/src/lib/i18n.js`
- `frontend/src/__tests__/subscription-trial-handoff.test.jsx`
- `frontend/src/__tests__/onboarding-garmin-autofill.test.jsx`
- `frontend/src/__tests__/onboarding-runindex-activation.test.jsx`
- `frontend/src/__tests__/settings-page.test.jsx`

## Nouveau flow Trial
1. FREE clicks the Trial CTA.
2. If Garmin is not connected, the frontend opens the Garmin connect form.
3. `POST /api/garmin/connect` handles authentication.
4. After Garmin success, the frontend refreshes canonical subscription state from the backend.
5. UI immediately reflects backend truth:
   - `trial` => Trial UI/badges
   - `premium` => Premium UI
   - `free` => clear message that the Garmin account is connected but Trial is unavailable, with Premium upsell
6. The frontend never calls `POST /api/subscription/start-trial` anymore.

## Mécanisme de refresh subscription
- `frontend/src/context/SubscriptionContext.jsx` now exposes an awaitable `refreshSubscription()`.
- `frontend/src/pages/Subscription.jsx` refreshes both `SubscriptionContext` and `/subscription/info?language=...` after Garmin success or stale-status retry.
- `frontend/src/pages/Onboarding.jsx` and `frontend/src/pages/Settings.jsx` also refresh `SubscriptionContext` after a successful Garmin connect.
- Backend remains the sole source of truth for FREE / TRIAL / PREMIUM.

## Tests exécutés et résultats
Executed from `frontend/` after `npm install --legacy-peer-deps`:
- `npx craco test --watchAll=false --runInBand --runTestsByPath src/__tests__/subscription-trial-handoff.test.jsx src/__tests__/onboarding-garmin-autofill.test.jsx src/__tests__/onboarding-runindex-activation.test.jsx src/__tests__/settings-page.test.jsx`
  - Result: `4 passed, 25 passed`
- `npm run build`
  - Result: `Compiled successfully`

## Runtime testé ou non
- Runtime tested in this task environment: not tested.
- Required post-merge runtime checklist from the task remains pending for the real runtime environment.
