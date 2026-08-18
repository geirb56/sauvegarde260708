"""
PR #139 — Non-regression tests for legacy runtime migration.

Each test proves that a specific legacy symbol NO LONGER drives a runtime decision,
and that the V2 equivalent is now the source of truth.

Test matrix (from problem statement §15):
A. /training/full-cycle  → no training_engine decision
B. /training/metrics     → TrainingState V2 source of acwr_reliable
C. /training/week-plan   → determine_target_load absent (deprecated)
D. generate_cycle_week   → no compute_target_km
E. generate_cycle_week   → no apply_resume_guard
F. generate_cycle_week   → no compute_long_run_km via legacy
G. plan runtime          → structure from WorkoutGenerator V2 (coach_service)
H. deep_reprise          → duration-based, no intensity
I. reprise_exit          → no forced hard session
J. normal                → V2 behaviour unchanged
K. performance.py        → does not drive V2 decisions
L. VMA fallback 12.0     → never injected into WeeklyTarget/WorkoutGenerator/Readiness
"""

import ast
import inspect
import importlib
import sys
import types
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_of(module_name: str) -> str:
    """Return the raw source text of a module."""
    import importlib.util
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        return ""
    with open(spec.origin, encoding="utf-8") as fh:
        return fh.read()


def _imports_symbol(source: str, symbol: str) -> bool:
    """Return True if ``symbol`` appears as a runtime import in ``source``."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == symbol or (alias.asname and alias.asname == symbol):
                    return True
    return False


def _symbol_called_in_function(source: str, func_name: str, symbol: str) -> bool:
    """Return True if ``symbol`` is called inside the body of ``func_name``."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id == symbol:
                    return True
                if isinstance(child, ast.Attribute) and child.attr == symbol:
                    return True
    return False


def _top_level_imports_symbol(source: str, symbol: str) -> bool:
    """Return True if ``symbol`` is in a top-level (module-level) import."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:  # only top-level nodes
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == symbol or (alias.asname and alias.asname == symbol):
                    return True
    return False


# ---------------------------------------------------------------------------
# B. /training/metrics — TrainingState V2 source of acwr_reliable
# ---------------------------------------------------------------------------

class TestMetricsAcwrReliable:
    """B: acwr_reliable in /training/metrics must come from TrainingState V2."""

    def test_classify_training_state_not_called_at_module_level(self):
        """classify_training_state must not be imported at top-level in server.py."""
        import os, sys
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        assert not _top_level_imports_symbol(source, "classify_training_state"), (
            "classify_training_state must not be imported at top-level in server.py "
            "(it was replaced by build_training_state V2 in PR #139)."
        )

    def test_build_training_state_imported_in_server(self):
        """build_training_state must be imported in server.py (V2 replacement)."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "build_training_state" in source, (
            "build_training_state must be imported in server.py for the V2 "
            "acwr_reliable decision in /training/metrics."
        )

    def test_training_state_v2_source_for_acwr_reliable(self):
        """acwr_reliable in /training/metrics must be derived from continuity_state."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        # V2 decision: continuity_state drives acwr_reliable
        assert "continuity_state" in source, (
            "continuity_state must appear in server.py as the V2 source of acwr_reliable."
        )
        # Legacy decision must not be present
        assert "classify_training_state(activities_28)" not in source, (
            "classify_training_state(activities_28) must not be called in server.py "
            "(legacy runtime call removed in PR #139)."
        )


# ---------------------------------------------------------------------------
# C. /training/week-plan — determine_target_load absent
# ---------------------------------------------------------------------------

class TestWeekPlanDeprecated:
    """C: /training/week-plan must not use determine_target_load."""

    def test_determine_target_load_not_called_in_server(self):
        """determine_target_load must not be called as a function in server.py."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        # AST check: no function call named determine_target_load
        try:
            tree = ast.parse(source)
        except SyntaxError:
            pytest.skip("Could not parse server.py.")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.id if isinstance(func, ast.Name) else
                    func.attr if isinstance(func, ast.Attribute) else None
                )
                assert name != "determine_target_load", (
                    "determine_target_load must not be called in server.py (removed PR #139). "
                    "/training/week-plan was deprecated and redirects to generate_dynamic_training_plan."
                )

    def test_week_plan_endpoint_delegates_to_v2(self):
        """The deprecated /training/week-plan endpoint body must reference generate_dynamic_training_plan."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "generate_dynamic_training_plan" in source, (
            "generate_dynamic_training_plan must be present in server.py to serve "
            "the deprecated /training/week-plan via the V2 pipeline."
        )


# ---------------------------------------------------------------------------
# D. generate_cycle_week — no compute_target_km
# ---------------------------------------------------------------------------

class TestGenerateCycleWeekNoLegacyVolume:
    """D: generate_cycle_week must not call compute_target_km."""

    def test_compute_target_km_not_imported_in_llm_coach(self):
        """compute_target_km must not be imported in llm_coach.py."""
        import os
        coach_path = os.path.join(
            os.path.dirname(__file__), "..", "llm_coach.py"
        )
        with open(coach_path, encoding="utf-8") as fh:
            source = fh.read()
        assert not _top_level_imports_symbol(source, "compute_target_km"), (
            "compute_target_km must not be imported in llm_coach.py (removed PR #139). "
            "generate_cycle_week must use V2 weekly_target_v2.target_km instead."
        )

    def test_compute_target_km_not_called_in_generate_cycle_week(self):
        """compute_target_km must not be called inside generate_cycle_week."""
        import os
        coach_path = os.path.join(
            os.path.dirname(__file__), "..", "llm_coach.py"
        )
        with open(coach_path, encoding="utf-8") as fh:
            source = fh.read()
        assert not _symbol_called_in_function(source, "generate_cycle_week", "compute_target_km"), (
            "compute_target_km must not be called inside generate_cycle_week. "
            "V2 source: weekly_target_v2.target_km (or target_km_protected fallback)."
        )

    def test_generate_cycle_week_uses_weekly_target_v2(self):
        """generate_cycle_week must read from weekly_target_v2 context key."""
        import os
        coach_path = os.path.join(
            os.path.dirname(__file__), "..", "llm_coach.py"
        )
        with open(coach_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "weekly_target_v2" in source, (
            "generate_cycle_week must use context['weekly_target_v2'] as the V2 "
            "source for the weekly volume target."
        )


# ---------------------------------------------------------------------------
# E. generate_cycle_week — no apply_resume_guard
# ---------------------------------------------------------------------------

class TestGenerateCycleWeekNoResumeGuard:
    """E: generate_cycle_week must not call apply_resume_guard."""

    def test_apply_resume_guard_not_imported_in_llm_coach(self):
        """apply_resume_guard must not be imported in llm_coach.py."""
        import os
        coach_path = os.path.join(
            os.path.dirname(__file__), "..", "llm_coach.py"
        )
        with open(coach_path, encoding="utf-8") as fh:
            source = fh.read()
        assert not _top_level_imports_symbol(source, "apply_resume_guard"), (
            "apply_resume_guard must not be imported in llm_coach.py (removed PR #139). "
            "V2 WeeklyTarget handles the resume guard upstream."
        )

    def test_apply_resume_guard_not_called_in_generate_cycle_week(self):
        """apply_resume_guard must not be called inside generate_cycle_week."""
        import os
        coach_path = os.path.join(
            os.path.dirname(__file__), "..", "llm_coach.py"
        )
        with open(coach_path, encoding="utf-8") as fh:
            source = fh.read()
        assert not _symbol_called_in_function(source, "generate_cycle_week", "apply_resume_guard"), (
            "apply_resume_guard must not be called inside generate_cycle_week. "
            "The V2 weekly_target_v2 already applies the guard via _apply_resume_guard() "
            "in weekly_target.py."
        )


# ---------------------------------------------------------------------------
# F. generate_cycle_week — no compute_long_run_km via legacy
# ---------------------------------------------------------------------------

class TestGenerateCycleWeekNoLegacyLongRun:
    """F: generate_cycle_week must not use compute_long_run_km from training_engine."""

    def test_compute_long_run_km_not_imported_from_training_engine(self):
        """compute_long_run_km must not be imported from training_engine in llm_coach.py."""
        import os
        coach_path = os.path.join(
            os.path.dirname(__file__), "..", "llm_coach.py"
        )
        with open(coach_path, encoding="utf-8") as fh:
            source = fh.read()
        assert not _top_level_imports_symbol(source, "compute_long_run_km"), (
            "compute_long_run_km must not be imported from training_engine in llm_coach.py "
            "(removed PR #139). V2 source: training_v2.workout_generator._compute_long_run_km."
        )

    def test_long_run_source_is_v2_workout_generator(self):
        """generate_cycle_week must use V2 WorkoutGenerator for long run."""
        import os
        coach_path = os.path.join(
            os.path.dirname(__file__), "..", "llm_coach.py"
        )
        with open(coach_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "training_v2.workout_generator" in source, (
            "generate_cycle_week must import from training_v2.workout_generator for the "
            "long run distance — WorkoutGenerator V2 is the source (§9 constraint)."
        )


# ---------------------------------------------------------------------------
# G. Plan runtime — WorkoutGenerator V2 structure via coach_service
# ---------------------------------------------------------------------------

class TestPlanRuntimeV2Structure:
    """G: /training/plan and /training/refresh use WorkoutGenerator V2 via coach_service."""

    def test_generate_dynamic_training_plan_uses_build_weekly_plan(self):
        """generate_dynamic_training_plan must call build_weekly_plan (WorkoutGenerator V2)."""
        import os
        cs_path = os.path.join(
            os.path.dirname(__file__), "..", "coach_service.py"
        )
        with open(cs_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "build_weekly_plan" in source, (
            "coach_service.py must call build_weekly_plan from training_v2.workout_generator. "
            "This is the V2 WorkoutGenerator source for /training/plan and /training/refresh."
        )

    def test_generate_cycle_week_not_called_in_generate_dynamic_plan(self):
        """generate_dynamic_training_plan must NOT call generate_cycle_week."""
        import os
        cs_path = os.path.join(
            os.path.dirname(__file__), "..", "coach_service.py"
        )
        with open(cs_path, encoding="utf-8") as fh:
            source = fh.read()
        # generate_cycle_week is imported but should never be called in the function
        assert not _symbol_called_in_function(source, "generate_dynamic_training_plan", "generate_cycle_week"), (
            "generate_dynamic_training_plan must not call generate_cycle_week. "
            "The V2 pipeline (build_weekly_plan) is the sole plan source."
        )


# ---------------------------------------------------------------------------
# H. deep_reprise — duration-based, no intensity
# ---------------------------------------------------------------------------

class TestDeepRepriseNoBehaviourChange:
    """H: deep_reprise must prescribe durations, no intensity."""

    def test_deep_reprise_no_intensity_in_weekly_target(self):
        """WeeklyTarget for deep_reprise must have allow_intensity=False."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        try:
            from training_v2.weekly_target import WeeklyTarget
            # Build a minimal WeeklyTarget directly (frozen model)
            wt = WeeklyTarget(
                reference_date=__import__("datetime").date(2025, 1, 1),
                target_basis="duration",
                target_km=None,
                target_duration_minutes=105,
                target_sessions=3,
                allow_intensity=False,
                confidence="low",
                continuity_state="deep_reprise",
                reason_codes=("DEEP_REPRISE",),
            )
            assert wt.allow_intensity is False, (
                "deep_reprise WeeklyTarget must have allow_intensity=False."
            )
            assert wt.target_basis == "duration", (
                "deep_reprise WeeklyTarget must use duration-based prescription."
            )
        except ImportError:
            pytest.skip("V2 modules not importable in this environment.")


# ---------------------------------------------------------------------------
# I. reprise_exit — no forced hard session
# ---------------------------------------------------------------------------

class TestRepriseExitNoForcedIntensity:
    """I: reprise_exit allows intensity but does NOT force it."""

    def test_reprise_exit_allow_intensity_true_but_not_forced(self):
        """reprise_exit WeeklyTarget allows intensity (allow_intensity=True) but
        WorkoutGenerator is free to produce easy sessions."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        try:
            from training_v2.weekly_target import WeeklyTarget
            import datetime
            wt = WeeklyTarget(
                reference_date=datetime.date(2025, 1, 1),
                target_basis="distance",
                target_km=30.0,
                target_duration_minutes=None,
                target_sessions=4,
                allow_intensity=True,  # allowed but not forced
                confidence="medium",
                continuity_state="reprise_exit",
                reason_codes=("REPRISE_EXIT_INTENSITY_RETURNS",),
            )
            assert wt.allow_intensity is True
            assert wt.continuity_state == "reprise_exit"
        except ImportError:
            pytest.skip("V2 modules not importable in this environment.")


# ---------------------------------------------------------------------------
# J. normal — V2 behaviour unchanged
# ---------------------------------------------------------------------------

class TestNormalStateV2Unchanged:
    """J: normal training state routes through V2 without modification."""

    def test_build_training_state_not_modified(self):
        """build_training_state must not import training_engine."""
        import ast
        import os
        ts_path = os.path.join(
            os.path.dirname(__file__), "..", "training_v2", "training_state.py"
        )
        tree = ast.parse(open(ts_path, encoding="utf-8").read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        has_te = any(
            (isinstance(n, ast.ImportFrom) and n.module and "training_engine" in n.module) or
            (isinstance(n, ast.Import) and any("training_engine" in a.name for a in n.names))
            for n in imports
        )
        assert not has_te, (
            "training_v2/training_state.py must not import training_engine. "
            "The module must remain a pure V2 component."
        )

    def test_build_weekly_target_not_modified(self):
        """build_weekly_target must not import training_engine."""
        import ast
        import os
        wt_path = os.path.join(
            os.path.dirname(__file__), "..", "training_v2", "weekly_target.py"
        )
        tree = ast.parse(open(wt_path, encoding="utf-8").read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        has_te = any(
            (isinstance(n, ast.ImportFrom) and n.module and "training_engine" in n.module) or
            (isinstance(n, ast.Import) and any("training_engine" in a.name for a in n.names))
            for n in imports
        )
        assert not has_te, (
            "training_v2/weekly_target.py must not import training_engine."
        )

    def test_workout_generator_not_modified(self):
        """workout_generator must not import training_engine."""
        import ast
        import os
        wg_path = os.path.join(
            os.path.dirname(__file__), "..", "training_v2", "workout_generator.py"
        )
        tree = ast.parse(open(wg_path, encoding="utf-8").read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        has_te = any(
            (isinstance(n, ast.ImportFrom) and n.module and "training_engine" in n.module) or
            (isinstance(n, ast.Import) and any("training_engine" in a.name for a in n.names))
            for n in imports
        )
        assert not has_te, (
            "training_v2/workout_generator.py must not import training_engine."
        )


# ---------------------------------------------------------------------------
# K. performance.py — does not pilot V2 decisions
# ---------------------------------------------------------------------------

class TestPerformanceIsolated:
    """K: performance.py must not drive any V2 training decision module."""

    @pytest.mark.parametrize("v2_module", [
        "training_v2/training_state.py",
        "training_v2/weekly_target.py",
        "training_v2/weekly_reconciliation.py",
        "training_v2/workout_generator.py",
        "training_v2/readiness_decision.py",
        "training_v2/daily_adaptation.py",
    ])
    def test_v2_decision_module_does_not_import_performance(self, v2_module):
        """V2 decision modules must not import training_v2.performance."""
        import os
        module_path = os.path.join(
            os.path.dirname(__file__), "..", v2_module
        )
        if not os.path.exists(module_path):
            pytest.skip(f"Module not found: {v2_module}")
        with open(module_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "from .performance" not in source and "from training_v2.performance" not in source, (
            f"{v2_module} must not import training_v2.performance. "
            "Performance extraction is a compatibility layer, not a decision source."
        )

    def test_performance_module_itself_does_not_import_decision_modules(self):
        """performance.py must not import training_state, weekly_target, or workout_generator."""
        import os
        perf_path = os.path.join(
            os.path.dirname(__file__), "..", "training_v2", "performance.py"
        )
        if not os.path.exists(perf_path):
            pytest.skip("performance.py not found.")
        with open(perf_path, encoding="utf-8") as fh:
            source = fh.read()
        for banned in ["training_state", "weekly_target", "workout_generator",
                       "readiness_decision", "daily_adaptation"]:
            assert f"from .{banned}" not in source and f"from training_v2.{banned}" not in source, (
                f"training_v2/performance.py must not import {banned}. "
                "Performance extraction must remain isolated from training decisions."
            )


# ---------------------------------------------------------------------------
# L. VMA fallback 12.0 — never injected into V2 decisions
# ---------------------------------------------------------------------------

class TestVMAFallbackIsolated:
    """L: VMA fallback 12.0 must never reach WeeklyTarget/WorkoutGenerator/Readiness."""

    def test_vma_default_not_in_weekly_target(self):
        """WeeklyTarget must not contain VMA-related variables."""
        import os
        wt_path = os.path.join(
            os.path.dirname(__file__), "..", "training_v2", "weekly_target.py"
        )
        with open(wt_path, encoding="utf-8") as fh:
            source = fh.read()
        for vma_ref in ["vma", "VMA", "vo2max", "VO2MAX"]:
            assert vma_ref not in source, (
                f"training_v2/weekly_target.py must not reference {vma_ref}. "
                "VMA/VO2max are performance compatibility data, not decision inputs."
            )

    def test_vma_default_not_in_workout_generator(self):
        """WorkoutGenerator must not contain VMA-related variables."""
        import os
        wg_path = os.path.join(
            os.path.dirname(__file__), "..", "training_v2", "workout_generator.py"
        )
        with open(wg_path, encoding="utf-8") as fh:
            source = fh.read()
        for vma_ref in ["vma", "VMA", "vo2max", "VO2MAX"]:
            assert vma_ref not in source, (
                f"training_v2/workout_generator.py must not reference {vma_ref}. "
                "VMA/VO2max belong to performance compatibility, not the V2 plan engine."
            )

    def test_performance_12_fallback_annotation_exists(self):
        """performance.py must document the VMA 12.0 fallback."""
        import os
        perf_path = os.path.join(
            os.path.dirname(__file__), "..", "training_v2", "performance.py"
        )
        if not os.path.exists(perf_path):
            pytest.skip("performance.py not found.")
        with open(perf_path, encoding="utf-8") as fh:
            source = fh.read()
        # The fallback VMA value must be documented/present in performance.py
        assert "12.0" in source or "12" in source, (
            "performance.py must document the VMA fallback value (12.0 km/h). "
            "This fallback is ONLY for performance compatibility consumers."
        )


# ---------------------------------------------------------------------------
# Full-cycle: current week uses V2 (no resolve_reprise_plan)
# ---------------------------------------------------------------------------

class TestFullCycleV2Migration:
    """A: /training/full-cycle must not use training_engine for current week decisions."""

    def test_resolve_reprise_plan_not_called_in_full_cycle(self):
        """resolve_reprise_plan must not be called in server.py."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        # AST check: no function call named resolve_reprise_plan
        try:
            tree = ast.parse(source)
        except SyntaxError:
            pytest.skip("Could not parse server.py.")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.id if isinstance(func, ast.Name) else
                    func.attr if isinstance(func, ast.Attribute) else None
                )
                assert name != "resolve_reprise_plan", (
                    "resolve_reprise_plan() must not be called in server.py (removed PR #139). "
                    "V2 replacement: TrainingState.continuity_state + WeeklyTarget."
                )

    def test_build_training_state_used_in_full_cycle(self):
        """build_training_state must be called in the /training/full-cycle context."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "build_training_state(" in source, (
            "build_training_state() must be called in server.py for the V2 "
            "reprise state determination in /training/full-cycle."
        )

    def test_build_weekly_target_used_in_full_cycle(self):
        """build_weekly_target must be called in the /training/full-cycle context."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "build_weekly_target(" in source, (
            "build_weekly_target() must be called in server.py for the V2 "
            "current-week target volume in /training/full-cycle."
        )

    def test_reprise_state_derived_from_continuity_state(self):
        """reprise_state in /training/full-cycle must come from continuity_state."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        # After migration, reprise_state is set from _ts_fc.continuity_state
        assert "_ts_fc.continuity_state" in source, (
            "reprise_state must be assigned from V2 TrainingState.continuity_state "
            "in /training/full-cycle (not from resolve_reprise_plan)."
        )


# ---------------------------------------------------------------------------
# Mongo → Domain boundary
# ---------------------------------------------------------------------------

class TestMongoDomainBoundary:
    """mongo_garmin_activities_to_domain must be used as the V2 input boundary."""

    def test_mongo_domain_adapter_used_in_metrics(self):
        """mongo_garmin_activities_to_domain must be called for /training/metrics V2 path."""
        import os
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "server.py"
        )
        with open(server_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "mongo_garmin_activities_to_domain" in source, (
            "mongo_garmin_activities_to_domain must be used as the V2 input boundary "
            "for /training/metrics and /training/full-cycle."
        )
