"""Unit tests for PR07C.2 -- GZip bypass for SSE responses.

Verifies that SSEAwareGZipMiddleware (middleware/__init__.py):

  1. SSE + Accept-Encoding: gzip  ->  no Content-Encoding: gzip.
  2. First SSE frame delivered immediately (not buffered).
  3. Non-SSE HTTP response remains compressible (GZip active).
  4. Existing SSE test files are still present.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Minimal stubs so imports don't require a real environment
# ---------------------------------------------------------------------------

def _stub(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


for _m in (
    "redis", "redis.asyncio", "redis.exceptions",
    "motor", "motor.motor_asyncio",
    "jose", "jose.jwt", "jose.exceptions",
    "passlib", "passlib.context",
    "stripe",
    "celery",
):
    _stub(_m)

sys.modules["redis"].exceptions = _stub("redis.exceptions")
sys.modules["redis.exceptions"].ResponseError = Exception
sys.modules["redis.asyncio"].from_url = MagicMock()

# ---------------------------------------------------------------------------
# Import the middleware class under test
# ---------------------------------------------------------------------------

from middleware import SSEAwareGZipMiddleware  # noqa: E402

OK = "\033[32m[OK]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
_failures: list[str] = []


def _ok(msg: str) -> None:
    print(f"  {OK} {msg}", flush=True)


def _fail(msg: str) -> None:
    print(f"  {FAIL} {msg}", flush=True)
    _failures.append(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scope(path: str, accept: str = "", accept_encoding: str = "gzip") -> dict:
    headers: list[tuple[bytes, bytes]] = []
    if accept:
        headers.append((b"accept", accept.encode()))
    if accept_encoding:
        headers.append((b"accept-encoding", accept_encoding.encode()))
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
    }


async def _fake_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


# ---------------------------------------------------------------------------
# Test 1 -- SSE + Accept-Encoding: gzip -> no Content-Encoding: gzip
# ---------------------------------------------------------------------------

async def test_sse_no_gzip_header():
    """SSE response must not carry Content-Encoding: gzip."""
    print("\n[TEST 1] SSE + Accept-Encoding: gzip -> no Content-Encoding: gzip", flush=True)

    sse_body = ("data: " + "x" * 1200 + "\n\n").encode()

    async def sse_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [[b"content-type", b"text/event-stream"]]})
        await send({"type": "http.response.body", "body": sse_body, "more_body": False})

    middleware = SSEAwareGZipMiddleware(sse_app, minimum_size=1000)
    response_headers: list = []

    async def capture_send(msg):
        if msg["type"] == "http.response.start":
            response_headers.extend(msg.get("headers", []))

    # Bypass via Accept: text/event-stream
    scope = _make_scope("/api/garmin/sync/stream", accept="text/event-stream")
    await middleware(scope, _fake_receive, capture_send)
    header_names = {k.lower() for k, _ in response_headers}
    if b"content-encoding" in header_names:
        _fail("SSE response has Content-Encoding header (should be absent)")
    else:
        _ok("No Content-Encoding on SSE response (Accept: text/event-stream)")

    # Bypass via path ending /stream (no Accept header)
    response_headers.clear()
    scope2 = _make_scope("/api/garmin/sync/stream")
    await middleware(scope2, _fake_receive, capture_send)
    if b"content-encoding" in {k.lower() for k, _ in response_headers}:
        _fail("Path-based bypass failed: Content-Encoding still present")
    else:
        _ok("Path-based bypass works (path ends with /stream)")


# ---------------------------------------------------------------------------
# Test 2 -- First SSE frame delivered immediately
# ---------------------------------------------------------------------------

async def test_sse_first_frame_immediate():
    """Frames must be delivered as soon as sent, not buffered."""
    print("\n[TEST 2] First SSE frame delivered immediately (no buffering)", flush=True)

    frames_received: list[bytes] = []

    async def streaming_sse_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [[b"content-type", b"text/event-stream"]]})
        await send({"type": "http.response.body", "body": b": connected\n\n", "more_body": True})
        await send({"type": "http.response.body", "body": b"data: hello\n\n", "more_body": False})

    async def capture_send(msg):
        if msg["type"] == "http.response.body":
            frames_received.append(msg.get("body", b""))

    middleware = SSEAwareGZipMiddleware(streaming_sse_app, minimum_size=1000)
    scope = _make_scope("/api/garmin/sync/stream", accept="text/event-stream")
    await middleware(scope, _fake_receive, capture_send)

    if len(frames_received) < 2:
        _fail(f"Expected 2 separate frames, got {len(frames_received)}")
    elif frames_received[0] != b": connected\n\n":
        _fail(f"First frame wrong: {frames_received[0]!r}")
    else:
        _ok(f"First frame delivered immediately: {frames_received[0]!r}")


# ---------------------------------------------------------------------------
# Test 3 -- Non-SSE response remains compressible
# ---------------------------------------------------------------------------

async def test_non_sse_still_compressed():
    """Regular JSON responses > 1 KB must still be GZip-compressed."""
    print("\n[TEST 3] Non-SSE HTTP response remains compressible", flush=True)

    large_body = json.dumps({"data": "x" * 2000}).encode()

    async def json_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [[b"content-type", b"application/json"]]})
        await send({"type": "http.response.body", "body": large_body, "more_body": False})

    middleware = SSEAwareGZipMiddleware(json_app, minimum_size=1000)
    captured_headers: list = []
    captured_body = bytearray()

    async def capture_send(msg):
        if msg["type"] == "http.response.start":
            captured_headers.extend(msg.get("headers", []))
        elif msg["type"] == "http.response.body":
            captured_body.extend(msg.get("body", b""))

    scope = _make_scope("/api/activities", accept="application/json", accept_encoding="gzip")
    await middleware(scope, _fake_receive, capture_send)

    header_map = {k.lower(): v for k, v in captured_headers}
    if b"content-encoding" not in header_map or header_map[b"content-encoding"] != b"gzip":
        _fail("Non-SSE response was NOT compressed (GZip inactive)")
    else:
        try:
            decompressed = gzip.decompress(bytes(captured_body))
            assert b"data" in decompressed
            _ok("Non-SSE JSON response compressed with GZip")
        except Exception as exc:
            _fail(f"Body not valid gzip: {exc}")


# ---------------------------------------------------------------------------
# Test 4 -- Existing SSE test files are still present
# ---------------------------------------------------------------------------

def test_existing_sse_files():
    """Existing SSE test modules must still be present (no file removal)."""
    print("\n[TEST 4] Existing SSE test files present", flush=True)
    tests_dir = Path(__file__).resolve().parent
    for name in (
        "test_sse",
        "test_sync_progress_sse_pr07b",
        "test_sync_progress_payload_pr07c",
    ):
        path = tests_dir / f"{name}.py"
        if not path.exists():
            _fail(f"{name}.py not found")
        else:
            _ok(f"{name}.py present")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def _main() -> int:
    print("PR07C.2 -- GZip SSE bypass tests", flush=True)
    for t in (
        test_sse_no_gzip_header,
        test_sse_first_frame_immediate,
        test_non_sse_still_compressed,
    ):
        try:
            await t()
        except Exception as exc:
            _fail(f"{t.__name__}: {exc}")

    test_existing_sse_files()

    if _failures:
        print(f"\nRESULT: {len(_failures)} FAILED", flush=True)
        for f in _failures:
            print(f"  * {f}", flush=True)
        return 1
    print("\nRESULT: ALL PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
