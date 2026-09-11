# RUNINDEX PR244 REPORT

- Base branch: `copilot/dev`
- Exact base SHA: `554ae174761b5c3d0abe010383b17230c0b8c8ec`
- Exact final head SHA: `e44556ee40342cca951d75b8f3f18ebbc664aaf6`
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
- Preserved missing pillar values as `—` and added explicit copy when RunIndex is available but pillar detail is not.

## Explicit non-regression confirmation
- No Training V2 prescription logic changes.
- No RunIndex science changes.
- No Readiness formula changes.
- No Performance Curve or Race Prediction algorithm changes.
- No Garmin ingestion / truth-source changes.
- No subscription or admin-guard rule changes.

## Tests / results
- Focused suites: `CI=1 npx craco test --watchAll=false --runTestsByPath src/__tests__/layout-mobile-nav.test.jsx src/__tests__/sessions-page.test.jsx src/__tests__/coach-page.test.jsx src/__tests__/progress-mobile-ux.test.jsx src/__tests__/training-v2-page.test.jsx` ✅ (5 suites, 85 tests passed)
- Full frontend suite: `CI=1 npx craco test --watchAll=false --forceExit` ✅ (24 suites, 340 tests passed)
- Diff check: `git diff --check` ✅

## Build result
- `npm run build` ✅

## Mobile widths audited
- 360 px targeted by responsive layout changes
- 390 px targeted by responsive layout changes
- 430 px targeted by responsive layout changes

## Remaining P2 visual debt
- Progress can still feel dense on long premium payloads, but hierarchy and chart readability are improved without changing data contracts.
