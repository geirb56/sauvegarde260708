"""PR134 — Weekly Reconciliation V2 tests."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")

from training_v2.training_response import RecentTrainingResponse
from training_v2.weekly_reconciliation import (
    WeeklyReconciliationAction,
    build_weekly_reconciliation,
)
from training_v2.weekly_target import WeeklyTarget

REF = date(2026, 8, 17)
MODULE_PATH = Path(__file__).resolve().parents[1] / "training_v2" / "weekly_reconciliation.py"


def _source_text() -> str:
    with MODULE_PATH.open("r", encoding="utf-8") as handle:
        return handle.read()


def _target_distance(
    *,
    sessions: int = 4,
    km: float = 40.0,
    allow_intensity: bool = True,
    continuity: str = "normal",
) -> WeeklyTarget:
    return WeeklyTarget(
        reference_date=REF,
        target_basis="distance",
        target_km=km,
        target_duration_minutes=None,
        target_sessions=sessions,
        allow_intensity=allow_intensity,
        confidence="medium",
        continuity_state=continuity,
        reason_codes=("BASE_TARGET",),
    )


def _target_duration(
    *,
    sessions: int = 3,
    minutes: int = 120,
    allow_intensity: bool = False,
    continuity: str = "deep_reprise",
) -> WeeklyTarget:
    return WeeklyTarget(
        reference_date=REF,
        target_basis="duration",
        target_km=None,
        target_duration_minutes=minutes,
        target_sessions=sessions,
        allow_intensity=allow_intensity,
        confidence="medium",
        continuity_state=continuity,
        reason_codes=("BASE_TARGET",),
    )


def _response(
    *,
    status: str = "sufficient",
    confidence: str = "moderate",
    observed_runs_per_week: float = 4.0,
    observed_distance_km: float = 152.0,
    observed_duration_minutes: float = 560.0,
    volume_trend: str = "stable",
    frequency_pattern: str = "stable",
    long_run_trend: str = "stable",
    cardiac_efficiency_trend: str = "stable",
) -> RecentTrainingResponse:
    observed_runs = int(round(observed_runs_per_week * 4))
    return RecentTrainingResponse(
        reference_date=REF,
        window_days=28,
        available_running_activities=8,
        selected_running_activities=8,
        response_status=status,
        confidence=confidence,
        observed_distance_km=observed_distance_km,
        observed_duration_minutes=observed_duration_minutes,
        observed_runs=observed_runs,
        observed_runs_per_week=observed_runs_per_week,
        longest_run_km=16.0,
        longest_run_duration_minutes=90.0,
        hr_coverage_count=6,
        intensity_coverage_count=6,
        average_hr_recent=145.0,
        average_pace_recent_s_per_km=340.0,
        cardiac_efficiency_samples=(0.020, 0.021, 0.019, 0.020),
        cardiac_efficiency_trend=cardiac_efficiency_trend,
        volume_trend=volume_trend,
        frequency_pattern=frequency_pattern,
        long_run_trend=long_run_trend,
        intensity_exposure_trend="stable",
        reason_codes=(),
    )


def test_a_recent_response_none_keep():
    target = _target_distance()
    result = build_weekly_reconciliation(proposed_target=target, recent_response=None)
    assert result.action == WeeklyReconciliationAction.KEEP
    assert "RECENT_RESPONSE_UNAVAILABLE" in result.reason_codes


def test_b_response_unavailable_keep():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(),
        recent_response=_response(status="unavailable", confidence="none"),
    )
    assert result.action == WeeklyReconciliationAction.KEEP
    assert "RECENT_RESPONSE_UNAVAILABLE" in result.reason_codes


def test_c_response_insufficient_keep():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(),
        recent_response=_response(status="insufficient", confidence="low"),
    )
    assert result.action == WeeklyReconciliationAction.KEEP
    assert "RECENT_RESPONSE_INSUFFICIENT" in result.reason_codes


def test_d_target_4_observed_compatible_keep():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4, km=40.0),
        recent_response=_response(observed_runs_per_week=3.5, observed_distance_km=152.0),
    )
    assert result.action == WeeklyReconciliationAction.KEEP


def test_e_target_4_observed_low_reduce_frequency():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4, km=40.0),
        recent_response=_response(observed_runs_per_week=2.5, observed_distance_km=160.0),
    )
    assert result.action == WeeklyReconciliationAction.REDUCE_BOTH
    assert result.reconciled_target.target_sessions == 3
    assert result.reconciled_target.target_km == 30.0


def test_f_target_3_observed_3_keep():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=3, km=30.0),
        recent_response=_response(observed_runs_per_week=3.0, observed_distance_km=120.0),
    )
    assert result.action == WeeklyReconciliationAction.KEEP


def test_g_distance_target_compatible_keep():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(km=40.0),
        recent_response=_response(observed_distance_km=136.0),
    )
    assert result.action == WeeklyReconciliationAction.KEEP


def test_h_distance_target_far_above_observed_reduce_volume():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(km=40.0),
        recent_response=_response(observed_runs_per_week=4.0, observed_distance_km=88.0),
    )
    assert result.action == WeeklyReconciliationAction.REDUCE_VOLUME
    assert result.reconciled_target.target_km == 34.0


def test_i_volume_and_frequency_under_target_reduce_both():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(km=40.0, sessions=4),
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=88.0),
    )
    assert result.action == WeeklyReconciliationAction.REDUCE_BOTH
    assert result.reconciled_target.target_sessions == 3
    assert result.reconciled_target.target_km == 30.0


def test_j_duration_based_target_reduction_possible():
    result = build_weekly_reconciliation(
        proposed_target=_target_duration(minutes=120, sessions=3, continuity="deep_reprise"),
        recent_response=_response(observed_runs_per_week=3.0, observed_duration_minutes=300.0),
    )
    assert result.action == WeeklyReconciliationAction.REDUCE_VOLUME
    assert result.reconciled_target.target_duration_minutes == 102


def test_k_duration_target_no_km_conversion():
    result = build_weekly_reconciliation(
        proposed_target=_target_duration(minutes=120, sessions=3),
        recent_response=_response(
            observed_distance_km=20.0,
            observed_duration_minutes=440.0,
            observed_runs_per_week=3.0,
        ),
    )
    assert result.action == WeeklyReconciliationAction.KEEP
    assert result.reconciled_target.target_km is None


def test_l_volume_trend_decreasing_alone_no_auto_reduction():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(km=40.0),
        recent_response=_response(observed_distance_km=136.0, volume_trend="decreasing"),
    )
    assert result.action == WeeklyReconciliationAction.KEEP


def test_m_frequency_pattern_decreasing_alone_no_auto_reduction():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4),
        recent_response=_response(observed_runs_per_week=3.2, frequency_pattern="decreasing"),
    )
    assert result.action == WeeklyReconciliationAction.KEEP


def test_n_cardiac_decreasing_alone_no_auto_reduction():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(km=40.0, sessions=4),
        recent_response=_response(
            observed_runs_per_week=3.5,
            observed_distance_km=152.0,
            cardiac_efficiency_trend="decreasing",
        ),
    )
    assert result.action == WeeklyReconciliationAction.KEEP
    assert "RECENT_CARDIAC_RESPONSE_CAUTION" in result.reason_codes


def test_o_favorable_response_never_increases():
    target = _target_distance(km=40.0, sessions=4)
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=6.0, observed_distance_km=220.0),
    )
    assert result.action == WeeklyReconciliationAction.KEEP
    assert result.reconciled_target.target_sessions == target.target_sessions
    assert result.reconciled_target.target_km == target.target_km


def test_p_observed_runs_very_high_never_more_sessions():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4),
        recent_response=_response(observed_runs_per_week=8.0),
    )
    assert result.reconciled_target.target_sessions == 4


def test_q_observed_volume_very_high_never_more_volume():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(km=40.0),
        recent_response=_response(observed_distance_km=400.0),
    )
    assert result.reconciled_target.target_km == 40.0


def test_r_allow_intensity_unchanged():
    target = _target_distance(allow_intensity=False)
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=88.0),
    )
    assert result.reconciled_target.allow_intensity is target.allow_intensity


def test_s_continuity_state_unchanged():
    target = _target_distance(continuity="partial_reprise", allow_intensity=False)
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=88.0),
    )
    assert result.reconciled_target.continuity_state == "partial_reprise"


def test_t_deep_reprise_remains_duration_based():
    target = _target_duration(minutes=120, sessions=3, continuity="deep_reprise")
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_duration_minutes=240.0, observed_runs_per_week=2.0),
    )
    assert result.reconciled_target.target_basis == "duration"
    assert result.reconciled_target.target_km is None


def test_u_partial_reprise_protection_conserved():
    target = _target_distance(continuity="partial_reprise", allow_intensity=False)
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=88.0),
    )
    assert result.reconciled_target.continuity_state == "partial_reprise"
    assert result.reconciled_target.allow_intensity is False


def test_v_reprise_exit_protection_conserved():
    target = _target_distance(continuity="reprise_exit", allow_intensity=True)
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=88.0),
    )
    assert result.reconciled_target.continuity_state == "reprise_exit"
    assert result.reconciled_target.allow_intensity is True


def test_w_original_weekly_target_not_mutated():
    target = _target_distance(sessions=4, km=40.0)
    build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=88.0),
    )
    assert target.target_sessions == 4
    assert target.target_km == 40.0


def test_x_same_inputs_same_result():
    target = _target_distance(sessions=4, km=40.0)
    response = _response(observed_runs_per_week=2.0, observed_distance_km=88.0)
    result_a = build_weekly_reconciliation(proposed_target=target, recent_response=response)
    result_b = build_weekly_reconciliation(proposed_target=target, recent_response=response)
    assert result_a == result_b


def test_y_no_datetime_now_or_today_calls():
    source = _source_text()
    assert "datetime.now(" not in source
    assert "date.today(" not in source


def test_z_no_garmin_or_gccli_import():
    source = _source_text().lower()
    assert "garmin" not in source
    assert "gccli" not in source


def test_aa_no_db_http_redis():
    source = _source_text().lower()
    assert "import pymongo" not in source
    assert "from pymongo" not in source
    assert "import redis" not in source
    assert "from redis" not in source
    assert "import requests" not in source
    assert "from requests" not in source
    assert "import http" not in source
    assert "from http" not in source


def test_ab_no_llm_or_random():
    source = _source_text().lower()
    assert "import openai" not in source
    assert "from openai" not in source
    assert "import anthropic" not in source
    assert "from anthropic" not in source
    assert "import random" not in source


def test_ac_no_training_engine_import():
    source = _source_text()
    assert "training_engine" not in source


def test_ad_no_lt1_lt2_logic():
    source = _source_text().lower()
    assert "lt1" not in source
    assert "lt2" not in source


def test_ae_no_move_action():
    assert "MOVE" not in {action.value for action in WeeklyReconciliationAction}


def test_af_no_trail_or_elevation_logic():
    source = _source_text().lower()
    assert "trail" not in source
    assert "elevation" not in source


def test_real_case_1_target_4_40_observed_4_38_keep():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4, km=40.0),
        recent_response=_response(observed_runs_per_week=4.0, observed_distance_km=152.0),
    )
    assert result.action == WeeklyReconciliationAction.KEEP


def test_real_case_2_target_4_40_observed_2_22_reduce_both():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4, km=40.0),
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=88.0),
    )
    assert result.action == WeeklyReconciliationAction.REDUCE_BOTH
    assert result.reconciled_target.target_sessions == 3
    assert result.reconciled_target.target_km == 30.0


def test_real_case_3_target_3_30_observed_3_23_reduce_volume_only():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=3, km=30.0),
        recent_response=_response(observed_runs_per_week=3.0, observed_distance_km=92.0),
    )
    assert result.action == WeeklyReconciliationAction.REDUCE_VOLUME


def test_real_case_4_target_3_30_observed_3_35_keep_never_increase():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=3, km=30.0),
        recent_response=_response(observed_runs_per_week=3.0, observed_distance_km=140.0),
    )
    assert result.action == WeeklyReconciliationAction.KEEP
    assert result.reconciled_target.target_km == 30.0


def test_real_case_5_deep_reprise_120_3_observed_100_keep_duration_based():
    result = build_weekly_reconciliation(
        proposed_target=_target_duration(minutes=120, sessions=3, continuity="deep_reprise"),
        recent_response=_response(observed_runs_per_week=3.0, observed_duration_minutes=400.0),
    )
    assert result.action == WeeklyReconciliationAction.KEEP
    assert result.reconciled_target.target_basis == "duration"
    assert result.reconciled_target.allow_intensity is False


def test_b1_target_5_observed_1_5_frequency_reduction_capped_to_4():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=5, km=50.0),
        recent_response=_response(observed_runs_per_week=1.5, observed_distance_km=200.0),
    )
    assert result.reconciled_target.target_sessions == 4
    assert "SESSION_FREQUENCY_REDUCTION_CAPPED" in result.reason_codes


def test_b2_target_4_observed_2_0_new_sessions_3():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4, km=40.0),
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=160.0),
    )
    assert result.reconciled_target.target_sessions == 3


def test_b3_target_3_observed_1_0_new_sessions_2():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=3, km=30.0),
        recent_response=_response(observed_runs_per_week=1.0, observed_distance_km=120.0),
    )
    assert result.reconciled_target.target_sessions == 2


def test_b4_frequency_reduce_with_compatible_volume_forces_reduce_both_to_session_safe_max():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4, km=40.0),
        recent_response=_response(observed_runs_per_week=2.5, observed_distance_km=160.0),
    )
    assert result.reconciled_target.target_sessions == 3
    assert result.reconciled_target.target_km == 30.0
    assert result.action == WeeklyReconciliationAction.REDUCE_BOTH
    assert "SESSION_LOAD_CONCENTRATION_GUARD" in result.reason_codes
    assert "VOLUME_REDUCED_FOR_FREQUENCY_SAFETY" in result.reason_codes


def test_b5_volume_only_reduction_keeps_floor_when_frequency_unchanged():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4, km=40.0),
        recent_response=_response(observed_runs_per_week=4.0, observed_distance_km=88.0),
    )
    assert result.reconciled_target.target_sessions == 4
    assert result.reconciled_target.target_km == 34.0
    assert result.action == WeeklyReconciliationAction.REDUCE_VOLUME
    assert "SESSION_LOAD_CONCENTRATION_GUARD" not in result.reason_codes


def test_b6_frequency_and_volume_low_final_volume_capped_by_session_safety():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=4, km=40.0),
        recent_response=_response(observed_runs_per_week=2.0, observed_distance_km=88.0),
    )
    assert result.reconciled_target.target_sessions == 3
    assert result.reconciled_target.target_km <= 30.0
    assert result.action == WeeklyReconciliationAction.REDUCE_BOTH


def test_b7_deep_reprise_duration_guard_applies_with_frequency_reduction():
    target = _target_duration(minutes=120, sessions=3, continuity="deep_reprise")
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=1.5, observed_duration_minutes=560.0),
    )
    assert result.reconciled_target.target_sessions == 2
    assert result.reconciled_target.target_duration_minutes <= 80
    assert result.reconciled_target.target_basis == "duration"
    assert result.reconciled_target.allow_intensity is target.allow_intensity
    assert result.reconciled_target.continuity_state == target.continuity_state
    assert result.reconciled_target.target_km is None


def test_b8_target_sessions_1_never_goes_to_zero():
    result = build_weekly_reconciliation(
        proposed_target=_target_distance(sessions=1, km=10.0),
        recent_response=_response(observed_runs_per_week=0.1, observed_distance_km=40.0),
    )
    assert result.reconciled_target.target_sessions == 1


def test_b9_distance_average_per_session_never_increases_when_frequency_reduced():
    target = _target_distance(sessions=4, km=40.0)
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=2.5, observed_distance_km=160.0),
    )
    assert result.reconciled_target.target_sessions < target.target_sessions
    new_avg = result.reconciled_target.target_km / result.reconciled_target.target_sessions
    old_avg = target.target_km / target.target_sessions
    assert new_avg <= old_avg + 1e-9


def test_c1_duration_average_per_session_never_increases_when_frequency_reduced():
    target = _target_duration(minutes=120, sessions=3)
    result = build_weekly_reconciliation(
        proposed_target=target,
        recent_response=_response(observed_runs_per_week=1.5, observed_duration_minutes=560.0),
    )
    assert result.reconciled_target.target_sessions < target.target_sessions
    new_avg = result.reconciled_target.target_duration_minutes / result.reconciled_target.target_sessions
    old_avg = target.target_duration_minutes / target.target_sessions
    assert new_avg <= old_avg + 1e-9
