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
| Frontend production build | Pending |
| SPA fallback and static-file behavior | Pending |
| React direct-route/refresh checks | Pending |
| Railway API configuration unchanged | Pending |

## Risks and blockers

- No live Netlify deployment or manual Netlify/Railway setting changes were performed. The deployed site's `REACT_APP_BACKEND_URL` must remain configured to point to Railway; this PR does not change it.
- No Netlify Functions are present in the audited repository tree. The frontend's configured API calls target the separate backend URL rather than a same-origin Netlify `/api/*` proxy.

## PR provenance

- Base: `copilot/dev` at `7dd262de4aa4d3355cf0659a5a3d4ad092e42d5f`
- Head: pending commit
