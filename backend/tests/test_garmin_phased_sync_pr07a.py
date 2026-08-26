from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub_module(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


for _mod in ("redis", "redis.asyncio", "redis.exceptions", "motor", "motor.motor_asyncio"):
    if _mod not in sys.modules:
        _stub_module(_mod)

_events_stream_stub = _stub_module("events.stream")
_events_stream_stub.emit_activity_created = AsyncMock()

_feed_stub = _stub_module("feed")
_cache_stub = _stub_module("feed.realtime_cache")
_cache_stub.FEED_MAXLEN = 50
_cache_stub.warm_feed = AsyncMock()

_cfg_stub = _stub_module("config")
_secrets_stub = _stub_module("config.secrets")
_secrets_stub.get_secret = MagicMock(return_value=None)


from garmin import service as svc  # noqa: E402
from garmin import sync_progress  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _activity(activity_id: int) -> dict:
    return {
        "external_id": str(activity_id),
        "name": f"Run {activity_id}",
        "activity_type": "running",
        "start_time": f"2026-08-{activity_id:02d}T08:00:00",
        "distance": 5000.0,
        "duration": 1500.0,
        "avg_hr": 150,
    }


def _metric(day: str, *, resting_hr=48, sleep_hours=7.2, hrv=None) -> dict:
    return {
        "date": day,
        "resting_hr": resting_hr,
        "sleep_hours": sleep_hours,
        "sleep_score": 80,
        "hrv": hrv,
        "source": "garmin",
    }


def _mock_db(*, deep_sync_done: bool = True):
    db = MagicMock()
    db.garmin_connections.find_one = AsyncMock(
        return_value={"connected": True, "deep_sync_done": deep_sync_done, "garmin_username": "runner@example.com"}
    )
    db.garmin_connections.update_one = AsyncMock()
    db.garmin_activities.find_one = AsyncMock(return_value={"start_time": "2026-08-01T08:00:00"})
    db.garmin_activities.count_documents = AsyncMock(return_value=12)
    db.garmin_daily_metrics.update_one = AsyncMock()
    return db


def _progress_spy(initial=None):
    states = []
    current = dict(initial or {})

    async def fake_update(_user_id: str, **fields):
        current.update(fields)
        if current.get("phase") == "queued":
            current["status"] = "queued"
        elif current.get("phase") in {"complete", "partial_success", "failed"}:
            current["status"] = current["phase"]
        else:
            current["status"] = "in_progress"
        states.append(dict(current))
        return dict(current)

    async def fake_get(_user_id: str):
        return dict(current) if current else None

    return states, fake_update, fake_get


def test_sync_orders_activities_then_today_run_index_then_metrics_windows():
    db = _mock_db()
    provider = MagicMock()
    provider.sync_activities.return_value = [_activity(1), _activity(2)]
    provider.get_daily_metrics.side_effect = [
        [_metric("2026-08-08", hrv=None), _metric("2026-08-07", hrv=60)],
        [_metric("2026-07-31", hrv=58)],
    ]
    events = []
    progress_states, fake_update, fake_get = _progress_spy()

    async def fake_ingest(*_args, **_kwargs):
        events.append("activities_persisted")
        return {"synced": 2, "new": 2, "newest_start": "2026-08-08T08:00:00", "new_running_dates": ["2026-08-08"]}

    async def fake_refresh(*_args, **_kwargs):
        events.append("run_index_ready")
        return {"today_snapshot": {"date": "2026-08-09"}, "workouts": []}

    async def fake_persist_metrics(_db, _user_id, metrics):
        if len(metrics) == 2:
            events.append("metrics_7d")
        else:
            events.append("metrics_30d")
        return len(metrics)

    async def fake_history(*_args, **_kwargs):
        events.append("history_backfill")
        return {"snapshots_created": 1, "snapshots_updated": 0}

    with (
        patch.object(svc.session_store, "ensure_session", new=AsyncMock(return_value=True)),
        patch.object(svc.session_store, "save_session", new=AsyncMock(return_value=True)),
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "_ingest_activities", new=AsyncMock(side_effect=fake_ingest)),
        patch.object(svc, "_finalize_connection", new=AsyncMock(return_value=12)),
        patch.object(svc, "_persist_daily_metrics", new=AsyncMock(side_effect=fake_persist_metrics)),
        patch.object(svc, "_sync_vo2max_for_running_dates", new=AsyncMock(return_value=1)),
        patch.object(svc, "_build_and_persist_capabilities", new=AsyncMock()),
        patch.object(svc, "refresh_today_run_index_after_garmin_activities", new=AsyncMock(side_effect=fake_refresh)),
        patch.object(svc, "backfill_run_index_history_after_garmin_sync", new=AsyncMock(side_effect=fake_history)),
        patch.object(svc, "compute_run_index", new=AsyncMock(return_value={"metrics": {"run_readiness": 75}})),
        patch.object(svc, "update_sync_progress", new=AsyncMock(side_effect=fake_update)),
        patch.object(svc, "get_sync_progress", new=AsyncMock(side_effect=fake_get)),
    ):
        result = _run(svc.sync(db, "user-1"))

    assert result["success"] is True
    assert result["status"] == "complete"
    assert events == [
        "activities_persisted",
        "run_index_ready",
        "metrics_7d",
        "metrics_30d",
        "history_backfill",
    ]
    assert provider.get_daily_metrics.call_args_list[0].args == ("user-1",)
    assert provider.get_daily_metrics.call_args_list[0].kwargs == {"days": 7, "start_days_ago": 1}
    assert provider.get_daily_metrics.call_args_list[1].args == ("user-1",)
    assert provider.get_daily_metrics.call_args_list[1].kwargs == {"days": 23, "start_days_ago": 8}
    assert [state["phase"] for state in progress_states] == [
        "activities_fetching",
        "activities_ready",
        "run_index_ready",
        "metrics_7d_fetching",
        "readiness_ready",
        "enriching",
        "complete",
    ]


def test_sync_without_hrv_still_marks_daily_metrics_ready():
    db = _mock_db()
    provider = MagicMock()
    provider.sync_activities.return_value = [_activity(1)]
    provider.get_daily_metrics.side_effect = [
        [_metric("2026-08-08", resting_hr=47, sleep_hours=7.5, hrv=None)],
        [],
    ]
    _, fake_update, fake_get = _progress_spy()

    with (
        patch.object(svc.session_store, "ensure_session", new=AsyncMock(return_value=True)),
        patch.object(svc.session_store, "save_session", new=AsyncMock(return_value=True)),
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "_ingest_activities", new=AsyncMock(return_value={"synced": 1, "new": 1, "newest_start": "2026-08-08T08:00:00", "new_running_dates": ["2026-08-08"]})),
        patch.object(svc, "_finalize_connection", new=AsyncMock(return_value=7)),
        patch.object(svc, "_persist_daily_metrics", new=AsyncMock(side_effect=lambda *_args: len(_args[-1]))),
        patch.object(svc, "_sync_vo2max_for_running_dates", new=AsyncMock(return_value=1)),
        patch.object(svc, "_build_and_persist_capabilities", new=AsyncMock()),
        patch.object(svc, "refresh_today_run_index_after_garmin_activities", new=AsyncMock(return_value={"today_snapshot": {"date": "2026-08-09"}, "workouts": []})),
        patch.object(svc, "backfill_run_index_history_after_garmin_sync", new=AsyncMock(return_value={})),
        patch.object(svc, "compute_run_index", new=AsyncMock(return_value={"metrics": {"run_readiness": 71}})),
        patch.object(svc, "update_sync_progress", new=AsyncMock(side_effect=fake_update)),
        patch.object(svc, "get_sync_progress", new=AsyncMock(side_effect=fake_get)),
    ):
        result = _run(svc.sync(db, "user-1"))

    assert result["daily_metrics_status"] == "ready"
    assert result["readiness_status"] == "ready"


def test_sync_fetches_vo2max_once_per_new_running_date():
    db = _mock_db()
    provider = MagicMock()
    provider.sync_activities.return_value = [_activity(1), _activity(2)]
    provider.get_daily_metrics.side_effect = [[_metric("2026-08-08", hrv=58)], []]
    _, fake_update, fake_get = _progress_spy()

    with (
        patch.object(svc.session_store, "ensure_session", new=AsyncMock(return_value=True)),
        patch.object(svc.session_store, "save_session", new=AsyncMock(return_value=True)),
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(
            svc,
            "_ingest_activities",
            new=AsyncMock(
                return_value={
                    "synced": 2,
                    "new": 2,
                    "newest_start": "2026-08-08T08:00:00",
                    "new_running_dates": ["2026-08-08", "2026-08-07"],
                }
            ),
        ),
        patch.object(svc, "_finalize_connection", new=AsyncMock(return_value=8)),
        patch.object(svc, "_persist_daily_metrics", new=AsyncMock(side_effect=lambda *_args: len(_args[-1]))),
        patch.object(svc, "_sync_vo2max_for_running_dates", new=AsyncMock(return_value=2)) as mock_vo2max,
        patch.object(svc, "_build_and_persist_capabilities", new=AsyncMock()),
        patch.object(svc, "refresh_today_run_index_after_garmin_activities", new=AsyncMock(return_value={"today_snapshot": {"date": "2026-08-09"}, "workouts": []})),
        patch.object(svc, "backfill_run_index_history_after_garmin_sync", new=AsyncMock(return_value={})),
        patch.object(svc, "compute_run_index", new=AsyncMock(return_value={"metrics": {"run_readiness": 75}})),
        patch.object(svc, "update_sync_progress", new=AsyncMock(side_effect=fake_update)),
        patch.object(svc, "get_sync_progress", new=AsyncMock(side_effect=fake_get)),
    ):
        result = _run(svc.sync(db, "user-1"))

    assert result["success"] is True
    mock_vo2max.assert_awaited_once_with(db, "user-1", provider, ["2026-08-08", "2026-08-07"])


def test_sync_with_no_usable_physio_keeps_readiness_ready_when_score_present():
    db = _mock_db()
    provider = MagicMock()
    provider.sync_activities.return_value = [_activity(1)]
    provider.get_daily_metrics.side_effect = [[], []]
    _, fake_update, fake_get = _progress_spy()

    with (
        patch.object(svc.session_store, "ensure_session", new=AsyncMock(return_value=True)),
        patch.object(svc.session_store, "save_session", new=AsyncMock(return_value=True)),
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "_ingest_activities", new=AsyncMock(return_value={"synced": 1, "new": 1, "newest_start": "2026-08-08T08:00:00", "new_running_dates": []})),
        patch.object(svc, "_finalize_connection", new=AsyncMock(return_value=4)),
        patch.object(svc, "_persist_daily_metrics", new=AsyncMock(side_effect=lambda *_args: len(_args[-1]))),
        patch.object(svc, "_sync_vo2max_for_running_dates", new=AsyncMock(return_value=0)),
        patch.object(svc, "_build_and_persist_capabilities", new=AsyncMock()),
        patch.object(svc, "refresh_today_run_index_after_garmin_activities", new=AsyncMock(return_value={"today_snapshot": {"date": "2026-08-09"}, "workouts": []})),
        patch.object(svc, "backfill_run_index_history_after_garmin_sync", new=AsyncMock(return_value={})),
        patch.object(svc, "compute_run_index", new=AsyncMock(return_value={"metrics": {"run_readiness": 60}})),
        patch.object(svc, "update_sync_progress", new=AsyncMock(side_effect=fake_update)),
        patch.object(svc, "get_sync_progress", new=AsyncMock(side_effect=fake_get)),
    ):
        result = _run(svc.sync(db, "user-1"))

    assert result["daily_metrics_status"] == "no_usable_data"
    assert result["readiness_status"] == "ready"


def test_metrics_failure_after_run_index_returns_partial_success():
    db = _mock_db()
    provider = MagicMock()
    provider.sync_activities.return_value = [_activity(1)]
    provider.get_daily_metrics.side_effect = RuntimeError("gccli timeout")
    progress_states, fake_update, fake_get = _progress_spy()

    with (
        patch.object(svc.session_store, "ensure_session", new=AsyncMock(return_value=True)),
        patch.object(svc.session_store, "save_session", new=AsyncMock(return_value=True)),
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "_ingest_activities", new=AsyncMock(return_value={"synced": 1, "new": 1, "newest_start": "2026-08-08T08:00:00", "new_running_dates": ["2026-08-08"]})),
        patch.object(svc, "_finalize_connection", new=AsyncMock(return_value=6)),
        patch.object(svc, "_sync_vo2max_for_running_dates", new=AsyncMock(return_value=1)),
        patch.object(svc, "_build_and_persist_capabilities", new=AsyncMock()),
        patch.object(svc, "refresh_today_run_index_after_garmin_activities", new=AsyncMock(return_value={"today_snapshot": {"date": "2026-08-09"}, "workouts": []})),
        patch.object(svc, "update_sync_progress", new=AsyncMock(side_effect=fake_update)),
        patch.object(svc, "get_sync_progress", new=AsyncMock(side_effect=fake_get)),
    ):
        result = _run(svc.sync(db, "user-1"))

    assert result["success"] is True
    assert result["status"] == "partial_success"
    assert result["run_index_status"] == "ready"
    assert result["daily_metrics_status"] == "failed"
    assert result["readiness_status"] == "unavailable"
    assert progress_states[-1]["phase"] == "partial_success"


def test_activity_failure_stays_failed_before_run_index():
    db = _mock_db()
    provider = MagicMock()
    provider.sync_activities.side_effect = RuntimeError("activities boom")
    progress_states, fake_update, fake_get = _progress_spy()

    with (
        patch.object(svc.session_store, "ensure_session", new=AsyncMock(return_value=True)),
        patch.object(svc.session_store, "save_session", new=AsyncMock(return_value=True)),
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "update_sync_progress", new=AsyncMock(side_effect=fake_update)),
        patch.object(svc, "get_sync_progress", new=AsyncMock(side_effect=fake_get)),
    ):
        result = _run(svc.sync(db, "user-1"))

    assert result["success"] is False
    assert progress_states[-1]["phase"] == "failed"
    assert progress_states[-1]["run_index_status"] == "failed"


def test_sync_resume_retries_metrics_without_refetching_activities():
    db = _mock_db()
    provider = MagicMock()
    provider.get_daily_metrics.side_effect = [[_metric("2026-08-08", hrv=59)], []]
    _, fake_update, fake_get = _progress_spy(
        {
            "phase": "partial_success",
            "activities_status": "ready",
            "activities_count": 11,
            "run_index_status": "ready",
            "daily_metrics_status": "failed",
            "readiness_status": "unavailable",
        }
    )

    with (
        patch.object(svc.session_store, "ensure_session", new=AsyncMock(return_value=True)),
        patch.object(svc.session_store, "save_session", new=AsyncMock(return_value=True)),
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "_persist_daily_metrics", new=AsyncMock(side_effect=lambda *_args: len(_args[-1]))),
        patch.object(svc, "_sync_vo2max_for_running_dates", new=AsyncMock(return_value=0)),
        patch.object(svc, "_build_and_persist_capabilities", new=AsyncMock()),
        patch.object(svc, "refresh_today_run_index_after_garmin_activities", new=AsyncMock()) as mock_refresh,
        patch.object(svc, "backfill_run_index_history_after_garmin_sync", new=AsyncMock(return_value={})),
        patch.object(svc, "compute_run_index", new=AsyncMock(return_value={"metrics": {"run_readiness": 77}})),
        patch.object(svc, "update_sync_progress", new=AsyncMock(side_effect=fake_update)),
        patch.object(svc, "get_sync_progress", new=AsyncMock(side_effect=fake_get)),
    ):
        result = _run(svc.sync(db, "user-1"))

    assert result["success"] is True
    assert provider.get_daily_metrics.call_count == 2
    mock_refresh.assert_not_called()


def test_incremental_sync_still_refreshes_run_index():
    db = _mock_db()
    provider = MagicMock()
    provider.sync_activities.return_value = [_activity(9)]
    _, fake_update, fake_get = _progress_spy()

    with (
        patch.object(svc.session_store, "ensure_session", new=AsyncMock(return_value=True)),
        patch.object(svc.session_store, "save_session", new=AsyncMock(return_value=True)),
        patch.object(svc, "get_provider_for_user", return_value=provider),
        patch.object(svc, "_ingest_activities", new=AsyncMock(return_value={"synced": 1, "new": 1, "newest_start": "2026-08-09T08:00:00", "new_running_dates": ["2026-08-09"]})),
        patch.object(svc, "_finalize_connection", new=AsyncMock(return_value=13)),
        patch.object(svc, "_sync_vo2max_for_running_dates", new=AsyncMock(return_value=1)) as mock_vo2max,
        patch.object(svc, "_build_and_persist_capabilities", new=AsyncMock()) as mock_caps,
        patch.object(svc, "refresh_today_run_index_after_garmin_activities", new=AsyncMock(return_value={"today_snapshot": {"date": "2026-08-09"}, "workouts": []})),
        patch.object(svc, "backfill_run_index_history_after_garmin_sync", new=AsyncMock(return_value={})),
        patch.object(svc, "update_sync_progress", new=AsyncMock(side_effect=fake_update)),
        patch.object(svc, "get_sync_progress", new=AsyncMock(side_effect=fake_get)),
    ):
        result = _run(svc.incremental_sync(db, "user-1"))

    assert result["success"] is True
    assert result["metrics_count"] == 0
    assert result["status"] == "complete"
    mock_vo2max.assert_awaited_once_with(db, "user-1", provider, ["2026-08-09"])
    mock_caps.assert_awaited_once()


class _FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value


def test_sync_progress_is_isolated_and_sanitized():
    redis = _FakeRedis()

    with patch("jobs.redis_client.get_redis", return_value=redis):
        first = _run(
            sync_progress.update_sync_progress(
                "user-a",
                phase="queued",
                activities_count=3,
                garmin_token="secret",
                session_payload="sensitive",
            )
        )
        second = _run(
            sync_progress.update_sync_progress(
                "user-b",
                phase="complete",
                daily_metrics_status="ready",
                readiness_status="ready",
            )
        )
        loaded_first = _run(sync_progress.get_sync_progress("user-a"))
        loaded_second = _run(sync_progress.get_sync_progress("user-b"))

    assert first["status"] == "queued"
    assert second["status"] == "complete"
    assert loaded_first["phase"] == "queued"
    assert loaded_second["phase"] == "complete"
    assert "garmin_token" not in loaded_first
    assert "session_payload" not in loaded_first
    assert json.loads(redis.data["runindex:garmin:sync_status:user-a"])["activities_count"] == 3
