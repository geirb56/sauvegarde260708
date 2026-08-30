# RUNINDEX — PR #221 REPORT

## SHA départ réel
- Base branch: `copilot/dev`
- Start SHA: `24148c8faed917f284e9842ec4bde66936c26f84`
- Verification: commit message `Merge pull request #220 ...` confirms #220 merged.

## Branche
- Working branch: `copilot/221-trial-security-one-garmin-one-trial`

## Cause A37
`POST /api/subscription/start-trial` allowed any authenticated JWT user to activate a trial directly, bypassing Garmin Trial Registry authority.

## Ancienne chaîne de bypass
`JWT user -> /api/subscription/start-trial -> subscriptions.status=trial + trial_used=true` without Garmin identity/registry validation.

## Nouvelle autorité Trial
Single server authority remains Garmin connect flow:
1. `POST /api/garmin/connect`
2. `garmin.service.connect()` reads authenticated Garmin profile server-side
3. `activate_garmin_trial(db, user_id, garmin_identity)` enforces eligibility and activation rules

`/api/subscription/start-trial` now always returns `403` and cannot activate trial.

## Source exacte de `garmin_identity`
Server-derived only from Garmin provider profile email:
- `backend/garmin/service.py::_derive_garmin_identity_from_profile(profile)`
- Source field: `profile["email"]` returned by `provider.get_profile(user_id)`
- Canonicalization: `strip().lower()`
- Frontend-provided username/email is not used for trial grant.

## Garantie atomique
Atomic claim is enforced in `activate_garmin_trial` with:
- `garmin_trial_registry.find_one_and_update(..., upsert=True, $setOnInsert)`
- Unique index on `garmin_trial_registry.garmin_identity`
- Claim token (`trial_claim_token`) to detect winner vs already-existing claim

Concurrent requests for same Garmin identity result in one winner only.

## Changements fonctionnels
- `backend/server.py`
  - Hardened `/api/subscription/start-trial`: direct activation removed, returns `403`.
- `backend/subscription_manager.py`
  - Added guardrails in `activate_garmin_trial`:
    - PREMIUM remains PREMIUM (no regression)
    - Active TRIAL is not restarted
    - `trial_used=True` users cannot get a second trial
    - Registry claim skipped for ineligible statuses
- `backend/tests/test_start_trial.py`
  - Updated to validate bypass is blocked.
- `backend/tests/test_garmin_trial_eligibility.py`
  - Added/strengthened tests for:
    - PREMIUM non-regression
    - TRIAL non-restart (trial dates unchanged)
    - concurrency winner count exactly one

## Tests ajoutés/exécutés
Executed:
- `python -m pytest tests/test_start_trial.py tests/test_garmin_trial_eligibility.py tests/test_garmin_connect_trial_flow.py`

Result:
- `32 passed`

## Limites
- This PR secures trial authority and bypass path only (scope #221).
- No Paddle checkout/webhook/readiness/goal algorithm changes.

## Runtime production testé ou non
- Not tested on production runtime in this task environment.
