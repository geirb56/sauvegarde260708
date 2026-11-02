# C396 — Reconcile Coach prompt contracts after C392-B

- Base: `copilot/dev` @ `fd2e4e592bd29a20a6814faa3dc05bf617eec95e` (merge of PR #382, C392-B present)
- Scope: `backend/llm_coach.py` (1 sentence), `tests/test_llm_coach_voice.py`, `tests/test_coach_c394_active_workout_context.py`

## Failures reproduced (14 / 226)

Environment note: `pytest-asyncio` had to be installed locally; without it async tests fail spuriously (not a repo regression). `litellm`/`emergentintegrations` are not installable offline and are not needed by these tests.

- `test_llm_coach_voice.py::test_final_prompt_keeps_grounding_and_language` ×12 (4 modes × fr/en/es): required `Use pace display strings verbatim` in the user prompt too (C392-B consolidated it in the system prompt).
- `test_coach_c394_active_workout_context.py::test_prompt_allows_recent_workouts_but_keeps_roles_and_limits`: missing `A comparison never replaces the selected workout` — a **real prompt regression** (protection lost in C392-B).
- `test_coach_c394_active_workout_context.py::test_prompt_contract_covers_reasoning_followups_and_limits`: obsolete keyword `hypotheses` (now "C. Hypothesis" contract).

C393, C392-B and Coach Context V2 tests all passed once pytest-asyncio was present.

## Changes

1. `llm_coach.py`: re-added `A comparison never replaces the selected workout.` to the roles bullet of the system prompt. No other prompt change; 700-char limit untouched.
2. Voice test: language directive asserted in both prompts; physiological, permission, no-new-prescription, comparison and non-relaxation guards asserted in the system prompt only (and explicitly *not* duplicated in the user prompt); per-mode directives asserted, other modes absent. Three stale user-prompt assertions (`do not infer effort labels…`, `they do not establish…`, `do not invent a prescription…`) matched text that no longer exists anywhere in the code and were replaced by the system-prompt checks above.
3. C394 test: `hypotheses` replaced by the C392-B hypothesis contract (general knowledge label, never an established cause, never proof of progress) plus follow-up continuity assertions.

## Results

- Before: 14 failed, 212 passed
- After: 226 passed (`tests/test_llm_coach_voice.py tests/test_coach_c394_active_workout_context.py tests/test_coach_c392b_evidence_prompt.py tests/test_coach_c393_fallback_quota.py tests/test_coach_context_v2.py`)

## Protections maintained

C392-B evidence levels/permissions, C393 fallback/quota/refund, C394 selected-workout role & follow-up continuity: all asserted and passing. No skip/xfail/test removal.

## Unresolved

None in code. Real LLM behaviour must still be validated on Emergent from the exact head SHA.

Verdict: **GO** (contract level).
