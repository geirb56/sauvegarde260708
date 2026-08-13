"""R2B — Tests for Readiness Final Aggregation V2.

Covers:
- SUFFICIENT: full aggregation, NORMAL confidence.
- DEGRADED: renormalized weights, REDUCED confidence.
- INSUFFICIENT: score=None, NONE confidence.
- Defensive case: no subscores despite SUFFICIENT/DEGRADED level.
- Reason code propagation.
- Architecture invariants (determinism, bounds, rounding, no I/O, no legacy).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root or backend directory.
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from training_v2.readiness import (
    PRODUCT_CALIBRATION_V1_WEIGHT_LOAD,
    PRODUCT_CALIBRATION_V1_WEIGHT_PHYSIO,
    PRODUCT_CALIBRATION_V1_WEIGHT_SLEEP,
    ReadinessConfidence,
    ReadinessResult,
    build_readiness_result,
)
from training_v2.readiness_subscores import LoadSubscore, PhysioSubscore, SleepSubscore
from training_v2.readiness_sufficiency import (
    ReasonCode,
    ReadinessSufficiency,
    SufficiencyLevel,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _suf(level: SufficiencyLevel, reasons: list[ReasonCode] | None = None) -> ReadinessSufficiency:
    return ReadinessSufficiency(level=level, reasons=sorted(reasons or []))


def _physio(score: float | None) -> PhysioSubscore:
    return PhysioSubscore(score=score, rhr_component=None, hrv_component=None)


def _sleep(score: float | None) -> SleepSubscore:
    return SleepSubscore(score=score)


def _load(score: float | None) -> LoadSubscore:
    return LoadSubscore(score=score)


# ---------------------------------------------------------------------------
# CAS 1 — INSUFFICIENT
# ---------------------------------------------------------------------------


class TestInsufficient:
    def test_score_is_none(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.INSUFFICIENT, [ReasonCode.missing_physio, ReasonCode.missing_load]),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert result.score is None

    def test_confidence_is_none(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.INSUFFICIENT, [ReasonCode.missing_physio]),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert result.confidence == ReadinessConfidence.NONE

    def test_reasons_propagated(self):
        reasons_in = [ReasonCode.missing_physio, ReasonCode.missing_load]
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.INSUFFICIENT, reasons_in),
            physio=None,
            sleep=None,
            load=None,
        )
        assert set(result.reasons) == set(reasons_in)

    def test_no_subscores_still_none(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.INSUFFICIENT),
            physio=None,
            sleep=None,
            load=None,
        )
        assert result.score is None
        assert result.confidence == ReadinessConfidence.NONE

    def test_score_never_zero_by_default(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.INSUFFICIENT),
            physio=None,
            sleep=None,
            load=None,
        )
        assert result.score != 0

    def test_sufficiency_level_propagated(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.INSUFFICIENT),
            physio=None,
            sleep=None,
            load=None,
        )
        assert result.sufficiency_level == SufficiencyLevel.INSUFFICIENT


# ---------------------------------------------------------------------------
# CAS 2 — SUFFICIENT
# ---------------------------------------------------------------------------


class TestSufficient:
    def test_nominal_80_90_70(self):
        # (80×40 + 90×30 + 70×30) / 100 = 80.0
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert result.score == 80.0
        assert result.confidence == ReadinessConfidence.NORMAL

    def test_all_100(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(100),
            sleep=_sleep(100),
            load=_load(100),
        )
        assert result.score == 100.0

    def test_all_0(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(0),
            sleep=_sleep(0),
            load=_load(0),
        )
        assert result.score == 0.0

    def test_confidence_normal(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert result.confidence == ReadinessConfidence.NORMAL

    def test_sufficiency_level_propagated(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert result.sufficiency_level == SufficiencyLevel.SUFFICIENT

    def test_reasons_empty(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert result.reasons == []


# ---------------------------------------------------------------------------
# CAS 2b — SUFFICIENT + sous-score(s) manquant(s) → REDUCED
# ---------------------------------------------------------------------------


class TestSufficientWithMissingSubscores:
    def test_sufficient_sleep_none(self):
        # physio=80, sleep=None, load=70
        # (80×40 + 70×30) / (40+30) = (3200+2100)/70 = 5300/70 ≈ 75.714... → 75.7
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(None),
            load=_load(70),
        )
        assert result.score == 75.7
        assert result.confidence == ReadinessConfidence.REDUCED
        assert result.sufficiency_level == SufficiencyLevel.SUFFICIENT

    def test_sufficient_load_none(self):
        # physio=80, sleep=90, load=None
        # (80×40 + 90×30) / (40+30) = (3200+2700)/70 = 5900/70 ≈ 84.285... → 84.3
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(None),
        )
        assert result.score == 84.3
        assert result.confidence == ReadinessConfidence.REDUCED
        assert result.sufficiency_level == SufficiencyLevel.SUFFICIENT

    def test_sufficient_physio_none(self):
        # physio=None, sleep=90, load=80
        # (90×30 + 80×30) / (30+30) = (2700+2400)/60 = 5100/60 = 85.0
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(None),
            sleep=_sleep(90),
            load=_load(80),
        )
        assert result.score == 85.0
        assert result.confidence == ReadinessConfidence.REDUCED
        assert result.sufficiency_level == SufficiencyLevel.SUFFICIENT

    def test_sufficient_all_available_still_normal(self):
        # All three subscores present → NORMAL (regression guard)
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert result.confidence == ReadinessConfidence.NORMAL

    def test_sufficient_no_subscores_none_confidence(self):
        # No usable subscores → NONE (defensive, regression guard)
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(None),
            sleep=_sleep(None),
            load=_load(None),
        )
        assert result.score is None
        assert result.confidence == ReadinessConfidence.NONE


# ---------------------------------------------------------------------------
# CAS 3 — DEGRADED
# ---------------------------------------------------------------------------


class TestDegraded:
    def test_sleep_absent(self):
        # physio=70, sleep=None, load=80
        # (70×40 + 80×30) / (40+30) = (2800+2400)/70 = 5200/70 ≈ 74.285... → 74.3
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.DEGRADED, [ReasonCode.missing_sleep]),
            physio=_physio(70),
            sleep=_sleep(None),
            load=_load(80),
        )
        assert result.score == 74.3
        assert result.confidence == ReadinessConfidence.REDUCED

    def test_physio_absent(self):
        # sleep=90, load=80 — physio absent
        # (90×30 + 80×30) / (30+30) = (2700+2400)/60 = 5100/60 = 85.0
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.DEGRADED),
            physio=_physio(None),
            sleep=_sleep(90),
            load=_load(80),
        )
        assert result.score == 85.0
        assert result.confidence == ReadinessConfidence.REDUCED

    def test_load_absent(self):
        # physio=80, sleep=90 — load absent
        # (80×40 + 90×30) / (40+30) = (3200+2700)/70 = 5900/70 ≈ 84.285... → 84.3
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.DEGRADED),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(None),
        )
        assert result.score == 84.3
        assert result.confidence == ReadinessConfidence.REDUCED

    def test_reasons_propagated(self):
        reasons_in = [ReasonCode.missing_sleep, ReasonCode.thin_load_history]
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.DEGRADED, reasons_in),
            physio=_physio(70),
            sleep=_sleep(None),
            load=_load(80),
        )
        assert set(result.reasons) == set(reasons_in)

    def test_sufficiency_level_propagated(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.DEGRADED),
            physio=_physio(70),
            sleep=_sleep(None),
            load=_load(80),
        )
        assert result.sufficiency_level == SufficiencyLevel.DEGRADED


# ---------------------------------------------------------------------------
# Defensive case — no usable subscores despite SUFFICIENT/DEGRADED
# ---------------------------------------------------------------------------


class TestDefensive:
    def test_sufficient_no_subscores(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(None),
            sleep=_sleep(None),
            load=_load(None),
        )
        assert result.score is None
        assert result.confidence == ReadinessConfidence.NONE

    def test_degraded_no_subscores(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.DEGRADED),
            physio=None,
            sleep=None,
            load=None,
        )
        assert result.score is None
        assert result.confidence == ReadinessConfidence.NONE

    def test_score_never_zero_when_no_subscores(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(None),
            sleep=_sleep(None),
            load=_load(None),
        )
        assert result.score != 0


# ---------------------------------------------------------------------------
# Architecture invariants
# ---------------------------------------------------------------------------


class TestArchitectureInvariants:
    def test_deterministic(self):
        """Same inputs always produce identical outputs."""
        kwargs = dict(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        r1 = build_readiness_result(**kwargs)
        r2 = build_readiness_result(**kwargs)
        assert r1 == r2

    def test_score_bounded_0_100_lower(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(0),
            sleep=_sleep(0),
            load=_load(0),
        )
        assert result.score is not None
        assert result.score >= 0.0

    def test_score_bounded_0_100_upper(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(100),
            sleep=_sleep(100),
            load=_load(100),
        )
        assert result.score is not None
        assert result.score <= 100.0

    def test_score_rounded_1_decimal(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.DEGRADED),
            physio=_physio(70),
            sleep=_sleep(None),
            load=_load(80),
        )
        assert result.score is not None
        # Must have at most 1 decimal place.
        assert result.score == round(result.score, 1)

    def test_result_is_immutable(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        with pytest.raises(Exception):
            result.score = 999  # type: ignore[misc]

    def test_confidence_is_enum_not_numeric(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert isinstance(result.confidence, ReadinessConfidence)
        assert not isinstance(result.confidence, (int, float))

    def test_no_recommendation_field(self):
        result = build_readiness_result(
            sufficiency=_suf(SufficiencyLevel.SUFFICIENT),
            physio=_physio(80),
            sleep=_sleep(90),
            load=_load(70),
        )
        assert not hasattr(result, "recommendation")
        assert not hasattr(result, "status")
        assert not hasattr(result, "color")

    def test_r2a_unchanged(self):
        """Importing R2A module should still work and produce same results."""
        from training_v2.readiness_subscores import (
            LoadSubscore,
            PhysioSubscore,
            SleepSubscore,
            build_load_subscore,
            build_physio_subscore,
            build_sleep_subscore,
        )
        assert LoadSubscore is not None
        assert PhysioSubscore is not None
        assert SleepSubscore is not None
        assert build_load_subscore is not None
        assert build_physio_subscore is not None
        assert build_sleep_subscore is not None

    def test_imports_r1_valid(self):
        from training_v2.readiness_sufficiency import (
            ReasonCode,
            ReadinessSufficiency,
            SufficiencyLevel,
            build_readiness_sufficiency,
        )
        assert SufficiencyLevel.SUFFICIENT is not None

    def test_no_datetime_now_in_module(self):
        """Source code must not call datetime.now() in executable code."""
        module_path = Path(__file__).resolve().parent.parent / "training_v2" / "readiness.py"
        source = module_path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for datetime.now() or datetime.datetime.now()
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "now":
                    pytest.fail("datetime.now() call found in readiness.py executable code")

    def test_no_io_in_module(self):
        """Source code must not import db/http libraries."""
        module_path = Path(__file__).resolve().parent.parent / "training_v2" / "readiness.py"
        source = module_path.read_text()
        for forbidden in ("import requests", "import httpx", "import motor", "import pymongo", "import sqlalchemy"):
            assert forbidden not in source, f"Found forbidden import: {forbidden}"

    def test_no_legacy_formulas_in_module(self):
        """Source code must not import from legacy engine or garmin insights."""
        module_path = Path(__file__).resolve().parent.parent / "training_v2" / "readiness.py"
        source = module_path.read_text()
        assert "readiness_engine" not in source
        assert "garmin.insights" not in source

    def test_weight_constants_present(self):
        assert PRODUCT_CALIBRATION_V1_WEIGHT_PHYSIO == 40.0
        assert PRODUCT_CALIBRATION_V1_WEIGHT_SLEEP == 30.0
        assert PRODUCT_CALIBRATION_V1_WEIGHT_LOAD == 30.0

    def test_weight_sum_100(self):
        total = (
            PRODUCT_CALIBRATION_V1_WEIGHT_PHYSIO
            + PRODUCT_CALIBRATION_V1_WEIGHT_SLEEP
            + PRODUCT_CALIBRATION_V1_WEIGHT_LOAD
        )
        assert total == 100.0
