# RUNINDEX — MICRO-PR CORRECTIVE REPORT

## Objective
Fix RunIndex History current pillar contract so current pillar values and evolutions use valid current snapshot fields.

## Base branch
- `copilot/dev`

## Base SHA
- `4533049ca6e7516c85cd4bceb0ff7ec826b5db35`

## Files modified
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/services/run_index_history.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_run_index_history_service.py`

## Bug cause confirmed
In `backend/services/run_index_history.py`, `_build_history_response()` read current pillars with `current_source.get("speed")` / `endurance` / `consistency` / `efficiency` while `current_snapshot` from `upsert_run_index_snapshot()` exposes `speed_score`, `endurance_score`, `consistency_score`, `efficiency_score`.

## Applied correction
Updated `_build_history_response()` pillar read path to use explicit fallback mapping when current normalized keys are absent:
- `speed` → `speed_score`
- `endurance` → `endurance_score`
- `consistency` → `consistency_score`
- `efficiency` → `efficiency_score`

This keeps history entries unchanged and fixes current pillar contract for current snapshots.

## Mapping used (final)
For each pillar `p` in `speed/endurance/consistency/efficiency`:
- use `current_source[p]` when key exists;
- otherwise use `current_source[f"{p}_score"]`.

## `None != 0` confirmation
Added explicit regression assertions proving `None` current pillar values remain `None` and are not transformed to `0`, and that evolution remains `None` when current or first value is missing.

## Tests executed
1. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_run_index_history_service.py tests/test_run_index_current_single_source_pr216.py`
   - Result: import errors due missing dependencies in environment (`fastapi`, then `email_validator`) while `tests/test_run_index_history_service.py` cases executed and passed.
2. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_run_index_history_service.py`
   - Result: `11 passed in 0.74s`.
3. `cd /home/runner/work/sauvegarde260708/sauvegarde260708 && git diff --check`
   - Result: no output.

## Out of scope
- No product out-of-scope debt was modified.

## Scope confirmations
- No RunIndex science/weighting/sufficiency logic modified.
- No Speed/Endurance/Consistency/Efficiency formula modified.
- No Garmin source contract modified.
- No frontend files modified.
- No merge performed.

## Revision pointers
- Base: `4533049ca6e7516c85cd4bceb0ff7ec826b5db35`
- Head at report time: `c2fe2d0d4c3a4f294474338b5958bebff592e5ed`
