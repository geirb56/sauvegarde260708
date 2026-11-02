# C392-B — Evidence-aware natural conversational Coach

Base/start SHA: `7572d3f` (`copilot/dev`, no drift since the audited reference; C393/C394 intact).
Scope: `backend/llm_coach.py` prompts + `backend/tests/test_coach_c392b_evidence_prompt.py`. No change to server.py, V2/V3, Narrative, Training, frontend, entitlements.

## Instructions removed / merged / clarified
- Merged: the raw-metrics / no-LT / no-progress / permissions / pace-string / bounded-history / prescription-authority rules were repeated in `SYSTEM_PROMPT_COACH` and in the `enrich_chat_response` user prompt. The full rule set now lives in the system prompt; the user prompt keeps a short turn-level reminder (context-specific: current-only training context, truncated history, language).
- Removed: "Present several plausible hypotheses (heat, fatigue, drift, hydration)". Replaced by: one relevant explanation is enough.
- Clarified: four evidence levels (Observation / Validated classification / Hypothesis / Personalized conclusion); probable session type vs relative intensity vs physiological intensity; general mechanisms allowed, personal application needs evidence + permission; interval irregularity and magnitude (no "regular"/"slight" for significant gaps); treadmill without validated intensity stays descriptive; history/message cannot relax rules.
- Preserved literally: permissions, Premium restriction directive, comparability, confidence metadata, no invented FCmax/LT/VMA/VO2max/reps, no longitudinal conclusion, Training V2 authority.

## Verified data contract (what the LLM actually receives)
- `selected_workout_permissions` (coach_context_v2.py:350-359): `intensity_interpretation_allowed` = V2 `signals.intensity.available`; `progress_regression_allowed`, `physiological_efficiency_allowed`, `causal_explanation_allowed` are **always false**; `similar_comparison_available/comparable/descriptive_only` from V2 similar comparison. Removed entirely when Premium/trial is absent.
- `validated_workout_observations` (server.py:2023): V3 `headline`, `analysis`, `interpretation`, `limitations` only (strings). No structured V3 classification/confidence fields are transmitted; "probable session type" is therefore only available as text inside these strings. Absent → no classification may be claimed.
- V2 analysis embedded in `workout_detail.analysis` with availability/limitations/confidence; recent_workouts bounded with coverage metadata; current training context flagged `current_only`.
- Because `causal_explanation_allowed` is always false, personalized causes stay forbidden; only general mechanisms are allowed (prompt states this).

## Blockers (not implemented, out of scope)
- Passing structured V3 classification (type, confidence, relative vs physiological intensity) and per-repetition regularity flags would require server.py/V3 contract changes.
- A permission distinguishing "general mechanism" from "personal cause" is not in the context.

## Tests
- `python -m pytest tests/test_coach_c392b_evidence_prompt.py tests/test_coach_context_v2.py tests/test_coach_c393_fallback_quota.py tests/test_narrative_coach_v3.py tests/test_pr211_coach_llm_cleanup.py` → 453 passed, 1 failed.
- The 1 failure (`test_pr211…::test_server_coach_analyze_no_hr_speed_vma_exposure`) is pre-existing on `7572d3f` (verified via stash).
- Environment: `emergentintegrations`/`litellm` private packages could not be installed (offline); the tests mock `_call_gpt`.
- Levels: unit/contract tests only. **Real LLM behaviour: NOT TESTED.**
- Not covered by deterministic tests: actual model compliance for irregular intervals, treadmill, 37 % gap, long run (needs benchmark).

## Truncation diagnosis (no change; default 700 kept)
- `_call_gpt(response_max_chars=700)` callers: `enrich_chat_response` (chat, default 700), `localization.py:62`, `narrative_coach_v3.py:753`, `hybrid_coach_c359.py:1312` (check their own limits before any change).
- `metadata["response_truncated"]` is set in `_call_gpt` but `server.py` only logs `meta` on failure; no production rate is accessible from the repo, so problematic truncation is **not demonstrated**.
- Mechanics: cut at 700 chars, back to last sentence end only if after char 400 → a hard mid-sentence cut is possible. The style directives ask for 3–5 sentences (60–110 words ≈ 400–700 chars) so the limit is borderline for initial answers.
- Proposal (later PR): chat-specific limit after auditing other callers, and logging `response_truncated` rate.

## Benchmark protocol (preparation only; no real calls without explicit authorization)
- Variants: A = C394 prompt (`7572d3f`), B = historical specialized prompt (C391), C = this prompt, ref = C388 deterministic narrative.
- Sessions: 10/10 intervals, 12/10 easy run, 13/09 long run, 26/10, 19/10 treadmill. ≥3 repetitions each when budget permits, same context payload and temperature across variants, randomized order, blind labelling.
- Axes (scored separately): factual reliability, relevance, naturalness, personalization, usefulness, concision, stability.
- Verdict per response: Conforme / Réserve mineure / Non conforme / Indéterminé. Prudent hypotheses are not penalized; factual errors are never excused by naturalness.
- Checks: irregular recoveries not called regular, no minimizing adjective for large gaps (37 %), no progress from one comparison, no intensity from low HR or treadmill, general endurance explanation not framed as personal proof, `response_truncated` rate recorded.

## Residual risks
Prompt-only mitigation; model may still deviate. Shorter user prompt relies on the system prompt for rules (same call, both always sent). Truncation unquantified.
