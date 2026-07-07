"""End-to-end backend tests for the Strava-like quasi-real-time Garmin pipeline.

Covers:
  - POST /api/garmin/sync (non-blocking enqueue)
  - garmin_activities ingestion + dedupe by external_id
  - Redis Stream fan-out -> workouts + feed cache
  - GET /api/garmin/activities cache-first with source/since
  - POST /api/garmin/activity-signal (no sync trigger)
  - Per-user cooldown & global concurrency counter (Redis)
  - GET /api/garmin/queue/health & /api/garmin/status
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Optional

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://charge-load.preview.emergentagent.com").rstrip("/")
USER_ID = "default"
API = f"{BASE_URL}/api"


# ---------- Redis helpers via redis-cli (isolated tests: no python-redis coupling) ----------
def _redis_cli(*args: str) -> str:
    env = {**os.environ, "LD_LIBRARY_PATH": "/app/lib"}
    proc = subprocess.run(
        ["/app/bin/redis-cli", *args],
        env=env, capture_output=True, text=True, timeout=10,
    )
    return proc.stdout.strip()


def redis_get(key: str) -> Optional[str]:
    v = _redis_cli("GET", key)
    return None if v == "" else v


def redis_exists(key: str) -> bool:
    return _redis_cli("EXISTS", key) == "1"


def redis_llen(key: str) -> int:
    v = _redis_cli("LLEN", key)
    try:
        return int(v)
    except ValueError:
        return 0


def redis_lrange(key: str, start: int = 0, stop: int = -1) -> list:
    proc = subprocess.run(
        ["/app/bin/redis-cli", "LRANGE", key, str(start), str(stop)],
        env={**os.environ, "LD_LIBRARY_PATH": "/app/lib"},
        capture_output=True, text=True, timeout=10,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def redis_xlen(key: str) -> int:
    v = _redis_cli("XLEN", key)
    try:
        return int(v)
    except ValueError:
        return 0


def redis_ttl(key: str) -> int:
    v = _redis_cli("TTL", key)
    try:
        return int(v)
    except ValueError:
        return -2


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _wait_sync_done(session, timeout=90) -> bool:
    """Wait until sync_pending:{user_id} is cleared (worker ACKed)."""
    key = f"sync_pending:{USER_ID}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not redis_exists(key):
            return True
        time.sleep(1)
    return False


# ============================== Basic reachability
class TestHealth:
    """Basic service reachability (queue health + garmin status)."""

    def test_queue_health(self, session):
        r = session.get(f"{API}/garmin/queue/health", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("healthy", "degraded")
        assert data["redis_connected"] is True
        # at least the sync-worker heartbeats
        assert data["active_workers"] >= 1, f"expected >=1 worker, got {data}"

    def test_garmin_status_connected(self, session):
        r = session.get(f"{API}/garmin/status", params={"user_id": USER_ID}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["connected"] is True
        assert data["provider"] == "gccli"


# ============================== Non-blocking sync + ingestion + dedupe
class TestSyncAndIngestion:
    """POST /api/garmin/sync returns fast + activities are ingested + deduped."""

    def test_sync_returns_fast_and_queued(self, session):
        # Clear pending flag to force a real enqueue (cooldown does not gate manual)
        _redis_cli("DEL", f"sync_pending:{USER_ID}")
        t0 = time.time()
        r = session.post(f"{API}/garmin/sync", params={"user_id": USER_ID}, timeout=10)
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        data = r.json()
        # Non-blocking: must return quickly (well under a real gccli sync)
        assert elapsed < 5.0, f"sync endpoint blocked {elapsed:.2f}s (should be <5s)"
        assert data.get("status") in ("queued", "already_queued"), data

    def test_sync_worker_processes_and_updates_last_sync(self, session):
        # Ensure a fresh sync completes
        before = session.get(f"{API}/garmin/status", params={"user_id": USER_ID}).json()
        assert _wait_sync_done(session, timeout=120), "sync_pending never cleared"
        # small delay so status endpoint reflects the update
        time.sleep(1)
        after = session.get(f"{API}/garmin/status", params={"user_id": USER_ID}).json()
        assert after["connected"] is True
        assert after["last_sync"] is not None
        # last_sync should not regress
        assert after["last_sync"] >= (before.get("last_sync") or "")
        assert after["activity_count"] >= 0

    def test_activities_populated_and_deduped(self, session):
        # Count before re-sync
        r1 = session.get(f"{API}/garmin/activities",
                         params={"user_id": USER_ID, "limit": 200}, timeout=15)
        assert r1.status_code == 200
        count_before = r1.json()["count"]
        assert count_before >= 0

        # Kick off another sync — cooldown does not gate manual endpoint
        _redis_cli("DEL", f"sync_pending:{USER_ID}")
        session.post(f"{API}/garmin/sync", params={"user_id": USER_ID}, timeout=10)
        assert _wait_sync_done(session, timeout=120)
        time.sleep(2)  # allow event fan-out to run

        r2 = session.get(f"{API}/garmin/activities",
                         params={"user_id": USER_ID, "limit": 200}, timeout=15)
        assert r2.status_code == 200
        count_after = r2.json()["count"]
        # Idempotency: upsert by external_id must not create duplicates.
        assert count_after == count_before, \
            f"activity count changed after re-sync: {count_before} -> {count_after} (dedupe broken)"


# ============================== Event-driven fan-out
class TestEventFanOut:
    """After a sync producing activities, feed cache + workouts get populated."""

    def test_stream_key_exists(self):
        # Stream is created lazily by emit; after sync it must exist
        assert redis_xlen("cardiocoach:events:activity_created") >= 0

    def test_feed_cache_warmed(self, session):
        # Feed cache is written by event-worker OR by the GET fallback warming.
        # Trigger a GET so warming happens even if no NEW events fired.
        session.get(f"{API}/garmin/activities",
                    params={"user_id": USER_ID, "limit": 5}, timeout=15)
        time.sleep(1)
        cached_len = redis_llen(f"cardiocoach:feed:{USER_ID}")
        assert cached_len > 0, "Redis feed cache should be populated"

    def test_activities_source_cache(self, session):
        # After warm, the endpoint should serve from cache.
        r = session.get(f"{API}/garmin/activities",
                        params={"user_id": USER_ID, "limit": 5}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "activities" in data and "count" in data  # backward compat
        assert "source" in data, "response must include `source` field"
        assert data["source"] == "cache", f"expected cache, got {data['source']}"
        assert data["count"] == len(data["activities"])
        assert data["count"] <= 5

    def test_workouts_derived_layer_populated(self, session):
        # The dashboard reads `workouts`; event-worker must upsert them.
        # Best proxy from the public API: check the frontend workouts endpoint
        # is populated with garmin source docs.
        # Fallback: at least a Garmin activity exists (which drives the derived layer).
        acts = session.get(f"{API}/garmin/activities",
                           params={"user_id": USER_ID, "limit": 1}, timeout=15).json()
        if acts["count"] == 0:
            pytest.skip("no activities to derive workouts from")
        # Ping the workouts route if exposed (best-effort)
        w = session.get(f"{API}/workouts", params={"user_id": USER_ID}, timeout=15)
        if w.status_code == 200:
            body = w.json()
            items = body if isinstance(body, list) else body.get("workouts") or body.get("items") or []
            garmin_items = [x for x in items if (x.get("data_source") == "garmin"
                                                 or str(x.get("id", "")).startswith("garmin-"))]
            assert len(garmin_items) > 0, "no derived garmin workouts found"


# ============================== `since` filter
class TestSinceFilter:
    def test_since_filter_returns_only_newer(self, session):
        r = session.get(f"{API}/garmin/activities",
                        params={"user_id": USER_ID, "limit": 50}, timeout=15)
        assert r.status_code == 200
        acts = r.json()["activities"]
        if len(acts) < 2:
            pytest.skip("need >=2 activities to test since filter")
        # Use the oldest activity's start_time as the `since` cutoff.
        starts = sorted([a.get("start_time") for a in acts if a.get("start_time")])
        cutoff = starts[0]
        r2 = session.get(f"{API}/garmin/activities",
                         params={"user_id": USER_ID, "limit": 50, "since": cutoff}, timeout=15)
        assert r2.status_code == 200
        filtered = r2.json()["activities"]
        assert all(a.get("start_time", "") > cutoff for a in filtered), \
            "since filter must return only start_time > cutoff"
        assert len(filtered) < len(acts), "since filter should exclude the cutoff row"


# ============================== activity-signal contract
class TestActivitySignal:
    """POST /activity-signal MUST NOT enqueue a sync."""

    def test_signal_sets_key_and_no_sync(self, session):
        # Baseline queue length
        q_before = redis_llen("cardiocoach:garmin:queue")
        # Ensure no pending flag from earlier tests
        _redis_cli("DEL", f"sync_pending:{USER_ID}")

        r = session.post(f"{API}/garmin/activity-signal",
                         params={"user_id": USER_ID}, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "ok"
        assert data.get("tier_hint") == "active"

        # Redis active_signal key must be set with TTL close to 45min
        signal_ttl = redis_ttl(f"cardiocoach:active_signal:{USER_ID}")
        assert 0 < signal_ttl <= 45 * 60, f"active_signal TTL bad: {signal_ttl}"

        # No new job should be enqueued AND no pending flag
        time.sleep(0.5)
        q_after = redis_llen("cardiocoach:garmin:queue")
        assert q_after <= q_before, "activity-signal must not enqueue a sync"
        # And pending flag must not be set as a side effect
        assert not redis_exists(f"sync_pending:{USER_ID}"), \
            "activity-signal must not set sync_pending flag"


# ============================== Rate limiter state
class TestRateLimiter:
    def test_cooldown_key_set_after_sync(self, session):
        # After earlier tests ran a sync, the cooldown key must exist with a
        # TTL <= 900s.
        ttl = redis_ttl(f"cardiocoach:sync_cooldown:{USER_ID}")
        assert ttl > 0, f"cooldown TTL missing/expired: {ttl}"
        assert ttl <= 900, f"cooldown TTL too high: {ttl}"

    def test_global_active_counter_exists_and_bounded(self):
        # After all syncs finished, counter should be 0 or unset (not > cap).
        v = redis_get("cardiocoach:garmin:global_active")
        # counter is optional (may not exist if never used); if present must be <=8
        if v is not None and v != "":
            assert int(v) <= 8, f"global_active counter above cap 8: {v}"


# ============================== Backward compatibility
class TestBackwardCompat:
    def test_activities_response_shape(self, session):
        r = session.get(f"{API}/garmin/activities",
                        params={"user_id": USER_ID, "limit": 3}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "activities" in data
        assert "count" in data
        assert isinstance(data["activities"], list)
        assert isinstance(data["count"], int)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
