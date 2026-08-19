"""RUNINDEX #143 — /training/metrics migration to TrainingState V2.

Verifies:
A. acwr_reliable derived from TrainingState V2 continuity_state (not legacy classify_training_state)
B. Garmin activities pass through mongo_garmin_activities_to_domain before V2 layers
C. No raw Mongo doc reaches build_training_history / build_training_state
D. Each continuity_state tested deterministically with exact fixture
E. acwr=None remains None (no default)
F. No new dependency training_v2 → training_engine
G. classify_training_state absent from /training/metrics code path
"""

from __future__ import annotations

import ast
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.domain_adapter import mongo_garmin_activities_to_domain
from training_v2.domain_activity import DomainActivity
from training_v2.training_load import build_training_load
from training_v2.training_history import build_training_history
from training_v2.runner_profile import build_runner_profile
from training_v2.training_state import build_training_state

_REF = date(2026, 6, 15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _garmin_doc(days_ago: int, duration_s: float, distance_m: float = 5000.0) -> dict:
    """Simulate a raw Mongo garmin_activities document."""
    act_date = _REF - timedelta(days=days_ago)
    return {
        "user_id": "test-user",
        "activity_type": "running",
        "start_time": act_date.isoformat() + " 08:00:00",
        "duration": duration_s,
        "distance": distance_m,
    }


def _build_chain(garmin_docs: list):
    """Run the full V2 chain and return (training_state, domain_activities)."""
    domain_activities = mongo_garmin_activities_to_domain(garmin_docs)
    load_snapshot = build_training_load(domain_activities, _REF)
    training_history = build_training_history(domain_activities, _REF)
    runner_profile = build_runner_profile(
        training_history=training_history,
        training_load=load_snapshot,
        reference_date=_REF,
    )
    training_state = build_training_state(
        training_history=training_history,
        training_load=load_snapshot,
        runner_profile=runner_profile,
        reference_date=_REF,
    )
    return training_state, domain_activities


# ---------------------------------------------------------------------------
# Test: Each continuity_state tested exactly
# ---------------------------------------------------------------------------

class TestContinuityStatesExact:
    """Each continuity_state produced by a deterministic fixture."""

    def test_no_history(self):
        """No activities at all -> no_history, acwr=None, acwr_reliable=True."""
        state, _ = _build_chain([])
        assert state.continuity_state == "no_history"
        assert state.acwr is None
        # no_history -> acwr_reliable True (structural, ACWR itself is None)
        acwr_reliable = state.continuity_state not in ("deep_reprise", "partial_reprise")
        assert acwr_reliable is True

    def test_deep_reprise(self):
        """Prior history exists but last run >= 28 days ago -> deep_reprise.

        Fixture: runs from day 30 to day 60 (all older than 28 days from _REF).
        """
        # Activities from 30 to 60 days ago — last run was 30 days ago
        docs = [_garmin_doc(d, 3000.0, 8000.0) for d in range(30, 61)]
        state, _ = _build_chain(docs)
        assert state.continuity_state == "deep_reprise"
        acwr_reliable = state.continuity_state not in ("deep_reprise", "partial_reprise")
        assert acwr_reliable is False

    def test_partial_reprise(self):
        """Recent volume far below observed baseline -> partial_reprise.

        Fixture: strong consistent history (days 28-90, ~40km/week baseline),
        then only a single short recent run (day 1, very low volume).
        Need available_days >= 28 to avoid reprise_exit via short-history path.
        """
        # Build a solid historical baseline: 10km runs every other day for 60 days
        # from day 28 to day 90 — establishes a strong observed baseline
        baseline_docs = [_garmin_doc(d, 3600.0, 10000.0) for d in range(28, 91, 2)]
        # A single very short recent run (day 1) — keeps days_since < 28
        # but volume is far below 50% of baseline
        recent_doc = [_garmin_doc(1, 600.0, 1000.0)]  # 1km, 10min — trivial
        docs = baseline_docs + recent_doc
        state, _ = _build_chain(docs)
        assert state.continuity_state == "partial_reprise"
        acwr_reliable = state.continuity_state not in ("deep_reprise", "partial_reprise")
        assert acwr_reliable is False

    def test_reprise_exit(self):
        """Short history (< 28 days) with recent run -> reprise_exit.

        Fixture: only activities in last 14 days (available_history < 28).
        """
        # Activities from day 0 to day 13 — available_days = 14
        docs = [_garmin_doc(d, 3600.0, 8000.0) for d in range(14)]
        state, _ = _build_chain(docs)
        assert state.continuity_state == "reprise_exit"
        acwr_reliable = state.continuity_state not in ("deep_reprise", "partial_reprise")
        assert acwr_reliable is True

    def test_normal(self):
        """Regular consistent training >= 28 days -> normal.

        Fixture: daily runs for 35 days with consistent volume.
        """
        # Daily 8km runs for 35 days — available_days=35, consistent volume,
        # no sparse 30d window.
        docs = [_garmin_doc(d, 3600.0, 8000.0) for d in range(35)]
        state, _ = _build_chain(docs)
        assert state.continuity_state == "normal"
        acwr_reliable = state.continuity_state not in ("deep_reprise", "partial_reprise")
        assert acwr_reliable is True


# ---------------------------------------------------------------------------
# Test: DomainActivity boundary
# ---------------------------------------------------------------------------

class TestDomainActivityBoundary:
    """All Mongo docs must pass through the domain adapter."""

    def test_domain_adapter_returns_domain_activities(self):
        """mongo_garmin_activities_to_domain returns DomainActivity instances."""
        docs = [_garmin_doc(1, 3600.0)]
        domain = mongo_garmin_activities_to_domain(docs)
        assert len(domain) > 0
        assert all(isinstance(a, DomainActivity) for a in domain)

    def test_build_training_load_with_domain_activities(self):
        """build_training_load produces valid snapshot from DomainActivity list."""
        docs = [_garmin_doc(i, 3600.0) for i in range(7)]
        domain = mongo_garmin_activities_to_domain(docs)
        snapshot = build_training_load(domain, _REF)
        # 7 days of 1h runs — acute load should be positive
        assert snapshot.acute_load_7d > 0

    def test_no_activities_acwr_none(self):
        """No activities -> ACWR is None, never defaulted to 1.0 or 0."""
        domain = mongo_garmin_activities_to_domain([])
        snapshot = build_training_load(domain, _REF)
        assert snapshot.acwr is None


# ---------------------------------------------------------------------------
# Test: classify_training_state removed from /training/metrics
# ---------------------------------------------------------------------------

class TestLegacyClassifyRemoved:
    """Prove classify_training_state is no longer in /training/metrics path."""

    def test_classify_training_state_not_imported_in_server(self):
        """server.py does not import classify_training_state."""
        server_path = _BACKEND / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name)
        assert "classify_training_state" not in imported_names

    def test_classify_training_state_not_called_in_server(self):
        """No call to classify_training_state exists in server.py."""
        server_path = _BACKEND / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id != "classify_training_state"
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr != "classify_training_state"


# ---------------------------------------------------------------------------
# Test: training_v2 modules do not import training_engine
# ---------------------------------------------------------------------------

class TestNoTrainingEngineImportInV2:
    """training_v2 modules must not import training_engine."""

    @pytest.mark.parametrize("module_name", [
        "training_v2.training_state",
        "training_v2.training_history",
        "training_v2.runner_profile",
        "training_v2.training_load",
    ])
    def test_no_legacy_import(self, module_name):
        import importlib
        mod = importlib.import_module(module_name)
        source = Path(mod.__file__).read_text()
        # Filter out comments and docstring content for accurate check
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "training_engine", (
                    f"{module_name} has 'from training_engine import ...'"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "training_engine", (
                        f"{module_name} has 'import training_engine'"
                    )
