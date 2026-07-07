# CardioCoach — Project Setup Record

## Problem Statement
Pull https://github.com/geirb56/sauvegarde260629 and set it up so it runs. Replace /app contents.

## App Overview
CardioCoach — running/cardio training coach. Garmin (gccli) integration, AI coach (LLM), RunIndex/readiness engines, training plans, Stripe subscriptions, Terra integration.

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
