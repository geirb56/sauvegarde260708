# 15C — Coach human voice and response hierarchy

## Base and revision evidence

- PR #310 was verified **merged** before any edit (2026-10-06).
- Exact #310 merge commit, canonical `copilot/dev` HEAD and initial task HEAD:
  `db16420ed8c7ff26bf997e7e613baed100f633a6`.
- Merge parents: `d830a26ab005bbdd4e7c4ed9f38a9efdd086bef3` and
  `e7e8b1d1a90d5e31c44a2326b856b4274a6d380c`.
- Final implementation HEAD: `ef8773fc6bcc48b4861c041fb6b1228704ec61df`.
  Later documentation-only commits record validation results. The final delivered
  branch HEAD is reported in the delivery message and PR; a document cannot embed
  its own containing commit's hash.
- Base branch: `copilot/dev`. Delivery must remain **NON MERGÉE**.

## Changed files and scope

- `backend/llm_coach.py`: presentation directive and selection-only generic style.
- `backend/tests/test_llm_coach_voice.py`: deterministic outgoing-prompt contracts.
- `frontend/src/lib/i18n.js`: aligned FR/EN/ES copy.
- `frontend/src/__tests__/coach-page.test.jsx`: localized UI/API contracts.
- `docs/reports/COACH_VOICE_FINALIZATION.md`: evidence and remaining runtime gate.

No new engine, RAG, fact calculation, physiology, prescription or adaptation logic.
No changes to Coach Context V2, Training V2, Workout Analysis V2, Garmin, infrastructure,
subscriptions, authentication, colors, or the separate 3-selected/2-prescribed issue.

## Presentation modes

`_build_response_style_directive` selects instructions, not facts:

- `selected_workout_initial`: selected detail with empty workout-scoped history.
  Takeaway first; usually 3–5 sentences / 60–110 words; at most 2–3 numerical facts
  **including comparison figures**; useful `comparison.similar` prioritized;
  at most one necessary caveat; no exhaustive recap or forced template.
- `selected_workout_followup`: selected detail with existing scoped history.
  Answer the current question directly in usually 1–3 sentences; no full recap;
  do not repeat established limitations unless the new conclusion requires them.
- `current_training`: without selected detail, when today/week context is present.
  For scheduling questions, exact served prescription first, brief explanation,
  changes only as established by existing authorities. Never choose an alternative
  type, distance, pace, day or adaptation. Other questions retain concise general style.
- `general`: no selected detail or today/week context. Direct, usually 2–5 sentences,
  personal data only when useful.

Distinctive authorized takeaway → useful similar comparison → interpretation-changing
limitation. Elevation, cadence, max HR, sample sizes, coverage, windows and methodology
remain available, but are secondary unless material or requested.

Presentation never relaxes intensity, progress/regression, efficiency, causality,
comparability, confidence, availability or descriptive-only guards. Pace strings stay
verbatim; current training/readiness/load/performance cannot establish historical state.
Technical terms stay internal except for explicitly technical questions. Overlapping
limitations are summarized naturally instead of stacked.

## FR / EN / ES and API continuity

- Automatic analysis asks what matters most, not for “deep analysis”.
- Empty-state explains help with today's workout, recent runs and Garmin observations.
- Supporting note refers naturally to the RunIndex plan, not prescription authorities.
- Suggestions avoid effort-distribution dissertations, “patterns” jargon and implied
  availability of HR zones.
- `Coach.jsx` unchanged: workout identity, unique auto-trigger, query cleanup,
  navigation, follow-up context and clearing history preserve existing behavior.

## Validation

Exact commands (working directories under
`/home/runner/work/sauvegarde260708/sauvegarde260708`):

Backend, from `backend/`, with the prepared Python environment:

```sh
python -m pytest tests/test_coach_context_v2.py tests/test_coach_contract_unified.py tests/test_llm_coach_voice.py -q
```

Frontend, from `frontend/`:

```sh
CI=true npx craco test --watchAll=false --forceExit --runInBand src/__tests__/coach-page.test.jsx src/__tests__/chat-coach-subscription-status.test.jsx src/__tests__/workout-analysis-v2-pages.test.jsx
npm run build
```

Whitespace, from the repository root:

```sh
git diff --check
git diff db16420ed8c7ff26bf997e7e613baed100f633a6 --check
```

Results on implementation HEAD `ef8773fc6bcc48b4861c041fb6b1228704ec61df`:

- Backend: **172 passed**, 14 deprecation warnings, exit 0 (1.95 s).
  Python 3.12.3; `/tmp/sauvegarde_venv`; relevant core packages restored to
  existing requirements pins (including FastAPI 0.110.1, Motor 3.3.1, PyMongo 4.5.0).
  Existing test tooling: pytest 9.1.1, pytest-xdist 3.8.0, pytest-asyncio 1.4.0.
  The entire production requirements set was not installed: the private LiteLLM wheel
  was unreachable and emergentintegrations 0.1.0 unavailable on public PyPI.
  These suites mock LLM calls and passed without those integrations.
- Frontend: **95 passed**, **3 suites passed**, exit 0 (4.037 s).
  Node 22.23.3 / npm 10.9.9, using the unchanged existing lockfile restored with
  `npm ci --legacy-peer-deps`.
- Build: **compiled successfully**, exit 0; main JS 332.88 kB and CSS 15.06 kB gzipped.
- `git diff --check` and the base-to-head diff check: passed.
- Validation commands were executed by a task agent; no test or build tooling was added.

Initial frontend attempts after `npm install --legacy-peer-deps --no-package-lock`
failed on `@radix-ui/primitive/is-development` and `ajv/dist/compile/codegen`.
Restoring the existing locked tree with `npm ci --legacy-peer-deps` resolved both;
the requested tests and build were rerun successfully. No source, dependency manifest
or lockfile workaround was introduced.

The deterministic tests intercept `_call_gpt`; no external LLM is called. They verify
mode selection, numerical-fact budget, comparison priority, caveat/secondary-fact rules,
no-recap follow-ups, immutable context, language directives in all four modes and three
languages, plus preserved authority/physiology/pace/time guards.
UI tests verify natural FR/EN/ES empty-state/supporting note and automatic CTA payload,
single automatic post, follow-up workout ID, clearing context and absent ID in general chat.

CodeQL: **0 alerts** for Python and JavaScript. The automated review tool could not
run its configured model (`capi-prod-claude-sonnet-4.6` unavailable); its nominal success
wrapper is not counted as a completed review. A separate read-only code-review agent
reviewed the implementation diff and reported **no significant issues**.

## Required product QA — still pending after merge and Emergent pull

Tests of prompt instructions are **not proof that a real LLM always follows them**.
The product is not declared runtime-finalized by this PR.

1. **01/10** (9.66 km, ~1h06, 6:48/km, 141/171 bpm): WorkoutDetail → Coach,
   immediate takeaway, only useful figures, similar comparison, 3–5 sentences,
   no exhaustive report or unsupported intensity inference.
2. **28/09** (10.18 km, ~1h11, 6:59/km, 127/144 bpm): no reference to 01/10,
   descriptive comparison and hierarchical response, no exhaustive report.
3. **Same-workout follow-up**: “Que retiens-tu surtout de cette séance ?”:
   direct 1–3 sentences, no full recap, workout ID preserved.
4. **Today/week**: next planned session and impact of recent runs:
   exact served prescription, no invented alternative, natural explanation.
5. **Empty-state**: no internal authority/engine/second-prescription jargon.

Check CTA, empty-state, supporting note and actual response language in FR/EN/ES.
No merge is performed by this task.
