# RUNNER_PROFILE_PR07_REPORT

## Scope PR07
- Added pure, deterministic, immutable `RunnerProfile` layer in:
  - `backend/training_v2/runner_profile.py`
- Added exports in:
  - `backend/training_v2/__init__.py`
- Added tests in:
  - `backend/tests/test_runner_profile_pr07.py`

## Business rules implemented
- Uses required inputs: `TrainingHistory`, `TrainingLoadSnapshot`, `GarminCapabilities`, `user_profile`, `physiological_metrics`, `reference_date`.
- No historical engine, frontend, endpoint, score/readiness, Garmin sync, Redis or MongoDB changes.
- No fallback to `20 km`.
- No implicit estimation for VMA, VO₂max, FC max, or pace.
- Observed profile prioritizes `window_30d` and falls back to `window_90d` only per-metric, only when 30d metric is not exploitable and `>= 90` days of history are available.
- If neither observed metric nor explicit declared metric exists, returns `None`.
- `experience_level` based only on history depth.

## `profile_confidence` rule (explicit)
Implemented exactly as required:
- history `>= 90` days → `high`
- history `30–89` days → `medium`
- history `1–29` days → `low`
- no history but at least one exploitable declared data point → `low`
- no declared nor observed data → `none`

Important invariant:
- Declared-only data never yields `medium` or `high`.

Declared exploitable data detection includes at minimum:
- `typical_weekly_km`
- `typical_weekly_hours`
- `typical_runs_per_week`
- `typical_long_run_km`
- `typical_speed_kmh`
- `discipline`
- `preferred_days_per_week`
- `max_days_per_week`
- `max_hr`
- `injury_constraints`
- `availability_constraints`

## Blocking tests added
- Empty history + declared profile:
  - `typical_weekly_km = 25`
  - `primary_discipline = "road"`
  - `experience_level = "unknown"`
  - `profile_confidence = "low"`
- Totally empty case:
  - `experience_level = "unknown"`
  - `profile_confidence = "none"`
