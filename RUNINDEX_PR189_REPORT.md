# RUNINDEX PR189 REPORT

## CURRENT_ARCHITECTURE
- `backend/training_v2/performance_model.py` (before PR189) built `qualified_pool` via `_build_qualified_performance_pool()` from `evaluate_performance_quality()` (#188 semantics).
- Predictions were produced in `predict_races()` by calling `_select_riegel_source()` independently for each target (5K/10K/Semi/Marathon), then `_riegel()` and `_riegel_confidence()` per target.
- `_endurance_support()` fed a target-specific time penalty, so final outputs were additionally target-shaped outside pure Riegel.

### Audit flags
- `CURRENT_PREDICTION_ARCHITECTURE = per-target independent source selection`
- `CURRENT_SOURCE_SELECTION_PER_TARGET = YES`
- `CURRENT_MONOTONICITY_GUARANTEE = NO`

## PROBLEM_DEMONSTRATION
- Independent source selection can pick different effort levels for each target.
- Without a shared curve parameterization, cross-target pace inversions are possible (`pace_half < pace_10k`), even when each target prediction is locally defensible.

## CHOSEN_CURVE_MODEL
- Implemented shared curve model for all race targets:
  - `T(D) = A * D^k`
  - log-space fit: `log(T) = log(A) + k * log(D)`
- All contributors come strictly from #188 `qualified=True` performances.

## ALTERNATIVES_CONSIDERED
- Keep per-target source selection + post-hoc monotonic patch: rejected (explicitly forbidden).
- Single fixed source for all targets: rejected (too brittle with multiple qualified performances).
- Unbounded 2-point fit: rejected (can produce physiologically implausible `k`).

## WHY_CHOSEN
- Shared curve enforces monotonic pace naturally when `k >= 1`.
- Preserves #188 qualification semantics and no-lookahead guarantees.
- Supports single-observation fallback (`k=1.06`) and robust multi-observation fitting.

## FIT_METHOD
- New internal curve builder `_build_performance_curve()`:
  - 1 qualified performance: direct Riegel fallback (`single_performance_riegel`, `k=1.06`).
  - Multiple performances: weighted log-linear fit.
  - `n>=3`: robust reweighting (Huber-style iterations on log residuals).
  - Degenerate same-distance multi-point case: `same_distance_prior_k_fallback`.

## WEIGHTING
- Base per-observation weight = `quality_score * recency_weight * quality_confidence_weight`.
- `quality_score` and `quality_confidence` come from #188 only.

## RECENCY_POLICY
- Recency is applied only during shared curve construction.
- Step weights tied to existing confidence age bands:
  - `<=21d: 1.0`, `<=56d: 0.85`, `<=120d: 0.70`, `<=730d: 0.55`, older: `0`.
- No per-target recency source switch.

## QUALITY_POLICY
- Qualified-only contributors (`qualified=False` never included).
- Quality confidence affects contributor weight (`high > medium > low`).

## K_POLICY
- Raw fit validated against `CURVE_K_MIN=1.0` and `CURVE_K_MAX=1.25`.
- If raw fit is outside bounds: treated as observation conflict, not silently accepted.
- Conflict fallback: `prior_k_conflict_fallback` with `k=1.06` and reduced trust.

## OUTLIER_POLICY
- Robust residual reweighting (for `n>=3`) reduces leverage of incompatible points.
- Contributors are retained with robust weights for diagnostics.

## EXTRAPOLATION_POLICY
- Symmetric extrapolation ratio per target:
  - `min_observed max(target/obs, obs/target)`
- Prediction null when extrapolation is excessive (`ratio > 6.0`).
- Confidence degraded as extrapolation increases; near-null zone at `>4.5`.

## CONFIDENCE_POLICY
- Confidence now derives from curve health and extrapolation:
  - extrapolation ratio tiers,
  - curve conflict flag,
  - fit quality,
  - contributor recency/quality confidence.
- No VMA dependency.

## ENDURANCE_SUPPORT_POLICY
- `_endurance_support()` kept for readiness/support indicators.
- Removed target-specific endurance time penalty to avoid double counting with fitted `k`.

## SINGLE_PERFORMANCE_FALLBACK
- Implemented: `T(D) = T_source * (D / D_source)^1.06` via `single_performance_riegel`.

## ZERO_PERFORMANCE_BEHAVIOR
- If no qualified performance exists: all race predictions remain null/insufficient.

## PROPERTY_TEST_RESULTS
- Added `tests/test_performance_model_pr189.py` property test over 120 deterministic scenarios.
- Complete scenarios (all 4 targets non-null): `>=100` enforced.
- Monotonicity failures: `0`.

## REGRESSION_RESULTS
Executed:
- `python -m pytest -q tests/test_performance_model_pr185.py tests/test_performance_model_pr186.py tests/test_performance_model_pr188.py tests/test_performance_model_pr189.py tests/test_training_v2_domain_activity.py`
- `python -m pytest -q tests/test_data_isolation.py`

Result:
- `183 passed, 0 failed`.

## CONTRACT / ENDPOINT NOTES
- `GET /training/race-predictions` contract preserved for frontend fields:
  - `predicted_time_seconds` equivalent source (`predicted_time_s` internal),
  - `predicted_time_formatted` (`predicted_time_str`),
  - `predicted_pace_min_km` (`predicted_pace_str`),
  - `confidence`.
- Existing source metadata semantics adjusted internally for multi-contributor curve (`source_type=performance_curve_v2` when contributors>1).
- `GET /training/vma-history` behavior unchanged by this PR.

## SCOPE CHECK
- Modified:
  - `backend/training_v2/performance_model.py`
  - `backend/tests/test_performance_model_pr189.py`
  - `backend/server.py` (methodology text only)
  - `RUNINDEX_PR189_REPORT.md`
- Frontend untouched.

LIVE_ACCOUNT_TEST = NOT_RUN_IN_GITHUB_ENVIRONMENT
