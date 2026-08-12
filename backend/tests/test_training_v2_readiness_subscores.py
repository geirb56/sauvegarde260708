"""R2A — Tests for Readiness Subscores V2."""

from __future__ import annotations

import ast
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.readiness_signals import ReadinessLoadSignal
from training_v2.readiness_subscores import (
    LoadSubscore,
    PhysioSubscore,
    ReadinessSubscores,
    SleepSubscore,
    build_load_subscore,
    build_physio_subscore,
    build_readiness_subscores,
    build_sleep_subscore,
)
from training_v2.training_intensity import TrainingIntensityProfile


def _load_signal(change: float | None) -> ReadinessLoadSignal:
    return ReadinessLoadSignal(
        acute_load_7d=300.0,
        chronic_weekly_load=250.0,
        load_change_percent=change,
        acwr=1.2,
    )


def _intensity_profile(
    *,
    coverage: float | None,
    moderate: float | None,
    vigorous: float | None,
) -> TrainingIntensityProfile:
    return TrainingIntensityProfile(
        reference_date=date(2026, 8, 12),
        window_days=2,
        duration_minutes=60.0,
        moderate_minutes=moderate,
        vigorous_minutes=vigorous,
        activities_total=1 if coverage is not None else 0,
        activities_with_intensity=1 if coverage and coverage > 0 else 0,
        activities_without_intensity=0 if coverage and coverage > 0 else 1 if coverage is not None else 0,
        intensity_coverage_ratio=coverage,
    )


class TestPhysioSubscore:
    def test_rhr_improvement_100(self):
        sub = build_physio_subscore(rhr_delta_bpm=-1.0, hrv_delta_percent=None)
        assert sub.rhr_component == 100.0
        assert sub.score == 100.0

    def test_rhr_plus_1(self):
        assert build_physio_subscore(rhr_delta_bpm=1.0, hrv_delta_percent=None).score == 90.0

    def test_rhr_plus_3(self):
        assert build_physio_subscore(rhr_delta_bpm=3.0, hrv_delta_percent=None).score == 75.0

    def test_rhr_plus_5(self):
        assert build_physio_subscore(rhr_delta_bpm=5.0, hrv_delta_percent=None).score == 55.0

    def test_rhr_plus_7(self):
        assert build_physio_subscore(rhr_delta_bpm=7.0, hrv_delta_percent=None).score == 35.0

    def test_rhr_above_8(self):
        assert build_physio_subscore(rhr_delta_bpm=9.0, hrv_delta_percent=None).score == 20.0

    def test_hrv_stable(self):
        assert build_physio_subscore(rhr_delta_bpm=None, hrv_delta_percent=0.0).score == 100.0

    def test_hrv_minus_7(self):
        assert build_physio_subscore(rhr_delta_bpm=None, hrv_delta_percent=-7.0).score == 90.0

    def test_hrv_minus_15(self):
        assert build_physio_subscore(rhr_delta_bpm=None, hrv_delta_percent=-15.0).score == 70.0

    def test_hrv_minus_25(self):
        assert build_physio_subscore(rhr_delta_bpm=None, hrv_delta_percent=-25.0).score == 45.0

    def test_hrv_below_minus_30(self):
        assert build_physio_subscore(rhr_delta_bpm=None, hrv_delta_percent=-31.0).score == 25.0

    def test_rhr_and_hrv_mean(self):
        sub = build_physio_subscore(rhr_delta_bpm=3.0, hrv_delta_percent=-15.0)
        assert sub.rhr_component == 75.0
        assert sub.hrv_component == 70.0
        assert sub.score == pytest.approx(72.5)

    def test_rhr_only(self):
        sub = build_physio_subscore(rhr_delta_bpm=1.0, hrv_delta_percent=None)
        assert sub.rhr_component == 90.0
        assert sub.hrv_component is None
        assert sub.score == 90.0

    def test_hrv_only(self):
        sub = build_physio_subscore(rhr_delta_bpm=None, hrv_delta_percent=-15.0)
        assert sub.rhr_component is None
        assert sub.hrv_component == 70.0
        assert sub.score == 70.0

    def test_both_absent_none(self):
        sub = build_physio_subscore(rhr_delta_bpm=None, hrv_delta_percent=None)
        assert sub.rhr_component is None
        assert sub.hrv_component is None
        assert sub.score is None


class TestSleepSubscore:
    def test_8h(self):
        assert build_sleep_subscore(sleep_duration_hours=8.0).score == 100.0

    def test_7_5h(self):
        assert build_sleep_subscore(sleep_duration_hours=7.5).score == 90.0

    def test_6_5h(self):
        assert build_sleep_subscore(sleep_duration_hours=6.5).score == 70.0

    def test_5_5h(self):
        assert build_sleep_subscore(sleep_duration_hours=5.5).score == 45.0

    def test_below_5h(self):
        assert build_sleep_subscore(sleep_duration_hours=4.9).score == 20.0

    def test_9h_no_penalty(self):
        assert build_sleep_subscore(sleep_duration_hours=9.0).score == 100.0

    def test_none_is_none(self):
        assert build_sleep_subscore(sleep_duration_hours=None).score is None


class TestLoadSubscore:
    def test_stable_load(self):
        assert build_load_subscore(load_signal=_load_signal(0.0), recent_intensity_profile=None).score == 100.0

    def test_plus_10_percent(self):
        assert build_load_subscore(load_signal=_load_signal(10.0), recent_intensity_profile=None).score == 100.0

    def test_plus_20_percent(self):
        assert build_load_subscore(load_signal=_load_signal(20.0), recent_intensity_profile=None).score == 90.0

    def test_plus_30_percent(self):
        assert build_load_subscore(load_signal=_load_signal(30.0), recent_intensity_profile=None).score == 75.0

    def test_plus_50_percent(self):
        assert build_load_subscore(load_signal=_load_signal(50.0), recent_intensity_profile=None).score == 55.0

    def test_60_percent(self):
        assert build_load_subscore(load_signal=_load_signal(60.0), recent_intensity_profile=None).score == 55.0

    def test_load_decrease(self):
        assert build_load_subscore(load_signal=_load_signal(-20.0), recent_intensity_profile=None).score == 100.0

    def test_load_change_percent_none(self):
        assert build_load_subscore(load_signal=_load_signal(None), recent_intensity_profile=None).score is None

    def test_intensity_profile_absent_no_modifier(self):
        assert build_load_subscore(load_signal=_load_signal(20.0), recent_intensity_profile=None).score == 90.0

    def test_coverage_none_no_modifier(self):
        profile = _intensity_profile(coverage=None, moderate=10.0, vigorous=10.0)
        assert build_load_subscore(load_signal=_load_signal(20.0), recent_intensity_profile=profile).score == 90.0

    def test_moderate_none_and_vigorous_none_no_modifier(self):
        profile = _intensity_profile(coverage=0.5, moderate=None, vigorous=None)
        assert build_load_subscore(load_signal=_load_signal(20.0), recent_intensity_profile=profile).score == 90.0

    def test_explicit_zero_is_not_none(self):
        profile = _intensity_profile(coverage=1.0, moderate=0.0, vigorous=0.0)
        assert build_load_subscore(load_signal=_load_signal(20.0), recent_intensity_profile=profile).score == 90.0

    def test_partial_data_moderate_only_small_penalty(self):
        profile = _intensity_profile(coverage=1.0, moderate=20.0, vigorous=None)
        assert build_load_subscore(load_signal=_load_signal(20.0), recent_intensity_profile=profile).score == 85.0

    def test_vigorous_known_extra_penalty_capped(self):
        profile = _intensity_profile(coverage=1.0, moderate=10.0, vigorous=5.0)
        assert build_load_subscore(load_signal=_load_signal(20.0), recent_intensity_profile=profile).score == 80.0

    def test_load_signal_none(self):
        assert build_load_subscore(load_signal=None, recent_intensity_profile=None).score is None


class TestArchitecture:
    def test_bundle_determinism(self):
        profile = _intensity_profile(coverage=1.0, moderate=20.0, vigorous=0.0)
        s1 = build_readiness_subscores(
            rhr_delta_bpm=3.0,
            hrv_delta_percent=-15.0,
            sleep_duration_hours=7.5,
            load_signal=_load_signal(30.0),
            recent_intensity_profile=profile,
        )
        s2 = build_readiness_subscores(
            rhr_delta_bpm=3.0,
            hrv_delta_percent=-15.0,
            sleep_duration_hours=7.5,
            load_signal=_load_signal(30.0),
            recent_intensity_profile=profile,
        )
        assert s1 == s2

    def test_scores_bounded_0_100(self):
        subs = build_readiness_subscores(
            rhr_delta_bpm=999.0,
            hrv_delta_percent=-999.0,
            sleep_duration_hours=100.0,
            load_signal=_load_signal(999.0),
            recent_intensity_profile=_intensity_profile(coverage=1.0, moderate=1000.0, vigorous=1000.0),
        )
        for score in (subs.physio.score, subs.sleep.score, subs.load.score):
            assert score is not None
            assert 0.0 <= score <= 100.0

    def test_no_final_readiness_fields(self):
        subs = build_readiness_subscores(
            rhr_delta_bpm=None,
            hrv_delta_percent=None,
            sleep_duration_hours=None,
            load_signal=None,
            recent_intensity_profile=None,
        )
        assert not hasattr(subs, "readiness_score")
        assert not hasattr(subs, "readiness_status")
        assert not hasattr(subs, "recommendation")
        assert not hasattr(subs, "final_score")

    def test_contract_types(self):
        subs = build_readiness_subscores(
            rhr_delta_bpm=1.0,
            hrv_delta_percent=-7.0,
            sleep_duration_hours=7.5,
            load_signal=_load_signal(20.0),
            recent_intensity_profile=None,
        )
        assert isinstance(subs, ReadinessSubscores)
        assert isinstance(subs.physio, PhysioSubscore)
        assert isinstance(subs.sleep, SleepSubscore)
        assert isinstance(subs.load, LoadSubscore)

    def test_module_has_no_datetime_now(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "training_v2"
            / "readiness_subscores.py"
        )
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "now"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "datetime"
            ):
                raise AssertionError("Forbidden datetime.now() call found")

    def test_no_provider_dependency(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "training_v2"
            / "readiness_subscores.py"
        )
        tree = ast.parse(src.read_text())
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        names.append(alias.name)
                elif node.module:
                    names.append(node.module)
        for name in names:
            assert not name.startswith("garmin"), f"Forbidden import: {name}"
            assert not name.startswith("terra"), f"Forbidden import: {name}"
            assert not name.startswith("strava"), f"Forbidden import: {name}"

    def test_imports_still_valid(self):
        from training_v2 import (
            PhysioBaseline,
            PhysioSignal,
            ReadinessSufficiency,
            ReadinessSufficiencyInput,
            TrainingIntensityProfile,
            TrainingLoadSnapshot,
        )
        from training_v2.readiness_signals import (
            compute_hrv_deviation,
            compute_rhr_deviation,
            extract_load_signal,
            extract_sleep_signal,
        )

        assert PhysioBaseline is not None
        assert PhysioSignal is not None
        assert ReadinessSufficiency is not None
        assert ReadinessSufficiencyInput is not None
        assert TrainingIntensityProfile is not None
        assert TrainingLoadSnapshot is not None
        assert compute_rhr_deviation is not None
        assert compute_hrv_deviation is not None
        assert extract_sleep_signal is not None
        assert extract_load_signal is not None
