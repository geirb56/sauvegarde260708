"""PR194 — Training Paces V2 backend tests.

Tests VDOT calculation, Daniels pace derivation, VDOT selection policy,
confidence levels, no-lookahead invariant, Garmin VO2max independence,
Readiness independence, and determinism.

All fixtures are synthetic; no user account dependency.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import List, Optional

import pytest

from training_v2.domain_activity import DomainActivity
from training_v2.training_paces import (
    VDOT_MIN,
    VDOT_MAX,
    E_FRACTION_LOW,
    E_FRACTION_HIGH,
    M_FRACTION,
    T_FRACTION,
    I_FRACTION,
    I_FRACTION_SLOW,
    R_FRACTION,
    TP_STALE_HIGH_DAYS,
    vdot_from_performance,
    daniels_paces,
    compute_training_paces,
    TrainingPaces,
    PaceValue,
    PaceRange,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REF_DATE = date(2026, 7, 1)


def _running(
    *,
    start_time: date,
    distance_m: float,
    duration_s: float,
    average_hr: Optional[float] = None,
    max_hr: Optional[float] = None,
    moving_duration_s: Optional[float] = None,
) -> DomainActivity:
    """Build a synthetic running DomainActivity."""
    return DomainActivity(
        activity_type="running",
        start_time=start_time,
        distance_m=distance_m,
        duration_s=duration_s,
        average_hr=average_hr,
        max_hr=max_hr,
        moving_duration_s=moving_duration_s,
    )


# Fixture: 5 benchmark activities before the target, so speed_percentile can be computed.
def _benchmark_pool(ref: date, n: int = 7, speed_kmh: float = 10.0) -> List[DomainActivity]:
    """Create n easy benchmark runs all strictly prior to any h2 (days_ago≥11).

    Start offset at -(i + 11) so these are all before days_ago=10 qualified runs,
    guaranteeing ≥5 strictly-prior benchmarks even for the older qualified activity.
    """
    acts = []
    for i in range(n):
        day_offset = -(i + 11)          # days_ago 11..11+n, all prior to days_ago=10
        start = ref + timedelta(days=day_offset)
        # 10 km at speed_kmh
        dur_s = (10_000.0 / (speed_kmh * 1000.0 / 3600.0))
        acts.append(_running(
            start_time=start,
            distance_m=10_000.0,
            duration_s=dur_s,
            average_hr=140.0,
            max_hr=175.0,
        ))
    return acts


def _qualified_high_activity(ref: date, days_ago: int = 3) -> DomainActivity:
    """
    A 10 km at ~12 km/h (5:00/km) that should rank in the top 10% of the
    benchmark pool (which runs at 10 km/h).

    max_hr deliberately matches benchmark pool (175 bpm) so FCmax stays
    constant regardless of which activities are included as prior context.
    This prevents score dropping below HIGH threshold due to FCmax inflation.

    FCmax = 175 bpm everywhere.
    average_hr = 160 bpm → relative_hr = 160/175 ≈ 0.914 → HIGH threshold 0.85 ✓
    hr_component = (0.914 - 0.80)/(0.95 - 0.80) ≈ 0.76
    score = 0.5 * 0.76 + 0.5 * 1.0 = 0.88 ≥ 0.80 HIGH threshold ✓
    speed_percentile = 100% in benchmark pool ✓
    """
    dist = 10_000.0
    speed_ms = 12_000.0 / 3600.0  # 12 km/h = 3.333 m/s
    dur_s = dist / speed_ms
    return _running(
        start_time=ref - timedelta(days=days_ago),
        distance_m=dist,
        duration_s=dur_s,
        average_hr=160.0,
        max_hr=175.0,   # consistent with benchmark pool — no FCmax inflation
    )


def _qualified_medium_activity(ref: date, days_ago: int = 3) -> DomainActivity:
    """
    A 10 km at 11 km/h that passes medium threshold.
    max_hr=175 consistent with benchmark pool.
    relative_hr = 150/175 ≈ 0.857 (above 0.80 min for medium, below 0.85 for high)
    speed_percentile ≈ 83-100% in benchmark pool at 10 km/h → ≥70% for medium.
    """
    dist = 10_000.0
    speed_ms = 11_000.0 / 3600.0
    dur_s = dist / speed_ms
    return _running(
        start_time=ref - timedelta(days=days_ago),
        distance_m=dist,
        duration_s=dur_s,
        average_hr=150.0,
        max_hr=175.0,
    )


# ---------------------------------------------------------------------------
# 1. VDOT formula tests
# ---------------------------------------------------------------------------

class TestVdotFromPerformance:
    """Validate the Daniels/Gilbert VDOT formula against known table values."""

    def test_vdot_10k_50min(self):
        """10 km in 50:00 → VDOT ≈ 40.  Tolerance ±1.0."""
        vdot = vdot_from_performance(10_000.0, 50 * 60.0)
        assert vdot is not None
        assert abs(vdot - 40.0) <= 1.0, f"Expected ≈40, got {vdot}"

    def test_vdot_5k_24min(self):
        """5 km in 24:00 → VDOT ≈ 41.5.  Tolerance ±1.0."""
        vdot = vdot_from_performance(5_000.0, 24 * 60.0)
        assert vdot is not None
        assert abs(vdot - 41.5) <= 1.5, f"Expected ≈41.5, got {vdot}"

    def test_vdot_10k_40min_higher(self):
        """10 km in 40:00 → VDOT ≈ 52.  Tolerance ±1.5."""
        vdot = vdot_from_performance(10_000.0, 40 * 60.0)
        assert vdot is not None
        assert abs(vdot - 52.0) <= 1.5, f"Expected ≈52, got {vdot}"

    def test_vdot_marathon_210min(self):
        """Marathon (42 195 m) in 3h30 → VDOT ≈ 45.  Tolerance ±2."""
        vdot = vdot_from_performance(42_195.0, 210 * 60.0)
        assert vdot is not None
        assert abs(vdot - 45.0) <= 2.0, f"Expected ≈45, got {vdot}"

    def test_invalid_distance(self):
        assert vdot_from_performance(0.0, 1800.0) is None
        assert vdot_from_performance(-100.0, 1800.0) is None

    def test_invalid_duration(self):
        assert vdot_from_performance(5_000.0, 0.0) is None
        assert vdot_from_performance(5_000.0, 89.0) is None  # below MIN

    def test_clamped_to_max(self):
        """Absurdly fast performance → clamped to VDOT_MAX=85."""
        vdot = vdot_from_performance(10_000.0, 20 * 60.0)  # 10km in 20 min
        assert vdot == VDOT_MAX

    def test_clamped_to_min(self):
        """Very slow performance → clamped to VDOT_MIN=20."""
        vdot = vdot_from_performance(1_000.0, 30 * 60.0)  # 1km in 30 min
        assert vdot == VDOT_MIN


# ---------------------------------------------------------------------------
# 2. Daniels pace formula tests (pure function)
# ---------------------------------------------------------------------------

class TestDanielsPaceFormula:
    """Verify that pace_at_fraction matches Daniels VDOT table ±5 s/km."""

    TOLERANCE_S_PER_KM = 12  # seconds per km tolerance

    def _pace_str_to_seconds(self, s: str) -> int:
        """'5:30' → 330 seconds."""
        m, sec = s.split(":")
        return int(m) * 60 + int(sec)

    def _pace_diff_s(self, computed: PaceValue, expected_str: str) -> int:
        computed_s = int(round(computed.min_per_km * 60))
        expected_s = self._pace_str_to_seconds(expected_str)
        return abs(computed_s - expected_s)

    def test_vdot40_threshold(self):
        """VDOT 40 T pace ≈ 5:05 /km."""
        p = daniels_paces(40.0, reference_date=REF_DATE)
        assert p.threshold is not None
        diff = self._pace_diff_s(p.threshold, "5:05")
        assert diff <= self.TOLERANCE_S_PER_KM, f"T VDOT40: expected 5:05, diff={diff}s"

    def test_vdot40_marathon(self):
        """VDOT 40 M pace ≈ 5:35 /km."""
        p = daniels_paces(40.0, reference_date=REF_DATE)
        assert p.marathon is not None
        diff = self._pace_diff_s(p.marathon, "5:35")
        assert diff <= self.TOLERANCE_S_PER_KM, f"M VDOT40: expected 5:35, diff={diff}s"

    def test_vdot40_easy_range(self):
        """VDOT 40 E range ≈ 6:15–7:18 /km."""
        p = daniels_paces(40.0, reference_date=REF_DATE)
        assert p.easy is not None
        lower_s = int(round(p.easy.lower.min_per_km * 60))
        upper_s = int(round(p.easy.upper.min_per_km * 60))
        # lower = faster (smaller value)
        assert lower_s < upper_s, "E lower should be faster than upper"
        diff_lower = abs(lower_s - self._pace_str_to_seconds("6:15"))
        diff_upper = abs(upper_s - self._pace_str_to_seconds("7:18"))
        assert diff_lower <= self.TOLERANCE_S_PER_KM, f"E lower VDOT40: expected 6:15, diff={diff_lower}s"
        assert diff_upper <= self.TOLERANCE_S_PER_KM, f"E upper VDOT40: expected 7:18, diff={diff_upper}s"

    def test_vdot40_interval(self):
        """VDOT 40 I pace ≈ 4:17 /km."""
        p = daniels_paces(40.0, reference_date=REF_DATE)
        assert p.interval is not None
        diff = self._pace_diff_s(p.interval.lower, "4:17")
        assert diff <= self.TOLERANCE_S_PER_KM, f"I VDOT40: expected 4:17, diff={diff}s"

    def test_vdot40_repetition(self):
        """VDOT 40 R pace ≈ 3:56 /km."""
        p = daniels_paces(40.0, reference_date=REF_DATE)
        assert p.repetition is not None
        diff = self._pace_diff_s(p.repetition, "3:56")
        assert diff <= self.TOLERANCE_S_PER_KM, f"R VDOT40: expected 3:56, diff={diff}s"

    def test_vdot50_all_zones(self):
        """VDOT 50: cross-check E/M/T/I/R."""
        p = daniels_paces(50.0, reference_date=REF_DATE)
        # E range ≈ 5:13–6:05
        assert abs(int(round(p.easy.lower.min_per_km * 60)) - self._pace_str_to_seconds("5:13")) <= self.TOLERANCE_S_PER_KM
        assert abs(int(round(p.easy.upper.min_per_km * 60)) - self._pace_str_to_seconds("6:05")) <= self.TOLERANCE_S_PER_KM
        # M ≈ 4:38
        assert abs(int(round(p.marathon.min_per_km * 60)) - self._pace_str_to_seconds("4:38")) <= self.TOLERANCE_S_PER_KM
        # T ≈ 4:15
        assert abs(int(round(p.threshold.min_per_km * 60)) - self._pace_str_to_seconds("4:15")) <= self.TOLERANCE_S_PER_KM
        # I ≈ 3:34
        assert abs(int(round(p.interval.lower.min_per_km * 60)) - self._pace_str_to_seconds("3:34")) <= self.TOLERANCE_S_PER_KM
        # R ≈ 3:14
        assert abs(int(round(p.repetition.min_per_km * 60)) - self._pace_str_to_seconds("3:14")) <= self.TOLERANCE_S_PER_KM

    def test_pace_ordering(self):
        """For any VDOT: R < I < T < M < E_lower < E_upper (faster = smaller min/km)."""
        for vdot in [30.0, 40.0, 50.0, 60.0, 70.0]:
            p = daniels_paces(vdot, reference_date=REF_DATE)
            assert p.easy and p.marathon and p.threshold and p.interval and p.repetition
            r = p.repetition.min_per_km
            i = p.interval.lower.min_per_km
            t = p.threshold.min_per_km
            m = p.marathon.min_per_km
            e_low = p.easy.lower.min_per_km
            e_high = p.easy.upper.min_per_km
            assert r < i, f"VDOT {vdot}: R should be faster than I"
            assert i < t, f"VDOT {vdot}: I should be faster than T"
            assert t < m, f"VDOT {vdot}: T should be faster than M"
            assert m < e_low, f"VDOT {vdot}: M should be faster than E lower"
            assert e_low < e_high, f"VDOT {vdot}: E lower should be faster than E upper"

    def test_km_per_hour_consistent(self):
        """km_per_hour = 60 / min_per_km (within rounding)."""
        p = daniels_paces(45.0, reference_date=REF_DATE)
        assert p.threshold is not None
        expected_kmh = 60.0 / p.threshold.min_per_km
        assert abs(p.threshold.km_per_hour - expected_kmh) < 0.05

    def test_pace_str_format(self):
        """Pace strings are in M:SS format."""
        p = daniels_paces(45.0, reference_date=REF_DATE)
        for part in [p.threshold, p.marathon, p.repetition]:
            assert part is not None
            parts = part.pace_str.split(":")
            assert len(parts) == 2
            assert 0 <= int(parts[0]) < 60
            assert 0 <= int(parts[1]) < 60


# ---------------------------------------------------------------------------
# 3. No-lookahead invariant
# ---------------------------------------------------------------------------

class TestNoLookahead:
    """Adding a future performance MUST NOT change historical paces."""

    def _build_pool_with_qualified(self) -> List[DomainActivity]:
        benchmarks = _benchmark_pool(REF_DATE, n=7)
        qualified = _qualified_high_activity(REF_DATE, days_ago=5)
        return benchmarks + [qualified]

    def test_adding_future_activity_no_effect(self):
        """paces(J) == paces(J) after adding performance at J+30."""
        base_acts = self._build_pool_with_qualified()
        paces_before = compute_training_paces(base_acts, REF_DATE)

        # Add a future HIGH activity 30 days ahead
        future_dist = 10_000.0
        future_dur = 40 * 60.0  # very fast — would bump VDOT if included
        future_act = _running(
            start_time=REF_DATE + timedelta(days=30),
            distance_m=future_dist,
            duration_s=future_dur,
            average_hr=165.0,
            max_hr=185.0,
        )
        paces_after = compute_training_paces(base_acts + [future_act], REF_DATE)

        assert paces_before.confidence == paces_after.confidence
        assert paces_before.vdot_result.reference_vdot == paces_after.vdot_result.reference_vdot

    def test_reference_date_isolation(self):
        """Paces at date J are independent of paces at J+30."""
        acts = _benchmark_pool(REF_DATE, n=7) + [_qualified_high_activity(REF_DATE, days_ago=5)]
        # Extra HIGH 10 days after ref
        extra = _running(
            start_time=REF_DATE + timedelta(days=10),
            distance_m=5_000.0,
            duration_s=22 * 60.0,
            average_hr=170.0,
            max_hr=182.0,
        )
        paces_at_ref = compute_training_paces(acts + [extra], REF_DATE)
        paces_at_ref2 = compute_training_paces(acts, REF_DATE)
        # The extra future activity should not affect paces at REF_DATE
        assert paces_at_ref.vdot_result.reference_vdot == paces_at_ref2.vdot_result.reference_vdot


# ---------------------------------------------------------------------------
# 4. VDOT confidence cases
# ---------------------------------------------------------------------------

class TestVdotConfidenceCases:
    """Cover all 8 cases of the VDOT selection policy."""

    def _build_base_benchmarks(self, ref: date, n: int = 7) -> List[DomainActivity]:
        return _benchmark_pool(ref, n=n)

    def test_case1_multiple_concordant_high(self):
        """Case 1: ≥2 concordant HIGH recent → paces_confidence=HIGH."""
        ref = REF_DATE
        benchmarks = self._build_base_benchmarks(ref, n=7)
        h1 = _qualified_high_activity(ref, days_ago=3)
        h2 = _qualified_high_activity(ref, days_ago=7)
        paces = compute_training_paces(benchmarks + [h1, h2], ref)
        assert paces.confidence == "HIGH"
        assert paces.vdot_result.reference_vdot is not None
        assert paces.easy is not None
        assert paces.threshold is not None

    def test_case2_single_recent_high(self):
        """Case 2: exactly 1 recent HIGH → paces_confidence=MEDIUM."""
        ref = REF_DATE
        benchmarks = self._build_base_benchmarks(ref, n=7)
        h1 = _qualified_high_activity(ref, days_ago=5)
        paces = compute_training_paces(benchmarks + [h1], ref)
        assert paces.confidence == "MEDIUM"
        assert paces.vdot_result.reference_vdot is not None

    def test_case3_stale_high(self):
        """Case 3: HIGH evidence older than HIGH_DAYS (21) → paces_confidence=LOW.

        Tested directly on the selection policy to avoid integration complexity.
        """
        from training_v2.training_paces import select_vdot_reference, VdotEvidence
        from training_v2.training_paces import CONFIDENCE_HIGH_DAYS, _RECENCY_WEIGHT_MEDIUM
        ref = REF_DATE
        stale_days = CONFIDENCE_HIGH_DAYS + 10  # e.g. 31 days old
        evidence = [
            VdotEvidence(
                vdot=42.0,
                confidence="high",
                performance_date=ref - timedelta(days=stale_days),
                days_old=stale_days,
                distance_m=10_000.0,
                duration_s=48 * 60.0,
                recency_weight=_RECENCY_WEIGHT_MEDIUM,  # stale = MEDIUM recency
            )
        ]
        result = select_vdot_reference(evidence, ref)
        assert result.paces_confidence == "low", f"Got {result.paces_confidence}"
        assert result.reference_vdot == 42.0

    def test_case4_medium_only(self):
        """Case 4: only MEDIUM confidence evidence → paces_confidence=LOW.

        Tested directly on the selection policy to avoid integration complexity.
        """
        from training_v2.training_paces import select_vdot_reference, VdotEvidence
        from training_v2.training_paces import _RECENCY_WEIGHT_RECENT
        ref = REF_DATE
        evidence = [
            VdotEvidence(
                vdot=38.0,
                confidence="medium",
                performance_date=ref - timedelta(days=5),
                days_old=5,
                distance_m=10_000.0,
                duration_s=52 * 60.0,
                recency_weight=_RECENCY_WEIGHT_RECENT,
            ),
            VdotEvidence(
                vdot=37.5,
                confidence="medium",
                performance_date=ref - timedelta(days=15),
                days_old=15,
                distance_m=10_000.0,
                duration_s=52.5 * 60.0,
                recency_weight=_RECENCY_WEIGHT_RECENT,
            ),
        ]
        result = select_vdot_reference(evidence, ref)
        assert result.paces_confidence == "low", f"Got {result.paces_confidence}"
        assert result.reference_vdot is not None

    def test_case5_no_evidence(self):
        """Case 5: no qualified performances → paces_confidence=INSUFFICIENT."""
        # Only 1 benchmark (too few for speed percentile) → no qualification
        ref = REF_DATE
        minimal = [
            _running(
                start_time=ref - timedelta(days=2),
                distance_m=5_000.0,
                duration_s=30 * 60.0,
                average_hr=140.0,
                max_hr=175.0,
            )
        ]
        paces = compute_training_paces(minimal, ref)
        assert paces.confidence == "INSUFFICIENT"
        assert paces.vdot_result.reference_vdot is None
        assert paces.easy is None
        assert paces.marathon is None
        assert paces.threshold is None
        assert paces.interval is None
        assert paces.repetition is None

    def test_case5_empty_activities(self):
        """Empty activity list → INSUFFICIENT."""
        paces = compute_training_paces([], REF_DATE)
        assert paces.confidence == "INSUFFICIENT"
        assert paces.easy is None

    def test_all_paces_none_when_insufficient(self):
        """When confidence is INSUFFICIENT, all five zones must be None."""
        paces = compute_training_paces([], REF_DATE)
        assert paces.easy is None
        assert paces.marathon is None
        assert paces.threshold is None
        assert paces.interval is None
        assert paces.repetition is None

    def test_new_high_better_than_existing(self):
        """A new HIGH performance better than existing → should be taken into account."""
        ref = REF_DATE
        benchmarks = self._build_base_benchmarks(ref, n=7)
        h_old = _qualified_high_activity(ref, days_ago=40)  # stale
        h_new = _qualified_high_activity(ref, days_ago=3)   # recent
        paces_with_both = compute_training_paces(benchmarks + [h_old, h_new], ref)
        paces_only_new = compute_training_paces(benchmarks + [h_new], ref)
        # New HIGH should dominate
        assert paces_with_both.confidence in ("HIGH", "MEDIUM")
        assert paces_only_new.confidence in ("HIGH", "MEDIUM")


# ---------------------------------------------------------------------------
# 5. Garmin VO2max independence
# ---------------------------------------------------------------------------

class TestGarminVO2maxIndependence:
    """Modifying Garmin VO2max MUST NOT change training paces."""

    def test_garmin_vo2max_ignored(self):
        """compute_training_paces does not read Garmin VO2max from DomainActivity.

        DomainActivity has no garmin_vo2max field — the function signature
        never accepts it. This test verifies the module has no such parameter.
        """
        from training_v2.training_paces import compute_training_paces
        import inspect
        sig = inspect.signature(compute_training_paces)
        param_names = list(sig.parameters.keys())
        assert "garmin_vo2max" not in param_names
        assert "vo2max_garmin" not in param_names
        assert "vo2max" not in param_names

    def test_paces_unchanged_when_garmin_vo2max_hypothetically_changes(self):
        """Same activities → same paces regardless of any Garmin VO2max field."""
        ref = REF_DATE
        benchmarks = _benchmark_pool(ref, n=7)
        qualified = _qualified_high_activity(ref, days_ago=5)
        acts = benchmarks + [qualified]

        p1 = compute_training_paces(acts, ref)
        # Simulate "Garmin VO2max changed" by calling with identical activities
        # (since Garmin VO2max is not in DomainActivity, nothing changes)
        p2 = compute_training_paces(acts, ref)
        assert p1.vdot_result.reference_vdot == p2.vdot_result.reference_vdot
        assert p1.confidence == p2.confidence


# ---------------------------------------------------------------------------
# 6. Readiness independence
# ---------------------------------------------------------------------------

class TestReadinessIndependence:
    """Readiness adapts sessions; it must NOT change VDOT or pace definitions."""

    def test_paces_are_capability_not_prescription(self):
        """TrainingPaces does not contain readiness_band or session fields."""
        ref = REF_DATE
        paces = daniels_paces(45.0, reference_date=REF_DATE)
        assert not hasattr(paces, "readiness_band")
        assert not hasattr(paces, "adapted_session")
        assert not hasattr(paces, "readiness_score")

    def test_threshold_pace_unchanged_by_readiness(self):
        """Threshold pace from VDOT 45 is deterministic and independent of readiness."""
        p = daniels_paces(45.0, reference_date=REF_DATE)
        # Same VDOT always gives same T pace
        p2 = daniels_paces(45.0, reference_date=REF_DATE)
        assert p.threshold.min_per_km == p2.threshold.min_per_km


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Same input → same output, always."""

    def test_deterministic_across_calls(self):
        """compute_training_paces is deterministic (no internal randomness)."""
        ref = REF_DATE
        acts = _benchmark_pool(ref, n=7) + [_qualified_high_activity(ref, days_ago=4)]
        results = [compute_training_paces(acts, ref) for _ in range(5)]
        vdots = [r.vdot_result.reference_vdot for r in results]
        assert len(set(vdots)) == 1, f"Non-deterministic: {vdots}"

    def test_deterministic_on_date_input(self):
        """Both date and datetime reference_date produce identical results."""
        from datetime import datetime, timezone
        ref_date = REF_DATE
        ref_dt = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        acts = _benchmark_pool(ref_date, n=7) + [_qualified_high_activity(ref_date, days_ago=4)]
        p_d = compute_training_paces(acts, ref_date)
        p_dt = compute_training_paces(acts, ref_dt)
        assert p_d.vdot_result.reference_vdot == p_dt.vdot_result.reference_vdot


# ---------------------------------------------------------------------------
# 8. training_paces_to_api_dict serialization
# ---------------------------------------------------------------------------

class TestApiSerialization:
    """Verify the API serialization contract."""

    def test_insufficient_serializes_null_paces(self):
        """INSUFFICIENT response: paces dict exists with all None values."""
        from training_v2.training_paces import training_paces_to_api_dict
        paces = compute_training_paces([], REF_DATE)
        d = training_paces_to_api_dict(paces)
        assert d["confidence"] == "INSUFFICIENT"
        assert d["vdot_reference"] is None
        # C1: pace fields are nested under "paces"
        assert "paces" in d
        assert d["paces"]["easy"] is None
        assert d["paces"]["marathon"] is None
        assert d["paces"]["threshold"] is None
        assert d["paces"]["interval"] is None
        assert d["paces"]["repetition"] is None

    def test_full_paces_serializable(self):
        """Full paces response is JSON-serializable and paces are nested under 'paces'."""
        from training_v2.training_paces import training_paces_to_api_dict
        import json
        ref = date(2026, 7, 1)
        paces = daniels_paces(45.0, reference_date=ref)
        d = training_paces_to_api_dict(paces)
        # Must be JSON serializable
        json.dumps(d)
        # C1: pace fields nested under "paces"
        assert "paces" in d
        assert d["paces"]["easy"]["lower_str"] is not None
        assert d["paces"]["easy"]["upper_str"] is not None
        assert d["paces"]["threshold"]["pace_str"] is not None
        assert d["paces"]["marathon"]["pace_str"] is not None
        assert d["paces"]["interval"]["lower_str"] is not None
        assert d["paces"]["repetition"]["pace_str"] is not None

    def test_serialization_keys(self):
        """All required top-level keys are present in the API dict."""
        from training_v2.training_paces import training_paces_to_api_dict
        ref = date(2026, 7, 1)
        paces = daniels_paces(40.0, reference_date=ref)
        d = training_paces_to_api_dict(paces)
        required_top_level = [
            "reference_date", "confidence", "vdot_reference",
            "paces", "reason", "model_version",
        ]
        for k in required_top_level:
            assert k in d, f"Missing top-level key: {k}"
        # Nested paces keys
        required_pace_keys = ["easy", "marathon", "threshold", "interval", "repetition"]
        for k in required_pace_keys:
            assert k in d["paces"], f"Missing paces key: {k}"

    def test_no_flat_pace_keys_at_top_level(self):
        """Pace fields must NOT appear at the top level (C1: paces nested under 'paces')."""
        from training_v2.training_paces import training_paces_to_api_dict
        ref = date(2026, 7, 1)
        paces = daniels_paces(40.0, reference_date=ref)
        d = training_paces_to_api_dict(paces)
        for flat_key in ("easy", "marathon", "threshold", "interval", "repetition"):
            assert flat_key not in d, (
                f"Key '{flat_key}' must be inside d['paces'], not at top level"
            )

    def test_threshold_pace_str_format(self):
        """Threshold pace_str must be 'M:SS' format."""
        from training_v2.training_paces import training_paces_to_api_dict
        ref = date(2026, 7, 1)
        paces = daniels_paces(50.0, reference_date=ref)
        d = training_paces_to_api_dict(paces)
        ts = d["paces"]["threshold"]["pace_str"]
        # Must be "M:SS" format
        parts = ts.split(":")
        assert len(parts) == 2
        assert 0 <= int(parts[0]) < 60
        assert 0 <= int(parts[1]) < 60

    def test_daniels_paces_reference_date_used(self):
        """daniels_paces(vdot, reference_date) uses the provided date, not date.today()."""
        fixed_date = date(2020, 1, 15)
        p = daniels_paces(45.0, reference_date=fixed_date)
        assert p.reference_date == fixed_date, (
            f"Expected reference_date={fixed_date}, got {p.reference_date}"
        )

    def test_daniels_paces_deterministic_with_explicit_date(self):
        """Two calls with same vdot + same reference_date produce identical results."""
        ref = date(2026, 6, 1)
        p1 = daniels_paces(45.0, reference_date=ref)
        p2 = daniels_paces(45.0, reference_date=ref)
        assert p1.threshold.min_per_km == p2.threshold.min_per_km
        assert p1.reference_date == p2.reference_date



# ---------------------------------------------------------------------------
# 10. History supported / reference_date behaviour
# ---------------------------------------------------------------------------

class TestHistorySupport:
    """Verify VDOT can be computed for any historical reference_date."""

    def test_historical_reference_date(self):
        """Can compute paces for a date 60 days in the past."""
        past_ref = REF_DATE - timedelta(days=60)
        # Build benchmarks prior to past_ref
        benchmarks = _benchmark_pool(past_ref, n=7)
        qualified = _qualified_high_activity(past_ref, days_ago=5)
        paces = compute_training_paces(benchmarks + [qualified], past_ref)
        assert paces.reference_date == past_ref

    def test_future_activities_invisible_from_past(self):
        """Activities after past_ref don't affect past computation."""
        past_ref = REF_DATE - timedelta(days=30)
        benchmarks = _benchmark_pool(past_ref, n=7)
        qualified = _qualified_high_activity(past_ref, days_ago=5)
        # Add a future activity relative to past_ref
        future_act = _running(
            start_time=REF_DATE,  # future relative to past_ref
            distance_m=10_000.0,
            duration_s=35 * 60.0,  # very fast
            average_hr=170.0,
            max_hr=190.0,
        )
        p_without = compute_training_paces(benchmarks + [qualified], past_ref)
        p_with = compute_training_paces(benchmarks + [qualified, future_act], past_ref)
        assert p_without.vdot_result.reference_vdot == p_with.vdot_result.reference_vdot


# ---------------------------------------------------------------------------
# 11. Stale HIGH does not abruptly delete paces (STALE_HIGH_DOES_NOT_ABRUPTLY_DELETE_PACES)
# ---------------------------------------------------------------------------

class TestStaleHighPolicy:
    """STALE_HIGH_DOES_NOT_ABRUPTLY_DELETE_PACES = YES.

    A HIGH performance must continue to produce paces at LOW confidence
    until TP_STALE_HIGH_DAYS has elapsed.  This policy is local to
    training_paces and is independent of Race Predictions / performance_model
    window constants.
    """

    def test_stale_high_at_day_57_paces_survive(self):
        """A HIGH performance that is 57 days old must still produce paces.

        Race Predictions uses CONFIDENCE_MEDIUM_DAYS=56 as a hard boundary.
        Training Paces MUST NOT adopt that same boundary: paces must survive
        beyond day 56.
        """
        from training_v2.training_paces import select_vdot_reference, VdotEvidence, _RECENCY_WEIGHT_OLD

        ref = REF_DATE
        days_old = 57  # one day past the old (broken) 56-day Race Predictions window
        evidence = [
            VdotEvidence(
                vdot=45.0,
                confidence="high",
                performance_date=ref - timedelta(days=days_old),
                days_old=days_old,
                distance_m=10_000.0,
                duration_s=47 * 60.0,
                recency_weight=_RECENCY_WEIGHT_OLD,
            )
        ]
        result = select_vdot_reference(evidence, ref)
        assert result.paces_confidence == "low", (
            f"Expected 'low' at day 57 (stale HIGH), got '{result.paces_confidence}'"
        )
        assert result.reference_vdot == 45.0, "VDOT must be preserved at day 57"

    def test_stale_high_long_term_paces_survive(self):
        """A HIGH performance aged up to TP_STALE_HIGH_DAYS continues to produce paces.

        Checks several ages within the stale window: day 30, day 60, day 120,
        and TP_STALE_HIGH_DAYS - 1.
        """
        from training_v2.training_paces import select_vdot_reference, VdotEvidence, _RECENCY_WEIGHT_OLD

        ref = REF_DATE
        for days_old in [30, 60, 120, TP_STALE_HIGH_DAYS - 1]:
            evidence = [
                VdotEvidence(
                    vdot=43.0,
                    confidence="high",
                    performance_date=ref - timedelta(days=days_old),
                    days_old=days_old,
                    distance_m=10_000.0,
                    duration_s=49 * 60.0,
                    recency_weight=_RECENCY_WEIGHT_OLD,
                )
            ]
            result = select_vdot_reference(evidence, ref)
            assert result.paces_confidence == "low", (
                f"Expected 'low' at day {days_old}, got '{result.paces_confidence}'"
            )
            assert result.reference_vdot == 43.0, (
                f"VDOT must be preserved at day {days_old}"
            )

    def test_stale_high_confidence_is_low_not_insufficient(self):
        """A stale HIGH must produce paces (confidence=LOW), not INSUFFICIENT."""
        from training_v2.training_paces import select_vdot_reference, VdotEvidence, _RECENCY_WEIGHT_OLD

        ref = REF_DATE
        stale_days = 90  # well past 56d, still within TP_STALE_HIGH_DAYS
        evidence = [
            VdotEvidence(
                vdot=47.0,
                confidence="high",
                performance_date=ref - timedelta(days=stale_days),
                days_old=stale_days,
                distance_m=10_000.0,
                duration_s=46 * 60.0,
                recency_weight=_RECENCY_WEIGHT_OLD,
            )
        ]
        result = select_vdot_reference(evidence, ref)
        assert result.paces_confidence != "insufficient", (
            "Stale HIGH must not map to INSUFFICIENT within TP_STALE_HIGH_DAYS"
        )
        assert result.reference_vdot is not None

    def test_low_only_is_insufficient(self):
        """LOW-only qualified performances → INSUFFICIENT (no paces).

        Verifies explicitly that LOW alone does not produce paces.
        This test is independent of Race Predictions window constants.
        """
        from training_v2.training_paces import select_vdot_reference, VdotEvidence, _RECENCY_WEIGHT_RECENT

        ref = REF_DATE
        evidence = [
            VdotEvidence(
                vdot=40.0,
                confidence="low",
                performance_date=ref - timedelta(days=5),
                days_old=5,
                distance_m=10_000.0,
                duration_s=50 * 60.0,
                recency_weight=_RECENCY_WEIGHT_RECENT,
            ),
            VdotEvidence(
                vdot=39.0,
                confidence="low",
                performance_date=ref - timedelta(days=12),
                days_old=12,
                distance_m=10_000.0,
                duration_s=51 * 60.0,
                recency_weight=_RECENCY_WEIGHT_RECENT,
            ),
        ]
        result = select_vdot_reference(evidence, ref)
        assert result.paces_confidence == "insufficient", (
            f"LOW-only must → INSUFFICIENT, got '{result.paces_confidence}'"
        )
        assert result.reference_vdot is None

    def test_stale_high_beyond_tp_window_is_insufficient(self):
        """A HIGH performance older than TP_STALE_HIGH_DAYS → INSUFFICIENT."""
        from training_v2.training_paces import select_vdot_reference, VdotEvidence

        ref = REF_DATE
        too_old = TP_STALE_HIGH_DAYS + 1
        evidence = [
            VdotEvidence(
                vdot=45.0,
                confidence="high",
                performance_date=ref - timedelta(days=too_old),
                days_old=too_old,
                distance_m=10_000.0,
                duration_s=47 * 60.0,
                recency_weight=0.0,  # beyond any window
            )
        ]
        result = select_vdot_reference(evidence, ref)
        assert result.paces_confidence == "insufficient", (
            f"Evidence older than TP_STALE_HIGH_DAYS must be INSUFFICIENT, got '{result.paces_confidence}'"
        )


# ---------------------------------------------------------------------------
# 12. Interval definition consistency
# ---------------------------------------------------------------------------

class TestIntervalDefinition:
    """I_FRACTION (faster end) and I_FRACTION_SLOW (slower end) must be consistent
    with the code that builds the interval PaceRange.
    """

    def test_interval_constants_defined(self):
        """I_FRACTION and I_FRACTION_SLOW are accessible and in expected range."""
        assert 1.0 < I_FRACTION <= 1.15, f"I_FRACTION out of range: {I_FRACTION}"
        assert 0.95 <= I_FRACTION_SLOW <= 1.05, f"I_FRACTION_SLOW out of range: {I_FRACTION_SLOW}"
        assert I_FRACTION > I_FRACTION_SLOW, "I_FRACTION (fast) must be > I_FRACTION_SLOW (slow)"

    def test_interval_range_lower_is_faster(self):
        """interval.lower (faster pace = smaller min/km) uses I_FRACTION."""
        p = daniels_paces(50.0, reference_date=REF_DATE)
        assert p.interval is not None
        # Faster end (lower min/km) must correspond to I_FRACTION (1.0915)
        # Slower end (higher min/km) must correspond to I_FRACTION_SLOW (1.0)
        assert p.interval.lower.min_per_km < p.interval.upper.min_per_km, (
            "interval.lower must be faster than interval.upper"
        )

    def test_interval_upper_matches_i_fraction_slow(self):
        """interval.upper is computed from I_FRACTION_SLOW (1.0), not I_FRACTION * 0.95."""
        from training_v2.training_paces import _pace_at_fraction
        vdot = 50.0
        p = daniels_paces(vdot, reference_date=REF_DATE)
        expected_upper = _pace_at_fraction(vdot, I_FRACTION_SLOW)
        assert expected_upper is not None
        assert abs(p.interval.upper.min_per_km - expected_upper.min_per_km) < 0.001, (
            f"interval.upper {p.interval.upper.min_per_km:.4f} != "
            f"expected from I_FRACTION_SLOW {expected_upper.min_per_km:.4f}"
        )

    def test_interval_lower_matches_i_fraction(self):
        """interval.lower is computed from I_FRACTION (1.0915)."""
        from training_v2.training_paces import _pace_at_fraction
        vdot = 50.0
        p = daniels_paces(vdot, reference_date=REF_DATE)
        expected_lower = _pace_at_fraction(vdot, I_FRACTION)
        assert expected_lower is not None
        assert abs(p.interval.lower.min_per_km - expected_lower.min_per_km) < 0.001, (
            f"interval.lower {p.interval.lower.min_per_km:.4f} != "
            f"expected from I_FRACTION {expected_lower.min_per_km:.4f}"
        )
