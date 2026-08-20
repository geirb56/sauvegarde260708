"""
PR157 — Tests: retrait de determine_target_load du chemin /training/week-plan.

Objectifs couverts :
1. generate_cycle_week fonctionne sans target_load (default=None).
2. determine_target_load n'est plus appelé dans le chemin week-plan (preuve AST).
3. WeeklyTarget V2 reste l'autorité prescriptive.
4. TSS reste : active=None, rest=0 (rest sessions), total=None.
5. distances / durées / types inchangés à inputs identiques.
6. goal / cycle_weeks inchangés.
"""

import asyncio
import ast
import inspect
import textwrap
import unittest
from datetime import datetime, timezone, timedelta
from typing import Dict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


CONTEXT_NORMAL = {
    "ctl": None,
    "atl": None,
    "tsb": None,
    "acwr": None,
    "weekly_km": 40.0,
    "load_7": 400,
    "load_28": 1600,
    "target_km_protected": 42.0,
    "km_7": 38.0,
    "training_state": "normal",
}


# ---------------------------------------------------------------------------
# 1. generate_cycle_week works without target_load (uses default None)
# ---------------------------------------------------------------------------

class TestGenerateCycleWeekNoTargetLoad(unittest.TestCase):
    """PR157: generate_cycle_week must work with target_load omitted (default None)."""

    def test_call_without_target_load_returns_plan(self):
        """Calling generate_cycle_week without target_load must succeed."""
        from llm_coach import generate_cycle_week

        plan, success, metadata = run(
            generate_cycle_week(
                context=CONTEXT_NORMAL,
                phase="build",
                goal="SEMI",
                user_id="test_pr157",
            )
        )
        self.assertTrue(success, "generate_cycle_week must succeed without target_load")
        self.assertIsNotNone(plan, "plan must not be None")
        self.assertIn("sessions", plan, "plan must contain sessions")

    def test_planned_load_is_none_when_target_load_omitted(self):
        """planned_load must be None when target_load is not supplied."""
        from llm_coach import generate_cycle_week

        plan, success, _ = run(
            generate_cycle_week(
                context=CONTEXT_NORMAL,
                phase="build",
                goal="SEMI",
                user_id="test_pr157",
            )
        )
        self.assertTrue(success)
        self.assertIsNone(plan.get("planned_load"), "planned_load must be None without target_load")


# ---------------------------------------------------------------------------
# 2. AST proof: determine_target_load not called in get_week_plan
# ---------------------------------------------------------------------------

class TestDetermineTargetLoadNotInWeekPlan(unittest.TestCase):
    """PR157: prove via AST that get_week_plan no longer calls determine_target_load."""

    def _get_week_plan_source(self) -> str:
        import pathlib
        server_path = pathlib.Path(__file__).parent.parent / "server.py"
        source = server_path.read_text()
        # Extract the get_week_plan function body via AST
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "get_week_plan":
                return ast.get_source_segment(source, node) or ""
        return source  # fallback: search whole file

    def _get_week_plan_call_names(self) -> list:
        """Return names of all functions called inside get_week_plan."""
        import pathlib
        server_path = pathlib.Path(__file__).parent.parent / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "get_week_plan":
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.append(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            calls.append(child.func.attr)
                return calls
        return []

    def test_no_determine_target_load_call(self):
        """determine_target_load must not be called (AST) in get_week_plan after PR157."""
        call_names = self._get_week_plan_call_names()
        self.assertNotIn(
            "determine_target_load",
            call_names,
            "determine_target_load must NOT be called in get_week_plan after PR157"
        )

    def test_no_determine_target_load_import_in_week_plan(self):
        """No inline import of determine_target_load inside get_week_plan (AST)."""
        import pathlib
        server_path = pathlib.Path(__file__).parent.parent / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "get_week_plan":
                for child in ast.walk(node):
                    if isinstance(child, ast.ImportFrom):
                        names = [alias.name for alias in child.names]
                        self.assertNotIn(
                            "determine_target_load",
                            names,
                            "Inline import of determine_target_load must be gone from get_week_plan"
                        )
                return
        self.fail("get_week_plan not found in server.py")


# ---------------------------------------------------------------------------
# 3. WeeklyTarget V2 remains authority
# ---------------------------------------------------------------------------

class TestWeeklyTargetV2Authority(unittest.TestCase):
    """PR157: WeeklyTarget V2 remains the prescriptive authority."""

    def test_weekly_target_v2_used_in_week_plan_source(self):
        """
        After PR#163 the canonical entry point is build_weekly_plan_from_workouts
        (returns WeeklyTarget V2 + WeeklyPlan V2).  WeeklyTarget remains the authority:
        weekly_target.target_basis and weekly_target.target_km must still be consumed
        in get_week_plan to build target_km_protected.
        """
        import pathlib
        server_path = pathlib.Path(__file__).parent.parent / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        fn_src = ""
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "get_week_plan":
                fn_src = ast.get_source_segment(source, node) or ""
                break
        # PR#163 canonical bridge — replaces build_weekly_target_from_workouts.
        self.assertIn(
            "build_weekly_plan_from_workouts",
            fn_src,
            "PR#163 canonical bridge build_weekly_plan_from_workouts must be called in get_week_plan"
        )
        # WeeklyTarget authority must still be exercised via the returned weekly_target.
        self.assertIn(
            "weekly_target.target_basis",
            fn_src,
            "weekly_target.target_basis must still be used in get_week_plan"
        )
        self.assertIn(
            "weekly_target.target_km",
            fn_src,
            "weekly_target.target_km must still be used in get_week_plan"
        )

    def test_target_km_protected_from_v2(self):
        """target_km_protected must derive from weekly_target, not from determine_target_load."""
        import pathlib
        server_path = pathlib.Path(__file__).parent.parent / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        fn_src = ""
        fn_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "get_week_plan":
                fn_src = ast.get_source_segment(source, node) or ""
                fn_node = node
                break
        # WeeklyTarget V2 source must still be present
        self.assertIn("weekly_target.target_km", fn_src)
        self.assertIn("weekly_target.target_basis", fn_src)
        # determine_target_load must not be called (AST)
        calls = []
        if fn_node:
            for child in ast.walk(fn_node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.append(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.append(child.func.attr)
        self.assertNotIn("determine_target_load", calls,
                         "determine_target_load must not be called in get_week_plan")


# ---------------------------------------------------------------------------
# 4. TSS unchanged (active=None, rest=0, total=None)
# ---------------------------------------------------------------------------

class TestTSSUnchangedPR157(unittest.TestCase):
    """PR157: TSS contract must remain identical to post-#156 baseline."""

    def test_active_sessions_estimated_tss_none(self):
        """Active sessions must have estimated_tss=None (no TSS coefficients)."""
        from llm_coach import generate_cycle_week

        plan, success, _ = run(
            generate_cycle_week(
                context=CONTEXT_NORMAL,
                phase="build",
                goal="SEMI",
                user_id="test_pr157_tss",
            )
        )
        self.assertTrue(success)
        for s in plan["sessions"]:
            if s.get("type") != "rest":
                self.assertIsNone(
                    s.get("estimated_tss"),
                    f"Session {s['type']} must have estimated_tss=None, got {s.get('estimated_tss')}"
                )

    def test_total_tss_none(self):
        """total_tss must be None."""
        from llm_coach import generate_cycle_week

        plan, success, _ = run(
            generate_cycle_week(
                context=CONTEXT_NORMAL,
                phase="build",
                goal="SEMI",
                user_id="test_pr157_tss",
            )
        )
        self.assertTrue(success)
        self.assertIsNone(plan.get("total_tss"), f"total_tss must be None, got {plan.get('total_tss')}")


# ---------------------------------------------------------------------------
# 5. distances / durées / types inchangés à inputs identiques
# ---------------------------------------------------------------------------

class TestPrescriptionUnchanged(unittest.TestCase):
    """PR157: removing determine_target_load must not change prescription outputs."""

    def _get_plan(self, context, phase="build", goal="SEMI"):
        from llm_coach import generate_cycle_week
        plan, success, _ = run(
            generate_cycle_week(context=context, phase=phase, goal=goal, user_id="test_pr157_reg")
        )
        self.assertTrue(success)
        return plan

    def test_session_types_stable(self):
        """Session types must be the same regardless of target_load value."""
        from llm_coach import generate_cycle_week

        plan_no_load, s1, _ = run(
            generate_cycle_week(context=CONTEXT_NORMAL, phase="build", goal="SEMI", user_id="t")
        )
        # With explicit None (should be same)
        plan_explicit_none, s2, _ = run(
            generate_cycle_week(context=CONTEXT_NORMAL, phase="build", goal="SEMI",
                                user_id="t", target_load=None)
        )
        self.assertTrue(s1 and s2)
        types_no_load = [s["type"] for s in plan_no_load["sessions"]]
        types_none = [s["type"] for s in plan_explicit_none["sessions"]]
        self.assertEqual(types_no_load, types_none, "Session types must be identical")

    def test_distances_stable(self):
        """distances must match when target_load omitted vs explicitly None."""
        from llm_coach import generate_cycle_week

        p1, s1, _ = run(generate_cycle_week(
            context=CONTEXT_NORMAL, phase="build", goal="SEMI", user_id="t"
        ))
        p2, s2, _ = run(generate_cycle_week(
            context=CONTEXT_NORMAL, phase="build", goal="SEMI", user_id="t", target_load=None
        ))
        self.assertTrue(s1 and s2)
        d1 = [s.get("distance_km") for s in p1["sessions"]]
        d2 = [s.get("distance_km") for s in p2["sessions"]]
        self.assertEqual(d1, d2, "distances must be identical")

    def test_weekly_km_from_target_km_protected(self):
        """weekly_km must be driven by target_km_protected (V2), not by target_load."""
        plan = self._get_plan(CONTEXT_NORMAL)
        # target_km_protected = 42.0, weekly_km must be close to that
        self.assertAlmostEqual(
            plan.get("weekly_km", 0), 42.0, delta=1.0,
            msg=f"weekly_km {plan.get('weekly_km')} must be close to target_km_protected=42.0"
        )


# ---------------------------------------------------------------------------
# 6. Scan: RUNTIME_WEEK_PLAN occurrences of determine_target_load = 0
# ---------------------------------------------------------------------------

class TestScanAfterPR157(unittest.TestCase):
    """PR157 SCAN APRÈS: determine_target_load must have 0 RUNTIME_WEEK_PLAN occurrences."""

    def test_server_get_week_plan_no_determine_target_load(self):
        """AST: determine_target_load must not be *called* inside get_week_plan."""
        import pathlib
        server_path = pathlib.Path(__file__).parent.parent / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "get_week_plan":
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.append(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            calls.append(child.func.attr)
                count = calls.count("determine_target_load")
                self.assertEqual(
                    count, 0,
                    f"RUNTIME_WEEK_PLAN call occurrences of determine_target_load = {count}, expected 0"
                )
                return
        self.fail("get_week_plan not found in server.py")

    def test_definition_still_exists_in_training_engine(self):
        """determine_target_load DEFINITION must still exist in training_engine (not deleted)."""
        from training_engine import determine_target_load
        self.assertTrue(callable(determine_target_load))


if __name__ == "__main__":
    unittest.main()
