"""Tests for the canonical ReadinessDecision layer."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.readiness import ReadinessConfidence, ReadinessResult  # noqa: E402
from training_v2.readiness_decision import (  # noqa: E402
    ReadinessBand,
    build_readiness_decision,
)
from training_v2.readiness_sufficiency import ReasonCode, SufficiencyLevel  # noqa: E402


def _readiness(
    score: float | None,
    *,
    confidence: ReadinessConfidence = ReadinessConfidence.NORMAL,
    sufficiency_level: SufficiencyLevel = SufficiencyLevel.SUFFICIENT,
    reasons: tuple[ReasonCode, ...] = (),
) -> ReadinessResult:
    return ReadinessResult(
        score=score,
        confidence=confidence,
        sufficiency_level=sufficiency_level,
        reasons=reasons,
    )


def test_A_none_readiness_is_unavailable():
    decision = build_readiness_decision(None)
    assert decision.band == ReadinessBand.UNAVAILABLE
    assert decision.score is None
    assert decision.reason_codes == ("READINESS_UNAVAILABLE",)


def test_B_score_none_is_unavailable():
    decision = build_readiness_decision(
        _readiness(
            None,
            confidence=ReadinessConfidence.NONE,
            sufficiency_level=SufficiencyLevel.SUFFICIENT,
        )
    )
    assert decision.band == ReadinessBand.UNAVAILABLE


def test_C_insufficient_with_score_none_is_unavailable():
    decision = build_readiness_decision(
        _readiness(
            None,
            confidence=ReadinessConfidence.NONE,
            sufficiency_level=SufficiencyLevel.INSUFFICIENT,
        )
    )
    assert decision.band == ReadinessBand.UNAVAILABLE
    assert decision.sufficiency_level == SufficiencyLevel.INSUFFICIENT


def test_D_score_90_is_favorable():
    assert build_readiness_decision(_readiness(90.0)).band == ReadinessBand.FAVORABLE


def test_E_score_75_is_favorable():
    assert build_readiness_decision(_readiness(75.0)).band == ReadinessBand.FAVORABLE


def test_F_score_74_9_is_caution():
    assert build_readiness_decision(_readiness(74.9)).band == ReadinessBand.CAUTION


def test_G_score_55_is_caution():
    assert build_readiness_decision(_readiness(55.0)).band == ReadinessBand.CAUTION


def test_H_score_54_9_is_low():
    assert build_readiness_decision(_readiness(54.9)).band == ReadinessBand.LOW


def test_I_score_40_is_low():
    assert build_readiness_decision(_readiness(40.0)).band == ReadinessBand.LOW


def test_J_score_39_9_is_very_low():
    assert build_readiness_decision(_readiness(39.9)).band == ReadinessBand.VERY_LOW


def test_K_score_0_is_very_low():
    decision = build_readiness_decision(_readiness(0.0))
    assert decision.band == ReadinessBand.VERY_LOW
    assert decision.score == 0.0


def test_L_degraded_with_score_preserves_metadata_and_calculates_band():
    decision = build_readiness_decision(
        _readiness(
            60.0,
            confidence=ReadinessConfidence.REDUCED,
            sufficiency_level=SufficiencyLevel.DEGRADED,
            reasons=(ReasonCode.missing_sleep,),
        )
    )
    assert decision.band == ReadinessBand.CAUTION
    assert decision.sufficiency_level == SufficiencyLevel.DEGRADED
    assert decision.confidence == ReadinessConfidence.REDUCED
    assert decision.readiness_reasons == (ReasonCode.missing_sleep,)


def test_M_same_inputs_same_result():
    readiness = _readiness(
        60.0,
        confidence=ReadinessConfidence.REDUCED,
        sufficiency_level=SufficiencyLevel.DEGRADED,
        reasons=(ReasonCode.thin_load_history,),
    )
    first = build_readiness_decision(readiness)
    second = build_readiness_decision(readiness)
    assert first == second
