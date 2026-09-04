"""C232 (correction) — tests for training_v2.session_structure.

BLOCKER FIXED: session_structure.py no longer fabricates interval/segment
structure (warmup/reps/recovery/cooldown for "quality", a marathon-pace
progression for "long_easy"). It only resolves a single, honest pace ZONE
for the whole session, and only for workout_types whose Daniels mapping is
unambiguous and literal (easy/recovery/long_easy — the entire session is,
by definition, run at Easy pace). "quality" (exact nature undecided by the
Training Engine) and "steady" (not in the Daniels vocabulary) never get a
fabricated pace.
"""

from __future__ import annotations

from datetime import date

import pytest

from training_v2.session_structure import resolve_session_pace_zone
from training_v2.training_paces import (
    PaceRange,
    PaceValue,
    TrainingPaces,
    VdotResult,
)


def _paces(*, easy=True, marathon=True, threshold=True) -> TrainingPaces:
    easy_range = (
        PaceRange(
            lower=PaceValue(min_per_km=5.5, km_per_hour=10.9),
            upper=PaceValue(min_per_km=6.2, km_per_hour=9.7),
        )
        if easy
        else None
    )
    marathon_value = PaceValue(min_per_km=5.0, km_per_hour=12.0) if marathon else None
    threshold_value = PaceValue(min_per_km=4.6, km_per_hour=13.0) if threshold else None
    return TrainingPaces(
        reference_date=date(2026, 8, 25),
        vdot_result=VdotResult(
            reference_vdot=50.0,
            paces_confidence="high",
            evidence_count=1,
            high_count=1,
            medium_count=0,
            concordant=True,
            reason="test fixture",
        ),
        confidence="HIGH",
        easy=easy_range,
        marathon=marathon_value,
        threshold=threshold_value,
        interval=None,
        repetition=None,
        reason="test fixture",
    )


def _insufficient_paces() -> TrainingPaces:
    return TrainingPaces(
        reference_date=date(2026, 8, 25),
        vdot_result=VdotResult(
            reference_vdot=None,
            paces_confidence="insufficient",
            evidence_count=0,
            high_count=0,
            medium_count=0,
            concordant=False,
            reason="test fixture",
        ),
        confidence="INSUFFICIENT",
        easy=None,
        marathon=None,
        threshold=None,
        interval=None,
        repetition=None,
        reason="test fixture",
    )


class TestNoFabricatedSplits:
    """#1/#2/#3 of the C232 mandatory test list."""

    def test_quality_never_gets_a_pace_zone_regardless_of_distance(self):
        # #1 — quality without a canonical structure: no repetition/warmup/
        # recovery invented, and — per the correction — no pace zone either,
        # since the engine has not decided quality's exact nature.
        paces = _paces()
        for distance_km in (2.0, 9.0, 21.0, None):
            assert resolve_session_pace_zone(workout_type="quality", paces=paces) is None

    def test_long_easy_never_gets_a_marathon_segment_pace(self):
        # #2 — long_easy without a canonical structure: no marathon-pace
        # segment invented. The zone resolved (if any) must be the Easy
        # pace range, never the Marathon PaceValue.
        paces = _paces()
        zone = resolve_session_pace_zone(workout_type="long_easy", paces=paces)
        assert zone == paces.easy
        assert zone != paces.marathon

    def test_no_ux_constant_creates_a_physiological_prescription(self):
        # #3 — the module exposes no calibration constants for warmup
        # length, rep length, recovery minutes, or long-run fractions.
        import training_v2.session_structure as module

        forbidden_names = (
            "_QUALITY_WARMUP_KM",
            "_QUALITY_REP_LENGTH_KM",
            "_QUALITY_RECOVERY_MINUTES",
            "_QUALITY_COOLDOWN_KM",
            "_QUALITY_MAX_REPS",
            "_LONG_RUN_LEAD_FRACTION",
            "_LONG_RUN_SUSTAINED_FRACTION",
            "_LONG_RUN_COOLDOWN_FRACTION",
            "SessionBlock",
            "build_session_blocks",
        )
        for name in forbidden_names:
            assert not hasattr(module, name), f"{name} must not exist (fabricated split constant)"


class TestWholeSessionEasyPaceTypes:
    def test_easy_gets_the_whole_session_easy_pace(self):
        paces = _paces()
        assert resolve_session_pace_zone(workout_type="easy", paces=paces) == paces.easy

    def test_recovery_gets_the_whole_session_easy_pace(self):
        paces = _paces()
        assert resolve_session_pace_zone(workout_type="recovery", paces=paces) == paces.easy

    def test_long_easy_gets_the_whole_session_easy_pace(self):
        paces = _paces()
        assert resolve_session_pace_zone(workout_type="long_easy", paces=paces) == paces.easy


class TestNoPaceZoneCategories:
    def test_steady_has_no_pace_zone(self):
        paces = _paces()
        assert resolve_session_pace_zone(workout_type="steady", paces=paces) is None

    def test_rest_has_no_pace_zone(self):
        paces = _paces()
        assert resolve_session_pace_zone(workout_type="rest", paces=paces) is None

    def test_unknown_workout_type_has_no_pace_zone(self):
        paces = _paces()
        assert resolve_session_pace_zone(workout_type="some_future_type", paces=paces) is None

    def test_none_workout_type_has_no_pace_zone(self):
        paces = _paces()
        assert resolve_session_pace_zone(workout_type=None, paces=paces) is None


class TestNoFallbackFabrication:
    def test_none_paces_never_fabricates_a_zone(self):
        # #8 — INSUFFICIENT (paces=None passed by the caller): pace stays
        # None, no fallback invented, even for an otherwise-eligible type.
        assert resolve_session_pace_zone(workout_type="easy", paces=None) is None
        assert resolve_session_pace_zone(workout_type="long_easy", paces=None) is None

    def test_insufficient_confidence_easy_field_is_none_so_zone_is_none(self):
        paces = _insufficient_paces()
        assert resolve_session_pace_zone(workout_type="easy", paces=paces) is None
        assert resolve_session_pace_zone(workout_type="long_easy", paces=paces) is None

    def test_missing_easy_pace_field_never_falls_back_to_another_zone(self):
        paces = _paces(easy=False)
        assert resolve_session_pace_zone(workout_type="easy", paces=paces) is None
        assert resolve_session_pace_zone(workout_type="long_easy", paces=paces) is None
