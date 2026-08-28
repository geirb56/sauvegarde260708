"""PR210 guardrails — Terra runtime removal, Garmin path preserved."""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_SERVER_SOURCE = (_BACKEND / "server.py").read_text(encoding="utf-8")


def test_no_terra_runtime_import_or_endpoint_in_server():
    assert "terra_integration" not in _SERVER_SOURCE
    assert '"/terra/' not in _SERVER_SOURCE
    assert "db.terra_tokens" not in _SERVER_SOURCE


def test_run_index_fallback_is_no_data_only():
    assert "return _CARDIO_COACH_NO_DATA" in _SERVER_SOURCE


_TODAY = date(2026, 8, 14)


def _metric(day_offset: int, ref: date) -> dict:
    d = ref - timedelta(days=day_offset)
    return {"date": d.isoformat(), "rhr": 52.0, "hrv": 55.0, "sleep_hours": 7.5, "sleep_quality": 85}


def _activity(day_offset: int, ref: date) -> dict:
    return {
        "activity_type": "running",
        "start_time": (ref - timedelta(days=day_offset)).isoformat(),
        "distance_m": 8000.0,
        "duration_s": 2400.0,
    }


def _make_db(docs: List[dict], acts: List[dict]) -> MagicMock:
    db = MagicMock()

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
    from garmin.insights import compute_run_index

    docs = [_metric(i, _TODAY) for i in range(14)]
    acts = [_activity(i, _TODAY) for i in range(5)]
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    assert payload.get("recommendation_color") in {"green", "yellow", "red"}


def test_garmin_path_readiness_v2_intact():
    from garmin.insights import compute_run_index

    docs = [_metric(i, _TODAY) for i in range(14)]
    acts = [_activity(i, _TODAY) for i in range(5)]
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    metrics = payload["metrics"]
    for key in ("run_readiness", "confidence", "sufficiency_level"):
        assert key in metrics
