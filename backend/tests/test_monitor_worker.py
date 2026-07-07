"""Tests for the dedicated monitor worker (state-change alerting, adaptive
interval, leader election). Uses live Redis for state keys; mocks send_alert to
count emissions without hitting a webhook.

Run:  cd /app/backend && python -m tests.test_monitor_worker
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from jobs.redis_client import get_redis  # noqa: E402
from workers import monitor_worker as mw  # noqa: E402


def _ok(m): print(f"  ✅ {m}", flush=True)
def _fail(m):
    print(f"  ❌ {m}", flush=True)
    raise AssertionError(m)


class _AlertRecorder:
    def __init__(self): self.calls = []
    async def __call__(self, level, message, payload):
        self.calls.append((level, message))


async def _clear(r):
    await r.delete(mw.STATE_KEY, mw.LAST_LEVEL_KEY, mw.LEADER_KEY)


async def test_adaptive_interval():
    print("\n[TEST 1] adaptive interval by status", flush=True)
    if mw.next_interval("unhealthy") != mw.INTERVAL_UNHEALTHY: _fail("unhealthy interval")
    if mw.next_interval("degraded") != mw.INTERVAL_DEGRADED: _fail("degraded interval")
    if mw.next_interval("healthy") != mw.INTERVAL_HEALTHY: _fail("healthy interval")
    if mw.next_interval(None) != mw.INTERVAL_HEALTHY: _fail("unknown -> healthy interval")
    _ok(f"30/60/120 = {mw.INTERVAL_UNHEALTHY}/{mw.INTERVAL_DEGRADED}/{mw.INTERVAL_HEALTHY}")


async def test_state_change_only(r):
    print("\n[TEST 2] alerts only on state change (no spam)", flush=True)
    await _clear(r)
    rec = _AlertRecorder()
    orig = mw.send_alert
    mw.send_alert = rec
    try:
        # 1st unhealthy: below threshold (2) -> no alert
        assert await mw.process_once(r, {"status": "unhealthy"}) is None
        # 2nd unhealthy: crosses threshold -> critical (emit once)
        lvl = await mw.process_once(r, {"status": "unhealthy", "queue_length": 5000})
        if lvl != "critical": _fail(f"expected critical on 2nd, got {lvl}")
        # 3rd + 4th unhealthy: still critical, but SAME level -> no new alert
        assert await mw.process_once(r, {"status": "unhealthy"}) is None
        assert await mw.process_once(r, {"status": "unhealthy"}) is None
        if len(rec.calls) != 1:
            _fail(f"expected exactly 1 alert across repeated unhealthy, got {len(rec.calls)}")
        _ok("critical emitted once, repeats suppressed")

        # recovery: healthy -> one 'info' recovery alert, then reset
        lvl = await mw.process_once(r, {"status": "healthy"})
        if lvl != "info": _fail(f"expected info recovery, got {lvl}")
        # healthy again -> nothing
        assert await mw.process_once(r, {"status": "healthy"}) is None
        if len(rec.calls) != 2:
            _fail(f"expected 2 total (critical+recovery), got {len(rec.calls)}")
        if await r.get(mw.LAST_LEVEL_KEY) is not None:
            _fail("last_level should be cleared after recovery")
        _ok("recovery emitted once on return to healthy, then silent")
    finally:
        mw.send_alert = orig
        await _clear(r)


async def test_degraded_then_escalate(r):
    print("\n[TEST 3] degraded warning then escalation to critical", flush=True)
    await _clear(r)
    rec = _AlertRecorder()
    orig = mw.send_alert
    mw.send_alert = rec
    try:
        # 5 consecutive degraded -> warning at the 5th
        from monitoring.alerts import DEGRADED_THRESHOLD
        for i in range(1, DEGRADED_THRESHOLD + 1):
            lvl = await mw.process_once(r, {"status": "degraded"})
        if lvl != "warning": _fail(f"expected warning at {DEGRADED_THRESHOLD}, got {lvl}")
        # escalate: 2 consecutive unhealthy -> critical (different level -> emit)
        await mw.process_once(r, {"status": "unhealthy"})
        lvl = await mw.process_once(r, {"status": "unhealthy"})
        if lvl != "critical": _fail(f"expected escalation to critical, got {lvl}")
        levels = [c[0] for c in rec.calls]
        if levels != ["warning", "critical"]:
            _fail(f"expected [warning, critical], got {levels}")
        _ok("warning then critical escalation emitted (2 alerts)")
    finally:
        mw.send_alert = orig
        await _clear(r)


async def test_leader_election(r):
    print("\n[TEST 4] leader election: one leader, standby denied, refresh works", flush=True)
    await _clear(r)
    if not await mw.acquire_or_refresh_leadership(r, "nodeA:1"):
        _fail("first candidate should become leader")
    if await mw.acquire_or_refresh_leadership(r, "nodeB:2"):
        _fail("second candidate should be denied (standby)")
    if not await mw.acquire_or_refresh_leadership(r, "nodeA:1"):
        _fail("existing leader should refresh and keep leadership")
    ttl = await r.ttl(mw.LEADER_KEY)
    if ttl <= 0 or ttl > mw.LEADER_TTL:
        _fail(f"leader TTL not refreshed correctly: {ttl}")
    _ok(f"single leader enforced, TTL refreshed ({ttl}s)")
    await _clear(r)


async def main() -> int:
    print("monitor_worker tests", flush=True)
    r = get_redis()
    await r.ping()
    failed = 0
    try:
        await test_adaptive_interval()
    except AssertionError:
        failed += 1
    for t in (test_state_change_only, test_degraded_then_escalate, test_leader_election):
        try:
            await t(r)
        except AssertionError:
            failed += 1
        except Exception as exc:
            print(f"  ❌ {t.__name__}: {exc}", flush=True)
            failed += 1
    print(f"\nRESULT: {'ALL PASSED ✅' if failed == 0 else f'{failed} FAILED ❌'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
