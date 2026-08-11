"""Unit tests for PR07C.1 — Sync Progress Payload Contract.

Verifies that the SSE payload includes:
  - run_index_status = "ready" and run_index = <integer value>
  - readiness_status = "ready" and readiness = <integer value>
  - activities_count = <integer count>

when the sync pipeline reaches the run_index_ready / readiness_ready phases.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Minimal stubs so modules import without real Redis / Mongo
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
            s.from_url = MagicMock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


OK = "\033[32m✅\033[0m"
FAIL = "\033[31m❌\033[0m"
_failures: list[str] = []


def _ok(msg: str) -> None:
    print(f"  {OK} {msg}", flush=True)


def _fail(msg: str) -> None:
    print(f"  {FAIL} {msg}", flush=True)
    _failures.append(msg)
    raise AssertionError(msg)


# ===========================================================================
# 1. _DEFAULT_STATUS contains run_index and readiness fields
# ===========================================================================

def test_default_status_contains_run_index_and_readiness():
    """_DEFAULT_STATUS must initialise run_index and readiness to None."""
    from garmin.sync_progress import _DEFAULT_STATUS  # noqa: PLC0415

    if "run_index" not in _DEFAULT_STATUS:
        _fail("'run_index' is missing from _DEFAULT_STATUS")
    if "readiness" not in _DEFAULT_STATUS:
        _fail("'readiness' is missing from _DEFAULT_STATUS")
    if _DEFAULT_STATUS["run_index"] is not None:
        _fail(f"'run_index' default should be None, got {_DEFAULT_STATUS['run_index']!r}")
    if _DEFAULT_STATUS["readiness"] is not None:
        _fail(f"'readiness' default should be None, got {_DEFAULT_STATUS['readiness']!r}")
    _ok("_DEFAULT_STATUS contains run_index=None and readiness=None")


# ===========================================================================
# 2. update_sync_progress preserves run_index and readiness in the snapshot
# ===========================================================================

def test_update_sync_progress_preserves_run_index_and_readiness():
    """Calling update_sync_progress with run_index / readiness must persist them."""
    snapshots: list[dict] = []

    class _FakeRedis:
        _store: dict = {}

        async def get(self, key):
            return self._store.get(key)

        async def set(self, key, value, ex=None):
            self._store[key] = value

    fake_redis = _FakeRedis()

    async def fake_emit(uid, snapshot):
        snapshots.append(dict(snapshot))
        return "1-0"

    import jobs.redis_client as rc_mod
    import events.sync_progress_stream as eps_mod
    import garmin.sync_progress as sp_mod

    orig_get_redis = rc_mod.get_redis
    orig_emit = eps_mod.emit_sync_progress

    try:
        rc_mod.get_redis = lambda: fake_redis
        eps_mod.emit_sync_progress = fake_emit

        # Simulate run_index_ready phase
        result = _run(sp_mod.update_sync_progress(
            "user1",
            phase="run_index_ready",
            activities_status="ready",
            activities_count=42,
            run_index_status="ready",
            run_index=375,
            daily_metrics_status="pending",
            readiness_status="pending",
            error_code=None,
        ))
    finally:
        rc_mod.get_redis = orig_get_redis
        eps_mod.emit_sync_progress = orig_emit

    if result.get("run_index_status") != "ready":
        _fail(f"run_index_status expected 'ready', got {result.get('run_index_status')!r}")
    if result.get("run_index") != 375:
        _fail(f"run_index expected 375, got {result.get('run_index')!r}")
    if result.get("activities_count") != 42:
        _fail(f"activities_count expected 42, got {result.get('activities_count')!r}")

    _ok("update_sync_progress persists run_index and activities_count in the snapshot")


def test_update_sync_progress_preserves_readiness():
    """Calling update_sync_progress with readiness must persist the value."""

    class _FakeRedis:
        _store: dict = {}

        async def get(self, key):
            return self._store.get(key)

        async def set(self, key, value, ex=None):
            self._store[key] = value

    fake_redis = _FakeRedis()

    async def fake_emit(uid, snapshot):
        return "1-0"

    import jobs.redis_client as rc_mod
    import events.sync_progress_stream as eps_mod
    import garmin.sync_progress as sp_mod

    orig_get_redis = rc_mod.get_redis
    orig_emit = eps_mod.emit_sync_progress

    try:
        rc_mod.get_redis = lambda: fake_redis
        eps_mod.emit_sync_progress = fake_emit

        result = _run(sp_mod.update_sync_progress(
            "user2",
            phase="readiness_ready",
            activities_status="ready",
            activities_count=10,
            run_index_status="ready",
            run_index=420,
            daily_metrics_status="ready",
            readiness_status="ready",
            readiness=78,
            error_code=None,
        ))
    finally:
        rc_mod.get_redis = orig_get_redis
        eps_mod.emit_sync_progress = orig_emit

    if result.get("readiness_status") != "ready":
        _fail(f"readiness_status expected 'ready', got {result.get('readiness_status')!r}")
    if result.get("readiness") != 78:
        _fail(f"readiness expected 78, got {result.get('readiness')!r}")
    if result.get("run_index") != 420:
        _fail(f"run_index expected 420, got {result.get('run_index')!r}")

    _ok("update_sync_progress persists readiness value in the snapshot")


# ===========================================================================
# 3. SSE frame carries run_index and readiness when run_index_status = ready
# ===========================================================================

def test_sse_snapshot_includes_run_index_and_readiness():
    """Initial SSE snapshot must include run_index and readiness fields."""
    import os
    import feed.sync_progress_sse as sse_mod
    import redis.asyncio as _aioredis

    snapshot_data = {
        "status": "in_progress",
        "phase": "readiness_ready",
        "activities_status": "ready",
        "activities_count": 55,
        "run_index_status": "ready",
        "run_index": 512,
        "daily_metrics_status": "ready",
        "readiness_status": "ready",
        "readiness": 82,
        "error_code": None,
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

    class _Req:
        async def is_disconnected(self):
            return False

    try:
        req = _Req()

        async def _run_test():
            async for chunk in sse_mod.sync_progress_event_stream("user1", req, "$"):
                if not chunk.startswith(":"):
                    return chunk
            return ""

        frame = _run(_run_test())
    finally:
        sse_mod.get_sync_progress = orig_get
        if orig_from_url is not None:
            _aioredis.from_url = orig_from_url
        if orig_env is None:
            os.environ.pop("REDIS_URL", None)

    # Parse data payload from frame
    data_line = next((l for l in frame.splitlines() if l.startswith("data:")), None)
    if data_line is None:
        _fail(f"No data line in SSE frame: {frame!r}")
    payload = json.loads(data_line[len("data:"):].strip())

    if payload.get("run_index_status") != "ready":
        _fail(f"SSE payload run_index_status expected 'ready', got {payload.get('run_index_status')!r}")
    if payload.get("run_index") != 512:
        _fail(f"SSE payload run_index expected 512, got {payload.get('run_index')!r}")
    if payload.get("readiness_status") != "ready":
        _fail(f"SSE payload readiness_status expected 'ready', got {payload.get('readiness_status')!r}")
    if payload.get("readiness") != 82:
        _fail(f"SSE payload readiness expected 82, got {payload.get('readiness')!r}")
    if payload.get("activities_count") != 55:
        _fail(f"SSE payload activities_count expected 55, got {payload.get('activities_count')!r}")

    _ok("SSE snapshot frame includes run_index, readiness, and activities_count with correct values")


# ===========================================================================
# Runner
# ===========================================================================

def main() -> int:
    print("\nPR07C.1 — Sync Progress Payload Contract — unit tests", flush=True)
    tests = [
        test_default_status_contains_run_index_and_readiness,
        test_update_sync_progress_preserves_run_index_and_readiness,
        test_update_sync_progress_preserves_readiness,
        test_sse_snapshot_includes_run_index_and_readiness,
    ]
    passed = 0
    for t in tests:
        print(f"\n[TEST] {t.__name__}", flush=True)
        try:
            t()
            passed += 1
        except AssertionError:
            pass
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
