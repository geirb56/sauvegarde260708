# Netlify SPA redirects — audit and validation

## Scope

Single-purpose change for Netlify's React single-page application routing. No backend, Garmin, Redis, physiology, or deployment settings were changed.

## Initial audit

- `frontend/src/App.js` uses `BrowserRouter` and declares React routes including `/login`, `/sessions/:id`, `/workout/:id`, `/progress`, and `/training`.
- Before this change, the repository had no `netlify.toml` or `_redirects` file, so it had no versioned Netlify SPA fallback, build command, or publish directory.
- The frontend build output is `frontend/build` (`frontend/package.json`: `npm run build` invokes `craco build`).
- The frontend has no Netlify Functions directory. Its API base is `${REACT_APP_BACKEND_URL}/api` (`frontend/src/config.js`); the frontend service worker also excludes `/api/` requests from its fetch handler. No frontend proxy or Netlify API rewrite existed.

## Correction

Added `/netlify.toml` with the frontend build base, build command, and `build` publish directory, plus one non-forced `200` rewrite to `/index.html`. Netlify can continue serving existing static files because the rule does not force the rewrite. Railway API configuration and frontend API code remain unchanged; no backend secret was added to browser-exposed variables.

## Validation

| Check | Result |
| --- | --- |
| `npm ci --legacy-peer-deps` | Completed; dependencies installed. npm reported 94 dependency audit findings (5 low, 13 moderate, 73 high, 3 critical); no dependency or lockfile was changed. |
| `npm run build` from `frontend/` | Passed; optimized production build created in `frontend/build`. Existing warning: `caniuse-lite` Browserslist data is seven months old. |
| Netlify TOML/build output check | Passed; TOML parsed, build base/command/publish values and non-forced `200` fallback verified, and `index.html`, `manifest.json`, `sw.js`, `offline.html`, and a representative icon were present in the build. |
| React routing regression test | Passed: `npx craco test --watchAll=false --forceExit src/__tests__/app-legacy-redirects.test.jsx` (1 suite, 4 tests). |
| Direct route / refresh on Netlify | Not exercised against a live Netlify site; deployment is intentionally out of scope. The versioned rewrite serves the SPA entry point for missing paths, while the React routing regression test passed locally. |
| Railway API configuration unchanged | Passed by scope review: only this report and `netlify.toml` differ from the base; frontend API code and backend files are unchanged. |

## Risks and blockers

- No live Netlify deployment or manual Netlify/Railway setting changes were performed. The deployed site's `REACT_APP_BACKEND_URL` must remain configured to point to Railway; this PR does not change it.
- No Netlify Functions are present in the audited repository tree. The frontend's configured API calls target the separate backend URL rather than a same-origin Netlify `/api/*` proxy.
- npm reported dependency audit findings during the install; dependency remediation is unrelated to this redirections-only change.

## PR provenance

- Base: `copilot/dev` at `7dd262de4aa4d3355cf0659a5a3d4ad092e42d5f`
- Code tested at head: `a7b7e5c96e3793a50768092130f273451fc18a02`
