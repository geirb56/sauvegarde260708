"""PR181 — CACHE_STALE_RUNINDEX: normal sync path invalidates dashboard cache.

Invariant tested:
  Garmin activities persisted
  → RunIndex CURRENT/history refresh  (via _complete_post_activities_pipeline
    or incremental_sync, both now call _dic.invalidate_user)
  → dashboard cache invalidated for user X
  → user Y is NOT invalidated

The test does NOT call invalidate_user() directly.  It drives the
service-layer function (_complete_post_activities_pipeline via
garmin_service.sync or the incremental path) with all external I/O mocked,
and verifies that the shared dashboard_insight_cache module ends up empty for
user X while remaining intact for user Y.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import dashboard_insight_cache as _dic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_cache(user_id: str, language: str = "fr") -> None:
    """Put a stale entry into the shared cache for *user_id*."""
    _dic.set(user_id, language, {"run_index": 42, "stale": True}, time.time() - 600)


def _has_cache(user_id: str, language: str = "fr") -> bool:
    return _dic.get(user_id, language) is not None


def _clear_cache() -> None:
    keys = list(_dic._cache.keys())
    for k in keys:
        del _dic._cache[k]


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

async def _noop_refresh(db, user_id):
    return {"today_snapshot": {"run_index": 500}}


async def _noop_backfill(db, user_id):
    return {"backfilled": 0}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNormalSyncCacheInvalidation:
    """Verify that the normal sync path invalidates the dashboard cache."""

    def setup_method(self):
        _clear_cache()

    def teardown_method(self):
        _clear_cache()

    def test_normal_sync_invalidates_user_x_not_user_y(self):
        """
        Drive garmin.service._complete_post_activities_pipeline with mocked
        I/O and confirm:
        - cache for user X is wiped
        - cache for user Y is untouched
        """
        USER_X = "user_normal_sync_x"
        USER_Y = "user_normal_sync_y"

        # Pre-seed both users' cache
        _seed_cache(USER_X)
        _seed_cache(USER_Y)
        assert _has_cache(USER_X), "precondition: X has cached entry"
        assert _has_cache(USER_Y), "precondition: Y has cached entry"

        # Import here to avoid side-effects at collection time
        from garmin import service as garmin_service

        # Build a minimal fake provider that returns an empty daily metrics list
        fake_provider = MagicMock()
        fake_provider.get_daily_metrics.return_value = []

        # Build a minimal fake DB
        fake_collection = MagicMock()
        fake_collection.count_documents = AsyncMock(return_value=5)
        fake_collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1, upserted_id=None))
        fake_collection.find_one = AsyncMock(return_value=None)
        fake_collection.update = AsyncMock(return_value=MagicMock())

        fake_db = MagicMock()
        fake_db.garmin_activities = fake_collection
        fake_db.garmin_connections = fake_collection
        fake_db.garmin_capabilities = fake_collection
        fake_db.garmin_daily_metrics = fake_collection

        async def _run():
            with (
                patch("garmin.service.refresh_today_run_index_after_garmin_activities",
                      new=AsyncMock(side_effect=_noop_refresh)),
                patch("garmin.service.backfill_run_index_history_after_garmin_sync",
                      new=AsyncMock(side_effect=_noop_backfill)),
                patch("garmin.service._backfill_workouts_user",
                      new=AsyncMock(return_value=None)),
                patch("garmin.service.update_sync_progress",
                      new=AsyncMock(return_value=None)),
                patch("garmin.service.compute_run_index",
                      new=AsyncMock(return_value={"metrics": {"run_readiness": 70}})),
                patch("garmin.service._build_and_persist_capabilities",
                      new=AsyncMock(return_value=None)),
                patch("garmin.service._persist_daily_metrics",
                      new=AsyncMock(return_value=0)),
            ):
                await garmin_service._complete_post_activities_pipeline(
                    fake_db,
                    USER_X,
                    fake_provider,
                    activity_count=5,
                    synced_count=3,
                    new_count=2,
                    deep_sync=False,
                    resume_from=None,
                )

        asyncio.run(_run())

        assert not _has_cache(USER_X), "cache for user X must be invalidated after normal sync"
        assert _has_cache(USER_Y), "cache for user Y must NOT be touched"

    def test_incremental_sync_invalidates_user_x_not_user_y(self):
        """
        Drive the incremental_sync branch (calls backfill then invalidate)
        and confirm the same invariant.
        """
        USER_X = "user_incremental_x"
        USER_Y = "user_incremental_y"

        _seed_cache(USER_X)
        _seed_cache(USER_Y)

        from garmin import service as garmin_service

        fake_provider = MagicMock()
        fake_provider.sync_activities.return_value = []

        fake_garmin_connection = {"user_id": USER_X, "connected": True, "garmin_username": "garmin@test.com"}
        fake_collection = MagicMock()
        fake_collection.count_documents = AsyncMock(return_value=3)
        fake_collection.update_one = AsyncMock(return_value=MagicMock(matched_count=1, upserted_id=None))
        fake_collection.find_one = AsyncMock(return_value=fake_garmin_connection)
        fake_collection.update = AsyncMock(return_value=MagicMock())

        fake_db = MagicMock()
        fake_db.garmin_activities = fake_collection
        fake_db.garmin_connections = fake_collection

        async def _run():
            with (
                patch("garmin.service.session_store") as mock_ss,
                patch("garmin.service.get_provider_for_user",
                      return_value=fake_provider),
                patch("garmin.service._ingest_activities",
                      new=AsyncMock(return_value={"synced": 2, "new": 1, "newest_start": None})),
                patch("garmin.service._finalize_connection",
                      new=AsyncMock(return_value=3)),
                patch("garmin.service.refresh_today_run_index_after_garmin_activities",
                      new=AsyncMock(side_effect=_noop_refresh)),
                patch("garmin.service.backfill_run_index_history_after_garmin_sync",
                      new=AsyncMock(side_effect=_noop_backfill)),
                patch("garmin.service._backfill_workouts_user",
                      new=AsyncMock(return_value=None)),
                patch("garmin.service.update_sync_progress",
                      new=AsyncMock(return_value=None)),
                patch("garmin.service._mark_sync_failed",
                      new=AsyncMock(return_value=None)),
            ):
                mock_ss.ensure_session = AsyncMock(return_value=True)
                await garmin_service.incremental_sync(fake_db, USER_X)

        asyncio.run(_run())

        assert not _has_cache(USER_X), "cache for user X must be invalidated after incremental sync"
        assert _has_cache(USER_Y), "cache for user Y must NOT be touched"
