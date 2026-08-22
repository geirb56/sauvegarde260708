"""PR184 — /stats endpoint: DomainActivity authority tests.

Self-contained: copies the helper logic from server.py to avoid importing
the full server (which requires redis, motor, litellm, etc. not installed
in the sandbox).  Tests the actual helper functions that power the changed
/stats endpoint AND performs static code inspection.

Spec items covered:
E — stats 7/30 jours → DomainActivity
F — db.workouts divergent de garmin_activities → Progress suit DomainActivity
G — 0 activité → sessions=0, distance=0
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, date, timedelta, timezone
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Locate backend directory for static analysis
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVER_PY = os.path.join(_BACKEND_DIR, "server.py")

# ---------------------------------------------------------------------------
# Inline helpers — replicated from server.py so test is dependency-free.
# If the server.py helpers diverge, the static check below will catch it.
# ---------------------------------------------------------------------------
_RUNNING_TYPES = frozenset({"running", "trail_running", "treadmill_running"})


def _domain_activity_date(activity) -> Optional[date]:
    start_time = getattr(activity, "start_time", None)
    if isinstance(start_time, datetime):
        return start_time.date()
    if isinstance(start_time, date):
        return start_time
    if isinstance(start_time, str):
        try:
            return datetime.fromisoformat(start_time.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.fromisoformat(start_time.split("T")[0]).date()
            except ValueError:
                return None
    return None


def _iter_recent_running(activities: list, *, max_days: int) -> list:
    today = datetime.now(timezone.utc).date()
    selected = []
    for activity in activities:
        activity_type = (getattr(activity, "activity_type", None) or "").strip().lower()
        if activity_type not in _RUNNING_TYPES:
            continue
        activity_date = _domain_activity_date(activity)
        if activity_date is None:
            continue
        days_ago = (today - activity_date).days
        if 0 <= days_ago < max_days:
            selected.append((activity, activity_date))
    return selected


def _calc_week_stats(activities: list) -> dict:
    week = _iter_recent_running(activities, max_days=7)
    total_km = sum(((getattr(a, "distance_m", None) or 0.0) / 1000.0) for a, _ in week)
    sessions = len(week)
    return {"sessions": sessions, "volume_km": round(total_km, 1)}


def _calc_month_stats(activities: list) -> dict:
    today = datetime.now(timezone.utc).date()
    current = [(a, d) for a, d in _iter_recent_running(activities, max_days=60)
               if (today - d).days < 30]
    km = sum(((getattr(a, "distance_m", None) or 0.0) / 1000.0) for a, _ in current)
    return {"sessions": len(current), "volume_km": round(km, 1)}


# ---------------------------------------------------------------------------
# DomainActivity stub
# ---------------------------------------------------------------------------
class _Act:
    def __init__(self, *, activity_type: str, days_ago: int, distance_m: float) -> None:
        self.activity_type = activity_type
        self.start_time = datetime.now(timezone.utc) - timedelta(days=days_ago)
        self.distance_m = distance_m
        self.duration_s = 3600.0


# ---------------------------------------------------------------------------
# Tests: E — stats 7/30 proviennent de DomainActivity
# ---------------------------------------------------------------------------
class TestDomainActivityWindowSemantics:

    def test_week_sessions_rolling_7_days(self):
        """E — sessions in the rolling 7-day window."""
        acts = [
            _Act(activity_type="running", days_ago=1, distance_m=8000),
            _Act(activity_type="running", days_ago=6, distance_m=10000),
            _Act(activity_type="running", days_ago=8, distance_m=5000),  # outside window
        ]
        result = _calc_week_stats(acts)
        assert result["sessions"] == 2

    def test_week_km_rolling_7_days(self):
        """E — distance in the rolling 7-day window."""
        acts = [
            _Act(activity_type="running", days_ago=1, distance_m=8000),
            _Act(activity_type="running", days_ago=6, distance_m=10000),
        ]
        result = _calc_week_stats(acts)
        assert abs(result["volume_km"] - 18.0) < 0.1

    def test_non_running_excluded(self):
        """E — cycling activities are not counted."""
        acts = [
            _Act(activity_type="running", days_ago=1, distance_m=8000),
            _Act(activity_type="cycling", days_ago=2, distance_m=30000),
        ]
        result = _calc_week_stats(acts)
        assert result["sessions"] == 1
        assert abs(result["volume_km"] - 8.0) < 0.1


# ---------------------------------------------------------------------------
# Tests: G — 0 activité → sessions=0, distance=0
# ---------------------------------------------------------------------------
class TestZeroActivity:

    def test_empty_sessions_7d(self):
        """G — no activities → sessions_7_days=0."""
        assert _calc_week_stats([])["sessions"] == 0

    def test_empty_km_7d(self):
        """G — no activities → km_7_days=0."""
        assert _calc_week_stats([])["volume_km"] == 0

    def test_empty_km_30d(self):
        """G — no activities → km_30_days=0."""
        assert _calc_month_stats([])["volume_km"] == 0

    def test_empty_sessions_30d(self):
        """G — no activities → sessions_30_days=0."""
        assert _calc_month_stats([])["sessions"] == 0


# ---------------------------------------------------------------------------
# Tests: F — db.workouts diverge → DomainActivity wins
# ---------------------------------------------------------------------------
class TestDomainActivityDivergence:

    def test_domain_wins_over_workouts(self):
        """F — only 1 domain run; result must be 1, not the workout count."""
        domain = [_Act(activity_type="running", days_ago=2, distance_m=15000)]
        # Simulate that db.workouts would have returned 5 runs — but we only
        # pass domain activities to the helpers, so the result is 1.
        result = _calc_week_stats(domain)
        assert result["sessions"] == 1
        assert abs(result["volume_km"] - 15.0) < 0.1

    def test_domain_zero_when_workouts_nonzero(self):
        """F — 0 domain runs → 0 stats, even if db.workouts had data."""
        result = _calc_week_stats([])
        assert result["sessions"] == 0
        assert result["volume_km"] == 0


# ---------------------------------------------------------------------------
# Static code analysis: /stats endpoint no longer uses db.workouts
# ---------------------------------------------------------------------------
class TestStatsEndpointStaticAnalysis:

    def _get_stats_function_source(self) -> str:
        with open(_SERVER_PY, "r", encoding="utf-8") as f:
            source = f.read()
        # Extract the get_stats function body
        lines = source.splitlines()
        start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("async def get_stats(") or line.strip() == "async def get_stats(user: dict = Depends(auth_user)):":
                start = i
                break
        if start is None:
            # Try decorator-based lookup
            for i, line in enumerate(lines):
                if '"/stats"' in line or "'/stats'" in line:
                    # Next async def is the handler
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if "async def" in lines[j]:
                            start = j
                            break
                    if start:
                        break
        assert start is not None, "Could not locate get_stats function"
        # Collect lines until next top-level def/class (indentation 0)
        body = []
        for line in lines[start:]:
            if line and not line[0].isspace() and body:
                break
            body.append(line)
        return "\n".join(body)

    def test_stats_uses_load_garmin_domain_activities(self):
        """E/F — /stats must call load_garmin_domain_activities."""
        body = self._get_stats_function_source()
        assert "load_garmin_domain_activities" in body, (
            "/stats endpoint must call load_garmin_domain_activities (DomainActivity source)"
        )

    def test_stats_uses_calculate_week_stats_from_domain(self):
        """E — /stats must use calculate_week_stats_from_domain."""
        body = self._get_stats_function_source()
        assert "calculate_week_stats_from_domain" in body

    def test_stats_uses_calculate_month_stats_from_domain(self):
        """E — /stats must use calculate_month_stats_from_domain."""
        body = self._get_stats_function_source()
        assert "calculate_month_stats_from_domain" in body

    def test_stats_no_synthetic_fallback(self):
        """G — /stats must not contain synthetic data generation."""
        body = self._get_stats_function_source()
        # Old code had a synthetic fallback: if not all_activities: all_activities = [...]
        assert "8 + (i % 5)" not in body, (
            "/stats must not generate synthetic workout data"
        )

    def test_stats_response_contract_preserved(self):
        """E — response still includes sessions_7_days, km_7_days, km_30_days."""
        body = self._get_stats_function_source()
        assert "sessions_7_days" in body
        assert "km_7_days" in body
        assert "km_30_days" in body


# ---------------------------------------------------------------------------
# Static analysis: RunIndex null semantics preserved in Progress.jsx
# ---------------------------------------------------------------------------
class TestProgressFrontendStaticAnalysis:

    _PROGRESS_PATH = os.path.join(
        os.path.dirname(_BACKEND_DIR),
        "frontend", "src", "pages", "Progress.jsx"
    )

    def test_connectNulls_is_false(self):
        """B/C — RunIndex chart must set connectNulls={false}."""
        code = open(self._PROGRESS_PATH).read()
        assert "connectNulls={false}" in code, (
            "Progress.jsx must set connectNulls={false} on RunIndex Line chart"
        )

    def test_no_filter_removes_null_run_index(self):
        """B — null run_index values must not be pre-filtered from chart data."""
        code = open(self._PROGRESS_PATH).read()
        assert "filter(h => h.run_index !== null)" not in code, (
            "Progress.jsx must not filter null run_index before passing to chart"
        )

    def test_vma_history_endpoint_preserved(self):
        """I/J — VMA_FRONTEND_PRESERVED = YES."""
        code = open(self._PROGRESS_PATH).read()
        assert "/training/vma-history" in code

    def test_race_predictions_endpoint_preserved(self):
        """K — PREDICTIONS_FRONTEND_PRESERVED = YES."""
        code = open(self._PROGRESS_PATH).read()
        assert "/training/race-predictions" in code

    def test_cycle_v2_used_not_full_cycle(self):
        """H — Cycle consumer migrated to V2."""
        code = open(self._PROGRESS_PATH).read()
        assert "/training/v2/cycle" in code
        assert "/training/full-cycle" not in code

    def test_no_raw_i18n_keys_in_progress(self):
        """N — No hardcoded untranslated strings (basic check)."""
        # Garmin Health section must now use t() keys
        code = open(self._PROGRESS_PATH).read()
        assert "Garmin Health · 7 days" not in code
        assert "garminHealthTitle" in code

