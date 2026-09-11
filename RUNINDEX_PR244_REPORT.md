# RUNINDEX PR244 REPORT

- Base branch: `copilot/dev`
- Exact base SHA: `554ae174761b5c3d0abe010383b17230c0b8c8ec`
- Implementation head SHA: `8f5ab2c23ed2d1bfcca2f337b2e843ee82610070`
- Final PR head SHA: reported at handoff to avoid an impossible self-referential SHA inside this report commit
- Navigation decision: mobile bottom navigation reduced to 5 primary destinations (`Home/Accueil`, `Training`, `Sessions`, `Coach`, `Progress`); Settings moved to the authenticated header and Admin remains admin-only in the header, not in the primary mobile bottom nav.

## Files changed
- `frontend/src/components/Layout.jsx`
- `frontend/src/styles/theme-modern.css`
- `frontend/src/pages/TrainingPlanV2.jsx`
- `frontend/src/pages/Sessions.jsx`
- `frontend/src/pages/WorkoutDetail.jsx`
- `frontend/src/pages/Coach.jsx`
- `frontend/src/pages/Progress.jsx`
- `frontend/src/lib/i18n.js`
- `frontend/src/__tests__/layout-mobile-nav.test.jsx`
- `frontend/src/__tests__/sessions-page.test.jsx`
- `frontend/src/__tests__/coach-page.test.jsx`
- `frontend/src/__tests__/progress-mobile-ux.test.jsx`
- `frontend/src/__tests__/training-v2-page.test.jsx`
- `RUNINDEX_PR244_REPORT.md`

## UX issues fixed by page

### Navigation / shared shell
- Removed Settings from the primary mobile bottom nav so labels fit without truncation.
- Kept only the primary user destinations in the bottom nav and kept Admin out of it.
- Moved Settings to the authenticated header and kept Admin available only for admins in the header.
- Preserved the authenticated R-only header branding from PR241.

### Training
- Reduced week-row crowding on mobile.
- Removed duplicate rest-day wording in week rows.
- Suppressed zero-distance sentinel display so `0.00 km` is not shown when no prescribed distance exists.
- Kept race rendering as `Course` / `Race` and kept races excluded from planned progress.
- Kept unmatched Garmin activities separate from prescribed-plan progress.

### Sessions
- Tightened card presentation and rendered heart rate with explicit `bpm` units.

### Workout Detail
- Improved the back affordance and limited return routes to in-app destinations.

### Coach
- Replaced the prototype-like empty state with explanation/advice framing and clear links back to Training and Sessions.
- Kept Training Today as the sole prescription authority.

### Progress
- Reduced trend-badge aggression and improved mobile chart tick density.
- Preserved missing pillar values as `—` and added neutral truthful copy: unavailable pillars stay excluded from the RunIndex calculation instead of being treated as zero.

## Explicit non-regression confirmation
- No Training V2 prescription logic changes.
- No RunIndex science changes.
- No Readiness formula changes.
- No Performance Curve or Race Prediction algorithm changes.
- No Garmin ingestion / truth-source changes.
- No subscription or admin-guard rule changes.

## Tests / results
- Focused suites: `CI=1 npx craco test --watchAll=false --runTestsByPath src/__tests__/layout-mobile-nav.test.jsx src/__tests__/sessions-page.test.jsx src/__tests__/coach-page.test.jsx src/__tests__/progress-mobile-ux.test.jsx src/__tests__/training-v2-page.test.jsx` ✅ (5 suites, 87 tests passed)
- Full frontend suite: `CI=1 npx craco test --watchAll=false --forceExit` ✅ (24 suites, 342 tests passed)
- Diff check: `git diff --check` ✅

## Build result
- `npm run build` ✅

## Mobile widths audited
- 360 px audited in rendered authenticated UI via headless Chromium + local mock API/server: Dashboard, Training, Sessions, Coach, Progress ✅
- 390 px audited in rendered authenticated UI via headless Chromium + local mock API/server: Dashboard, Training, Sessions, Coach, Progress ✅
- 430 px audited in rendered authenticated UI via headless Chromium + local mock API/server: Dashboard, Training, Sessions, Coach, Progress ✅
- FR + EN mobile nav labels checked at 360 px: `Accueil`, `Entraînement`, `Séances`, `Coach`, `Progression` and `Home`, `Training`, `Sessions`, `Coach`, `Progress` ✅
- Verified in the rendered UI: no horizontal overflow, no horizontal nav scrolling, no truncated primary nav labels, no Today badge collision, no duplicate rest text, no `0.00 km` sentinel, R-only header branding preserved, Settings accessible, Admin absent from primary bottom nav, Coach empty-state hierarchy usable, Progress x-axis labels readable.

## Remaining P2 visual debt
- Progress can still feel dense on long premium payloads, but hierarchy and chart readability are improved without changing data contracts.
