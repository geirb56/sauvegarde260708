# RunIndex — Deployment Notes

> Current deployment-oriented reference for the repository as verified on `copilot/dev` at `5b694ea669e5812e90fed138e350dd98712e5404`.
> This document describes the current runtime shape and the remaining final runtime gate.

---

## 1. Current runtime shape

RunIndex is currently documented around these runtime components:
- frontend runtime
- backend FastAPI runtime
- MongoDB
- Redis / Upstash-compatible Redis
- out-of-process workers
- GCCLI per-user Garmin sessions
- Paddle billing

This document does **not** claim that the full Beta runtime gate has already been completed.

---

## 2. Application components

### Frontend
- React frontend in `frontend/`
- consumes backend APIs for dashboard, training, onboarding, subscriptions, and coach UX

### Backend
- FastAPI backend in `backend/server.py`
- JWT-authenticated user identity
- Garmin, training, RunIndex, readiness, subscription, and Paddle endpoints

### Data stores
- MongoDB for application state and Garmin-derived data
- Redis-compatible runtime for queueing, locks, rate limiting, feed cache, and monitoring state

### Workers
Canonical worker entrypoint:
- `backend/workers/run_all.py`

It runs four workers:
- `sync_worker`: consumes the Redis queue and executes GCCLI sync
- `event_worker`: fans out `ACTIVITY_CREATED` into derived workouts + feed cache
- `scheduler_worker`: schedules incremental syncs with a Redis leader lock
- `monitor_worker`: evaluates queue health and emits alerts with a Redis leader lock

Railway worker packaging exists in:
- `deploy/railway/Dockerfile.worker`

---

## 3. Garmin runtime model

Current Garmin integration uses GCCLI.

Real current session architecture:
- one GCCLI session per user
- local session home under `GCCLI_HOME/{user_id}`
- encrypted session blob persisted in Mongo collection `garmin_sessions`
- restore-before-sync behavior when workers run in a different container/host
- delete-on-disconnect behavior
- strict per-user isolation

Do **not** document GCCLI as a single global runtime login.
Do **not** claim official Garmin OAuth capability unless the code actually implements it.

---

## 4. Current infrastructure assumptions in repo config

### Local/containerized runtime
Current repository Docker config provides:
- API container
- `sync-worker`
- `scheduler-worker`
- `event-worker`
- MongoDB container
- Redis container
- healthchecks on API, Redis, and Mongo

Important topology difference:
- local Docker Compose does **not** start a frontend service
- local Docker Compose does **not** start `monitor-worker`

### Production-style override
`docker-compose.prod.yml` removes direct external Redis/Mongo exposure and expects runtime secret injection.

### Railway worker runtime
`deploy/railway/Dockerfile.worker` packages the worker service that runs `python -m workers.run_all` and mounts `GCCLI_HOME` under `/data/gccli`.
That Railway runtime starts all four worker loops, including `monitor_worker`.

---

## 5. Secrets and configuration

Current environment/config categories include:
- Mongo: `MONGO_URL`, `DB_NAME`
- JWT/auth: `JWT_SECRET_KEY`, OAuth client IDs, `ADMIN_EMAILS`
- Redis: `REDIS_URL`
- frontend/runtime: `FRONTEND_URL`, `REACT_APP_BACKEND_URL`, `TRUSTED_PROXY_COUNT`
- Paddle: `PADDLE_API_KEY`, `PADDLE_WEBHOOK_SECRET`, `PADDLE_ENVIRONMENT`, `PADDLE_PRICE_ID`, `PADDLE_CLIENT_TOKEN`
- Garmin/GCCLI: `GCCLI_HOME`, optional bootstrap credentials, runtime connector settings
- worker tuning: concurrency, watchdog, scheduler, monitor intervals

Rules:
- inject secrets at runtime
- never commit real secrets
- do not echo secrets in logs or reports

---

## 6. Subscription and billing runtime

Current commercial contract:
- FREE
- TRIAL
- PREMIUM

Current authoritative behavior:
- new users start FREE
- 30-day trial is granted server-side after Garmin identity verification
- one Garmin identity = one trial
- Paddle is the paid subscription authority
- access control resolves from backend JWT identity and fails closed on invalid premium state
- Paddle webhooks are signature-verified server-side

---

## 7. Operational checks

Current runtime-oriented checks supported by the repository include:
- API health endpoint
- queue health monitoring
- worker leader locks
- worker queue watchdog/requeue behavior
- signed Paddle webhook verification
- Garmin session restore path across containers

Useful checks from the repository root:
```bash
docker compose up --build
curl http://localhost:8000/health
```

---

## 8. Final runtime gate before Beta

Canonical gate still to validate end-to-end:
- Garmin real connect / reconnect
- sync
- workers / queues
- RunIndex
- Performance Curve
- VMA history
- Training Paces
- Readiness
- Training Today
- Training Week
- structured prescription
- frozen snapshots
- Daily Adaptation
- prescribed vs performed
- Garmin matching
- unmatched actual
- local dates
- multi-user isolation
- imperial units
- FREE / TRIAL / PREMIUM
- Paddle
- trial Garmin identity
- onboarding
- mobile
- network / storage errors

Then:
- Controlled Beta

---

## 9. Documentation authority

Current canonical deployment/product references:
- `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`
- `DEPLOYMENT.md`

Historical reports remain historical evidence only.
They are not by themselves proof of current readiness.
