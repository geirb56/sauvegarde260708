# RunIndex — Master Roadmap & Decisions

Repository:
geirb56/sauvegarde260708

Current integration branch:
copilot/dev

Last verified HEAD:
5b694ea669e5812e90fed138e350dd98712e5404

Date:
2026-09-09

---

## 1. Purpose

This is the current canonical document for RunIndex.

Current truth is established from:
1. current code at the verified HEAD;
2. real Git / GitHub merge history;
3. merged tests and reports used as supporting evidence;
4. product decisions already documented and still reflected in code.

Historical PR and audit reports are evidence snapshots from a point in time.
They are not automatically updated after later merges.
Current truth is:
1. current code;
2. this canonical master document;
3. `DEPLOYMENT.md`;
4. historical reports as supporting evidence.

---

## 2. Operating branch policy

- `copilot/dev` is the active integration branch.
- New audits and documentation/code PRs start from `copilot/dev` unless explicitly instructed otherwise.
- `main` is not the operational branch for current day-to-day work.
- One PR = one objective.
- Never mark a PR as merged unless Git / GitHub confirms it.

Recently verified merged PRs on `copilot/dev`:
- #233 — Training UX V3 — merged
- #234 — Structured Workout Prescription V1 — merged
- #235 — Prescription Snapshot V2 — merged
- #236 — Structured Sessions UI — merged
- #237 — Copilot / CI reliability — merged
- #239 — Dashboard ↔ Training Truth Convergence — merged

Important merge facts:
- PR #238 does not exist on GitHub (`404`).
- PR #239 head: `e0c70412afb24d76973564c7ec44700d4f5cf611`
- PR #239 merge commit: `5b694ea669e5812e90fed138e350dd98712e5404`
- PR #239 merged: `2026-09-09`

---

## 3. Core product concepts

### 3.1 RunIndex

RunIndex is the medium/long-term view of running potential and performance.
It is not defined as “load + recovery + HRV”.

Current engine contract (`backend/engine/run_index_engine.py`):
- pillars: Speed, Endurance, Consistency, Efficiency;
- pillar scores are 0–100 or `None`;
- global RunIndex is a weighted average of non-`None` pillars, renormalized over remaining weights, then scaled to `/1000`;
- missing pillars are excluded, never replaced by `0`;
- sufficiency gate requires at least 3 valid running activities and at least 2 calculable pillars;
- if sufficiency is not met, `run_index = null` and status is `insufficient`.

Current pillar weights:
- Speed: 40%
- Endurance: 25%
- Consistency: 20%
- Efficiency: 15%

### 3.2 Readiness

Readiness is the freshness / capacity state of the day.
It is not a prescription authority.

Canonical readiness interpretation (`backend/training_v2/readiness_decision.py`):
- `FAVORABLE` / high freshness
- `CAUTION` / moderate freshness
- `LOW` or `VERY_LOW` / low freshness
- `UNAVAILABLE`

Product wording after PR #239:
- High freshness
- Moderate freshness
- Low freshness
- Unavailable

Readiness may be high on a rest day.
Example: high freshness + planned rest day is valid and coherent.

### 3.3 Training

Training is the prescription authority.

- Training decides the prescribed session.
- Garmin activity is the performed-observation authority.
- Readiness can adapt today's session conservatively, but it does not replace the plan as authority.

---

## 4. RunIndex canonical details

### 4.1 Speed

Current speed pillar (`backend/engine/run_index_engine.py`):
- race-performance component: 80%
- sustained-speed component: 20%
- sustained speed is best pace over a 20–75 minute effort
- it is explicitly not described as lactate-threshold measurement

### 4.2 Endurance

Current endurance pillar:
- longest run in last 30 days: 45%
- weekly km average: 35%
- long-run frequency in last 30 days: 20%

### 4.3 Consistency

Current consistency pillar:
- frequency: 40%
- weekly volume stability: 40%
- habit / gap regularity: 20%

### 4.4 Efficiency

Current efficiency pillar:
- score is based on median speed / heart-rate ratio across HR-tagged runs
- inter-run efficiency variability is observability only, not score aggregation
- if HR data is absent, efficiency stays `None` rather than becoming `0`

---

## 5. Training load contract

Current Training Load V2 (`backend/training_v2/training_load.py`):
- acute window = 7 days
- chronic window = 28 days
- `chronic_weekly_load = load_28d / 4`
- `ACWR = acute_load_7d / chronic_weekly_load`
- `acwr = None` when chronic weekly load is zero

Important rules:
- load is duration-based only
- no distance→duration fallback
- no TRIMP / TSS / provider-native load relabelling
- `None != 0`
- never describe this proxy as TSS when it is not TSS

---

## 6. Performance Curve V2

Canonical file: `backend/training_v2/performance_model.py`

Current implemented facts:
- formula: `T(D) = A × D^k`
- `RIEGEL_K = 1.06`
- race predictions come from qualified observed performances only
- slope-evidence uses HIGH-confidence observations only
- k-identifiability is checked explicitly
- diagnostics expose `slope_evidence_count`, distance min/max, confidence and uncertainty signals
- contributor-pool max age is currently `MAX_RIEGEL_SOURCE_AGE_DAYS = 730`
- `PERSONAL_SPEED_WINDOW_DAYS = 90` exists, but it controls only the strictly-prior personal-speed benchmark used while qualifying each performance
- `SLOPE_EVIDENCE_WINDOW_DAYS = 90` controls personal-k learning evidence only

Explicit window distinction:
- Qualification speed benchmark: 90 days
- Performance-curve contributors: up to 730 days
- Slope evidence: HIGH-confidence subset within that contributor pool and within `SLOPE_EVIDENCE_WINDOW_DAYS`

Product decision:
- personal-k / slope-evidence learning window is 90 days

Current code:
- the performance-curve contributor pool can include qualified observations up to 730 days for level calibration (`A`)
- personal-k is learned only from slope-evidence (HIGH + `days_ago <= 90`)
- medium/low and HIGH older than 90 days cannot modify personal-k

Status:
- personal-k contract aligned (HIGH-only, 90-day slope-evidence)
- level-recency contract for `A` remains only partially aligned at runtime

Interpretation:
- Product intent: `A` should represent the runner’s current/recent level
- Product intent: `k` should represent personal curve shape / relative endurance
- Runtime after PR249:
  - `k` is learned only from 90-day HIGH slope-evidence
  - MEDIUM/LOW and HIGH older than 90 days cannot modify personal-k
  - after final `k` selection, `A` is recalibrated at fixed slope
  - current qualified pool for `A` calibration can still include observations up to `MAX_RIEGEL_SOURCE_AGE_DAYS = 730`
  - therefore, recency alignment for `A` remains a dedicated follow-up corrective PR/work item

Fallback rule:
- when evidence cannot identify slope robustly, fallback to `k = 1.06`
- this is a prior fallback, not an arbitrary uplift

---

## 7. Current prediction vs potential

Current Race Prediction:
- what recent evidence reasonably supports today

Potential:
- the level the runner profile suggests could be reached with coherent training

Confidence:
- how solid the evidence is

Absolute rule:
- Potential is not Current Prediction minus or plus an arbitrary percentage
- there is no arbitrary uplift layer

Current status:
- a dedicated Potential Model remains future work until its scientific contract is actually implemented

---

## 8. Training Paces V2

Canonical files:
- `backend/training_v2/training_paces.py`
- `backend/training_v2/training_paces_authority.py`

Current authority:
- paces are derived from really observed qualified performances
- VDOT uses Daniels/Gilbert
- supported zones: `E / M / T / I / R`
- confidence tiers: `HIGH / MEDIUM / LOW / INSUFFICIENT`

Hard exclusions:
- no Garmin VO2max as pace authority
- no VMA shortcut
- no Race Prediction shortcut

Current loader contract:
- `TRAINING_PACES_ACTIVITY_LIMIT = 500`
- the canonical shared loader does not impose a 90-day cutoff
- the Training Engine 90-day activity window and Training Paces evidence history are different concepts
- age/confidence policy belongs to `training_paces.py`, not to the shared loader

---

## 9. Training V2 pipeline

Current canonical orchestration:

Garmin
→ DomainActivity
→ TrainingHistory
→ TrainingLoad
→ RunnerProfile
→ TrainingState
→ PlanGoal
→ Periodization
→ WeeklyTarget
→ RecentTrainingResponse
→ WeeklyReconciliation
→ WorkoutGenerator
→ DailyAdaptation

Current runtime layers now present in real code:
- prescribed vs performed
- Garmin matching
- unmatched actual
- served prescription
- structured workout
- immutable prescription snapshot
- Today / Week convergence
- local reference date

Authority split:
- Weekly plan remains the single training prescription base
- DailyAdaptation changes Today only and does not rebuild the weekly plan
- performed activity matching remains deterministic and Garmin-only

---

## 10. Structured workout and snapshot state

Merged sequence:
- #234 — Structured Workout Prescription
- #235 — Prescription Snapshot V2
- #236 — Structured Sessions UI

Current concepts in code:
- deterministic structure
- `workout_type`
- `quality_kind`
- warmup / work / recovery / cooldown
- frozen numeric paces inside the served snapshot
- `prescription_id`
- adaptation metadata
- `session_modified_from_planned`
- `historical_frozen`
- `historical_unavailable`

Important legacy rule:
- legacy snapshots without `quality_kind` keep a generic quality label
- no retroactive recompute is invented for old snapshots

The snapshot contract is provider-neutral.
It is explicitly designed so a future Garmin workout compiler can consume the frozen prescription without recomputing scientific logic.

---

## 11. Dashboard ↔ Training truth convergence (#239)

PR #239 is merged.

Dashboard weekly progress and Training now share:
- `frontend/src/lib/trainingWeekProgress.js`

Current rules:
- target authority comes from `/training/v2/week`
- matched = performed within the prescribed plan
- unmatched = outside the plan
- Dashboard rolling 7-day insight is not the same thing as plan completion
- `empty` = true zero
- `complete` = known value
- `partial` = unknown / incomplete
- `partial` never becomes `0%`
- `None != 0`

Product wording:
- Readiness = freshness state
- Training = prescription

---

## 12. Garmin architecture

RunIndex still relies on GCCLI.
There is no documented official Garmin OAuth flow here.

Current real session model:
- one GCCLI session per user
- user home path under `GCCLI_HOME/{user_id}`
- session persistence in Mongo collection `garmin_sessions`
- encrypted at rest via Fernet
- strict per-user isolation by `user_id`
- restore before sync when local session is missing
- delete stored session on disconnect

Implications:
- do not document GCCLI as a single global login
- do not describe official Garmin OAuth if it is not implemented

---

## 13. Backend, workers, and infrastructure

Current worker entrypoint:
- `backend/workers/run_all.py`

`run_all` starts:
- `sync_worker`
- `event_worker`
- `scheduler_worker`
- `monitor_worker`

Worker responsibilities:
- `sync_worker`: consumes Redis queue and runs GCCLI sync
- `event_worker`: fan-out of `ACTIVITY_CREATED` into derived workouts and feed cache
- `scheduler_worker`: schedules incremental syncs with Redis leader lock
- `monitor_worker`: queue-health alerts with Redis leader lock

Current infrastructure documented in repo/config:
- MongoDB
- Redis / Upstash-compatible Redis URL
- Railway worker image / runtime support
- frontend + backend runtime split
- worker health / queue / monitoring paths

Do not document the old `workers/sync_worker.py`-only architecture as the full system.

---

## 14. Subscription and trial contract

Canonical files:
- `backend/subscription_manager.py`
- `backend/access_control.py`
- `backend/services/paddle_webhook_security.py`

Current commercial contract:
- FREE: brand-new user starts free
- TRIAL: 30 days of Premium
- PREMIUM: active paid Paddle subscription

Trial rules:
- trial activates server-side after Garmin connection and verified Garmin identity
- one Garmin identity = one trial
- `trial_used` prevents replay
- frontend cannot create or reset the trial authority

Access-control rules:
- access is resolved from JWT user identity on the backend
- invalid/missing premium expiry fails closed to FREE
- DB/access errors fail closed to FREE for premium access

---

## 15. Historical report policy

Historical PR and audit reports remain historical artifacts.
Do not rewrite the full archive just to make old reports sound current.

Policy:
- historical reports keep their original point-in-time assertions
- later merges do not auto-rewrite those reports
- current truth lives in current code + canonical docs
- historical reports stay useful as evidence, not as live authority

---

## 16. Final runtime gate before beta

Before Beta, the canonical runtime gate is:
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

This repository is not to be described as fully production-ready without that gate being validated.

---

## 17. Roadmap after PR #240

Current documentation PR:
- #240 — Documentation Canonical Refresh

Next canonical sequence:
- #241 — Dashboard Polish Final
- #242 — Navigation / Sessions / Coach / Progress Cleanup
- #243 — Onboarding / Trial Final
- #244 — Current Race Predictions
- #245 — RunIndex Potential Model V1

Then:
- Final Runtime Gate
- Controlled Beta
- Garmin Workout Delivery V3
- Data Moat Foundation
- Runner Response Model
- Adaptive Training V3
- Social — Share Your Potential
- population / similar-runner learning

Do not reuse #238.

---

## 18. Product vision: Data Moat and response model

Current engines
↓
Data Moat Foundation
↓
prescription
+
performed Garmin workout
+
context
+
outcome
↓
Runner Response Model
↓
Adaptive Training V3

Longer term:
- population / similar-runner learning

Current status:
- this vision is not yet implemented as a complete Runner Response Model
- document it as future product direction, not current runtime fact

---

## 19. Future: Garmin workout delivery

Documented as future only:

RunIndex prescription
→ immutable snapshot
→ Garmin provider adapter / compiler
→ Garmin Connect
→ compatible device
→ performed activity
→ matching
→ response / outcome

This is not implemented in PR #240.
