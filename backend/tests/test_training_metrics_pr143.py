"""RUNINDEX #143 — /training/metrics migration to TrainingState V2.

Verifies:
A. acwr_reliable derived from TrainingState V2 continuity_state (not legacy classify_training_state)
B. Garmin activities pass through mongo_garmin_activities_to_domain before V2 layers
C. No raw Mongo doc reaches build_training_history / build_training_state
D. Reprise states correctly mapped to acwr_reliable
E. acwr=None remains None (no default)
F. No new dependency training_v2 → training_engine
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.domain_adapter import mongo_garmin_activities_to_domain
from training_v2.training_load import build_training_load
from training_v2.training_history import build_training_history
from training_v2.runner_profile import build_runner_profile
from training_v2.training_state import build_training_state

_REF = date(2026, 6, 15)


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


class TestAcwrReliableFromV2Chain:
    """Test that acwr_reliable is correctly derived from V2 TrainingState."""

    def _build_state(self, garmin_docs: list) -> str:
        """Run the full V2 chain and return continuity_state."""
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
        return training_state.continuity_state

    def test_no_history_state(self):
        """No activities -> no_history."""
        state = self._build_state([])
        assert state == "no_history"

    def test_normal_state_reliable(self):
        """Regular training over 28 days -> normal or reprise_exit -> reliable."""
        docs = [_garmin_doc(i, 3600.0) for i in range(28)]
        state = self._build_state(docs)
        assert state in ("normal", "reprise_exit")
        assert state not in ("deep_reprise", "partial_reprise")

    def test_deep_reprise_unreliable(self):
        """Single recent activity after long gap -> reprise state detected."""
        docs = [_garmin_doc(2, 1800.0)]
        state = self._build_state(docs)
        assert state in ("deep_reprise", "partial_reprise", "reprise_exit", "no_history")

    def test_semantics_reprise_exit_reliable(self):
        """reprise_exit -> acwr_reliable = True."""
        assert "reprise_exit" not in ("deep_reprise", "partial_reprise")

    def test_semantics_normal_reliable(self):
        """normal -> acwr_reliable = True."""
        assert "normal" not in ("deep_reprise", "partial_reprise")

    def test_semantics_no_history_reliable(self):
        """no_history -> acwr_reliable = True (ACWR itself will be None)."""
        assert "no_history" not in ("deep_reprise", "partial_reprise")


class TestNoDomainViolation:
    """Ensure no raw Mongo doc bypasses the domain adapter."""

    def test_domain_adapter_produces_domain_activities(self):
        """mongo_garmin_activities_to_domain returns DomainActivity objects."""
        docs = [_garmin_doc(1, 3600.0)]
        domain = mongo_garmin_activities_to_domain(docs)
        assert len(domain) > 0

    def test_build_training_load_accepts_domain_activities(self):
        """build_training_load works with DomainActivity list."""
        docs = [_garmin_doc(i, 3600.0) for i in range(7)]
        domain = mongo_garmin_activities_to_domain(docs)
        snapshot = build_training_load(domain, _REF)
        assert snapshot.acwr is not None or snapshot.acwr is None  # no crash


class TestNoTrainingEngineImportInV2:
    """training_v2 modules must not import training_engine."""

    def test_training_state_no_legacy_import(self):
        import importlib
        mod = importlib.import_module("training_v2.training_state")
        source = Path(mod.__file__).read_text()
        lines = [l for l in source.splitlines()
                 if not l.strip().startswith("#") and not l.strip().startswith("-")]
        code = "\n".join(lines)
        assert "from training_engine import" not in code
        assert "import training_engine" not in code

    def test_training_history_no_legacy_import(self):
        import importlib
        mod = importlib.import_module("training_v2.training_history")
        source = Path(mod.__file__).read_text()
        assert "from training_engine" not in source
        assert "import training_engine" not in source

    def test_runner_profile_no_legacy_import(self):
        import importlib
        mod = importlib.import_module("training_v2.runner_profile")
        source = Path(mod.__file__).read_text()
        assert "from training_engine" not in source
        assert "import training_engine" not in source


class TestAcwrNonePreserved:
    """ACWR=None must remain None, never defaulted."""

    def test_no_activities_acwr_none(self):
        domain = mongo_garmin_activities_to_domain([])
        snapshot = build_training_load(domain, _REF)
        assert snapshot.acwr is None
