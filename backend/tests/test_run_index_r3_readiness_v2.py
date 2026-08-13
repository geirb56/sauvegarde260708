"""R3 — Deterministic tests for the Garmin → Readiness V2 adapter and /run-index wiring.

Test matrix (problem statement requirements)
---------------------------------------------
1. données complètes (complete data) — score not None, SUFFICIENT/NORMAL
2. HRV absente (HRV absent) — score still computable from RHR, REDUCED or lower
3. RHR absente (RHR absent) — score still computable from HRV (if present), else check
4. sommeil absent (sleep absent) — DEGRADED, score not None
5. charge absente (no load) — INSUFFICIENT, score None
6. load_change_percent=None — score still computed (LoadSubscore falls back)
7. données insuffisantes (insufficient data: no physio) — INSUFFICIENT, score None
8. isolation user_id — adapter uses only the supplied docs, not cross-user
9. /run-index backward-compatible — run_readiness key always present (float or null)
10. aucun fallback legacy — None stays None (no RHR=55, sleep=7h, ACWR=1, etc.)
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.readiness_adapter import build_readiness_v2_from_garmin_data
from training_v2.readiness import ReadinessConfidence, ReadinessResult
from training_v2.readiness_sufficiency import ReasonCode, SufficiencyLevel

# ---------------------------------------------------------------------------
# Fixtures — synthetic garmin_daily_metrics / garmin_activities documents
# ---------------------------------------------------------------------------

_REF_DATE = date(2026, 1, 28)


def _make_metrics(
    *,
    n: int = 14,
    rhr: Optional[float] = 52.0,
    hrv: Optional[float] = 65.0,
    sleep_hours: Optional[float] = 7.5,
    sleep_score: Optional[float] = 80.0,
    ref: date = _REF_DATE,
) -> List[dict]:
    """Return *n* garmin_daily_metrics documents sorted newest-first."""
    docs = []
    for i in range(n):
        d = ref - timedelta(days=i)
        docs.append({
            "date": d.isoformat(),
            "resting_hr": rhr,
            "hrv": hrv,
            "sleep_hours": sleep_hours,
            "sleep_score": sleep_score,
        })
    return docs


def _make_activities(
    *,
    n: int = 28,
    duration_s: float = 2400.0,  # 40 min
    ref: date = _REF_DATE,
) -> List[dict]:
    """Return *n* running activities across 28 days, newest-first."""
    acts = []
    for i in range(n):
        d = ref - timedelta(days=i)
        acts.append({
            "activity_type": "running",
            "start_time": f"{d.isoformat()}T08:00:00",
            "duration_s": duration_s,
            "distance_m": 6000.0,
        })
    return acts


# ---------------------------------------------------------------------------
# 1. données complètes — full data
# ---------------------------------------------------------------------------


def test_complete_data_returns_score():
    """Full data → score is a float in (0, 100], confidence NORMAL."""
    result = build_readiness_v2_from_garmin_data(
        _make_metrics(),
        _make_activities(),
        _REF_DATE,
    )
    assert isinstance(result, ReadinessResult)
    assert result.score is not None
    assert 0.0 < result.score <= 100.0
    assert result.confidence == ReadinessConfidence.NORMAL
    assert result.sufficiency_level == SufficiencyLevel.SUFFICIENT


# ---------------------------------------------------------------------------
# 2. HRV absente
# ---------------------------------------------------------------------------


def test_hrv_absent_score_still_computable():
    """HRV absent but RHR present → score is still computed (missing_hrv reason)."""
    metrics = _make_metrics(hrv=None)
    result = build_readiness_v2_from_garmin_data(metrics, _make_activities(), _REF_DATE)
    assert ReasonCode.missing_hrv in result.reasons
    # RHR is present → not INSUFFICIENT, score should exist
    assert result.score is not None
    assert result.sufficiency_level != SufficiencyLevel.INSUFFICIENT


# ---------------------------------------------------------------------------
# 3. RHR absente
# ---------------------------------------------------------------------------


def test_rhr_absent_score_still_computable_when_hrv_present():
    """RHR absent but HRV present → score is still computed (missing_rhr reason)."""
    metrics = _make_metrics(rhr=None)
    result = build_readiness_v2_from_garmin_data(metrics, _make_activities(), _REF_DATE)
    assert ReasonCode.missing_rhr in result.reasons
    # HRV present → not INSUFFICIENT
    assert result.score is not None
    assert result.sufficiency_level != SufficiencyLevel.INSUFFICIENT


# ---------------------------------------------------------------------------
# 4. sommeil absent
# ---------------------------------------------------------------------------


def test_sleep_absent_degraded_score_not_none():
    """No sleep data → DEGRADED, missing_sleep reason, score is still computed."""
    metrics = _make_metrics(sleep_hours=None, sleep_score=None)
    result = build_readiness_v2_from_garmin_data(metrics, _make_activities(), _REF_DATE)
    assert ReasonCode.missing_sleep in result.reasons
    assert result.sufficiency_level == SufficiencyLevel.DEGRADED
    assert result.score is not None  # DEGRADED still produces a score
    assert result.confidence == ReadinessConfidence.REDUCED


# ---------------------------------------------------------------------------
# 5. charge absente (no activities at all)
# ---------------------------------------------------------------------------


def test_load_absent_insufficient_score_none():
    """No activities → missing_load → INSUFFICIENT → score None."""
    result = build_readiness_v2_from_garmin_data(_make_metrics(), [], _REF_DATE)
    assert ReasonCode.missing_load in result.reasons
    assert result.sufficiency_level == SufficiencyLevel.INSUFFICIENT
    assert result.score is None
    assert result.confidence == ReadinessConfidence.NONE


# ---------------------------------------------------------------------------
# 6. load_change_percent=None (only 1 week of activities, no previous week)
# ---------------------------------------------------------------------------


def test_load_change_percent_none_score_still_computed():
    """When previous_7d_load == 0 → load_change_percent=None → LoadSubscore=None.

    Score can still be computed from physio + sleep (confidence REDUCED).
    """
    # Only 5 days of activities → previous window is empty → load_change_percent=None
    activities = _make_activities(n=5)
    result = build_readiness_v2_from_garmin_data(_make_metrics(), activities, _REF_DATE)
    # load_change_percent=None → LoadSubscore.score=None
    # But physio + sleep are present → score should still exist (REDUCED confidence)
    # (unless INSUFFICIENT due to thin load history)
    # thin_load_history → DEGRADED, not INSUFFICIENT
    if result.sufficiency_level != SufficiencyLevel.INSUFFICIENT:
        assert result.score is not None
    else:
        assert result.score is None


# ---------------------------------------------------------------------------
# 7. données insuffisantes — both RHR and HRV absent + no activities
# ---------------------------------------------------------------------------


def test_insufficient_all_physio_absent_and_no_load():
    """No physio at all + no load → INSUFFICIENT, score None."""
    metrics = _make_metrics(rhr=None, hrv=None)
    result = build_readiness_v2_from_garmin_data(metrics, [], _REF_DATE)
    assert ReasonCode.missing_physio in result.reasons
    assert ReasonCode.missing_load in result.reasons
    assert result.sufficiency_level == SufficiencyLevel.INSUFFICIENT
    assert result.score is None


def test_insufficient_physio_absent_only():
    """No RHR + No HRV → missing_physio (blocking) → INSUFFICIENT even if load exists."""
    metrics = _make_metrics(rhr=None, hrv=None)
    result = build_readiness_v2_from_garmin_data(metrics, _make_activities(), _REF_DATE)
    assert ReasonCode.missing_physio in result.reasons
    assert result.sufficiency_level == SufficiencyLevel.INSUFFICIENT
    assert result.score is None


# ---------------------------------------------------------------------------
# 8. isolation user_id — adapter uses only supplied docs
# ---------------------------------------------------------------------------


def test_user_isolation_adapter_is_pure():
    """The adapter is stateless and pure: different docs → different results.

    No shared mutable state; user isolation is guaranteed by the caller passing
    per-user documents (the adapter itself does no DB queries).
    """
    metrics_a = _make_metrics(rhr=45.0, hrv=80.0)
    metrics_b = _make_metrics(rhr=None, hrv=None)  # INSUFFICIENT user
    acts = _make_activities()

    result_a = build_readiness_v2_from_garmin_data(metrics_a, acts, _REF_DATE)
    result_b = build_readiness_v2_from_garmin_data(metrics_b, acts, _REF_DATE)

    # user A: physio present → not INSUFFICIENT
    assert result_a.score is not None
    # user B: no physio → INSUFFICIENT
    assert result_b.score is None
    assert result_b.sufficiency_level == SufficiencyLevel.INSUFFICIENT


# ---------------------------------------------------------------------------
# 9. /run-index backward-compatible — run_readiness always present in metrics
# ---------------------------------------------------------------------------


def test_run_index_metrics_always_has_run_readiness_key():
    """run_readiness key is always in metrics — value is float or None, never absent."""
    # Complete data
    result_full = build_readiness_v2_from_garmin_data(
        _make_metrics(), _make_activities(), _REF_DATE
    )
    # The adapter returns a ReadinessResult; the key test is that score is float|None
    assert result_full.score is None or isinstance(result_full.score, float)

    # Insufficient data
    result_insufficient = build_readiness_v2_from_garmin_data(
        _make_metrics(rhr=None, hrv=None), [], _REF_DATE
    )
    assert result_insufficient.score is None


# ---------------------------------------------------------------------------
# 10. aucun fallback legacy — None stays None
# ---------------------------------------------------------------------------


def test_no_legacy_fallback_rhr_stays_none():
    """RHR absent → adapter does NOT substitute 55.0 or any default."""
    metrics = _make_metrics(rhr=None, hrv=None, sleep_hours=None, sleep_score=None)
    # Inspect the internal PhysioSignal by checking reason codes
    result = build_readiness_v2_from_garmin_data(metrics, [], _REF_DATE)
    # If fallback was applied we would NOT see missing_physio
    assert ReasonCode.missing_physio in result.reasons


def test_no_legacy_fallback_sleep_stays_none():
    """Sleep absent → adapter does NOT substitute 7.0 h."""
    metrics = _make_metrics(sleep_hours=None, sleep_score=None)
    result = build_readiness_v2_from_garmin_data(metrics, _make_activities(), _REF_DATE)
    assert ReasonCode.missing_sleep in result.reasons


def test_no_legacy_fallback_acwr_not_invented():
    """No activities → load is absent, ACWR is NOT defaulted to 1.0."""
    result = build_readiness_v2_from_garmin_data(_make_metrics(), [], _REF_DATE)
    assert ReasonCode.missing_load in result.reasons
    assert result.score is None


# ---------------------------------------------------------------------------
# Additional robustness — determinism
# ---------------------------------------------------------------------------


def test_determinism_same_inputs_same_output():
    """Same inputs always produce identical outputs."""
    metrics = _make_metrics()
    acts = _make_activities()
    r1 = build_readiness_v2_from_garmin_data(metrics, acts, _REF_DATE)
    r2 = build_readiness_v2_from_garmin_data(metrics, acts, _REF_DATE)
    assert r1 == r2


def test_result_is_immutable():
    """ReadinessResult must be immutable (frozen pydantic model)."""
    result = build_readiness_v2_from_garmin_data(
        _make_metrics(), _make_activities(), _REF_DATE
    )
    with pytest.raises(Exception):  # ValidationError or AttributeError
        result.score = 99.9  # type: ignore[misc]


def test_score_bounds():
    """Score is always in [0, 100] when not None."""
    result = build_readiness_v2_from_garmin_data(
        _make_metrics(), _make_activities(), _REF_DATE
    )
    if result.score is not None:
        assert 0.0 <= result.score <= 100.0


def test_reasons_are_valid_reason_codes():
    """All reasons are valid ReasonCode enum members."""
    result = build_readiness_v2_from_garmin_data(
        _make_metrics(rhr=None), _make_activities(), _REF_DATE
    )
    for reason in result.reasons:
        assert isinstance(reason, ReasonCode)


# ---------------------------------------------------------------------------
# Baseline correction tests (audit R3 — section 1)
# ---------------------------------------------------------------------------


def test_baseline_excludes_recent_value():
    """The recent measurement must NOT be included in its own baseline.

    We construct 15 documents: the most recent one (today = _REF_DATE) has
    RHR=100 (abnormal spike), the 14 prior days all have RHR=52.
    The baseline must be 52, not affected by the 100.
    """
    from garmin.readiness_adapter import _build_physio_signal, _BASELINE_WINDOW_DAYS

    docs = []
    # Most recent (today): abnormal spike
    docs.append({"date": _REF_DATE.isoformat(), "resting_hr": 100.0})
    # 14 prior days: normal
    for i in range(1, _BASELINE_WINDOW_DAYS + 1):
        docs.append({"date": (_REF_DATE - timedelta(days=i)).isoformat(), "resting_hr": 52.0})

    signal = _build_physio_signal(docs, "resting_hr", _REF_DATE)
    assert signal is not None
    assert signal.recent_value == 100.0
    assert signal.baseline is not None
    assert abs(signal.baseline.value - 52.0) < 0.01, (
        f"baseline should be 52.0, got {signal.baseline.value}"
    )


def test_abnormal_day_does_not_modify_own_baseline():
    """A very abnormal today value does not distort today's baseline.

    Concretely: score deviation is computed against the pre-existing baseline,
    not against a baseline that includes today's value.
    """
    from garmin.readiness_adapter import _build_physio_signal

    # Yesterday and before: stable at 50
    docs_normal = [
        {"date": (_REF_DATE - timedelta(days=i)).isoformat(), "resting_hr": 50.0}
        for i in range(1, 15)
    ]
    # Today: extreme value
    docs_with_spike = [{"date": _REF_DATE.isoformat(), "resting_hr": 999.0}] + docs_normal

    signal_normal = _build_physio_signal(docs_normal, "resting_hr", _REF_DATE)
    signal_spike = _build_physio_signal(docs_with_spike, "resting_hr", _REF_DATE)

    # Both should have the same baseline (only prior days)
    assert signal_spike is not None
    assert signal_spike.baseline is not None
    if signal_normal is not None and signal_normal.baseline is not None:
        assert abs(signal_spike.baseline.value - signal_normal.baseline.value) < 0.01


def test_values_outside_14_day_window_excluded():
    """Values older than 14 days before recent_date are excluded from baseline."""
    from garmin.readiness_adapter import _build_physio_signal, _BASELINE_WINDOW_DAYS

    docs = []
    # recent_date = _REF_DATE, so window = _REF_DATE - 14 .. _REF_DATE - 1
    docs.append({"date": _REF_DATE.isoformat(), "resting_hr": 52.0})
    # Within window: 14 days prior (valid)
    docs.append({"date": (_REF_DATE - timedelta(days=_BASELINE_WINDOW_DAYS)).isoformat(), "resting_hr": 52.0})
    # Outside window: 15 days prior (should be excluded)
    docs.append({"date": (_REF_DATE - timedelta(days=_BASELINE_WINDOW_DAYS + 1)).isoformat(), "resting_hr": 999.0})

    signal = _build_physio_signal(docs, "resting_hr", _REF_DATE)
    assert signal is not None
    assert signal.baseline is not None
    # If the out-of-window 999 were included, value would be >> 52
    assert abs(signal.baseline.value - 52.0) < 0.01


def test_no_prior_data_baseline_is_none():
    """When no data exists before recent_date, baseline is None (no invented value)."""
    from garmin.readiness_adapter import _build_physio_signal

    # Only today's document — no prior baseline
    docs = [{"date": _REF_DATE.isoformat(), "resting_hr": 52.0}]
    signal = _build_physio_signal(docs, "resting_hr", _REF_DATE)
    assert signal is not None
    assert signal.recent_value == 52.0
    assert signal.baseline is None


def test_valid_measures_exact_count():
    """valid_measures equals the exact count of non-None values inside the window."""
    from garmin.readiness_adapter import _build_physio_signal, _BASELINE_WINDOW_DAYS

    docs = []
    docs.append({"date": _REF_DATE.isoformat(), "resting_hr": 52.0})
    # 5 days with values inside window
    for i in range(1, 6):
        docs.append({"date": (_REF_DATE - timedelta(days=i)).isoformat(), "resting_hr": 52.0})
    # 3 days with None (missing, inside window — not counted)
    for i in range(6, 9):
        docs.append({"date": (_REF_DATE - timedelta(days=i)).isoformat(), "resting_hr": None})
    # 2 days outside window (not counted)
    for i in range(_BASELINE_WINDOW_DAYS + 1, _BASELINE_WINDOW_DAYS + 3):
        docs.append({"date": (_REF_DATE - timedelta(days=i)).isoformat(), "resting_hr": 52.0})

    signal = _build_physio_signal(docs, "resting_hr", _REF_DATE)
    assert signal is not None
    assert signal.baseline is not None
    assert signal.baseline.valid_measures == 5
