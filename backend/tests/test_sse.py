"""Test the SSE delivery layer (feed.sse.event_stream) — read-only, filtered."""

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from jobs.redis_client import get_redis  # noqa: E402
from events.stream import STREAM_KEY, emit_activity_created  # noqa: E402
from feed.sse import event_stream  # noqa: E402


def _ok(m): print(f"  ✅ {m}", flush=True)
def _fail(m):
    print(f"  ❌ {m}", flush=True)
    raise AssertionError(m)


class _FakeRequest:
    async def is_disconnected(self):
        return False


async def _last_stream_id(r) -> str:
    entries = await r.xrevrange(STREAM_KEY, count=1)
    return entries[0][0] if entries else "0-0"


async def _collect_until(agen, needle: str, other_user_frames: list, timeout=8):
    async def _run():
        async for chunk in agen:
            if chunk.startswith(":"):  # heartbeat/comment
                continue
            if "wrong-user" in chunk:
                other_user_frames.append(chunk)
            if needle in chunk:
                return chunk
        return None
    return await asyncio.wait_for(_run(), timeout=timeout)


async def test_stream_delivers_and_filters():
    print("\n[TEST 1] SSE delivers activity_created filtered by user_id", flush=True)
    r = get_redis()
    await r.ping()
    uid = f"sse-{uuid.uuid4().hex[:8]}"
    ext = f"ext-{uuid.uuid4().hex[:8]}"

    start_id = await _last_stream_id(r)
    # Emit one event for OUR user and one for another user (must be filtered out).
    await emit_activity_created("wrong-user", {"external_id": "other", "start_time": "2026-01-01T00:00:00+00:00"})
    await emit_activity_created(uid, {"external_id": ext, "start_time": "2026-01-02T00:00:00+00:00"})

    agen = event_stream(uid, _FakeRequest(), start_id)
    other = []
    try:
        frame = await _collect_until(agen, ext, other)
    finally:
        await agen.aclose()

    if not frame:
        _fail("did not receive our activity_created frame")
    if "event: activity_created" not in frame or f'"{ext}"' not in frame:
        _fail(f"frame malformed: {frame!r}")
    if "id: " not in frame:
        _fail("frame missing SSE id (needed for reconnect)")
    if other:
        _fail("received a frame for another user (filtering broken)")
    _ok("delivered our event with SSE id; other-user event filtered out")


async def test_reconnect_from_last_id():
    print("\n[TEST 2] reconnect resumes from Last-Event-ID (no replay of old)", flush=True)
    r = get_redis()
    uid = f"sse-{uuid.uuid4().hex[:8]}"
    ext1 = f"e1-{uuid.uuid4().hex[:6]}"
    ext2 = f"e2-{uuid.uuid4().hex[:6]}"

    start_id = await _last_stream_id(r)
    await emit_activity_created(uid, {"external_id": ext1, "start_time": "2026-01-03T00:00:00+00:00"})

    # First stream: read ext1, capture its SSE id.
    agen = event_stream(uid, _FakeRequest(), start_id)
    seen = []
    try:
        frame = await asyncio.wait_for(_first_data(agen), timeout=8)
    finally:
        await agen.aclose()
    resume_id = _extract_id(frame)
    if not resume_id:
        _fail("could not capture SSE id for reconnect")

    # Emit ext2 AFTER resume point, reconnect from resume_id -> should get ext2, not ext1.
    await emit_activity_created(uid, {"external_id": ext2, "start_time": "2026-01-04T00:00:00+00:00"})
    agen2 = event_stream(uid, _FakeRequest(), resume_id)
    got = []
    try:
        f2 = await asyncio.wait_for(_first_data(agen2), timeout=8)
    finally:
        await agen2.aclose()
    if f"\"{ext2}\"" not in f2:
        _fail(f"reconnect should deliver ext2, got: {f2!r}")
    if ext1 in f2:
        _fail("reconnect replayed the already-seen event (not idempotent)")
    _ok("reconnect resumed after Last-Event-ID (ext2 only, no replay)")


async def _first_data(agen):
    async for chunk in agen:
        if chunk.startswith(":"):
            continue
        return chunk
    return None


def _extract_id(frame: str):
    for line in (frame or "").splitlines():
        if line.startswith("id: "):
            return line[4:].strip()
    return None


async def main() -> int:
    print("SSE feed stream tests", flush=True)
    failed = 0
    for t in (test_stream_delivers_and_filters, test_reconnect_from_last_id):
        try:
            await t()
        except AssertionError:
            failed += 1
        except Exception as exc:
            print(f"  ❌ {t.__name__}: {exc}", flush=True)
            failed += 1
    print(f"\nRESULT: {'ALL PASSED ✅' if failed == 0 else f'{failed} FAILED ❌'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
