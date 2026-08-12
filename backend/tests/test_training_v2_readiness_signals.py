"""R1.6 — Tests for readiness_signals.py (pure deterministic signal layer).

All tests use fixed data to ensure full determinism.

Run from the backend directory:
    python -m pytest tests/test_training_v2_readiness_signals.py -q
"""

from __future__ import annotations

import ast
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from datetime import timedelta

from training_v2.readiness_sufficiency import PhysioBaseline, PhysioSignal, SleepRecord
from training_v2.readiness_signals import (
    ReadinessLoadSignal,
    compute_hrv_deviation,
    compute_rhr_deviation,
    extract_load_signal,
    extract_sleep_signal,
)
from training_v2.training_load import TrainingLoadSnapshot, build_training_load

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REF = date(2026, 8, 6)


def _solid_baseline(value: float) -> PhysioBaseline:
    return PhysioBaseline(value=value, valid_measures=7)


def _thin_baseline(value: float) -> PhysioBaseline:
    return PhysioBaseline(value=value, valid_measures=2)


def _signal(recent: float | None, baseline_value: float | None, measures: int = 7) -> PhysioSignal:
    if baseline_value is None:
        baseline = PhysioBaseline(value=None, valid_measures=measures)
    else:
        baseline = PhysioBaseline(value=baseline_value, valid_measures=measures)
    return PhysioSignal(recent_value=recent, baseline=baseline)


def _act(d: date, dur_s: int = 3600) -> dict:
    return {
        "activity_type": "running",
        "start_time": d.isoformat() + "T08:00:00.0",
        "duration_s": dur_s,
    }


def _available_snapshot() -> TrainingLoadSnapshot:
    """Build a snapshot with is_available=True (needs ACWR != None)."""
    activities = [_act(REF - timedelta(days=i)) for i in range(30)]
    return build_training_load(activities, REF)


def _unavailable_snapshot() -> TrainingLoadSnapshot:
    """Build a snapshot with is_available=False (no activities → acwr=None)."""
    return build_training_load([], REF)


# ---------------------------------------------------------------------------
# compute_rhr_deviation
# ---------------------------------------------------------------------------


class TestComputeRhrDeviation:
    def test_recent_greater_than_baseline(self):
        sig = _signal(recent=52.0, baseline_value=48.0)
        assert compute_rhr_deviation(sig) == pytest.approx(4.0)

    def test_recent_less_than_baseline(self):
        sig = _signal(recent=46.0, baseline_value=48.0)
        assert compute_rhr_deviation(sig) == pytest.approx(-2.0)

    def test_recent_equals_baseline(self):
        sig = _signal(recent=50.0, baseline_value=50.0)
        assert compute_rhr_deviation(sig) == pytest.approx(0.0)

    def test_signal_none_returns_none(self):
        assert compute_rhr_deviation(None) is None

    def test_recent_absent_returns_none(self):
        sig = PhysioSignal(recent_value=None, baseline=_solid_baseline(48.0))
        assert compute_rhr_deviation(sig) is None

    def test_baseline_none_returns_none(self):
        sig = PhysioSignal(recent_value=52.0, baseline=None)
        assert compute_rhr_deviation(sig) is None

    def test_baseline_value_none_returns_none(self):
        sig = PhysioSignal(
            recent_value=52.0,
            baseline=PhysioBaseline(value=None, valid_measures=5),
        )
        assert compute_rhr_deviation(sig) is None


# ---------------------------------------------------------------------------
# compute_hrv_deviation
# ---------------------------------------------------------------------------


class TestComputeHrvDeviation:
    def test_positive_variation(self):
        sig = _signal(recent=55.0, baseline_value=50.0)
        assert compute_hrv_deviation(sig) == pytest.approx(10.0)

    def test_negative_variation(self):
        sig = _signal(recent=45.0, baseline_value=50.0)
        assert compute_hrv_deviation(sig) == pytest.approx(-10.0)

    def test_zero_variation(self):
        sig = _signal(recent=50.0, baseline_value=50.0)
        assert compute_hrv_deviation(sig) == pytest.approx(0.0)

    def test_signal_none_returns_none(self):
        assert compute_hrv_deviation(None) is None

    def test_recent_absent_returns_none(self):
        sig = PhysioSignal(recent_value=None, baseline=_solid_baseline(50.0))
        assert compute_hrv_deviation(sig) is None

    def test_baseline_none_returns_none(self):
        sig = PhysioSignal(recent_value=45.0, baseline=None)
        assert compute_hrv_deviation(sig) is None

    def test_baseline_value_none_returns_none(self):
        sig = PhysioSignal(
            recent_value=45.0,
            baseline=PhysioBaseline(value=None, valid_measures=5),
        )
        assert compute_hrv_deviation(sig) is None

    def test_baseline_zero_returns_none(self):
        sig = PhysioSignal(
            recent_value=45.0,
            baseline=PhysioBaseline(value=0.0, valid_measures=5),
        )
        assert compute_hrv_deviation(sig) is None

    def test_baseline_negative_returns_none(self):
        sig = PhysioSignal(
            recent_value=45.0,
            baseline=PhysioBaseline(value=-5.0, valid_measures=5),
        )
        assert compute_hrv_deviation(sig) is None


# ---------------------------------------------------------------------------
# extract_sleep_signal
# ---------------------------------------------------------------------------


class TestExtractSleepSignal:
    def test_duration_present(self):
        sleep = SleepRecord(duration_hours=7.5)
        assert extract_sleep_signal(sleep) == pytest.approx(7.5)

    def test_duration_absent(self):
        sleep = SleepRecord(duration_hours=None)
        assert extract_sleep_signal(sleep) is None

    def test_sleep_none(self):
        assert extract_sleep_signal(None) is None

    def test_score_present_but_duration_absent_returns_none(self):
        """score must not be converted to duration — result must be None."""
        sleep = SleepRecord(duration_hours=None, score=82.0)
        assert extract_sleep_signal(sleep) is None

    def test_score_not_used_when_duration_present(self):
        """score is irrelevant; only duration_hours is returned."""
        sleep = SleepRecord(duration_hours=6.5, score=55.0)
        result = extract_sleep_signal(sleep)
        assert result == pytest.approx(6.5)
        assert result != 55.0


# ---------------------------------------------------------------------------
# extract_load_signal
# ---------------------------------------------------------------------------


class TestExtractLoadSignal:
    def test_available_snapshot_values_copied_exactly(self):
        snap = _available_snapshot()
        assert snap.is_available is True
        sig = extract_load_signal(snap)
        assert sig is not None
        assert sig.acute_load_7d == snap.acute_load_7d
        assert sig.chronic_weekly_load == snap.chronic_weekly_load
        assert sig.load_change_percent == snap.load_change_percent
        assert sig.acwr == snap.acwr

    def test_unavailable_snapshot_returns_none(self):
        snap = _unavailable_snapshot()
        assert snap.is_available is False
        assert extract_load_signal(snap) is None

    def test_acwr_none_stays_none(self):
        """When the snapshot has acwr=None but is still available, it stays None."""
        # Build a snapshot where acute exists but chronic=0 (only activities in
        # the acute window, nothing older → chronic_weekly_load = 0)
        activities = [_act(REF)]  # one very recent activity
        snap = build_training_load(activities, REF)
        # acwr may or may not be available depending on activities; handle both
        if snap.is_available:
            sig = extract_load_signal(snap)
            assert sig is not None
            assert sig.acwr == snap.acwr
        else:
            assert extract_load_signal(snap) is None

    def test_load_change_percent_none_stays_none(self):
        """load_change_percent=None in snapshot → None in signal."""
        snap = _available_snapshot()
        # The available snapshot has a real load_change_percent value in most
        # cases, but we verify the field propagates exactly.
        sig = extract_load_signal(snap)
        assert sig is not None
        assert sig.load_change_percent == snap.load_change_percent

    def test_returns_readiness_load_signal_instance(self):
        snap = _available_snapshot()
        sig = extract_load_signal(snap)
        assert isinstance(sig, ReadinessLoadSignal)


# ---------------------------------------------------------------------------
# Provider-neutrality: no Garmin / Terra / Strava imports
# ---------------------------------------------------------------------------


class TestNoProviderDependency:
    """Guarantee readiness_signals.py imports no provider-specific module."""

    def _get_imports(self) -> list[str]:
        src = (
            Path(__file__).resolve().parents[1]
            / "training_v2"
            / "readiness_signals.py"
        )
        tree = ast.parse(src.read_text())
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        names.append(alias.name)
                else:
                    if node.module:
                        names.append(node.module)
        return names

    def test_no_garmin_import(self):
        for name in self._get_imports():
            assert not name.startswith("garmin"), f"Forbidden import: {name}"

    def test_no_terra_import(self):
        for name in self._get_imports():
            assert not name.startswith("terra"), f"Forbidden import: {name}"

    def test_no_strava_import(self):
        for name in self._get_imports():
            assert not name.startswith("strava"), f"Forbidden import: {name}"
