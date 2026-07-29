# Audit — Access Control System: Free / Trial / Premium Feature Rights
> RunIndex — `backend/subscription_manager.py` + `backend/server.py`

---

## 1. Subscription Statuses

| Status          | Source             | Description                                      |
|-----------------|--------------------|--------------------------------------------------|
| `trial`         | Auto (new user)    | 30-day free trial — full access                  |
| `free`          | Trial expired      | Limited access — no AI, no sync, no plan         |
| `early_adopter` | Stripe (€4.99/mo)  | Full access — price locked for life              |
| `premium`       | Manual / reserved  | Full access                                      |
| `active`        | Stripe             | Full access — Stripe-managed paid subscription   |

---

## 2. Feature Access Matrix

| Feature           | free | trial | early_adopter | premium |
|-------------------|:----:|:-----:|:-------------:|:-------:|
| training_plan     |  ✗   |  ✓    |  ✓            |  ✓      |
| plan_adaptation   |  ✗   |  ✓    |  ✓            |  ✓      |
| session_analysis  |  ✗   |  ✓    |  ✓            |  ✓      |
| sync_enabled      |  ✗   |  ✓    |  ✓            |  ✓      |
| api_access        |  ✗   |  ✓    |  ✓            |  ✓      |
| llm_access        |  ✗   |  ✓    |  ✓            |  ✓      |
| full_access       |  ✗   |  ✓    |  ✓            |  ✓      |

Source: `FEATURES` dict in `subscription_manager.py`

---

## 3. Chat IA Monthly Message Limits

Source: `SUBSCRIPTION_TIERS` in `server.py` + `/api/chat/send` logic.

| Tier config    | Status mapping                       | Messages/month | Unlimited           |
|----------------|--------------------------------------|----------------|---------------------|
| `free`         | `free` (expired trial)               | 10             | ✗                   |
| `premium`      | `active` (Stripe, base tier)         | 25             | ✗                   |
| `confort`      | `active` (Stripe, mid tier)          | 50             | ✗                   |
| `pro`          | `active` (Stripe, top tier)          | 150 (soft cap) | ✓ (hard cap at 200) |
| `pro` (mapped) | `trial`                              | 999            | ✓                   |
| `premium`      | `early_adopter`                      | 999            | ✓                   |
| `premium`      | `premium`                            | 999            | ✓                   |

> Trial users are mapped to the `pro` tier config inside `/api/chat/send` to grant
> unlimited AI chat access throughout the trial period.

---

## 4. Protected Routes (require subscription ≠ `free`)

Enforced by `subscription_middleware` (HTTP middleware, runs before every request).
Returns **HTTP 403** for `free` users on any of the following prefixes:

```
/api/training/plan
/api/training/refresh
/api/training/full-cycle
/api/training/race-predictions
/api/coach/analyze
/api/coach/workout-analysis
/api/coach/detailed-analysis
/api/rag/
/api/workouts
```

---

## 5. Always-Public Routes (accessible regardless of subscription)

```
/api/health
/api/subscription/*
/api/premium/*
/api/user/*
/api/dashboard/insight
```

---

## 6. Middleware Stack (order of execution)

1. `rate_limit_middleware` — 120 req/min, burst = 30 per `user_id`
2. `subscription_middleware` — blocks `free` users on protected routes
3. `audit_middleware` — logs every API request to a rotating audit log file
4. Route handlers (with `auth_user` JWT dependency)

---

## 7. Trial Lifecycle

1. **New user** hits any endpoint → `get_user_subscription()` auto-creates a `trial` record in MongoDB.
2. **Trial duration**: 30 days (`TRIAL_DURATION_DAYS = 30`).
3. **On each request**: `check_trial_expiration()` compares `trial_end` to `now(UTC)`.
4. **If expired**: status updated to `free` in DB → next request is blocked on all protected routes.

---

## 8. Known Issues / Observations

| # | Finding | Severity | Location |
|---|---------|:--------:|----------|
| 1 | `DEMO_MODE=True` bypasses **all** feature access checks — `has_feature_access()` always returns `True` | HIGH | `subscription_manager.py` |
| 2 | `subscription_middleware` **fails open** on DB errors — allows access when subscription cannot be verified | MEDIUM | `server.py` ~L445 |
| 3 | `/api/chat/send` performs its own tier resolution independently of `subscription_middleware` — two separate code paths manage the same concept | LOW | `server.py` ~L5094 |
| 4 | Stripe `active` status requires a valid `expires_at` field — a missing or malformed date silently falls back to `free` (10-msg cap) | MEDIUM | `server.py` ~L5127 |
| 5 | Legacy `starter` tier is normalized to `premium` — no documented migration path | LOW | `server.py` `normalize_subscription_tier()` |

---

## 9. Summary

The access control system is **binary at the middleware level**: `free` = blocked,
everything else = full access. Quota differentiation (10 / 25 / 50 / 150 messages/month)
only applies inside the chat endpoint.

Trial users receive **premium-equivalent access for 30 days**, then drop to the fully
restricted free tier automatically.
