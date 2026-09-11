# RUNINDEX PR242 REPORT

- Base branch: `copilot/dev`
- Base SHA: `cf38498cfdc26053da9b6a1e8b5eadf4e653d3c6`
- Final head SHA (at PR open): `0a99bd16bfa8865e1eac7108c686cd6a51129e74`

## Exact bug

Dashboard partial-readiness detection still checked `metrics.sufficiency_level === "partial"`, while canonical backend `/run-index` values are uppercase enums (`SUFFICIENT`, `DEGRADED`, `INSUFFICIENT`).  
This could hide `"Données partielles"` for real `DEGRADED` payloads when visible scalar tiles happened to be populated.

## Canonical contract

- `SUFFICIENT`
- `DEGRADED`
- `INSUFFICIENT`

## Files changed

- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/__tests__/dashboard-polish-pr241.test.jsx`
- `RUNINDEX_PR242_REPORT.md`

## Tests

- `CI=true npx craco test --watchAll=false --runTestsByPath src/__tests__/dashboard-polish-pr241.test.jsx src/__tests__/dashboard-run-readiness-v2.test.jsx src/__tests__/dashboard-training-v2.test.jsx` ✅ (`3/3` suites, `81/81` tests)
- `CI=true npx craco test --watchAll=false --forceExit` ✅ (`19/19` suites, `327/327` tests)

## Build

- `npm run build` (from `frontend/`) ✅
- `git diff --check` ✅

## Scope confirmation

- Frontend only change.
- No backend/science formula or semantics changes.
- No navigation/Coach/Progress/Training polish changes.
