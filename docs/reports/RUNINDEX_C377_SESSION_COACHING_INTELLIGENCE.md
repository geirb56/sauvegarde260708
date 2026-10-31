# C377 — Session Coaching Intelligence

## 1. Audit initial

Repository: `geirb56/sauvegarde260708`; PR target: `copilot/dev`.
The target branch SHA resolved during this task was
`d4cc34b9968b8b0cbf247374f80a586c44e45901`.

Audited the existing C359/C365/C372/C374 coach modules, Narrative V3,
Workout Intelligence V3 models and builder, Workout Analysis V2 models and
builder, and their associated tests. There is no separate
`workout_analysis_v2_models.py`; the V2 models are declared in
`backend/workout_analysis_v2.py`.

Reusable authorities:

- `build_admissible_facts()` (`backend/hybrid_coach_c359.py:370-735`) gates
  V3 facts through workout-analysis authorization, finite evidence,
  permission-controlled history, validated recorded-effort identity, and
  optional scoped V2 evidence. It does not copy Narrative V3 prose.
- `primary_fact_candidates()` (`backend/hybrid_coach_editorial_c365.py:108-196`)
  supplies the existing deterministic candidate order. C377 filters its
  prescription candidate and does not change C365.
- `approved_v2_regularity()` and `approved_v2_pace_direction()`
  (`backend/hybrid_coach_v2_c372.py:31-157`) are the admission authorities for
  categorical repetition judgments and direction. They bind V2 version,
  owner, workout, phase identity, declared coverage, comparability, and proof.
- `CoachLanguageV1` stores typed conclusions with finite numeric evidence
  (`backend/coach_language.py:37-61`). C377 reads only the approved facts
  surfaced by C359; it never uses conclusion prose.
- V3 effort pace observations are copied from V2 phase paces in s/km and are
  recorded-effort-only. Their model explicitly disclaims whole-session
  coverage and regularity judgments (`backend/workout_intelligence_v3_models.py:163-202`).
- `effort.first`, `effort.last`, and `effort.coverage` are already validated
  against effort identity, source paths, and shared coverage by
  `backend/hybrid_coach_c359.py:198-367`.

Authority and contradiction policy:

1. Only C372-approved V2 repetition judgments can establish repetition
   regularity or pace direction. V3 dispersion, classification, and narrative
   language are not promoted to a categorical repetition verdict.
2. If V2 evidence is absent, mismatched, partial, or incoherent, C377 omits the
   V2 interpretation and abstains; it does not resolve a conflict by
   recalculation.
3. Valid V3 average-HR position can support only the existing descriptive
   position relative to reliable personal thresholds. It does not establish
   whole-session or easy-run intensity.
4. V3 historical trend judgments are excluded from C377 interpretation so the
   engine cannot turn them into a claim of performance progression. Strong,
   permission-authorized `comparison.*` facts remain eligible as observed
   comparisons, not as proof of fitness change.
5. `prescription.review` is excluded even if the caller passes
   `HybridPermissions.prescription=True`; C377 forces that permission off.

## 2. Files changed

- `backend/session_coaching_intelligence_c377.py` — standalone typed decision
  models, closed observation/interpretation/advice vocabularies, admission,
  selection, interpretation, and abstention.
- `backend/tests/test_session_coaching_intelligence_c377.py` — deterministic
  unit and adversarial tests using synthetic C359/C372 fixtures.
- `docs/reports/RUNINDEX_C377_SESSION_COACHING_INTELLIGENCE.md` — this report
  and machine-generated JSON examples.

No V2/V3 scientific calculations, physiological thresholds, routes, endpoints,
feature flags, permissions, frontend, dependencies, prescription engines, or
production wiring were changed. C377 performs no network, Garmin, MongoDB, or
LLM calls and is not activated by the application.

## 3. Architecture and contract

`build_session_coaching_decision(intelligence, *, access, permissions,
v2_evidence)` calls C359's admissible-fact builder and C365's deterministic
candidate order. It adds strict provenance/conclusion checks and converts only
the admitted facts into:

- `CoachingObservation`: closed fact code/category, single fact ID, source
  paths, finite evidence, source confidence, controlled scope, and existing
  limitations.
- `CoachingInterpretation`: at most one controlled semantic ID, linked to the
  primary observation, with explicit conditions and limitations. It contains
  no free-form meaning text.
- `CoachingAdvice`: at most one closed intent, linked to an observation and
  interpretation, with explicit conditions, contraindications, confidence,
  and source paths.
- `SessionCoachingDecision`: version, workout ID, at most one primary and two
  supporting observations, optional interpretation/advice, a closed abstention
  reason, limitations, and deduplicated provenance.

The result is deterministic and contains no clock, random value, external
service, provider text, or prescription context. A missing measurement remains
missing; it is not represented as a negative performance result.

## 4. Evidence reuse and selection

C377 keeps `primary_fact_candidates()` ordering, after filtering excluded
prescription facts. For intervals, an approved V2 pace direction ranks before
an approved V2 regularity verdict. Without a direction, regularity ranks before
descriptive endpoints/count. For non-interval sessions, C365 ordering continues
to prioritize permitted, validated facts such as historical comparisons,
session duration context, and supported personal-threshold position.

C377 does not derive continuous-run pace dynamics from session averages. The
current admissible-fact contract does not establish a continuous run's
late-session slowdown; therefore no `LATE_PACE_REDUCTION_OBSERVED` is emitted
for that case. V3 effort endpoints are not compared or converted into a new
trend.

## 5. Observation → interpretation → advice

| Admitted observation | Controlled interpretation | Advice |
| --- | --- | --- |
| `interval.pace_direction`, V2 `faster` | `PROGRESSIVE_EFFORT_OBSERVED` | None; progressive pacing is not treated as an error. |
| `interval.pace_direction`, V2 `slower` | `LATE_PACE_REDUCTION_OBSERVED` | None; no fatigue or poor-execution cause is inferred. |
| `interval.regularity`, V2 `homogeneous`, with no direction | `PACE_CONSISTENCY_OBSERVED` | `PRESERVE_PACE_CONSISTENCY`, only for a similar session and with explicit contraindications. |
| `interval.regularity`, V2 `variable`, with no direction | `PACE_VARIABILITY_OBSERVED` | `SEEK_STEADIER_PACE`, only for comparable efforts and with explicit contraindications. |
| `interval.regularity`, V2 `noticeable` | `PACE_VARIABILITY_OBSERVED` | None; C377 does not over-prescribe from the intermediate band. |
| `intensity.position`, reliable V3 personal thresholds | `INTENSITY_POSITION_SUPPORTED` | None; average HR does not establish a footing or whole-session effort. |
| Permission-authorized, strongly comparable `comparison.*` | `HISTORICAL_COMPARISON_OBSERVED` | None; not proof of fitness change or causality. |
| Counts, endpoints, session classification/duration, or unsupported metrics | No interpretation, or `INSUFFICIENT_EVIDENCE` through abstention | None. |

Advice is withheld whenever there is no eligible V2 regularity judgment, pace
direction conflicts with a consistency suggestion, comparability is missing,
evidence is incomplete, or the advice's conditions are not met. The emitted
intent is not user-facing prose; C378 must decide whether to express it, check
conditions/contraindications, and may abstain.

## 6. Abstention and safety

- Unauthorized access returns `permission_not_granted`.
- No admissible fact returns `no_admissible_observation`.
- Descriptive-only data or an unavailable/ambiguous categorical judgment
  returns `insufficient_evidence`.
- A supported observation without a safe individualized recommendation returns
  `no_safe_specific_advice`; `advice` remains `null`.
- Source paths must match the closed fact-specific provenance prefixes, and
  facts with prescription paths, invalid conclusions, duplicate IDs, malformed
  identity, or non-finite evidence are rejected.
- V2 evidence must continue to pass C372 owner/workout/version/phase/comparability
  checks. Recorded effort identity/coverage remains the C359 authority.
- C377 ignores V3 coach free text and does not diagnose fatigue, recovery,
  endurance, VO2max, performance improvement, preparation, race management,
  session success/failure, intention, sleep, stress, or nutrition.

## 7. V2/V3 and plan boundary

V2's approved, unique, versioned categorical judgment is the sole authority for
repetition regularity and direction. A V3 narrative that disagrees or simply
does not establish regularity does not override that validated V2 judgment;
without valid scoped V2 evidence, C377 abstains rather than promoting V3
dispersion. No V2 or V3 calculation is repeated.

C377's only input context is Workout Intelligence V3 plus optional already
scoped V2 evidence and existing access/history permissions. No plan or
prescription object enters the output path. Prescription permission is disabled
inside the builder, and prescription-linked facts are rejected.

## 8. Tests and validation

New C377 tests cover: homogeneous, progressive, slowing, variable, and
non-comparable intervals; three-effort direction scope; a stable footing;
long-run duration; owner-scoped history permission; absent history/thresholds;
missing and non-finite metrics; partial effort coverage; incoherent identities;
falsified provenance; V2/V3 narrative disagreement; prescription exclusion;
unauthorized access; determinism; and serialized contract bounds.

Results:

- `python -m pytest tests/test_session_coaching_intelligence_c377.py -q` —
  **22 passed**.
- Coaching/V2/V3 regression selection (C359, C365, C372, C374, Narrative V3,
  Coach Language, V2 facts/phases, V3 including its API/response checks, and
  C377) — **1373 passed**.
- `python -m flake8 session_coaching_intelligence_c377.py tests/test_session_coaching_intelligence_c377.py` —
  passed.
- `python -m black --check --line-length 79 session_coaching_intelligence_c377.py tests/test_session_coaching_intelligence_c377.py` —
  passed.
- `python -m compileall -q` on the new module and test file — passed.
- The full `tests/test_workout_analysis_v2.py` run had 171 passes and three
  existing `meaning.code` expectation failures, one per language:
  expected `meaning.consistent_pacing`, actual
  `meaning.hr_without_intensity_with_pacing`. C377 does not change V2 or those
  tests. This is recorded as an unresolved legacy-suite mismatch, not claimed
  as a green full suite.

## 9. Residual limits

- C377 intentionally supports only observations already admitted by C359/V2/V3;
  it does not add continuous-run split interpretation, infer workout intent, or
  create new historical-comparison logic.
- C377 emits controlled intent IDs, not final coaching language. Confidence
  `"none"` means the source authority supplies no confidence rating; it is not
  a probability or a newly assessed confidence.
- The existing V2 `meaning.code` mismatch above remains outside this PR.
- No production caller, API, user interface, or LLM consumes the decision yet.

## 10. C378 hand-off

C378 may consume a `SessionCoachingDecision` only after receiving the same
owner-authorized V3/V2 inputs. It should express only the closed observation,
interpretation, and optional advice IDs provided here; respect every condition,
contraindication, limitation, and provenance link; and retain abstention when
advice is `null` or the interpretation is missing. C378 must not infer intent,
recalculate science, compare with a prescription, or turn `confidence="none"`
into certainty. This engine is not a substitute for C378's rendering policy.

### Actual JSON output — homogeneous repetitions

Generated by serializing `build_session_coaching_decision()` with
`model_dump(mode="json")` from the real C372 V2 builder fixture
`calculated_case((300, 300, 300, 300))`:

```json
{
  "version": "c377-session-coaching-intelligence-1",
  "workout_id": "cur",
  "primary_observation": {
    "code": "interval.regularity",
    "category": "pacing",
    "fact_ids": ["interval.regularity"],
    "source_paths": [
      "workout_analysis_v2.workout.id",
      "workout_analysis_v2.phase_analysis",
      "workout_analysis_v2.coach_language.conclusions[0].code",
      "workout_analysis_v2.coach_language.conclusions[0].available",
      "workout_analysis_v2.coach_language.conclusions[0].kind",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.judgment_version",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.comparison_scope",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.metric",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.regularity_band",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.comparability_basis",
      "workout_analysis_v2.coach_language.conclusions[0].evidence.total_effort_count",
      "workout_analysis_v2.coach_language.conclusions[0].evidence.comparable_effort_count",
      "workout_analysis_v2.coach_language.conclusions[0].evidence.absolute_deviation_sec_per_km",
      "workout_analysis_v2.coach_language.conclusions[0].evidence.median_pace_sec_per_km"
    ],
    "evidence": {
      "regularity_band": "homogeneous",
      "source": "workout_analysis_v2",
      "status": "available",
      "efforts": 4,
      "comparability_basis": "duration"
    },
    "confidence": "none",
    "scope": "recorded_comparable_efforts",
    "limitations": [
      "recorded_comparable_efforts_only",
      "not_physiological_stability",
      "no_fatigue_progression_or_cause",
      "descriptive_not_good_or_bad"
    ]
  },
  "supporting_observations": [],
  "interpretation": {
    "code": "PACE_CONSISTENCY_OBSERVED",
    "observation_codes": ["interval.regularity"],
    "meaning": "PACE_CONSISTENCY_OBSERVED",
    "confidence": "none",
    "conditions": [
      "validated_v2_regularity_judgment",
      "all_comparable_recorded_efforts",
      "duration"
    ],
    "limitations": [
      "recorded_comparable_efforts_only",
      "not_physiological_stability",
      "no_fatigue_progression_or_cause",
      "descriptive_not_good_or_bad"
    ]
  },
  "advice": {
    "code": "PRESERVE_PACE_CONSISTENCY",
    "linked_observation_codes": ["interval.regularity"],
    "linked_interpretation_codes": ["PACE_CONSISTENCY_OBSERVED"],
    "advice_intent": "PRESERVE_PACE_CONSISTENCY",
    "conditions": [
      "v2_validated_homogeneous_regularity",
      "same_comparable_effort_structure",
      "next_similar_session_only"
    ],
    "contraindications": [
      "planned_progression_or_pace_variation",
      "workout_objective_calls_for_different_pacing"
    ],
    "confidence": "none",
    "source_paths": [
      "workout_analysis_v2.workout.id",
      "workout_analysis_v2.phase_analysis",
      "workout_analysis_v2.coach_language.conclusions[0].code",
      "workout_analysis_v2.coach_language.conclusions[0].available",
      "workout_analysis_v2.coach_language.conclusions[0].kind",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.judgment_version",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.comparison_scope",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.metric",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.regularity_band",
      "workout_analysis_v2.coach_language.conclusions[0].metadata.comparability_basis",
      "workout_analysis_v2.coach_language.conclusions[0].evidence.total_effort_count",
      "workout_analysis_v2.coach_language.conclusions[0].evidence.comparable_effort_count",
      "workout_analysis_v2.coach_language.conclusions[0].evidence.absolute_deviation_sec_per_km",
      "workout_analysis_v2.coach_language.conclusions[0].evidence.median_pace_sec_per_km"
    ]
  },
  "abstention_reason": null,
  "limitations": [
    "no_free_text_or_causal_inference",
    "no_prescription_or_plan_comparison",
    "missing_data_is_not_negative_performance"
  ],
  "provenance": [
    "workout_analysis_v2.workout.id",
    "workout_analysis_v2.phase_analysis",
    "workout_analysis_v2.coach_language.conclusions[0].code",
    "workout_analysis_v2.coach_language.conclusions[0].available",
    "workout_analysis_v2.coach_language.conclusions[0].kind",
    "workout_analysis_v2.coach_language.conclusions[0].metadata.judgment_version",
    "workout_analysis_v2.coach_language.conclusions[0].metadata.comparison_scope",
    "workout_analysis_v2.coach_language.conclusions[0].metadata.metric",
    "workout_analysis_v2.coach_language.conclusions[0].metadata.regularity_band",
    "workout_analysis_v2.coach_language.conclusions[0].metadata.comparability_basis",
    "workout_analysis_v2.coach_language.conclusions[0].evidence.total_effort_count",
    "workout_analysis_v2.coach_language.conclusions[0].evidence.comparable_effort_count",
    "workout_analysis_v2.coach_language.conclusions[0].evidence.absolute_deviation_sec_per_km",
    "workout_analysis_v2.coach_language.conclusions[0].evidence.median_pace_sec_per_km"
  ]
}
```

### Actual JSON output — missing session evidence

Generated by serializing `build_session_coaching_decision()` with
`model_dump(mode="json")` from `synthetic_case("sparse")`:

```json
{
  "version": "c377-session-coaching-intelligence-1",
  "workout_id": "synthetic-session-not-for-provider",
  "primary_observation": {
    "code": "session.unknown",
    "category": "classification",
    "fact_ids": ["session.unknown"],
    "source_paths": [
      "session_classification.type",
      "session_classification.confidence",
      "intensity_assessment.hr_used_bpm"
    ],
    "evidence": {
      "classification": "unknown",
      "average_hr_available": 0
    },
    "confidence": "none",
    "scope": "recorded_session_classification",
    "limitations": ["unknown_not_easy", "missing_average_hr"]
  },
  "supporting_observations": [],
  "interpretation": null,
  "advice": null,
  "abstention_reason": "insufficient_evidence",
  "limitations": [
    "no_free_text_or_causal_inference",
    "no_prescription_or_plan_comparison",
    "missing_data_is_not_negative_performance"
  ],
  "provenance": [
    "session_classification.type",
    "session_classification.confidence",
    "intensity_assessment.hr_used_bpm"
  ]
}
```
