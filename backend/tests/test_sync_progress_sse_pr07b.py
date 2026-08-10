"""Unit tests for PR07B: Garmin Sync Progress SSE infrastructure.

Covers:
  - events/sync_progress_stream.py  — emit_sync_progress, sanitization
  - garmin/sync_progress.py         — update_sync_progress publishes to stream
  - feed/sync_progress_sse.py       — snapshot-first delivery, user isolation,
                                      heartbeat, reconnect
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Minimal stubs so the modules import without real Redis / Mongo
# ---------------------------------------------------------------------------

def _stub(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


for _m in ("redis", "redis.asyncio", "redis.exceptions", "motor", "motor.motor_asyncio"):
    if _m not in sys.modules:
        s = _stub(_m)
        if _m == "redis.exceptions":
            s.ResponseError = Exception
        if _m == "redis.asyncio":
            # Provide a from_url that can be patched in individual tests
            s.from_url = MagicMock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


OK = "\033[32m✅\033[0m"
FAIL = "\033[31m❌\033[0m"
_failures = []


def _ok(msg):
    print(f"  {OK} {msg}", flush=True)


def _fail(msg):
    print(f"  {FAIL} {msg}", flush=True)
    _failures.append(msg)
    raise AssertionError(msg)


# ===========================================================================
# 1. emit_sync_progress — sanitization
# ===========================================================================

def test_emit_sanitizes_sensitive_keys():
    """emit_sync_progress must drop keys containing sensitive substrings."""
    from events.sync_progress_stream import _sanitize_payload

    dirty = {
        "status": "in_progress",
        "phase": "activities_fetching",
        "user_password": "s3cr3t",      # must be dropped
        "garmin_token": "abc123",        # must be dropped
        "session_id": "xyz",             # must be dropped
        "activities_status": "ready",    # must be kept
        "run_index_status": "pending",   # must be kept
    }
    clean = _sanitize_payload(dirty)
    for bad in ("user_password", "garmin_token", "session_id"):
        if bad in clean:
            _fail(f"sensitive key '{bad}' not removed from payload")
    for good in ("status", "phase", "activities_status", "run_index_status"):
        if good not in clean:
            _fail(f"safe key '{good}' was incorrectly removed")
    _ok("_sanitize_payload removes sensitive keys and keeps safe ones")


# ===========================================================================
# 2. update_sync_progress — publishes to the stream
# ===========================================================================

def test_update_sync_progress_publishes_to_stream():
    """update_sync_progress must call emit_sync_progress after writing to Redis."""
    published: list[dict] = []

    async def fake_emit(uid, snapshot):
        published.append({"user_id": uid, **snapshot})
        return "1234-0"

    async def fake_get(_uid):
        return None

    class _FakeRedis:
        async def get(self, *_, **__):
            return None

        async def set(self, *_, **__):
            pass

    import jobs.redis_client as rc_mod
    import events.sync_progress_stream as eps_mod
    import garmin.sync_progress as sp_mod

    orig_get_redis = rc_mod.get_redis
    orig_emit = eps_mod.emit_sync_progress
    orig_get = sp_mod.get_sync_progress
    try:
        rc_mod.get_redis = lambda: _FakeRedis()
        eps_mod.emit_sync_progress = fake_emit
        sp_mod.get_sync_progress = fake_get

        result = _run(sp_mod.update_sync_progress("user123", phase="activities_fetching"))
    finally:
        rc_mod.get_redis = orig_get_redis
        eps_mod.emit_sync_progress = orig_emit
        sp_mod.get_sync_progress = orig_get

    if not published:
        _fail("update_sync_progress did not call emit_sync_progress")
    assert published[0]["user_id"] == "user123"
    assert published[0]["phase"] == "activities_fetching"
    _ok("update_sync_progress publishes SYNC_PROGRESS event to the stream")


# ===========================================================================
# 3. sync_progress_event_stream — snapshot on connect
# ===========================================================================

async def _collect_frames(gen, max_frames=10, timeout=3):
    """Drive the async generator and collect up to max_frames non-comment frames."""
    frames = []
    try:
        async def _inner():
            async for chunk in gen:
                if chunk.startswith(":"):
                    continue  # heartbeat
                frames.append(chunk)
                if len(frames) >= max_frames:
                    break
        await asyncio.wait_for(_inner(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return frames


class _FakeRequest:
    _disconnected = False

    async def is_disconnected(self):
        return self._disconnected


def test_snapshot_emitted_on_connect():
    """First data frame must be the current sync state (snapshot)."""
    snapshot_data = {
        "status": "in_progress",
        "phase": "enriching",
        "run_index_status": "ready",
        "readiness_status": "ready",
    }

    async def fake_get_sync_progress(_uid):
        return snapshot_data

    class _FakeRedis:
        async def xread(self, *_, **__):
            return []

        async def aclose(self):
            pass

    import os
    import feed.sync_progress_sse as sse_mod

    orig_get = sse_mod.get_sync_progress
    orig_env = os.environ.get("REDIS_URL")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    sse_mod.get_sync_progress = fake_get_sync_progress

    import redis.asyncio as _aioredis
    orig_from_url = getattr(_aioredis, "from_url", None)
    _aioredis.from_url = lambda *_, **__: _FakeRedis()

    try:
        req = _FakeRequest()

        async def _run_test():
            frames = []
            async for chunk in sse_mod.sync_progress_event_stream("user1", req, "$"):
                if chunk.startswith(":"):
                    continue
                frames.append(chunk)
                req._disconnected = True
                break
            return frames

        frames = _run(_run_test())
    finally:
        sse_mod.get_sync_progress = orig_get
        if orig_from_url is not None:
            _aioredis.from_url = orig_from_url
        if orig_env is None:
            os.environ.pop("REDIS_URL", None)

    if not frames:
        _fail("no data frame emitted on connect")
    first = frames[0]
    if "event: sync_progress" not in first:
        _fail(f"first frame is not sync_progress: {first!r}")
    if "enriching" not in first:
        _fail(f"snapshot not in first frame: {first!r}")
    _ok("snapshot is emitted as first data frame on connect")


def test_user_isolation():
    """Events for other users must NOT be forwarded."""
    import os
    import feed.sync_progress_sse as sse_mod
    import redis.asyncio as _aioredis

    stream_entries_for_other = [
        (
            "runindex:events:sync_progress",
            [
                ("1000-0", {
                    "event": "SYNC_PROGRESS",
                    "user_id": "other_user",
                    "data": json.dumps({"status": "in_progress", "phase": "activities_fetching"}),
                    "emitted_at": "0",
                }),
            ],
        )
    ]

    call_count = [0]

    class _FakeRedis:
        async def xread(self, *_, **__):
            call_count[0] += 1
            if call_count[0] == 1:
                return stream_entries_for_other
            return []

        async def aclose(self):
            pass

    async def fake_get_sync_progress(_uid):
        return None

    orig_get = sse_mod.get_sync_progress
    orig_from_url = getattr(_aioredis, "from_url", None)
    orig_env = os.environ.get("REDIS_URL")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    sse_mod.get_sync_progress = fake_get_sync_progress
    _aioredis.from_url = lambda *_, **__: _FakeRedis()

    try:
        req = _FakeRequest()

        async def _run_test():
            data_frames = []
            async for chunk in sse_mod.sync_progress_event_stream("my_user", req, "$"):
                if chunk.startswith(":"):
                    req._disconnected = True
                    break
                data_frames.append(chunk)
            return data_frames

        frames = _run(_run_test())
    finally:
        sse_mod.get_sync_progress = orig_get
        if orig_from_url is not None:
            _aioredis.from_url = orig_from_url
        if orig_env is None:
            os.environ.pop("REDIS_URL", None)

    if frames:
        _fail(f"received frame(s) for another user: {frames}")
    _ok("events for other users are filtered out (user isolation)")


def test_no_sensitive_data_in_sse_frame():
    """SSE frame data must not contain sensitive keys."""
    import os
    import feed.sync_progress_sse as sse_mod
    import redis.asyncio as _aioredis

    snapshot_data = {
        "status": "in_progress",
        "phase": "activities_fetching",
        "run_index_status": "ready",
    }

    async def fake_get_sync_progress(_uid):
        return snapshot_data

    class _FakeRedis:
        async def xread(self, *_, **__):
            return []

        async def aclose(self):
            pass

    orig_get = sse_mod.get_sync_progress
    orig_from_url = getattr(_aioredis, "from_url", None)
    orig_env = os.environ.get("REDIS_URL")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    sse_mod.get_sync_progress = fake_get_sync_progress
    _aioredis.from_url = lambda *_, **__: _FakeRedis()

    try:
        req = _FakeRequest()

        async def _run_test():
            async for chunk in sse_mod.sync_progress_event_stream("user1", req, "$"):
                if not chunk.startswith(":"):
                    req._disconnected = True
                    return chunk
            return ""

        frame = _run(_run_test())
    finally:
        sse_mod.get_sync_progress = orig_get
        if orig_from_url is not None:
            _aioredis.from_url = orig_from_url
        if orig_env is None:
            os.environ.pop("REDIS_URL", None)

    for forbidden in ("password", "token", "secret", "credential", "cookie"):
        if forbidden in frame.lower():
            _fail(f"SSE frame contains forbidden key '{forbidden}'")
    _ok("SSE frame contains no sensitive keys")


# ===========================================================================
# 4. Phase vs Status contract (snapshot shape)
# ===========================================================================

def test_phase_vs_status_contract():
    """Snapshot must carry independent phase and *_status fields."""
    import garmin.sync_progress as sp_mod

    async def fake_get(_uid):
        return None

    class _FakeRedis:
        async def get(self, *_, **__):
            return None

        async def set(self, *_, **__):
            pass

    async def fake_emit(*_, **__):
        return "1-0"

    with (
        patch("garmin.sync_progress.get_sync_progress", side_effect=fake_get),
    ):
        import jobs.redis_client as rc_mod
        import events.sync_progress_stream as eps_mod

        orig_get_redis = rc_mod.get_redis
        orig_emit = eps_mod.emit_sync_progress
        rc_mod.get_redis = lambda: _FakeRedis()
        eps_mod.emit_sync_progress = fake_emit

        result = _run(
            sp_mod.update_sync_progress(
                "u1",
                phase="metrics_7d_fetching",
                run_index_status="ready",
                readiness_status="pending",
            )
        )

        rc_mod.get_redis = orig_get_redis
        eps_mod.emit_sync_progress = orig_emit

    assert result.get("phase") == "metrics_7d_fetching", result
    assert result.get("run_index_status") == "ready", result
    assert result.get("readiness_status") == "pending", result
    assert result.get("status") == "in_progress", result
    _ok("phase and *_status are independent fields in the snapshot")


# ===========================================================================
# Runner
# ===========================================================================

def main() -> int:
    print("\nPR07B — Garmin Sync Progress SSE — unit tests", flush=True)
    tests = [
        test_emit_sanitizes_sensitive_keys,
        test_snapshot_emitted_on_connect,
        test_user_isolation,
        test_no_sensitive_data_in_sse_frame,
        test_phase_vs_status_contract,
        test_update_sync_progress_publishes_to_stream,
    ]
    passed = 0
    for t in tests:
        name = t.__name__
        print(f"\n[TEST] {name}", flush=True)
        try:
            t()
            passed += 1
        except AssertionError:
            pass  # already recorded in _failures
        except Exception as exc:
            print(f"  {FAIL} unexpected error: {exc}", flush=True)
            _failures.append(str(exc))

    total = len(tests)
    print(
        f"\nRESULT: {passed}/{total} passed"
        + (" ✅" if passed == total else f" — {total - passed} FAILED ❌"),
        flush=True,
    )
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
