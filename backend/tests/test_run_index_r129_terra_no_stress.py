"""PR #129 correction — Terra path: no _stress formula, UNAVAILABLE recommendation.

Test matrix
-----------
A.  Source code: no runtime occurrence of _stress assignment on Terra path
B.  Source code: no 0.5 * hrv_delta weighting on Terra path
C.  Source code: no 0.3 * rhr_delta weighting on Terra path
D.  Source code: no 0.2 * sleep_score weighting on Terra path
E.  Terra path returns recommendation = UNAVAILABLE when Readiness V2 not available
F.  Terra path returns recommendation_color = gray
G.  Garmin path (compute_run_index) is unchanged: recommendation_color in green/yellow/red
H.  Terra UNAVAILABLE behavior: no physiological recommendation invented
"""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_SERVER_PY = _BACKEND / "server.py"
_SERVER_SOURCE = _SERVER_PY.read_text(encoding="utf-8")

# Locate the Terra path section (between Terra fallback comment and end of function)
# We search for the block after "Terra fallback" and before "/run-index/history"
_TERRA_SECTION_MATCH = re.search(
    r"Terra fallback.*?(?=@api_router\.get\(\"/run-index/history\")",
    _SERVER_SOURCE,
    re.DOTALL,
)
_TERRA_SECTION = _TERRA_SECTION_MATCH.group(0) if _TERRA_SECTION_MATCH else ""

# ---------------------------------------------------------------------------
# A–D: Static source checks on the Terra section
# ---------------------------------------------------------------------------


def test_no_stress_variable_assignment():
    """A. No '_stress =' assignment must exist in the Terra section."""
    assert "_stress" not in _TERRA_SECTION, (
        "Found '_stress' assignment in Terra path — forbidden by PR #129 correction.\n"
        f"Context: {_TERRA_SECTION[:500]}"
    )


def test_no_hrv_weighting():
    """B. No '0.5 * hrv_delta' or similar HRV weighting in Terra section."""
    assert "0.5 * hrv_delta" not in _TERRA_SECTION, (
        "Found '0.5 * hrv_delta' weighting in Terra path — forbidden by PR #129 correction."
    )


def test_no_rhr_weighting():
    """C. No '0.3 * rhr_delta' or similar RHR weighting in Terra section."""
    assert "0.3 * rhr_delta" not in _TERRA_SECTION, (
        "Found '0.3 * rhr_delta' weighting in Terra path — forbidden by PR #129 correction."
    )


def test_no_sleep_score_weighting():
    """D. No '0.2 * sleep_score' or similar sleep weighting in Terra section."""
    assert "0.2 * sleep_score" not in _TERRA_SECTION, (
        "Found '0.2 * sleep_score' weighting in Terra path — forbidden by PR #129 correction."
    )


def test_no_physio_threshold_5():
    """No '> 5.0' physio threshold in Terra section."""
    assert "> 5.0" not in _TERRA_SECTION, (
        "Found '> 5.0' physio threshold in Terra path — forbidden by PR #129 correction."
    )


def test_no_physio_threshold_2():
    """No '> 2.0' physio threshold in Terra section."""
    assert "> 2.0" not in _TERRA_SECTION, (
        "Found '> 2.0' physio threshold in Terra path — forbidden by PR #129 correction."
    )


# ---------------------------------------------------------------------------
# E–H: Behavioural checks via garmin.insights (Garmin path unchanged)
# ---------------------------------------------------------------------------

_TODAY = date(2026, 8, 14)
_RHR_NORMAL = 52.0
_HRV_NORMAL = 55.0


def _metric(day_offset: int, ref: date) -> dict:
    d = ref - timedelta(days=day_offset)
    return {"date": d.isoformat(), "rhr": _RHR_NORMAL, "hrv": _HRV_NORMAL,
            "sleep_hours": 7.5, "sleep_quality": 85}


def _activity(day_offset: int, ref: date) -> dict:
    return {
        "activity_type": "running",
        "start_time": (ref - timedelta(days=day_offset)).isoformat(),
        "distance_m": 8000.0,
        "duration_s": 2400.0,
    }


def _make_db(docs: List[dict], acts: List[dict]) -> MagicMock:
    db = MagicMock()
    db.garmin_connections.find_one = AsyncMock(return_value=None)
    db.daily_metrics.find_one = AsyncMock(return_value=None)
    db.baselines.find_one = AsyncMock(return_value=None)

    def _cursor(items):
        c = MagicMock()
        c.sort = MagicMock(return_value=c)
        c.limit = MagicMock(return_value=c)
        c.to_list = AsyncMock(return_value=list(items))
        c.__aiter__ = MagicMock(return_value=iter(items))
        return c

    db.garmin_daily_metrics.find = MagicMock(return_value=_cursor(docs))
    db.garmin_activities.find = MagicMock(return_value=_cursor(acts))
    return db


def test_garmin_path_recommendation_color_unchanged():
    """G. Garmin path still returns recommendation_color in green/yellow/red (not gray)."""
    from garmin.insights import compute_run_index

    docs = [_metric(i, _TODAY) for i in range(14)]
    acts = [_activity(i, _TODAY) for i in range(5)]
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    color = payload.get("recommendation_color")
    assert color in {"green", "yellow", "red"}, (
        f"Garmin path recommendation_color must be green/yellow/red, got: {color}"
    )


def test_garmin_path_readiness_v2_intact():
    """D. Garmin path: run_readiness, confidence, sufficiency_level still present."""
    from garmin.insights import compute_run_index

    docs = [_metric(i, _TODAY) for i in range(14)]
    acts = [_activity(i, _TODAY) for i in range(5)]
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    m = payload["metrics"]
    for key in ("run_readiness", "confidence", "sufficiency_level"):
        assert key in m, f"Garmin path must still expose '{key}' in metrics"


def test_terra_section_contains_unavailable():
    """E. Terra section must set recommendation = 'UNAVAILABLE'."""
    assert '"UNAVAILABLE"' in _TERRA_SECTION or "'UNAVAILABLE'" in _TERRA_SECTION, (
        "Terra path must set recommendation = 'UNAVAILABLE' — Readiness V2 not available on this path."
    )


def test_terra_section_contains_gray():
    """F. Terra section must set recommendation_color = 'gray'."""
    assert '"gray"' in _TERRA_SECTION or "'gray'" in _TERRA_SECTION, (
        "Terra path must set recommendation_color = 'gray' — UNAVAILABLE state."
    )
