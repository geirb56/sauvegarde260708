# RUNINDEX PR #147 — Report

## 1. HEAD copilot/dev (start)
`936c966` — Merge pull request #146

## 2. Failure reproduced before fix
```
FAILED backend/tests/test_plan_duration_decoupled.py::test_adjusted_weeks_is_base_weeks
AssertionError: assert "adjusted_weeks = base_weeks" in src
```
The string `"adjusted_weeks = base_weeks"` no longer exists in coach_service.py — the code now uses dict literal syntax `"adjusted_weeks": base_weeks`.

## 3. Invariant actually tested
**Readiness must NOT influence plan duration.** All non-None values assigned to the `"adjusted_weeks"` key must be simple references to `base_weeks` or `total_weeks` — never a computed expression involving readiness, multiplication, or subtraction.

## 4. Why the old test was fragile
It searched for a literal Python assignment string (`adjusted_weeks = base_weeks`). Any refactor (dict literal, rename, reformatting) breaks it without any semantic regression.

## 5. Strategy chosen
**AST-based** — parses `coach_service.py`, walks the AST of `generate_dynamic_training_plan`, finds all dict entries with key `"adjusted_weeks"`, and asserts each non-None value is a simple `ast.Name` node whose `id` is in `{"base_weeks", "total_weeks"}`.

This will correctly fail if someone introduces e.g. `"adjusted_weeks": base_weeks - 4` or `"adjusted_weeks": int(base_weeks * readiness_factor)`.

## 6. Modification
Replaced `test_adjusted_weeks_is_base_weeks` body with AST inspection logic. Added `import ast` at module top.

## 7. Files modified
- `backend/tests/test_plan_duration_decoupled.py`
- `RUNINDEX_PR147_REPORT.md` (this file)

## 8. Proof no business code changed
`coach_service.py` — untouched. No other business files modified.

## 9. Test file results
```
41 passed in 0.56s
```

## 10. Regression suite results
```
239 passed, 1 failed (pre-existing, unrelated: test_fallback_still_exists VMA pattern)
```
The pre-existing failure is about a VMA `/0.70` pattern check in `test_training_engine_pr2.py` — unrelated to duration decoupling.

## 11. Smoke
```python
import coach_service  # OK
```

## 12. Risk
**Minimal.** Test-only change. No runtime impact.

## 13. Recommendation #148
Investigate and fix the pre-existing `test_fallback_still_exists` failure (VMA /0.70 pattern) which predates this PR.

---

**Verdict: READY FOR MERGE INTO copilot/dev**
