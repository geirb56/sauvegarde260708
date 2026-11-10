# RUNINDEX C416 — Single Coach Experience

Base: `copilot/dev` @ `1ba556d` (C415). Head: branch `special-bassoon` (single C416 commit).
Frontend-only. No backend, MongoDB, quota, Training V2, prediction or physiology change.

## Architecture before / after

| | Before | After |
|---|---|---|
| Session sheet | Garmin summary + long Narrative V3 card (headline, analysis, interpretation, recommendation) or `coach_comment`, then "Analyser avec le Coach" | Garmin summary + compact facts (`WorkoutFacts`) + V2 observations + collapsible phases/splits + "Analyser avec le Coach" |
| Opening a sheet | `/coach/workout-intelligence` **and** `/coach/workout-comment` (LLM-capable) | `/coach/workout-intelligence` and `/coach/workout-analysis` only |
| Interpretation | Sheet and chat | Chat only (`/coach?analyze=<workout_id>`, unchanged) |

## Audit: information on the sheet

| Information | Provenance | Nature | In Coach chat context | On sheet after C416 |
|---|---|---|---|---|
| Distance, duration, pace, HR | `workouts` / V2 | fact | `workout_detail` | kept |
| Session type, effort/recovery counts | V3 `session_classification` | classification | `session_coaching_frame.v3_assessment.classification`, `workout_detail.analysis.phase_analysis` | kept (evidence list) |
| Intensity vs thresholds | V3 `intensity_assessment` | fact (reliable only) | frame `intensity` | kept |
| Relative HR reference, reference count | V3 `relative_effort` | fact | frame `relative_effort` | kept |
| Historical comparison + population, pace@HR / HR@pace deltas | V3 `historical_comparison` | fact | frame `historical_comparison` (+ provenance) | kept (details) |
| Multi-session trend | V3 `performance_trend` | classification | **No** — deliberately not sent (`_compact_v3_assessment`) | kept (stays on sheet, not duplicated in React) |
| Phases, recoveries, regularity, km splits | V2 | fact | `workout_detail.analysis` | kept (details) |
| V2 synthesis / observations / limitations | V2 | deterministic observation | `workout_detail.analysis` | kept |
| Narrative limitations | `narrative_coach_v3.limitations` | limit | `validated_workout_observations.limitations` | kept (all shown) |
| `narrative.headline/analysis/interpretation` | V3 | interpretive | `validated_workout_observations` | **removed** |
| `narrative.recommendation` | V3 | interpretive | not sent as prescription | **removed** |
| `coach_comment` (C396/C400) | LLM | interpretive | built from the chat context | **removed** |

Backend contracts and stored data are untouched; only the rendering changed.

## Removed from the sheet
Narrative headline, analysis, interpretation, recommendation, `coach_comment`, the "Analyse de séance" card, and the sheet's `/coach/workout-comment` request (which could trigger an LLM call just by opening the page).

## Facts preserved (proof)
`workout-analysis-v3-pages.test.jsx` (×3 pages ×3 languages): evidence counts, limitations, 4-effort/3-recovery interval session (10/10 shape), continuous run with comparison population and deltas, phases and splits in the collapsible, no prose, no `workout-comment` request, no POST. `coach-comment-render.test.jsx`, `coach-c415.test.jsx` updated accordingly.

## Chat context verification
Verified in code (`server.py::_assemble_coach_llm_context`, `coach_session_comment.build_session_chat_context`, `coach_context_v2._compact_v3_assessment`): the chat receives `workout_detail`, `validated_workout_observations`, `session_coaching_frame`. **Documented gap:** `performance_trend` is not transmitted by design, so the chat cannot discuss the multi-session trend shown on the sheet. Not rebuilt in React; a backend context change would need its own decision.

## Files
`frontend/src/components/workout/NarrativeWorkoutAnalysis.jsx` → `WorkoutFacts.jsx`; `pages/WorkoutDetail.jsx`, `SessionDetail.jsx`, `DetailedAnalysis.jsx`; `hooks/useWorkoutIntelligence.js`; tests `workout-analysis-v3-pages`, `coach-comment-render`, `coach-c415`, `analysis-format`; this report. `Coach.jsx` unchanged (C409–C415 behaviours, `requestSeq`, Evidence Guard, entitlements, quotas intact).

## Tests
- Full frontend: `CI=true npx craco test --watchAll=false --forceExit` → 41 suites, 1618 tests passed.
- `CI=true npm run build` → success.
- Backend not modified; backend suites not re-run.

## Residual risks
- `GET /coach/workout-intelligence` still calls `generate_narrative_coach_v3`, which only reaches an LLM when `C355_NARRATIVE_LLM_ENABLED` is truthy (default off, and skipped when V2 `session_synthesis` exists). Avoiding it entirely needs a backend change (not done).
- 390 px layout not visually verified (jsdom only); the facts use the existing single-column responsive grid.
- Natural-voice quality of accepted AI chat answers is **not** resolved or verified by C416.
- `performance_trend` gap above.
- The sheet now shows V2 observations together with V3 facts; labels reuse the existing "Key takeaways" key.

## Verdict
GO MERGE, conditional on a human check of the 390 px rendering and the env flag above (not merged automatically).
