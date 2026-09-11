# RunIndex

## 1. Product

RunIndex is a deterministic running product built around three separate concepts:
- **RunIndex**: medium/long-term performance and potential view
- **Readiness**: freshness / capacity state of the day
- **Training**: prescription authority

The LLM Coach is a separate explanation/conversation layer.
It is not the scientific authority.

## 2. Core concepts

### RunIndex

Current RunIndex is built from four pillars:
- Speed
- Endurance
- Consistency
- Efficiency

The global score is expressed on `/1000`.
Missing pillars are excluded and remaining weights are renormalized.
If sufficiency is not met, the score stays unavailable.

### Readiness

Readiness describes freshness state, not workout prescription.
Current user-facing states are:
- High freshness
- Moderate freshness
- Low freshness
- Unavailable

### Training

Training is the prescription authority.
Garmin activity is the performed-observation authority.
A high-readiness day can still legitimately be a rest day.

## 3. Architecture

Current core flow:

Garmin → `DomainActivity` → Training V2 engines → weekly plan / today adaptation

Current Training V2 pipeline:
- TrainingHistory
- TrainingLoad
- RunnerProfile
- TrainingState
- PlanGoal
- Periodization
- WeeklyTarget
- RecentTrainingResponse
- WeeklyReconciliation
- WorkoutGenerator
- DailyAdaptation

Additional current layers:
- prescribed vs performed
- Garmin matching
- unmatched actuals
- served prescription
- structured workout
- immutable prescription snapshot
- Today / Week convergence

## 4. Garmin

RunIndex currently uses GCCLI.

Current Garmin session model:
- one GCCLI session per user
- per-user home under `GCCLI_HOME/{user_id}`
- Mongo persistence in `garmin_sessions`
- encrypted at rest
- restored before sync when needed
- deleted on disconnect

Do not describe the current implementation as a single global Garmin login.
Do not describe official Garmin OAuth unless that flow exists in code.

## 5. Backend / workers

Backend:
- FastAPI
- MongoDB
- Redis-compatible queue/cache layer
- Paddle billing webhooks

Worker topology differs by runtime:
- local `docker-compose.yml` starts `sync-worker`, `scheduler-worker`, and `event-worker`
- Railway worker runtime uses `backend/workers/run_all.py` and starts `sync_worker`, `event_worker`, `scheduler_worker`, and `monitor_worker`

## 6. Frontend

Frontend lives in `frontend/` and consumes the backend APIs for dashboard, training, subscriptions, onboarding, and coach flows.

Shared Training/Dashboard weekly progress authority:
- `frontend/src/lib/trainingWeekProgress.js`

## 7. Subscription

Current commercial states:
- FREE
- TRIAL
- PREMIUM

Current rules:
- new user starts FREE
- 30-day Premium trial is activated server-side after Garmin identity verification
- one Garmin identity = one trial
- Paddle is the paid subscription authority
- invalid premium state fails closed

## 8. Local setup

### Backend / infra

From the repository root:

```bash
docker compose up --build
```

This starts:
- API
- Mongo
- Redis
- sync worker
- scheduler worker
- event worker

It does **not** start the frontend dev server or `monitor_worker`.

### Backend Python setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Frontend

Run the frontend separately in another terminal:

```bash
cd frontend
npm install --legacy-peer-deps
npm start
```

## 9. Tests

Backend:
```bash
cd backend
python -m pytest
```

Frontend:
```bash
cd frontend
npx craco test --watchAll=false --forceExit
npm run build
```

## 10. Canonical documentation

Current canonical references:
- `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`
- `DEPLOYMENT.md`

Historical PR/audit reports are evidence snapshots, not automatically updated current truth.

## 11. Security / secrets

Rules:
- never commit secrets
- inject runtime secrets via environment / secret manager
- never fabricate missing metrics (`None != 0`)
- no fake sleep / HRV / TSS / pace values
- deterministic science remains deterministic
