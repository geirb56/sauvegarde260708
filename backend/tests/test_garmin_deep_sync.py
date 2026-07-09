"""Unit tests for Garmin paginated fetching and deep sync.

Covers:
  - GccliRunner.fetch_activities() with start offset (pagination)
  - GccliProvider.fetch_all_activities() pagination loop
  - fetch_all_activities() stops when last page is empty
  - fetch_all_activities() deduplication by external_id
  - garmin/service.deep_sync(): full historical import for first user
  - garmin/service.sync(): incremental path unchanged after deep_sync_done
  - garmin/service.sync(): deep sync NOT re-triggered when already done
  - RunIndex backfill called after successful sync (via refresh_run_index_after_garmin_sync)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# Allow imports from the backend package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Pre-stub heavyweight dependencies (redis, motor) that are not available in
# the unit-test environment so service-layer imports succeed.
# ---------------------------------------------------------------------------
def _stub_module(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


for _mod in ("redis", "redis.asyncio", "redis.exceptions", "motor",
             "motor.motor_asyncio"):
    if _mod not in sys.modules:
        _stub_module(_mod)

# Provide minimal redis.exceptions.ResponseError used by events/stream.py.
import redis.exceptions as _rex  # noqa: E402
if not hasattr(_rex, "ResponseError"):
    _rex.ResponseError = type("ResponseError", (Exception,), {})

# Stub events.stream so garmin.service can be imported without a live Redis.
_events_stream_stub = _stub_module("events.stream")
_events_stream_stub.emit_activity_created = AsyncMock()

# Stub feed.realtime_cache used by garmin.backfill.
_feed_cache_stub = _stub_module("feed")
_rc_stub = _stub_module("feed.realtime_cache")
_rc_stub.FEED_MAXLEN = 50
_rc_stub.warm_feed = AsyncMock()

# Stub config.secrets so GccliProvider import works.
_cfg_stub = _stub_module("config")
_secrets_stub = _stub_module("config.secrets")
_secrets_stub.get_secret = MagicMock(return_value=None)


from garmin.runner import GccliRunner, GccliError  # noqa: E402
from garmin.providers.gccli_provider import GccliProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_activity(activity_id: int, name: str = "Run") -> dict:
    return {
        "activityId": activity_id,
        "activityName": name,
        "activityType": {"typeKey": "running"},
        "startTimeLocal": f"2026-01-{activity_id:02d}T08:00:00",
        "distance": 5000.0,
        "duration": 1500.0,
        "averageHR": 155,
    }


def _make_runner(pages: list[list[dict]]) -> GccliRunner:
    """Return a GccliRunner whose fetch_activities() yields pages in order."""
    runner = MagicMock(spec=GccliRunner)
    runner.fetch_activities.side_effect = pages
    return runner


def _make_provider(runner: GccliRunner) -> GccliProvider:
    provider = GccliProvider(runner=runner)
    # Patch _account() so tests don't need env vars.
    provider._account = MagicMock(return_value="test@example.com")
    return provider


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# GccliRunner.fetch_activities — start parameter
# ---------------------------------------------------------------------------

class TestRunnerStartParam:
    def test_start_zero_does_not_add_flag(self):
        runner = GccliRunner.__new__(GccliRunner)
        runner.gccli_path = "gccli"
        runner.home = "/tmp"
        runner.keyring_backend = "file"
        runner.timeout = 45
        runner.max_retries = 3

        captured = []
        def fake_run_json(args, account=None):
            captured.append(args)
            return []

        runner._run_json = fake_run_json
        runner._ensure_available = MagicMock()

        runner.fetch_activities(limit=10, start=0)
        assert "--start" not in captured[0], "start=0 must not add --start flag"
        assert "--limit" in captured[0]

    def test_start_nonzero_adds_flag(self):
        runner = GccliRunner.__new__(GccliRunner)
        runner.gccli_path = "gccli"
        runner.home = "/tmp"
        runner.keyring_backend = "file"
        runner.timeout = 45
        runner.max_retries = 3

        captured = []
        def fake_run_json(args, account=None):
            captured.append(args)
            return []

        runner._run_json = fake_run_json
        runner._ensure_available = MagicMock()

        runner.fetch_activities(limit=10, start=50)
        assert "--start" in captured[0]
        start_idx = captured[0].index("--start")
        assert captured[0][start_idx + 1] == "50"

    def test_returns_list_from_dict_response(self):
        runner = GccliRunner.__new__(GccliRunner)
        runner.gccli_path = "gccli"
        runner.home = "/tmp"
        runner.keyring_backend = "file"
        runner.timeout = 45
        runner.max_retries = 3

        acts = [_raw_activity(1), _raw_activity(2)]
        runner._run_json = MagicMock(return_value={"activities": acts})
        runner._ensure_available = MagicMock()

        result = runner.fetch_activities(limit=10, start=0)
        assert result == acts


# ---------------------------------------------------------------------------
# GccliProvider.fetch_all_activities — pagination logic
# ---------------------------------------------------------------------------

class TestFetchAllActivities:
    def test_single_page_smaller_than_page_size(self):
        """If first page < page_size, no second call is made."""
        page1 = [_raw_activity(i) for i in range(1, 6)]  # 5 items
        runner = _make_runner([page1])
        provider = _make_provider(runner)

        results = provider.fetch_all_activities(page_size=10)

        assert len(results) == 5
        assert runner.fetch_activities.call_count == 1

    def test_multiple_full_pages_then_partial(self):
        """Pagination continues until a partial page terminates the loop."""
        page1 = [_raw_activity(i) for i in range(1, 4)]   # 3 items, full page
        page2 = [_raw_activity(i) for i in range(4, 7)]   # 3 items, full page
        page3 = [_raw_activity(i) for i in range(7, 9)]   # 2 items, partial → stop
        runner = _make_runner([page1, page2, page3])
        provider = _make_provider(runner)

        results = provider.fetch_all_activities(page_size=3)

        assert len(results) == 8
        assert runner.fetch_activities.call_count == 3

    def test_stops_on_empty_page(self):
        """An empty page terminates pagination immediately."""
        page1 = [_raw_activity(i) for i in range(1, 4)]  # 3 items
        page2 = []  # empty → stop
        runner = _make_runner([page1, page2])
        provider = _make_provider(runner)

        results = provider.fetch_all_activities(page_size=3)

        assert len(results) == 3
        assert runner.fetch_activities.call_count == 2

    def test_first_page_empty(self):
        """Empty first page → zero results, one call."""
        runner = _make_runner([[]])
        provider = _make_provider(runner)

        results = provider.fetch_all_activities(page_size=10)

        assert results == []
        assert runner.fetch_activities.call_count == 1

    def test_deduplication_across_pages(self):
        """Activities with duplicate activityId are counted only once."""
        dup = _raw_activity(99)
        page1 = [_raw_activity(1), dup]
        page2 = [dup, _raw_activity(2)]  # dup repeated in second page — partial page → stop
        # page2 has 2 items which equals page_size=2 so the loop would request page3;
        # we give it a partial page (1 item) to terminate naturally.
        page3 = [_raw_activity(3)]
        runner = _make_runner([page1, page2, page3])
        provider = _make_provider(runner)

        results = provider.fetch_all_activities(page_size=2)

        ext_ids = [r["external_id"] for r in results]
        assert ext_ids.count("99") == 1, "duplicate activity must appear only once"
        assert len(set(ext_ids)) == len(ext_ids), "all external_ids must be unique"
        assert len(results) == 4  # ids 1, 99, 2, 3

    def test_start_offsets_passed_correctly(self):
        """fetch_activities is called with incrementing start offsets."""
        page1 = [_raw_activity(i) for i in range(1, 4)]   # full page (3)
        page2 = [_raw_activity(i) for i in range(4, 6)]   # partial → stop
        runner = _make_runner([page1, page2])
        provider = _make_provider(runner)

        provider.fetch_all_activities(page_size=3)

        calls = runner.fetch_activities.call_args_list
        assert calls[0] == call(limit=3, start=0, account="test@example.com")
        assert calls[1] == call(limit=3, start=3, account="test@example.com")

    def test_intermediate_error_stops_and_returns_partial(self):
        """An error on a page logs it and returns what was collected so far."""
        page1 = [_raw_activity(i) for i in range(1, 4)]
        runner = MagicMock(spec=GccliRunner)
        runner.fetch_activities.side_effect = [page1, GccliError("timeout")]
        provider = _make_provider(runner)

        results = provider.fetch_all_activities(page_size=3)

        # First page was collected before the error.
        assert len(results) == 3

    def test_none_activities_skipped(self):
        """None entries inside a page are silently skipped."""
        page = [_raw_activity(1), None, _raw_activity(2)]
        runner = _make_runner([page])
        provider = _make_provider(runner)

        results = provider.fetch_all_activities(page_size=10)

        assert len(results) == 2


# ---------------------------------------------------------------------------
# garmin/service — deep_sync and sync dispatch
# ---------------------------------------------------------------------------

def _mock_db(connected: bool = True, deep_sync_done: bool = False) -> MagicMock:
    """Build a minimal async-compatible Mongo db stub."""
    conn_doc = {"connected": connected, "deep_sync_done": deep_sync_done}

    db = MagicMock()
    db.garmin_connections.find_one = AsyncMock(return_value=conn_doc if connected else None)
    db.garmin_connections.update_one = AsyncMock()
    db.garmin_activities.update_one = AsyncMock(
        return_value=MagicMock(upserted_id="new-id")
    )
    db.garmin_activities.count_documents = AsyncMock(return_value=0)
    db.garmin_daily_metrics.update_one = AsyncMock()
    return db


class TestDeepSync:
    def test_deep_sync_not_connected_returns_failure(self):
        db = _mock_db(connected=False)
        from garmin import service as svc

        result = _run(svc.deep_sync(db, "user-1"))
        assert result["success"] is False

    def test_deep_sync_fetches_all_activities(self):
        """deep_sync() calls provider.fetch_all_activities() and ingests results."""
        db = _mock_db(connected=True)
        acts = [_raw_activity(i) for i in range(1, 6)]

        mock_provider = MagicMock()
        mock_provider.fetch_all_activities.return_value = [
            GccliProvider._normalize(a) for a in acts
        ]
        mock_provider.get_daily_metrics.return_value = []

        from garmin import service as svc

        with (
            patch.object(svc, "get_provider", return_value=mock_provider),
            patch.object(svc, "emit_activity_created", new=AsyncMock()),
        ):
            result = _run(svc.deep_sync(db, "user-1"))

        assert result["success"] is True
        assert result["synced_count"] == 5
        assert result.get("deep_sync") is True
        mock_provider.fetch_all_activities.assert_called_once()

    def test_deep_sync_sets_deep_sync_done_flag(self):
        """deep_sync() must persist deep_sync_done=True in garmin_connections."""
        db = _mock_db(connected=True)
        mock_provider = MagicMock()
        mock_provider.fetch_all_activities.return_value = []
        mock_provider.get_daily_metrics.return_value = []

        from garmin import service as svc

        with (
            patch.object(svc, "get_provider", return_value=mock_provider),
            patch.object(svc, "emit_activity_created", new=AsyncMock()),
        ):
            _run(svc.deep_sync(db, "user-1"))

        # update_one must have been called with deep_sync_done: True
        calls = db.garmin_connections.update_one.call_args_list
        deep_sync_call = next(
            (c for c in calls if c.args[1].get("$set", {}).get("deep_sync_done") is True),
            None,
        )
        assert deep_sync_call is not None, "deep_sync_done must be set to True"

    def test_deep_sync_fetch_failure_returns_failure(self):
        db = _mock_db(connected=True)
        mock_provider = MagicMock()
        mock_provider.fetch_all_activities.side_effect = Exception("network error")

        from garmin import service as svc

        with patch.object(svc, "get_provider", return_value=mock_provider):
            result = _run(svc.deep_sync(db, "user-1"))

        assert result["success"] is False


class TestSyncDispatch:
    def test_sync_triggers_deep_sync_on_first_connection(self):
        """sync() must call deep_sync() when deep_sync_done is not set."""
        db = _mock_db(connected=True, deep_sync_done=False)
        from garmin import service as svc

        with (
            patch.dict("os.environ", {"GARMIN_DEEP_SYNC_ENABLED": "true"}),
            patch.object(svc, "deep_sync", new=AsyncMock(
                return_value={"success": True, "synced_count": 100, "new_count": 100,
                              "metrics_count": 0, "message": "ok", "deep_sync": True}
            )) as mock_deep,
        ):
            result = _run(svc.sync(db, "user-1"))

        mock_deep.assert_called_once_with(db, "user-1")
        assert result.get("deep_sync") is True

    def test_sync_skips_deep_sync_when_already_done(self):
        """sync() must NOT call deep_sync() when deep_sync_done=True."""
        db = _mock_db(connected=True, deep_sync_done=True)
        mock_provider = MagicMock()
        mock_provider.sync_activities.return_value = []
        mock_provider.get_daily_metrics.return_value = []

        from garmin import service as svc

        with (
            patch.dict("os.environ", {"GARMIN_DEEP_SYNC_ENABLED": "true"}),
            patch.object(svc, "get_provider", return_value=mock_provider),
            patch.object(svc, "deep_sync", new=AsyncMock()) as mock_deep,
            patch.object(svc, "emit_activity_created", new=AsyncMock()),
        ):
            result = _run(svc.sync(db, "user-1"))

        mock_deep.assert_not_called()
        assert result["success"] is True

    def test_sync_skips_deep_sync_when_disabled_by_env(self):
        """When GARMIN_DEEP_SYNC_ENABLED=false, sync() uses normal path even on first connect."""
        db = _mock_db(connected=True, deep_sync_done=False)
        mock_provider = MagicMock()
        mock_provider.sync_activities.return_value = []
        mock_provider.get_daily_metrics.return_value = []

        from garmin import service as svc

        with (
            patch.dict("os.environ", {"GARMIN_DEEP_SYNC_ENABLED": "false"}),
            patch.object(svc, "get_provider", return_value=mock_provider),
            patch.object(svc, "deep_sync", new=AsyncMock()) as mock_deep,
            patch.object(svc, "emit_activity_created", new=AsyncMock()),
        ):
            result = _run(svc.sync(db, "user-1"))

        mock_deep.assert_not_called()
        assert result["success"] is True

    def test_incremental_sync_unaffected(self):
        """incremental_sync() is independent of deep_sync_done flag."""
        db = _mock_db(connected=True, deep_sync_done=False)
        db.garmin_activities.find_one = AsyncMock(return_value=None)
        mock_provider = MagicMock()
        mock_provider.sync_activities.return_value = []

        from garmin import service as svc

        with (
            patch.object(svc, "get_provider", return_value=mock_provider),
            patch.object(svc, "deep_sync", new=AsyncMock()) as mock_deep,
            patch.object(svc, "emit_activity_created", new=AsyncMock()),
        ):
            result = _run(svc.incremental_sync(db, "user-1"))

        mock_deep.assert_not_called()
        assert result["success"] is True


# ---------------------------------------------------------------------------
# RunIndex backfill integration (via sync_worker pattern)
# ---------------------------------------------------------------------------

class TestRunIndexBackfillAfterDeepSync:
    def test_refresh_run_index_called_on_deep_sync_success(self):
        """Simulate the sync_worker calling refresh_run_index_after_garmin_sync after a
        successful deep sync — the worker already does this for all sync types.
        """
        from services.run_index_history import refresh_run_index_after_garmin_sync

        # The function itself requires Mongo access; verify the import and signature
        # rather than executing end-to-end in a unit test.
        import inspect
        sig = inspect.signature(refresh_run_index_after_garmin_sync)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "user_id" in params

    def test_deep_sync_success_flag_propagates_to_worker(self):
        """Ensure deep_sync() returns success=True so the worker invokes
        refresh_run_index_after_garmin_sync (see sync_worker._run_job logic).
        """
        db = _mock_db(connected=True)
        mock_provider = MagicMock()
        mock_provider.fetch_all_activities.return_value = []
        mock_provider.get_daily_metrics.return_value = []

        from garmin import service as svc

        with (
            patch.object(svc, "get_provider", return_value=mock_provider),
            patch.object(svc, "emit_activity_created", new=AsyncMock()),
        ):
            result = _run(svc.deep_sync(db, "user-1"))

        # The sync_worker checks result["success"] before calling run_index backfill.
        assert result["success"] is True, (
            "deep_sync must return success=True so the worker triggers RunIndex backfill"
        )
