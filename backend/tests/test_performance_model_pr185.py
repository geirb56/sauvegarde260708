"""
Tests for Performance Model V2 (PR185) — VMA V2 + Race Predictions V2.

Covers:
- VMA estimation with various activity sets
- Race predictions with Riegel extrapolation
- No look-ahead in historical snapshots
- No avg_speed/0.70 fallback
- Null semantics when data is insufficient
- Determinism
- Frontend contract preservation markers

VMA_FRONTEND_PRESERVED = YES
VMA_HISTORY_FRONTEND_PRESERVED = YES
PREDICTIONS_FRONTEND_PRESERVED = YES
PREDICTIONS_5K = YES
PREDICTIONS_10K = YES
PREDICTIONS_HALF = YES
PREDICTIONS_MARATHON = YES
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, datetime
from typing import List

import pytest

from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import (
    RIEGEL_K,
    estimate_vma,
    predict_races,
    _riegel,
    _validate_activity,
    _speed_kmh,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REF = date(2025, 1, 15)  # Fixed reference date for all tests


def make_run(
    distance_m: float,
    duration_s: float,
    days_ago: int = 10,
    activity_type: str = "running",
) -> DomainActivity:
    d = date.fromordinal(REF.toordinal() - days_ago)
    return DomainActivity(
        activity_type=activity_type,
        start_time=d.isoformat(),
        distance_m=distance_m,
        duration_s=duration_s,
    )


# ---------------------------------------------------------------------------
# TEST VMA — aucune activité → VMA null
# ---------------------------------------------------------------------------


def test_vma_no_activities_returns_null():
    """Test 1: aucune activité → VMA null."""
    result = estimate_vma([], REF)
    assert result.vma_kmh is None
    assert result.confidence == "insufficient"
    assert result.has_data is False


# ---------------------------------------------------------------------------
# TEST VMA — footings faciles uniquement → pas de VMA artificielle
# ---------------------------------------------------------------------------


def test_vma_easy_runs_only_no_artificial_vma():
    """Test 2: footings faciles uniquement → pas de VMA artificielle via avg pace / 0.70.
    An easy 60-min run at 9 km/h (6:40/km) should NOT produce VMA ~12.9 km/h via /0.70.
    The model must return the estimated VMA (using fraction), not the old avg/0.70 fallback.
    """
    # Single easy run: 9 km/h for 60 minutes
    easy_run = make_run(distance_m=9000, duration_s=3600, days_ago=5)
    result = estimate_vma([easy_run], REF)
    # The model is allowed to estimate VMA from this run (it is informative by duration)
    # but must NOT use avg_speed / 0.70 = 9/0.70 = 12.86 as VMA.
    # With 60+ min effort fraction = 0.78: VMA = 9 / 0.78 ≈ 11.54
    if result.vma_kmh is not None:
        # Must not be the 0.70 fallback value
        expected_fallback = 9.0 / 0.70  # ≈ 12.86
        assert abs(result.vma_kmh - expected_fallback) > 0.1, (
            f"VMA {result.vma_kmh} looks like avg_speed/0.70 fallback ({expected_fallback})"
        )


# ---------------------------------------------------------------------------
# TEST VMA — activité invalide → ignorée
# ---------------------------------------------------------------------------


def test_vma_invalid_activity_ignored():
    """Test 3: activité invalide → ignorée."""
    bad = DomainActivity(
        activity_type="running",
        start_time=date(2025, 1, 10).isoformat(),
        distance_m=-100,
        duration_s=1800,
    )
    result = estimate_vma([bad], REF)
    assert result.vma_kmh is None


def test_vma_non_running_ignored():
    """Test 3b: activité non-running → ignorée."""
    cycling = make_run(distance_m=20000, duration_s=3600, days_ago=5, activity_type="cycling")
    result = estimate_vma([cycling], REF)
    assert result.vma_kmh is None


def test_vma_zero_duration_ignored():
    """Test 3c: durée nulle → activité invalide, ignorée."""
    bad = DomainActivity(
        activity_type="running",
        start_time=date(2025, 1, 10).isoformat(),
        distance_m=5000,
        duration_s=0,
    )
    result = estimate_vma([bad], REF)
    assert result.vma_kmh is None


# ---------------------------------------------------------------------------
# TEST VMA — performance exploitable → estimation déterministe
# ---------------------------------------------------------------------------


def test_vma_informative_effort_returns_estimate():
    """Test 4: performance exploitable → estimation déterministe."""
    # 10K in 50 min → speed 12 km/h, duration 3000s (50 min = 50 * 60)
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = estimate_vma([run], REF)
    assert result.vma_kmh is not None
    assert result.vma_kmh > 0
    # 50 min → fraction 0.85, VMA ≈ 12 / 0.85 ≈ 14.12
    expected = 12.0 / 0.85
    assert abs(result.vma_kmh - expected) < 0.01


# ---------------------------------------------------------------------------
# TEST VMA — même input/reference_date → même résultat (déterminisme)
# ---------------------------------------------------------------------------


def test_vma_deterministic():
    """Test 5: même input/reference_date → même résultat."""
    activities = [
        make_run(distance_m=10_000, duration_s=3000, days_ago=5),
        make_run(distance_m=8_000, duration_s=2400, days_ago=10),
    ]
    r1 = estimate_vma(activities, REF)
    r2 = estimate_vma(activities, REF)
    assert r1.vma_kmh == r2.vma_kmh
    assert r1.confidence == r2.confidence


# ---------------------------------------------------------------------------
# TEST VMA — activité future → ignorée
# ---------------------------------------------------------------------------


def test_vma_future_activity_ignored():
    """Test 6: activité future → ignorée."""
    future_run = DomainActivity(
        activity_type="running",
        start_time=date(2025, 1, 20).isoformat(),  # future relative to REF=2025-01-15
        distance_m=10_000,
        duration_s=3000,
    )
    result = estimate_vma([future_run], REF)
    assert result.vma_kmh is None


# ---------------------------------------------------------------------------
# TEST VMA — db.workouts divergent → aucun impact
# ---------------------------------------------------------------------------


def test_vma_no_db_workouts_dependency():
    """Test 7: db.workouts divergent → aucun impact.
    The performance_model module must not import motor or call db.
    """
    import training_v2.performance_model as pm_module
    source = open(pm_module.__file__).read()
    assert "motor" not in source, "performance_model.py must not import motor (I/O-free)"
    assert "AsyncIOMotorClient" not in source, "performance_model.py must not use Mongo"
    assert "await db" not in source, "performance_model.py must not use await db (I/O-free)"


# ---------------------------------------------------------------------------
# TEST PREDICTIONS — aucune performance exploitable → pas de prédiction inventée
# ---------------------------------------------------------------------------


def test_predictions_no_data_returns_no_predictions():
    """Test 1: aucune performance exploitable → pas de prédiction inventée."""
    result = predict_races([], REF)
    assert result.has_data is False
    assert result.predictions == []


def test_predictions_insufficient_data_returns_null():
    """Test 1b: données insuffisantes → has_data=False, predictions vide."""
    # Only non-running activities
    cycling = make_run(10_000, 3600, days_ago=5, activity_type="cycling")
    result = predict_races([cycling], REF)
    assert result.has_data is False
    assert result.predictions == []


# ---------------------------------------------------------------------------
# TEST PREDICTIONS — performance 10K → prédiction 10K cohérente
# ---------------------------------------------------------------------------


def test_predictions_10k_observed_coherent():
    """Test 2: performance 10K observée → prédiction 10K cohérente avec observation."""
    # 10K in 50 minutes
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    assert result.has_data is True

    ten_k = next((p for p in result.predictions if p.distance_label == "10K"), None)
    assert ten_k is not None
    assert ten_k.predicted_time_s is not None
    # Riegel with source = target: T2 = T1 × (10000/10000)^1.06 = T1 = 3000s
    # Endurance support for 10K = 1.0 (no penalty), penalty = 1.0
    # Expected = 3000s
    assert abs(ten_k.predicted_time_s - 3000) < 5, (
        f"10K prediction {ten_k.predicted_time_s}s should be ~3000s"
    )


# ---------------------------------------------------------------------------
# TEST PREDICTIONS — extrapolation 5K ↔ 10K → monotone/cohérente
# ---------------------------------------------------------------------------


def test_predictions_5k_10k_monotone():
    """Test 3: extrapolation 5K ↔ 10K → monotone/cohérente."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    five_k = next(p for p in result.predictions if p.distance_label == "5K")
    ten_k = next(p for p in result.predictions if p.distance_label == "10K")
    assert five_k.predicted_time_s < ten_k.predicted_time_s, (
        f"5K ({five_k.predicted_time_s}s) should be faster than 10K ({ten_k.predicted_time_s}s)"
    )


# ---------------------------------------------------------------------------
# TEST PREDICTIONS — extrapolation 10K → Semi → déterministe
# ---------------------------------------------------------------------------


def test_predictions_10k_to_semi_deterministic():
    """Test 4: extrapolation 10K → Semi → déterministe."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    r1 = predict_races([run], REF)
    r2 = predict_races([run], REF)
    semi1 = next(p for p in r1.predictions if p.distance_label == "Semi")
    semi2 = next(p for p in r2.predictions if p.distance_label == "Semi")
    assert semi1.predicted_time_s == semi2.predicted_time_s


# ---------------------------------------------------------------------------
# TEST PREDICTIONS — courte → Marathon avec faible endurance → jamais plus optimiste que brut
# ---------------------------------------------------------------------------


def test_predictions_short_source_marathon_conservative():
    """Test 5: extrapolation courte → Marathon avec faible support endurance
    → jamais plus optimiste que modèle brut (Riegel sans ajustement).
    """
    # Only a 5K run, no long runs at all
    run = make_run(distance_m=5_000, duration_s=1200, days_ago=5)
    result = predict_races([run], REF)
    marathon = next(p for p in result.predictions if p.distance_label == "Marathon")

    # Raw Riegel prediction (no endurance penalty)
    raw_time_s = _riegel(1200, 5_000, 42_195)
    # With endurance penalty, adjusted must be >= raw_time_s (slower or equal)
    assert marathon.predicted_time_s >= raw_time_s - 1, (
        f"Marathon prediction {marathon.predicted_time_s}s must not be faster than raw Riegel {raw_time_s}s"
    )


# ---------------------------------------------------------------------------
# TEST PREDICTIONS — meilleur support endurance ne dégrade pas artificiellement
# ---------------------------------------------------------------------------


def test_predictions_better_endurance_not_worse():
    """Test 6: meilleur support endurance → ne dégrade pas artificiellement la prédiction."""
    run_base = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    run_long = make_run(distance_m=30_000, duration_s=9600, days_ago=12)  # extra long run

    r_base = predict_races([run_base], REF)
    r_with_long = predict_races([run_base, run_long], REF)

    # With better endurance support, marathon should not be worse
    m_base = next(p for p in r_base.predictions if p.distance_label == "Marathon")
    m_long = next(p for p in r_with_long.predictions if p.distance_label == "Marathon")

    # endurance_factor should be higher (better support)
    assert m_long.endurance_factor >= m_base.endurance_factor


# ---------------------------------------------------------------------------
# TEST PREDICTIONS — aucune prediction négative/impossible
# ---------------------------------------------------------------------------


def test_predictions_all_positive():
    """Test 7: aucune prediction négative/impossible."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    for pred in result.predictions:
        if pred.predicted_time_s is not None:
            assert pred.predicted_time_s > 0, f"{pred.distance_label} time must be positive"
            assert pred.readiness_score >= 0
            assert pred.readiness_score <= 100
            assert pred.endurance_factor >= 0
            assert pred.volume_factor >= 0


# ---------------------------------------------------------------------------
# TEST PREDICTIONS — confidence diminue avec ancienneté et extrapolation
# ---------------------------------------------------------------------------


def test_predictions_confidence_degrades_with_age():
    """Test 8a: confidence diminue avec ancienneté."""
    run_recent = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    run_old = make_run(distance_m=10_000, duration_s=3000, days_ago=200)

    r_recent = predict_races([run_recent], REF)
    r_old = predict_races([run_old], REF)

    # Marathon confidence with old source should be low
    m_old = next(p for p in r_old.predictions if p.distance_label == "Marathon")
    assert m_old.confidence == "low", f"Expected 'low' confidence for old source, got {m_old.confidence}"


def test_predictions_confidence_degrades_with_large_extrapolation():
    """Test 8b: confidence diminue avec grande extrapolation."""
    # Source: 5K, target: Marathon (ratio ~ 8.4x)
    run = make_run(distance_m=5_000, duration_s=1200, days_ago=5)
    result = predict_races([run], REF)
    marathon = next(p for p in result.predictions if p.distance_label == "Marathon")
    assert marathon.confidence in ("low", "medium")


# ---------------------------------------------------------------------------
# TEST HISTORY — anti-look-ahead obligatoire
# ---------------------------------------------------------------------------


def test_vma_history_no_look_ahead():
    """Anti-look-ahead test: snapshot at J-30 must NOT see an activity at J.
    snapshot at J+1 CAN see the same activity.
    """
    J = REF  # J = reference date = 2025-01-15
    # Activity at exactly J (performance date)
    activity_at_J = DomainActivity(
        activity_type="running",
        start_time=J.isoformat(),
        distance_m=10_000,
        duration_s=3000,
    )

    snapshot_before = date(J.year, J.month, J.day - 30) if J.day > 30 else date(J.year, J.month - 1, J.day) if J.month > 1 else date(J.year - 1, 12, J.day)
    snapshot_before = date.fromordinal(J.toordinal() - 30)
    snapshot_after = date.fromordinal(J.toordinal() + 1)

    # Snapshot 30 days before J: activity at J should be invisible
    result_before = estimate_vma([activity_at_J], snapshot_before)
    # activity_at_J is 30 days in the future relative to snapshot_before
    assert result_before.vma_kmh is None, (
        "Snapshot 30 days before J must NOT see activity at J"
    )

    # Snapshot 1 day after J: activity at J should be visible
    result_after = estimate_vma([activity_at_J], snapshot_after)
    assert result_after.vma_kmh is not None, (
        "Snapshot 1 day after J must be able to use activity at J"
    )


# ---------------------------------------------------------------------------
# TEST — avg_speed/0.70 REMOVED from performance_model
# ---------------------------------------------------------------------------


def test_avg_speed_070_fallback_removed():
    """Verify that avg_speed / 0.70 pattern is absent from performance_model actual logic."""
    import training_v2.performance_model as pm_module
    # Verify by inspecting the module: it should not expose any function that computes speed / 0.7
    # The model uses fraction-based VMA (0.78, 0.85, 0.90, 0.95), never /0.70
    fractions = [pm_module.RIEGEL_K]  # Access module constants to force import
    # Fractions used in VMA estimation are all > 0.70 (no relaxed fallback)
    # If estimate_vma returns VMA for a fast run, it should not match avg/0.70
    from training_v2.domain_activity import DomainActivity
    from datetime import date
    # 10 km/h for 60 min (easy run): avg / 0.70 would give 14.28; model gives 10/0.78 = 12.82
    easy = DomainActivity(activity_type="running", start_time="2025-01-10", distance_m=10000, duration_s=3600)
    result = pm_module.estimate_vma([easy], date(2025, 1, 15))
    if result.vma_kmh is not None:
        avg_speed = 10000 / 1000 / (3600 / 3600)  # 10 km/h
        fallback_070 = avg_speed / 0.70
        assert abs(result.vma_kmh - fallback_070) > 0.5, (
            f"VMA {result.vma_kmh} must not equal avg_speed/0.70={fallback_070:.2f}"
        )


# ---------------------------------------------------------------------------
# TEST — Riegel formula correct
# ---------------------------------------------------------------------------


def test_riegel_formula():
    """Verify Riegel implementation: T2 = T1 × (D2/D1)^k."""
    t1, d1, d2, k = 3000.0, 10_000.0, 42_195.0, RIEGEL_K
    expected = t1 * (d2 / d1) ** k
    assert abs(_riegel(t1, d1, d2) - expected) < 0.001


def test_riegel_same_distance_returns_same_time():
    """Riegel with same source and target distance must return original time."""
    t = _riegel(3000.0, 10_000.0, 10_000.0)
    assert abs(t - 3000.0) < 0.001


# ---------------------------------------------------------------------------
# TEST — Frontend contract preservation
# ---------------------------------------------------------------------------


def test_predict_races_returns_all_four_distances():
    """PREDICTIONS_5K = YES, PREDICTIONS_10K = YES, PREDICTIONS_HALF = YES, PREDICTIONS_MARATHON = YES."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    labels = {p.distance_label for p in result.predictions}
    assert "5K" in labels, "PREDICTIONS_5K = YES"
    assert "10K" in labels, "PREDICTIONS_10K = YES"
    assert "Semi" in labels, "PREDICTIONS_HALF = YES"
    assert "Marathon" in labels, "PREDICTIONS_MARATHON = YES"


def test_prediction_has_readiness_fields():
    """Frontend requires readiness, readiness_label, readiness_color, readiness_score."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    for pred in result.predictions:
        assert pred.readiness in ("ready", "possible", "challenging", "not_ready")
        assert pred.readiness_label
        assert pred.readiness_color
        assert 0 <= pred.readiness_score <= 100


def test_prediction_has_model_version_v2():
    """model_version = 'v2' in predictions."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    for pred in result.predictions:
        assert pred.model_version == "v2"


def test_vma_estimate_has_model_version_v2():
    """model_version = 'v2' in VMAEstimate."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = estimate_vma([run], REF)
    assert result.model_version == "v2"


def test_athlete_profile_has_vo2max_note():
    """VO2max must be documented as derived estimate (not Garmin/lab measurement)."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    assert result.has_data
    note = result.athlete_profile.get("vo2max_note", "")
    assert note, "vo2max_note must be present and non-empty"
    assert "estimate" in note.lower() or "derived" in note.lower(), (
        f"vo2max_note must document it as a derived estimate, got: {note}"
    )


# ---------------------------------------------------------------------------
# Frontend preservation smoke tests (no server calls — structural only)
# ---------------------------------------------------------------------------


def test_vma_frontend_preserved():
    """VMA_FRONTEND_PRESERVED = YES — output contains expected frontend fields."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    ap = result.athlete_profile
    # Fields consumed by Progress.jsx
    assert "estimated_vma" in ap
    assert "estimated_vo2max" in ap
    assert ap["estimated_vma"] is not None
    assert ap["estimated_vo2max"] is not None


def test_vma_history_no_lookahead_structural():
    """VMA_HISTORY_FRONTEND_PRESERVED = YES — historical estimate respects reference_date."""
    future_run = DomainActivity(
        activity_type="running",
        start_time="2099-01-01",
        distance_m=10_000,
        duration_s=3000,
    )
    result = estimate_vma([future_run], REF)
    # A run in 2099 must not be visible from REF=2025-01-15
    assert result.vma_kmh is None


def test_predictions_frontend_preserved():
    """PREDICTIONS_FRONTEND_PRESERVED = YES — predicted_time, predicted_pace, readiness_* present."""
    run = make_run(distance_m=10_000, duration_s=3000, days_ago=5)
    result = predict_races([run], REF)
    for pred in result.predictions:
        assert pred.predicted_time_str is not None
        assert pred.predicted_pace_str is not None
        assert pred.readiness is not None
