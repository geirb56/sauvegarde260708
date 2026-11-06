# RUNINDEX C405 — Dedicated prompt for the automatic session comment (C400)

## 1. Base
- Branch `copilot/c405-session-comment-prompt`, base `origin/copilot/dev` = `7b953c1` (merge of PR #390, C403). Clean tree at start.
- C402 and C403 present (`coach_session_comment.py`, `c403-session-comment-v4`). `C400_SESSION_COMMENT_ENABLED` read from the environment, default OFF (`coach_session_comment.py:60`). Unchanged.
- No C401 or C404 report exists in the repo; the C404 raw comments and their exact contexts are absent.

## 2. Real generation path (proven by code)
Validated V3 observations (`server._coach_validated_workout_observations`) → `coach_session_comment.build_comment_context` → `llm_coach.generate_session_comment` → `_call_gpt` (gpt-4.1-mini, 15 s, `_clean_response(max_chars=700)`) → `validate_session_comment` (C403) → comment or C388 fallback. Cache, in-flight dedup and timeout live in `coach_session_comment._generate`. If `validated_workout_observations` is absent the route falls back.

## 3. Observations actually sent to C400
| Observation | Source | Existing priority | Confidence | Permission | In C400 | Exploitable |
|---|---|---|---|---|---|---|
| headline / analysis / interpretation / limitations | V3 deterministic strings | headline first (ordering only) | none per item | via permissions | yes | yes |
| `session_synthesis` primary / supporting (≤2) / limitations / abstention | V2 `CoachSessionSynthesisV2` | explicit primary vs supporting | finite evidence + source_paths | via permissions | yes, inside `workout_detail.analysis` (not stripped) | yes when populated |
| `coach_language`, `signals`, `pacing`, `phase_analysis` | V2 | no | evidence | via permissions | yes (same) | yes |
| `comparison.similar` | V2 | no | comparable flag | `similar_comparison_available` | yes | yes if allowed |
| `history_as_of_session` (prior sessions only, trend not established) | C402 | no | — | — | yes | descriptive only |
| `runner_profile`, `declared_goal` (current goal), `reliable_physiology` | C402 | no | — | — | yes | restricted |
| Training V2, readiness, load, paces, `recent_workouts` | — | — | — | — | no (dropped by C402) | n/a |

Conclusion: a reliable priority (`session_synthesis.primary`, `validated_workout_observations.headline`) exists and is transmitted. The context is sufficient to implement; STOP not triggered. Whether `session_synthesis` is populated for a given real session is a data question that cannot be checked here.

## 4. Defects of the previous prompt (proven by code only)
- Reused `SYSTEM_PROMPT_COACH` (chat prompt: Q&A, follow-ups, "ask a clarification question", "recent_workouts", evidence levels A–D) for a generation without a question.
- Added the chat `_build_response_style_directive` plus `_PROMPT_GUARDS`, redundant with the system prompt and chat-oriented.
- "At most one limitation" + prompt caveat rules ("say what you cannot conclude") push towards routine reserves.
- Runtime style defects reported by C404 (robotic, metric accumulation, repeated reserves) are **not verifiable here**: hypothesis.

## 5. Change
Only `backend/llm_coach.py`: new `SYSTEM_PROMPT_SESSION_COMMENT` (exact text in the file, ~45 lines), `generate_session_comment` uses it with `_lang_directive(language)`; `_SESSION_COMMENT_DIRECTIVE`, `_PROMPT_GUARDS` and the chat style directive are no longer used by C400. Unchanged: `SYSTEM_PROMPT_COACH`, `enrich_chat_response`, `_clean_response`, `_call_gpt`, model, timeout, cache, context builder, permissions, C403 validator, C388 fallback, flag (OFF), API contracts.
Differences: autonomous prompt; selection of one main observation reusing `session_synthesis` / V3 headline; style rules (2–4 sentences, no routine caveat, no question/compliment/prescription); every factual guard of the old path is kept (permissions, no invented number, history provenance, goal = current goal only, no progress/causality/intensity/LT/VO2max/max-HR claims, no sensations).
Truncation: `_call_gpt` cuts at 700 characters (`response_truncated` in metadata); a truncated comment is then judged by C403. Unchanged and documented.

## 6. Tests
- Updated one obsolete test (`test_session_comment_uses_chat_prompt…` → dedicated prompt) and added: dedicated prompt used, no chat directive, permissions and context transmitted, FR/EN/ES contracts, guardrail presence, chat keeps `SYSTEM_PROMPT_COACH`.
- Targeted suites (`test_coach_c400/c402/c403_session_comment`, `test_coach_context_v2`, `test_llm_coach_voice`, `test_narrative_c388`): **467 passed, 0 failed**.
- Full `backend/tests` in this sandbox (no MongoDB): 192 failed / 63 errors with the change vs 184 / 54 without; the failing sets differ only in `test_idor_integration.py::TestCoachHistoryIntegration` setup errors (environment/ordering, unrelated to `llm_coach`).

## 7. Fixed evaluation grid (set before any generation)
Eliminatory: invented figure, wrong historical attribution, unauthorized comparison, unauthorized physiological conclusion, new prescription, permission violation. Quality 0–5 (specificity, relevance of main observation, usefulness, naturalness, concision, no repetition, no needless caveat); a comment without a specific verifiable useful observation cannot score ≥4. Exploratory thresholds: 0 eliminatory, ≥4/5 comments ≥4/5, ≥4/5 relevant main observation, ≥4/5 specific, ≤1/5 needless caveat. C403 acceptance is reported separately and is not a GO criterion.

## 8. LLM experiment — NOT PERFORMED
- No LLM key (`EMERGENT_LLM_KEY` absent; `_call_gpt` returns `None`) and `emergentintegrations` is not installed; no Garmin/Mongo access allowed.
- The five C404 reference comments and their exact contexts (10/10, 12/10, 13/09, 26/10, 19/10/2026) are not in the repo.
- No comment was simulated. Sections "C404 references, C405 raw comments, A/B comparison, notes, factual verification, C403 results, false rejects/accepts, latency" are therefore **empty**. Latency, tokens (not exposed by the client) and truncation were not measured.

## 9. Residual risks
- Naturalness gain is a hypothesis, untested at runtime.
- The new prompt may change the C403 acceptance rate in either direction; unmeasured.
- A model may still ignore guardrails; only C403 (heuristic, not absolute proof) checks outputs.
- If `session_synthesis` is empty for a session, the prompt falls back to V3 strings and descriptive output.

## 10. Recommendation
**No GO.** Runtime evaluation incomplete. The PR is reviewable for code and tests only. Next, with the key and the C404 contexts, run the 5-session A/B with the grid above and independent human review. If the prompt alone is insufficient, consider deterministic upstream selection of the observation (not implemented). C400 stays OFF; no chaining to C406.
