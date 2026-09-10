# RUNINDEX PR241 REPORT

- Base SHA: `730ef620ae78182747274b2ce9dc3a1bf9fd5b77`
- Branch: `copilot/copilot241-dashboard-polish-final-v2`
- Checkpoint 1 commit: `e756de33a3c05b34db57fc63fb7417831f191035`
- Checkpoint 2 commit: `f260da73500e2da04241e604a8c5964bdcdb8a3e`

## Files changed

- `frontend/public/runindex-symbol.png`
- `frontend/public/icons/icon-72x72.png`
- `frontend/public/icons/icon-96x96.png`
- `frontend/public/icons/icon-128x128.png`
- `frontend/public/icons/icon-144x144.png`
- `frontend/public/icons/icon-152x152.png`
- `frontend/public/icons/icon-192x192.png`
- `frontend/public/icons/icon-384x384.png`
- `frontend/public/icons/icon-512x512.png`
- `frontend/src/components/Layout.jsx`
- `frontend/src/styles/theme-modern.css`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/lib/i18n.js`
- `frontend/src/__tests__/auth-ui.test.jsx`
- `frontend/src/__tests__/dashboard-training-v2.test.jsx`
- `frontend/src/__tests__/dashboard-polish-pr241.test.jsx`

## Shared header component changed

Yes. The shared authenticated mobile header was updated once in `frontend/src/components/Layout.jsx`, which is the protected layout used by authenticated pages.

## Asset used

- Authenticated mobile header asset: `frontend/public/runindex-symbol.png`
- Source: derived from the existing official `frontend/public/icons/icon-512x512.png`
- Result: transparent R-only mark with no text, no black square, and no artificial border

## App icon / favicon status

- Updated in place to R-only transparent variants:
  - `frontend/public/icons/icon-72x72.png`
  - `frontend/public/icons/icon-96x96.png`
  - `frontend/public/icons/icon-128x128.png`
  - `frontend/public/icons/icon-144x144.png`
  - `frontend/public/icons/icon-152x152.png`
  - `frontend/public/icons/icon-192x192.png`
  - `frontend/public/icons/icon-384x384.png`
  - `frontend/public/icons/icon-512x512.png`
- Existing manifest and favicon/app-icon references remain valid and now resolve to the R-only asset family.

## Readiness partial-data behavior

- Readiness formula unchanged.
- Dashboard now shows a compact partial-data badge when the displayed readiness evidence is incomplete.
- Missing displayed values remain missing:
  - HRV: `—`
  - Sleep: `—`
  - Resting HR: `—` when missing
  - Load: `—` when missing
- No frontend science rule was introduced.

## `0 min` behavior

- Real rest displays `Jour de repos`.
- Endurance with missing duration keeps the workout type visible without inventing `0 min`.
- Positive duration still renders normally.

## Tests

Targeted suites run:

- `src/__tests__/dashboard-run-readiness-v2.test.jsx`
- `src/__tests__/dashboard-training-v2.test.jsx`
- `src/__tests__/dashboard-premium-preview.test.jsx`
- `src/__tests__/dashboard-polish-pr241.test.jsx`
- `src/__tests__/auth-ui.test.jsx`

Results:

- Targeted run: `5/5` suites passed, `107/107` tests passed
- Frontend full suite: `19/19` suites passed, `325/325` tests passed

Added / updated coverage for:

- rest day rendering with no artificial `0 min`
- endurance with missing duration
- positive duration rendering
- partial readiness indicator visible only when appropriate
- full readiness without false partial badge
- HRV / Sleep null rendering as `—`
- RunIndex missing pillar never coerced to `0`
- FREE gating unchanged
- weekly partial data not shown as `0%`
- authenticated shared header using the R-only asset
- old full-logo small-format asset no longer used in authenticated header

## Build

- `npm run build` from `frontend/`: PASS

## Visual audit

Audit artifacts:

- JSON summary: `tmp/pr241-visual/audit.json`
- Screenshots:
  - `tmp/pr241-visual/screens/dashboard-full-readiness-390.png`
  - `tmp/pr241-visual/screens/dashboard-partial-readiness-390.png`
  - `tmp/pr241-visual/screens/dashboard-rest-390.png`
  - `tmp/pr241-visual/screens/dashboard-workout-390.png`
  - `tmp/pr241-visual/screens/header-dashboard-390.png`
  - `tmp/pr241-visual/screens/header-sessions-390.png`

Validated widths:

- `360px`
- `390px`
- `412px`
- `430px`

Observed results from `tmp/pr241-visual/audit.json`:

- no horizontal overflow at all validated widths
- authenticated header logo source is `/runindex-symbol.png`
- transparent logo corners verified in-browser
- header remained balanced on Dashboard and Sessions
- partial-data badge appears in the partial-readiness scenario
- rest scenario shows `Jour de repos`
- no audited scenario displayed artificial `0 min`

## Backend / science scope

- No backend files changed
- No Readiness formula change
- No RunIndex engine change
- No Performance Curve / Training Paces / WorkoutGenerator / DailyAdaptation / WeeklyReconciliation / Garmin matching change

## Remaining debt intentionally left for #242 / #243

- bottom navigation crowding / truncation (`#242`)
- Training page duplicate and cramped items (`#242`)
- Progress page overlap / badge / prediction presentation polish (`#242`)
- Coach hierarchy / empty-state polish (`#242`)
- Sessions FC/bpm polish (`#242`)
- Workout detail copy / hierarchy polish (`#242`)
- Login / onboarding polish (`#243`)
