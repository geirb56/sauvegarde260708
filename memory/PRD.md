# RunIndex — Project Setup Record

## Problem Statement
Pull https://github.com/geirb56/sauvegarde260629 and set it up so it runs. Replace /app contents.

## App Overview
RunIndex — running/cardio training coach. Garmin (gccli) integration, AI coach (LLM), RunIndex/readiness engines, training plans, Stripe subscriptions, Terra integration.

## Tech Stack
- Backend: FastAPI + Motor (MongoDB), emergentintegrations (Emergent LLM key), Stripe, Redis (jobs/queue/SSE/workers)
- Frontend: React 19 + CRACO + Tailwind + Radix UI + recharts
- Services (supervisor): backend:8001, frontend:3000, mongodb, redis:6379 (added)

## Setup Done (2026-07-07)
- Cloned repo into /app (preserved platform .git/.emergent, kept protected .env vars)
- Installed backend requirements + frontend yarn deps
- backend/.env: added EMERGENT_LLM_KEY, STRIPE_API_KEY=sk_test_emergent, FRONTEND_URL, REDIS_URL
- Added redis supervisor service using vendored /app/bin/redis-server (LD_LIBRARY_PATH=/app/lib)
- Fixed bug in frontend/plugins/visual-edits/babel-metadata-plugin.js (null parentPath.parentPath crash) that blocked webpack build (Coach.jsx)
- Verified: dashboard + Coach pages render, /api/stats /api/dashboard/insight return data, gccli auto-installed at startup

## Notes
- gccli Garmin login only triggers if GARMIN_PROVIDER=gccli (not set) — no Garmin creds required to boot
- Celery/worker processes (sync/monitor/scheduler) are separate; not started by API

## Backlog / Next
- Configure Garmin credentials (GARMIN_USERNAME/PASSWORD/GARMIN_PROVIDER) for real sync if desired
- Start worker processes if background sync/SSE features are needed

## Garmin Connected (2026-07-07)
- backend/.env: GARMIN_PROVIDER=gccli, GARMIN_USERNAME, GARMIN_PASSWORD set (account: mallegolbrieg@gmail.com)
- gccli one-time headless login succeeded; OAuth token persisted at /app/backend/.gccli_home (auto-refreshes)
- Added 4 worker supervisor services: garmin-sync-worker, garmin-event-worker, garmin-scheduler-worker, garmin-monitor-worker
- Verified end-to-end: 30 activities + 30 derived workouts + 7 daily metrics synced; RunIndex 390/1000, Run Readiness 77, RHR 47, Sleep 7.7h
- Scheduler auto-enqueues incremental syncs (~60s scan); event worker builds workouts layer + SSE feed

## Pull sauvegarde260708 — newer version (2026-07-08)
- Pulled commit 9fe9e8c (Merge PR #2). ~60 code files updated vs previous; deps unchanged; babel fix already included upstream.
- rsynced into /app preserving .git/.emergent/.env/.gccli_home/bin. Garmin creds + workers intact.
- API root now "RunIndex API" (rebrand); queue renamed runindex:garmin:queue.
- All services healthy; gccli session reused; Garmin still connected (30 activities). Dashboard renders (RunIndex 390, Readiness 77).

## Branding RunIndex (2026-07-08)
- New logo integrated: header (Layout.jsx) now uses /runindex-logo.png (background keyed out from original navy JPG -> transparent PNG via PIL)
- Full logo added to Onboarding welcome screen + new BrandSplash loading screen (LoadingSpinner.jsx) used on Dashboard initial load (pulse animation)
- Regenerated favicon/PWA icons (72-512px) with the green "R" mark on navy
- Created light-background logo variant /runindex-logo-light.png (dark navy "Run" text) for light surfaces / print / emails

## Pull sauvegarde260708 — Sessions tab (2026-07-09)
- Pulled commit 9909760 (Merge PR #3 "sessions tab"). New: pages/Sessions.jsx, pages/SessionDetail.jsx; modified App.js (routes /sessions, /sessions/:id), Layout.jsx (nav item), i18n.js (sessions translations en/fr/es).
- BUG in pulled code: `sessions` i18n block was nested under `workout` -> pages call t("sessions.*") -> raw keys shown. FIXED in lib/i18n.js by promoting workout.sessions to a top-level `sessions` alias per language (post-object normalization loop).
- Verified: Sessions list (30 Garmin activities, filters/sort/search translated) + SessionDetail (metrics + AI analysis sections) render correctly. Branding (logo) preserved.

## Pull sauvegarde260708 — UI harmonization (2026-07-09 PR#4)
- Pulled commit 8f2bcca. Modified: index.css, theme-modern.css, tailwind.config.js, Dashboard/Progress/SessionDetail/Settings/TrainingPlan/WorkoutDetail.jsx.
- Confirmed all prior agent fixes are now in the repo (logo in Layout.jsx, header-logo-img/brand-splash-logo CSS, BrandSplash in Dashboard, i18n sessions alias) -> user's Save-to-GitHub worked.
- Deps unchanged; no compile errors; dashboard + branding + Garmin data all verified working.
