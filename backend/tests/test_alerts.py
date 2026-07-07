"""Tests for monitoring.alerts — pure evaluation + best-effort webhook."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring import alerts  # noqa: E402
from monitoring.alerts import (  # noqa: E402
    evaluate_queue_health,
    send_alert,
    AlertState,
    LEVEL_CRITICAL,
    LEVEL_WARNING,
    UNHEALTHY_THRESHOLD,
    DEGRADED_THRESHOLD,
)


def _ok(m): print(f"  ✅ {m}", flush=True)
def _fail(m):
    print(f"  ❌ {m}", flush=True)
    raise AssertionError(m)


def test_unhealthy_two_consecutive():
    print("\n[TEST 1] unhealthy 2x consecutive -> critical", flush=True)
    st = AlertState()
    r1 = evaluate_queue_health({"status": "unhealthy"}, st)
    if r1.level is not None:
        _fail("first unhealthy must NOT alert")
    if r1.state.unhealthy_streak != 1:
        _fail(f"streak should be 1, got {r1.state.unhealthy_streak}")
    r2 = evaluate_queue_health({"status": "unhealthy", "queue_length": 3000}, r1.state)
    if r2.level != LEVEL_CRITICAL:
        _fail(f"second consecutive unhealthy should be critical, got {r2.level}")
    if "queue_length" not in r2.fields:
        _fail("critical alert should carry payload fields")
    _ok(f"critical after {UNHEALTHY_THRESHOLD} consecutive unhealthy")


def test_degraded_five_consecutive():
    print("\n[TEST 2] degraded 5x consecutive -> warning", flush=True)
    st = AlertState()
    res = None
    for i in range(1, DEGRADED_THRESHOLD + 1):
        res = evaluate_queue_health({"status": "degraded"}, st)
        st = res.state
        if i < DEGRADED_THRESHOLD and res.level is not None:
            _fail(f"should not alert before {DEGRADED_THRESHOLD} (i={i})")
    if res.level != LEVEL_WARNING:
        _fail(f"expected warning at {DEGRADED_THRESHOLD}, got {res.level}")
    _ok(f"warning after {DEGRADED_THRESHOLD} consecutive degraded")


def test_healthy_resets():
    print("\n[TEST 3] healthy resets both streaks", flush=True)
    st = AlertState(unhealthy_streak=1, degraded_streak=4)
    r = evaluate_queue_health({"status": "healthy"}, st)
    if r.level is not None:
        _fail("healthy should not alert")
    if r.state.unhealthy_streak != 0 or r.state.degraded_streak != 0:
        _fail(f"streaks should reset, got {r.state}")
    _ok("healthy resets streaks to 0")


def test_degraded_breaks_unhealthy_streak():
    print("\n[TEST 4] status change breaks the other streak", flush=True)
    st = AlertState(unhealthy_streak=1)
    r = evaluate_queue_health({"status": "degraded"}, st)
    if r.state.unhealthy_streak != 0 or r.state.degraded_streak != 1:
        _fail(f"degraded should reset unhealthy streak, got {r.state}")
    _ok("degraded resets unhealthy streak (non-consecutive)")


def test_unknown_status_noop():
    print("\n[TEST 5] unknown/missing status -> no alert, state unchanged", flush=True)
    st = AlertState(unhealthy_streak=1, degraded_streak=2)
    r = evaluate_queue_health({}, st)
    if r.level is not None or r.state != st:
        _fail(f"unknown status should be a no-op, got {r}")
    _ok("unknown status is a no-op")


async def _run_send_alert_no_webhook():
    print("\n[TEST 6] send_alert logs, skips webhook when unset", flush=True)
    os.environ.pop("ALERT_WEBHOOK_URL", None)
    # Should not raise, should not attempt any POST.
    await send_alert(LEVEL_CRITICAL, "test message", {"status": "unhealthy"})
    _ok("send_alert without ALERT_WEBHOOK_URL is a safe no-op (log only)")


async def _run_send_alert_webhook_failure():
    print("\n[TEST 7] webhook failure never propagates (best-effort)", flush=True)
    os.environ["ALERT_WEBHOOK_URL"] = "http://127.0.0.1:59999/nope"  # nothing listening
    posted = {"count": 0}

    class _FailClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            posted["count"] += 1
            raise RuntimeError("connection refused")

    import httpx
    orig = httpx.AsyncClient
    httpx.AsyncClient = _FailClient
    try:
        await send_alert(LEVEL_WARNING, "boom", {"status": "degraded"})  # must not raise
    finally:
        httpx.AsyncClient = orig
        os.environ.pop("ALERT_WEBHOOK_URL", None)
    if posted["count"] != 2:  # initial + exactly one retry
        _fail(f"expected 2 POST attempts (1 retry), got {posted['count']}")
    _ok("webhook failure retried once then swallowed (no exception)")


def main() -> int:
    print("monitoring.alerts tests", flush=True)
    failed = 0
    sync_tests = (test_unhealthy_two_consecutive, test_degraded_five_consecutive,
                  test_healthy_resets, test_degraded_breaks_unhealthy_streak,
                  test_unknown_status_noop)
    for t in sync_tests:
        try:
            t()
        except AssertionError:
            failed += 1
    for coro in (_run_send_alert_no_webhook, _run_send_alert_webhook_failure):
        try:
            asyncio.run(coro())
        except AssertionError:
            failed += 1
        except Exception as exc:
            print(f"  ❌ {coro.__name__}: {exc}", flush=True)
            failed += 1
    print(f"\nRESULT: {'ALL PASSED ✅' if failed == 0 else f'{failed} FAILED ❌'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
