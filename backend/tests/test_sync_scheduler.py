"""Tests for the smart scheduler (pure), rate limiter, and feed cache."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sync import scheduler as sch  # noqa: E402
from sync import rate_limiter as rl  # noqa: E402
from feed import realtime_cache as fc  # noqa: E402
from jobs.redis_client import get_redis  # noqa: E402


def _ok(m): print(f"  ✅ {m}", flush=True)
def _fail(m):
    print(f"  ❌ {m}", flush=True)
    raise AssertionError(m)


def test_classify_tier():
    print("\n[TEST 1] tier classification (pure)", flush=True)
    now = 1_000_000.0
    if sch.classify_tier(now, now - 60, None) != sch.TIER_ACTIVE:
        _fail("recent app signal -> ACTIVE")
    if sch.classify_tier(now, None, now - 3600) != sch.TIER_ACTIVE:
        _fail("workout 1h ago -> ACTIVE")
    if sch.classify_tier(now, None, now - 2 * 24 * 3600) != sch.TIER_NORMAL:
        _fail("activity 2 days ago -> NORMAL")
    if sch.classify_tier(now, None, now - 10 * 24 * 3600) != sch.TIER_INACTIVE:
        _fail("activity 10 days ago -> INACTIVE")
    if sch.classify_tier(now, None, None) != sch.TIER_INACTIVE:
        _fail("no signals -> INACTIVE")
    _ok("ACTIVE / NORMAL / INACTIVE classified correctly")


def test_is_due():
    print("\n[TEST 2] due decision by cadence", flush=True)
    now = 1_000_000.0
    if not sch.is_due(now, None, sch.TIER_ACTIVE):
        _fail("never synced -> due")
    if sch.is_due(now, now - 300, sch.TIER_ACTIVE):
        _fail("synced 5min ago, ACTIVE(15m) -> NOT due")
    if not sch.is_due(now, now - 1000, sch.TIER_ACTIVE):
        _fail("synced 16min ago, ACTIVE -> due")
    if sch.is_due(now, now - 3600, sch.TIER_NORMAL):
        _fail("synced 1h ago, NORMAL(2h) -> NOT due")
    if not sch.is_due(now, now - 25 * 3600, sch.TIER_INACTIVE):
        _fail("synced 25h ago, INACTIVE(24h) -> due")
    _ok("cadence gating correct for all tiers")


async def test_cooldown(r):
    print("\n[TEST 3] per-user cooldown", flush=True)
    uid = "cooldown-test-user"
    await r.delete(f"{rl.COOLDOWN_PREFIX}{uid}")
    if not await rl.cooldown_ok(uid):
        _fail("fresh user should be outside cooldown")
    await rl.set_cooldown(uid, seconds=30)
    if await rl.cooldown_ok(uid):
        _fail("user in cooldown should be blocked")
    ttl = await r.ttl(f"{rl.COOLDOWN_PREFIX}{uid}")
    if not (0 < ttl <= 30):
        _fail(f"cooldown TTL wrong: {ttl}")
    await r.delete(f"{rl.COOLDOWN_PREFIX}{uid}")
    _ok("cooldown blocks then expires")


async def test_global_cap(r):
    print("\n[TEST 4] global concurrency cap", flush=True)
    await r.delete(rl.GLOBAL_ACTIVE_KEY)
    acquired = 0
    for _ in range(rl.GLOBAL_MAX + 3):
        if await rl.acquire_global_slot():
            acquired += 1
    if acquired != rl.GLOBAL_MAX:
        _fail(f"expected {rl.GLOBAL_MAX} slots, got {acquired}")
    # release one -> can acquire one more
    await rl.release_global_slot()
    if not await rl.acquire_global_slot():
        _fail("should acquire after a release")
    # cleanup
    for _ in range(rl.GLOBAL_MAX + 5):
        await rl.release_global_slot()
    await r.delete(rl.GLOBAL_ACTIVE_KEY)
    _ok(f"cap enforced at {rl.GLOBAL_MAX}, slot freed on release")


async def test_feed_cache(r):
    print("\n[TEST 5] feed cache update / since / warm", flush=True)
    uid = "feed-test-user"
    await r.delete(fc._key(uid))
    await fc.update_feed(uid, {"external_id": "a1", "start_time": "2026-01-01T10:00:00+00:00"})
    await fc.update_feed(uid, {"external_id": "a2", "start_time": "2026-01-02T10:00:00+00:00"})
    feed = await fc.get_feed(uid, limit=10)
    if [a["external_id"] for a in feed] != ["a2", "a1"]:
        _fail(f"newest-first order wrong: {feed}")
    newer = await fc.get_feed(uid, since="2026-01-01T12:00:00+00:00", limit=10)
    if [a["external_id"] for a in newer] != ["a2"]:
        _fail(f"since filter wrong: {newer}")
    # warm replaces
    await fc.warm_feed(uid, [
        {"external_id": "b1", "start_time": "2026-02-01T10:00:00+00:00"},
        {"external_id": "b2", "start_time": "2026-02-02T10:00:00+00:00"},
    ])
    warmed = await fc.get_feed(uid, limit=10)
    if [a["external_id"] for a in warmed] != ["b2", "b1"]:
        _fail(f"warm order wrong: {warmed}")
    await r.delete(fc._key(uid))
    _ok("feed newest-first, since filter, warm-replace all correct")


async def main() -> int:
    print("sync scheduler / rate limiter / feed cache tests", flush=True)
    failed = 0
    for t in (test_classify_tier, test_is_due):
        try:
            t()
        except AssertionError:
            failed += 1
    r = get_redis()
    await r.ping()
    for t in (test_cooldown, test_global_cap, test_feed_cache):
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
