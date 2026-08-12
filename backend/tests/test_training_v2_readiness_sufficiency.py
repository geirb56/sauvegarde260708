"""R1 — Tests for ReadinessSufficiency (deterministic sufficiency layer).

All tests use a fixed reference_date of 2026-08-06 to ensure full
determinism — no datetime.now() is called anywhere.

Run from the backend directory:
    python -m pytest tests/test_training_v2_readiness_sufficiency.py -q
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2.readiness_sufficiency import (
    PhysioBaseline,
    PhysioSignal,
    ReasonCode,
    ReadinessSufficiency,
    ReadinessSufficiencyInput,
    SleepRecord,
    SufficiencyLevel,
    build_readiness_sufficiency,
)
from training_v2.training_load import TrainingLoadSnapshot, build_training_load

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REF = date(2026, 8, 6)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_snapshot(confidence: str) -> TrainingLoadSnapshot:
    """Build a synthetic TrainingLoadSnapshot with the desired confidence level.

    We construct the snapshot by passing activities that produce the right
    confidence level, using the same build_training_load logic as production.
    """

    def _act(d: date, dur_s: int = 3600) -> dict:
        return {
            "activity_type": "running",
            "start_time": d.isoformat() + "T08:00:00.0",
            "distance": 10000,
            "duration": dur_s,
        }

    if confidence == "none":
        # No activities at all → confidence = "none"
        return build_training_load([], REF)

    if confidence == "low":
        # 1 activity 3 days ago → history_depth < 14 days → "low"
        return build_training_load([_act(REF - timedelta(days=3))], REF)

    if confidence == "medium":
        # Activities spanning 20 days → 14 ≤ days < 28 → "medium"
        activities = [
            _act(REF - timedelta(days=d))
            for d in range(0, 21, 3)
        ]
        return build_training_load(activities, REF)

    if confidence == "high":
        # Activities spanning >= 28 days → "high"
        activities = [
            _act(REF - timedelta(days=d))
            for d in range(0, 30, 3)
        ]
        return build_training_load(activities, REF)

    raise ValueError(f"Unknown confidence level: {confidence}")


def _solid_rhr(value: float = 58.0, measures: int = 7) -> PhysioSignal:
    return PhysioSignal(
        recent_value=value,
        baseline=PhysioBaseline(valid_measures=measures),
    )


def _solid_hrv(value: float = 45.0, measures: int = 6) -> PhysioSignal:
    return PhysioSignal(
        recent_value=value,
        baseline=PhysioBaseline(valid_measures=measures),
    )


def _thin_rhr(value: float = 58.0, measures: int = 3) -> PhysioSignal:
    return PhysioSignal(
        recent_value=value,
        baseline=PhysioBaseline(valid_measures=measures),
    )


def _thin_hrv(value: float = 45.0, measures: int = 2) -> PhysioSignal:
    return PhysioSignal(
        recent_value=value,
        baseline=PhysioBaseline(valid_measures=measures),
    )


def _absent_signal() -> None:
    return None


def _sleep() -> SleepRecord:
    return SleepRecord()


def _build(
    rhr: PhysioSignal | None,
    hrv: PhysioSignal | None,
    sleep: SleepRecord | None,
    load_confidence: str,
) -> ReadinessSufficiency:
    inp = ReadinessSufficiencyInput(
        rhr=rhr,
        hrv=hrv,
        sleep=sleep,
        load=_load_snapshot(load_confidence),
    )
    return build_readiness_sufficiency(inp)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAllAvailable:
    """All signals present and solid → SUFFICIENT with no reasons."""

    def test_sufficient_no_reasons(self):
        result = _build(_solid_rhr(), _solid_hrv(), _sleep(), "high")
        assert result.level == SufficiencyLevel.SUFFICIENT
        assert result.reasons == []

    def test_sufficient_medium_load(self):
        result = _build(_solid_rhr(), _solid_hrv(), _sleep(), "medium")
        assert result.level == SufficiencyLevel.SUFFICIENT
        assert result.reasons == []


class TestHRVAbsentRHRSolid:
    """HRV absent but RHR exploitable → SUFFICIENT + missing_hrv."""

    def test_sufficient_with_missing_hrv(self):
        result = _build(_solid_rhr(), _absent_signal(), _sleep(), "high")
        assert result.level == SufficiencyLevel.SUFFICIENT
        assert ReasonCode.missing_hrv in result.reasons
        assert ReasonCode.missing_rhr not in result.reasons
        assert ReasonCode.missing_physio not in result.reasons

    def test_missing_hrv_medium_load(self):
        result = _build(_solid_rhr(), _absent_signal(), _sleep(), "medium")
        assert result.level == SufficiencyLevel.SUFFICIENT
        assert ReasonCode.missing_hrv in result.reasons


class TestRHRAbsentHRVSolid:
    """RHR absent but HRV exploitable → SUFFICIENT + missing_rhr."""

    def test_sufficient_with_missing_rhr(self):
        result = _build(_absent_signal(), _solid_hrv(), _sleep(), "high")
        assert result.level == SufficiencyLevel.SUFFICIENT
        assert ReasonCode.missing_rhr in result.reasons
        assert ReasonCode.missing_hrv not in result.reasons
        assert ReasonCode.missing_physio not in result.reasons

    def test_missing_rhr_medium_load(self):
        result = _build(_absent_signal(), _solid_hrv(), _sleep(), "medium")
        assert result.level == SufficiencyLevel.SUFFICIENT
        assert ReasonCode.missing_rhr in result.reasons


class TestBothPhysioAbsent:
    """Both HRV and RHR absent → INSUFFICIENT + missing_physio."""

    def test_insufficient_missing_physio(self):
        result = _build(_absent_signal(), _absent_signal(), _sleep(), "high")
        assert result.level == SufficiencyLevel.INSUFFICIENT
        assert ReasonCode.missing_physio in result.reasons
        assert ReasonCode.missing_hrv in result.reasons
        assert ReasonCode.missing_rhr in result.reasons

    def test_missing_physio_with_bad_load(self):
        result = _build(_absent_signal(), _absent_signal(), _sleep(), "none")
        assert result.level == SufficiencyLevel.INSUFFICIENT
        assert ReasonCode.missing_physio in result.reasons
        assert ReasonCode.missing_load in result.reasons


class TestSleepAbsent:
    """Sleep absent with solid physio → DEGRADED + missing_sleep."""

    def test_degraded_missing_sleep(self):
        result = _build(_solid_rhr(), _solid_hrv(), None, "high")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.missing_sleep in result.reasons
        assert ReasonCode.missing_physio not in result.reasons

    def test_degraded_missing_sleep_one_signal(self):
        result = _build(_solid_rhr(), _absent_signal(), None, "high")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.missing_sleep in result.reasons
        assert ReasonCode.missing_hrv in result.reasons


class TestLoadAbsent:
    """No exploitable load → INSUFFICIENT + missing_load."""

    def test_insufficient_missing_load(self):
        result = _build(_solid_rhr(), _solid_hrv(), _sleep(), "none")
        assert result.level == SufficiencyLevel.INSUFFICIENT
        assert ReasonCode.missing_load in result.reasons
        assert ReasonCode.missing_physio not in result.reasons


class TestThinBaselineRHR:
    """RHR baseline < 5 measures → DEGRADED + thin_baseline_rhr."""

    def test_degraded_thin_rhr_baseline(self):
        result = _build(_thin_rhr(), _solid_hrv(), _sleep(), "high")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.thin_baseline_rhr in result.reasons

    def test_degraded_thin_rhr_no_hrv(self):
        result = _build(_thin_rhr(), _absent_signal(), _sleep(), "high")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.thin_baseline_rhr in result.reasons
        assert ReasonCode.missing_hrv in result.reasons

    def test_not_thin_rhr_when_exactly_5(self):
        rhr = PhysioSignal(recent_value=58.0, baseline=PhysioBaseline(valid_measures=5))
        result = _build(rhr, _solid_hrv(), _sleep(), "high")
        assert result.level == SufficiencyLevel.SUFFICIENT
        assert ReasonCode.thin_baseline_rhr not in result.reasons


class TestThinBaselineHRV:
    """HRV baseline < 5 measures → DEGRADED + thin_baseline_hrv."""

    def test_degraded_thin_hrv_baseline(self):
        result = _build(_solid_rhr(), _thin_hrv(), _sleep(), "high")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.thin_baseline_hrv in result.reasons

    def test_degraded_thin_hrv_no_rhr(self):
        result = _build(_absent_signal(), _thin_hrv(), _sleep(), "high")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.thin_baseline_hrv in result.reasons
        assert ReasonCode.missing_rhr in result.reasons

    def test_not_thin_hrv_when_exactly_5(self):
        hrv = PhysioSignal(recent_value=45.0, baseline=PhysioBaseline(valid_measures=5))
        result = _build(_solid_rhr(), hrv, _sleep(), "high")
        assert result.level == SufficiencyLevel.SUFFICIENT
        assert ReasonCode.thin_baseline_hrv not in result.reasons


class TestThinLoadHistory:
    """Load history < 14 days → DEGRADED + thin_load_history."""

    def test_degraded_thin_load_history(self):
        result = _build(_solid_rhr(), _solid_hrv(), _sleep(), "low")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.thin_load_history in result.reasons


class TestMultipleAnomalies:
    """Multiple anomalies → cumulative, deterministic reasons."""

    def test_missing_sleep_and_thin_load(self):
        result = _build(_solid_rhr(), _solid_hrv(), None, "low")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.missing_sleep in result.reasons
        assert ReasonCode.thin_load_history in result.reasons

    def test_missing_sleep_thin_rhr_baseline_thin_load(self):
        result = _build(_thin_rhr(), _solid_hrv(), None, "low")
        assert result.level == SufficiencyLevel.DEGRADED
        reasons = result.reasons
        assert ReasonCode.missing_sleep in reasons
        assert ReasonCode.thin_baseline_rhr in reasons
        assert ReasonCode.thin_load_history in reasons

    def test_reasons_are_sorted(self):
        result = _build(_thin_rhr(), _absent_signal(), None, "low")
        assert result.reasons == sorted(result.reasons, key=lambda r: r.value)

    def test_reasons_are_deduplicated(self):
        result = _build(_thin_rhr(), _absent_signal(), None, "low")
        assert len(result.reasons) == len(set(result.reasons))

    def test_physio_absent_load_absent_sleep_absent(self):
        result = _build(_absent_signal(), _absent_signal(), None, "none")
        assert result.level == SufficiencyLevel.INSUFFICIENT
        reasons = result.reasons
        assert ReasonCode.missing_physio in reasons
        assert ReasonCode.missing_load in reasons
        assert ReasonCode.missing_sleep in reasons
        assert ReasonCode.missing_rhr in reasons
        assert ReasonCode.missing_hrv in reasons

    def test_missing_hrv_thin_rhr_sleep_ok(self):
        """HRV absent, RHR present with thin baseline → DEGRADED due to thin RHR."""
        result = _build(_thin_rhr(), _absent_signal(), _sleep(), "high")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.missing_hrv in result.reasons
        assert ReasonCode.thin_baseline_rhr in result.reasons

    def test_missing_rhr_thin_hrv_sleep_ok(self):
        """RHR absent, HRV present with thin baseline → DEGRADED due to thin HRV."""
        result = _build(_absent_signal(), _thin_hrv(), _sleep(), "high")
        assert result.level == SufficiencyLevel.DEGRADED
        assert ReasonCode.missing_rhr in result.reasons
        assert ReasonCode.thin_baseline_hrv in result.reasons


class TestExactlyEightReasonCodes:
    """Confirm there are exactly 8 distinct reason codes in the enum."""

    def test_eight_reason_codes(self):
        all_codes = set(ReasonCode)
        assert len(all_codes) == 8
        expected = {
            ReasonCode.missing_hrv,
            ReasonCode.missing_rhr,
            ReasonCode.missing_physio,
            ReasonCode.missing_sleep,
            ReasonCode.missing_load,
            ReasonCode.thin_baseline_rhr,
            ReasonCode.thin_baseline_hrv,
            ReasonCode.thin_load_history,
        }
        assert all_codes == expected


class TestNoNeutralValues:
    """The engine must not fabricate neutral values for absent signals."""

    def test_absent_rhr_stays_none(self):
        inp = ReadinessSufficiencyInput(
            rhr=None,
            hrv=_solid_hrv(),
            sleep=_sleep(),
            load=_load_snapshot("high"),
        )
        assert inp.rhr is None

    def test_absent_hrv_stays_none(self):
        inp = ReadinessSufficiencyInput(
            rhr=_solid_rhr(),
            hrv=None,
            sleep=_sleep(),
            load=_load_snapshot("high"),
        )
        assert inp.hrv is None

    def test_absent_sleep_stays_none(self):
        inp = ReadinessSufficiencyInput(
            rhr=_solid_rhr(),
            hrv=_solid_hrv(),
            sleep=None,
            load=_load_snapshot("high"),
        )
        assert inp.sleep is None

    def test_result_has_no_score_field(self):
        result = _build(_solid_rhr(), _solid_hrv(), _sleep(), "high")
        assert not hasattr(result, "score")
        assert not hasattr(result, "readiness_score")
        assert not hasattr(result, "value")
