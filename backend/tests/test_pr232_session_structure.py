"""PR232 — Training UX V3: unit tests for training_v2.session_structure.

Pure function tests (no DB, no FastAPI): build_session_blocks() must never
fabricate a pace, must decompose quality/long_easy sessions into a readable
warmup/main/recovery/cooldown (or segment) breakdown, and must return None
for rest / unknown sessions.

Run from the backend directory:
    python -m pytest tests/test_pr232_session_structure.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET_KEY", "test-pr232-session-structure-32ch!")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from training_v2.session_structure import build_session_blocks  # noqa: E402
from training_v2.training_paces import (  # noqa: E402
    PaceRange,
    PaceValue,
    TrainingPaces,
    VdotResult,
)


def _paces(confidence: str = "HIGH") -> TrainingPaces:
    if confidence == "INSUFFICIENT":
        vr = VdotResult(
            reference_vdot=None, paces_confidence="INSUFFICIENT", evidence_count=0,
            high_count=0, medium_count=0, concordant=False, reason="none",
        )
        return TrainingPaces(
            reference_date=date(2025, 1, 1), vdot_result=vr, confidence="INSUFFICIENT",
            easy=None, marathon=None, threshold=None, interval=None, repetition=None,
            reason="insufficient",
        )
    vr = VdotResult(
        reference_vdot=50.0, paces_confidence=confidence, evidence_count=2,
        high_count=2, medium_count=0, concordant=True, reason="ok",
    )
    easy = PaceRange(
        lower=PaceValue(min_per_km=6.25, km_per_hour=9.6),
        upper=PaceValue(min_per_km=6.6, km_per_hour=9.1),
    )
    marathon = PaceValue(min_per_km=5.6, km_per_hour=10.7)
    threshold = PaceValue(min_per_km=5.15, km_per_hour=11.6)
    return TrainingPaces(
        reference_date=date(2025, 1, 1), vdot_result=vr, confidence=confidence,
        easy=easy, marathon=marathon, threshold=threshold, interval=None,
        repetition=None, reason="ok",
    )


def test_rest_session_has_no_blocks():
    assert build_session_blocks(
        workout_type="rest", distance_km=None, duration_minutes=None, paces=_paces(),
    ) is None


def test_unknown_workout_type_has_no_blocks():
    assert build_session_blocks(
        workout_type=None, distance_km=5.0, duration_minutes=None, paces=_paces(),
    ) is None


def test_simple_easy_session_is_a_single_block_with_easy_pace():
    blocks = build_session_blocks(
        workout_type="easy", distance_km=7.0, duration_minutes=None, paces=_paces(),
    )
    assert blocks is not None
    assert len(blocks) == 1
    block = blocks[0]
    assert block.label == "main"
    assert block.distance_km == 7.0
    assert block.repetitions is None
    assert block.pace is not None
    assert block.pace.lower.min_per_km == 6.25
    assert block.pace.upper.min_per_km == 6.6


def test_quality_session_has_warmup_main_reps_recovery_cooldown():
    blocks = build_session_blocks(
        workout_type="quality", distance_km=9.0, duration_minutes=None, paces=_paces(),
    )
    assert blocks is not None
    labels = [b.label for b in blocks]
    assert labels == ["warmup", "main", "recovery", "cooldown"]

    warmup, main, recovery, cooldown = blocks
    assert warmup.distance_km == 2.0
    assert warmup.pace is not None

    # 9 - 2 (warmup) - 1 (cooldown) = 6 km main -> 3 reps of 2 km @ threshold.
    assert main.repetitions == 3
    assert main.distance_km == 2.0
    assert main.pace is not None
    assert main.pace.lower.min_per_km == 5.15
    assert main.pace.upper.min_per_km > main.pace.lower.min_per_km

    assert recovery.distance_km is None
    assert recovery.duration_minutes == 2.0
    assert recovery.pace is None

    assert cooldown.distance_km == 1.0
    assert cooldown.pace is not None


def test_short_quality_session_falls_back_to_single_main_block():
    blocks = build_session_blocks(
        workout_type="quality", distance_km=3.0, duration_minutes=None, paces=_paces(),
    )
    assert blocks is not None
    assert len(blocks) == 1
    assert blocks[0].label == "main"
    assert blocks[0].distance_km == 3.0


def test_long_run_below_threshold_is_a_single_easy_block():
    blocks = build_session_blocks(
        workout_type="long_easy", distance_km=12.0, duration_minutes=None, paces=_paces(),
    )
    assert blocks is not None
    assert len(blocks) == 1
    assert blocks[0].label == "main"
    assert blocks[0].distance_km == 12.0
    assert blocks[0].pace is not None


def test_long_run_above_threshold_has_three_ordered_segments():
    blocks = build_session_blocks(
        workout_type="long_easy", distance_km=18.0, duration_minutes=None, paces=_paces(),
    )
    assert blocks is not None
    assert len(blocks) == 3
    assert [b.label for b in blocks] == ["segment", "segment", "segment"]
    assert [b.order for b in blocks] == [0, 1, 2]

    lead, sustained, cooldown = blocks
    # Sums to the total distance (within rounding).
    assert round(lead.distance_km + sustained.distance_km + cooldown.distance_km, 1) == 18.0
    # Middle segment is faster (marathon pace) than the lead/cooldown easy segments.
    assert sustained.pace.lower.min_per_km < lead.pace.lower.min_per_km
    assert sustained.pace.lower.min_per_km < cooldown.pace.lower.min_per_km


def test_insufficient_paces_never_fabricates_a_pace():
    blocks = build_session_blocks(
        workout_type="quality", distance_km=9.0, duration_minutes=None, paces=_paces("INSUFFICIENT"),
    )
    assert blocks is not None
    assert all(b.pace is None for b in blocks)
    # Structure (reps, distances) is still meaningful even without a pace.
    assert blocks[1].repetitions == 3


def test_none_paces_object_never_fabricates_a_pace():
    blocks = build_session_blocks(
        workout_type="easy", distance_km=7.0, duration_minutes=None, paces=None,
    )
    assert blocks is not None
    assert blocks[0].pace is None


def test_duration_based_session_without_distance_has_no_km_split():
    blocks = build_session_blocks(
        workout_type="easy", distance_km=None, duration_minutes=45, paces=_paces(),
    )
    assert blocks is not None
    assert len(blocks) == 1
    assert blocks[0].distance_km is None
    assert blocks[0].duration_minutes == 45
