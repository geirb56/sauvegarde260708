"""R3 — Integration tests for compute_run_index(db, user_id) with a DB fake.

These tests exercise the full path from the DB layer through Readiness V2:
  garmin_daily_metrics + garmin_activities → compute_run_index → payload

Test matrix
-----------
- queries are filtered by user_id (multi-user isolation)
- metrics.run_readiness == ReadinessResult.score (float or None)
- confidence is exposed in metrics
- sufficiency_level is exposed in metrics
- readiness_reasons is exposed in metrics
- INSUFFICIENT → run_readiness = None
- legacy_run_readiness is absent from metrics
- payload backward-compatible (run_readiness key always present)
- multi-user: user A data does not bleed into user B result
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.insights import compute_run_index
from garmin.readiness_adapter import build_readiness_v2_from_garmin_data
from training_v2.readiness_sufficiency import SufficiencyLevel

# ---------------------------------------------------------------------------
# DB fake helpers
# ---------------------------------------------------------------------------

_REF = date(2026, 1, 28)
_USER_A = "user_a_id"
_USER_B = "user_b_id"


def _iso(d: date) -> str:
    return d.isoformat()


def _metrics_docs(
    user_id: str,
    *,
    n: int = 14,
    rhr: Optional[float] = 52.0,
    hrv: Optional[float] = 65.0,
    sleep_hours: Optional[float] = 7.5,
    sleep_score: Optional[float] = 80.0,
    ref: date = _REF,
) -> List[dict]:
    docs = []
    for i in range(n):
        d = ref - timedelta(days=i)
        docs.append({
            "user_id": user_id,
            "date": _iso(d),
            "resting_hr": rhr,
            "hrv": hrv,
            "sleep_hours": sleep_hours,
            "sleep_score": sleep_score,
        })
    return docs


def _activity_docs(
    user_id: str,
    *,
    n: int = 28,
    ref: date = _REF,
) -> List[dict]:
    acts = []
    for i in range(n):
        d = ref - timedelta(days=i)
        acts.append({
            "user_id": user_id,
            "activity_type": "running",
            "start_time": f"{_iso(d)}T08:00:00",
            "duration_s": 2400.0,
            "distance_m": 6000.0,
        })
    return acts


class _FakeQuery:
    """Chainable fake query that returns a fixed list via to_list()."""

    def __init__(self, docs: List[dict]) -> None:
        self._docs = docs

    def sort(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int = None) -> List[dict]:
        return list(self._docs)


class _FakeCollection:
    """Fake MongoDB collection whose find() returns only docs matching user_id."""

    def __init__(self, all_docs: List[dict]) -> None:
        self._all = all_docs

    def find(self, filter_: dict, projection: dict = None) -> _FakeQuery:
        uid = filter_.get("user_id")
        docs = [d for d in self._all if d.get("user_id") == uid] if uid else list(self._all)
        return _FakeQuery(docs)


class _FakeDB:
    """Fake async DB with garmin_daily_metrics and garmin_activities collections."""

    def __init__(
        self,
        metrics_docs: List[dict],
        activity_docs: List[dict],
    ) -> None:
        self.garmin_daily_metrics = _FakeCollection(metrics_docs)
        self.garmin_activities = _FakeCollection(activity_docs)
        self.garmin_vo2max = MagicMock()
        self.garmin_vo2max.find_one = AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_readiness_matches_v2_score_sufficient():
    """metrics.run_readiness is a float when data is SUFFICIENT."""
    metrics_docs = _metrics_docs(_USER_A)
    activity_docs = _activity_docs(_USER_A)
    db = _FakeDB(metrics_docs, activity_docs)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    m = payload["metrics"]
    expected = build_readiness_v2_from_garmin_data(metrics_docs, activity_docs, _REF)
    assert m["run_readiness"] is not None
    assert isinstance(m["run_readiness"], float)
    assert 0.0 < m["run_readiness"] <= 100.0
    assert m["run_readiness"] == expected.score
    assert m["sufficiency_level"] == expected.sufficiency_level.value
    assert m["confidence"] == expected.confidence.value


@pytest.mark.asyncio
async def test_degraded_run_readiness_keeps_v2_score():
    """Missing sleep data → DEGRADED, V2 score still exposed."""
    metrics_docs = _metrics_docs(_USER_A, sleep_hours=None, sleep_score=None)
    activity_docs = _activity_docs(_USER_A)
    db = _FakeDB(metrics_docs, activity_docs)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    m = payload["metrics"]
    expected = build_readiness_v2_from_garmin_data(metrics_docs, activity_docs, _REF)

    assert expected.sufficiency_level == SufficiencyLevel.DEGRADED
    assert expected.score is not None
    assert m["run_readiness"] == expected.score
    assert m["sufficiency_level"] == SufficiencyLevel.DEGRADED.value
    assert m["confidence"] == expected.confidence.value


@pytest.mark.asyncio
async def test_confidence_exposed():
    """metrics.confidence is present and non-empty."""
    db = _FakeDB(_metrics_docs(_USER_A), _activity_docs(_USER_A))
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    assert "confidence" in payload["metrics"]
    assert payload["metrics"]["confidence"]


@pytest.mark.asyncio
async def test_sufficiency_level_exposed():
    """metrics.sufficiency_level is present and non-empty."""
    db = _FakeDB(_metrics_docs(_USER_A), _activity_docs(_USER_A))
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    assert "sufficiency_level" in payload["metrics"]
    assert payload["metrics"]["sufficiency_level"]


@pytest.mark.asyncio
async def test_readiness_reasons_exposed():
    """metrics.readiness_reasons is a list (may be empty when SUFFICIENT)."""
    db = _FakeDB(_metrics_docs(_USER_A), _activity_docs(_USER_A))
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    assert "readiness_reasons" in payload["metrics"]
    assert isinstance(payload["metrics"]["readiness_reasons"], list)


@pytest.mark.asyncio
async def test_insufficient_run_readiness_is_none():
    """INSUFFICIENT data (no physio, no activities) → run_readiness = None."""
    # No physio, no activities → INSUFFICIENT
    empty_metrics = _metrics_docs(_USER_A, rhr=None, hrv=None)
    db = _FakeDB(empty_metrics, [])
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    m = payload["metrics"]
    assert m["run_readiness"] is None
    assert m["sufficiency_level"] == SufficiencyLevel.INSUFFICIENT.value


@pytest.mark.asyncio
async def test_insufficient_score_none_recommendation_unavailable_gray():
    """INSUFFICIENT → score None → recommendation UNAVAILABLE, color gray.

    None must NEVER produce REST / EASY RUN / RUN HARD: those are training
    recommendations that require a valid score.  When data is insufficient
    the state is purely informational (unavailable), not actionable.
    """
    empty_metrics = _metrics_docs(_USER_A, rhr=None, hrv=None)
    db = _FakeDB(empty_metrics, [])
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    # Score must be None
    assert payload["metrics"]["run_readiness"] is None
    # Color is gray (unavailable state)
    assert payload["recommendation_color"] == "gray"
    # Recommendation must NOT be a training directive
    rec = payload["recommendation"]
    assert rec not in {"REST", "EASY RUN", "RUN HARD", "REPOS", "FOOTING FACILE", "SÉANCE INTENSE",
                       "DESCANSO", "CARRERA SUAVE", "ENTRENO INTENSO"}


@pytest.mark.asyncio
async def test_legacy_run_readiness_absent_from_metrics():
    """legacy_run_readiness is removed from /run-index metrics."""
    empty_metrics = _metrics_docs(_USER_A, rhr=None, hrv=None)
    db = _FakeDB(empty_metrics, [])
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    m = payload["metrics"]
    assert "legacy_run_readiness" not in m
    assert m["run_readiness"] is None


@pytest.mark.asyncio
async def test_payload_backward_compatible_run_readiness_key_always_present():
    """run_readiness key is always present in metrics — value is float or None."""
    # Sufficient
    db_ok = _FakeDB(_metrics_docs(_USER_A), _activity_docs(_USER_A))
    payload_ok = await compute_run_index(db_ok, _USER_A, reference_date=_REF)
    assert payload_ok is not None
    assert "run_readiness" in payload_ok["metrics"]

    # Insufficient
    db_bad = _FakeDB(_metrics_docs(_USER_A, rhr=None, hrv=None), [])
    payload_bad = await compute_run_index(db_bad, _USER_A, reference_date=_REF)
    assert payload_bad is not None
    assert "run_readiness" in payload_bad["metrics"]
    assert payload_bad["metrics"]["run_readiness"] is None


@pytest.mark.asyncio
async def test_run_readiness_never_zero_for_insufficient():
    """run_readiness must be None, not 0, when INSUFFICIENT."""
    empty_metrics = _metrics_docs(_USER_A, rhr=None, hrv=None)
    db = _FakeDB(empty_metrics, [])
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None
    assert payload["metrics"]["run_readiness"] != 0
    assert payload["metrics"]["run_readiness"] is None


@pytest.mark.asyncio
async def test_multi_user_isolation_via_db_layer():
    """compute_run_index(userA) uses only userA's data — not userB's.

    User A: full physio data → SUFFICIENT, run_readiness is not None.
    User B: no physio, no activities → INSUFFICIENT, run_readiness is None.
    Both coexist in the same fake DB.
    """
    all_metrics = _metrics_docs(_USER_A, rhr=52.0, hrv=65.0) + _metrics_docs(_USER_B, rhr=None, hrv=None)
    all_activities = _activity_docs(_USER_A) + []  # user B has no activities

    db = _FakeDB(all_metrics, all_activities)

    payload_a = await compute_run_index(db, _USER_A, reference_date=_REF)
    payload_b = await compute_run_index(db, _USER_B, reference_date=_REF)

    assert payload_a is not None
    assert payload_b is not None

    # User A: physio present, activities present → score not None
    assert payload_a["metrics"]["run_readiness"] is not None

    # User B: no physio, no activities → INSUFFICIENT → None
    assert payload_b["metrics"]["run_readiness"] is None
    assert payload_b["metrics"]["sufficiency_level"] == SufficiencyLevel.INSUFFICIENT.value


@pytest.mark.asyncio
async def test_queries_filtered_by_user_id():
    """DB queries are filtered by user_id — user B's data is not returned for user A.

    We put a contradictory document for user B (rhr=None) and a valid document
    for user A, then verify user A's result is healthy (not poisoned by user B).
    """
    # User A: 14 good metric docs + 28 activities
    # User B: 14 docs with no physio — if leaked into user A's query, would produce INSUFFICIENT
    all_metrics = _metrics_docs(_USER_A, rhr=52.0, hrv=65.0) + _metrics_docs(_USER_B, rhr=None, hrv=None)
    all_activities = _activity_docs(_USER_A)

    db = _FakeDB(all_metrics, all_activities)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)

    assert payload is not None
    # If user B's docs leaked in, physio would be absent → INSUFFICIENT
    assert payload["metrics"]["run_readiness"] is not None
    assert payload["metrics"]["sufficiency_level"] != SufficiencyLevel.INSUFFICIENT.value
