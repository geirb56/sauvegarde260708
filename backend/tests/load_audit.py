"""CardioCoach — SRE load & resilience audit harness.

Methodology: to exercise the queue/worker/lock/dedup machinery WITHOUT hammering
Garmin (single gccli account), we enqueue jobs for DISTINCT, UNCONNECTED user
ids. service.sync() returns fast ("not connected"), so we measure the infra
(API non-blocking, Redis queue, worker throughput, Mongo, locks) rather than
gccli itself.
"""
import asyncio, time, statistics, sys, os
import aiohttp
import redis as redissync

BASE = "http://localhost:8001"
QUEUE_KEY = "cardiocoach:garmin:queue"
R = redissync.from_url(os.environ.get("AUDIT_REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)


def pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = int(round((p / 100.0) * (len(s) - 1)))
    return s[k]


def clear_keys():
    for k in R.scan_iter("sync_*"):
        R.delete(k)
    R.delete(QUEUE_KEY)


async def fire(session, uid):
    t0 = time.perf_counter()
    try:
        async with session.post(f"{BASE}/api/garmin/sync", params={"user_id": uid}) as r:
            await r.text()
            return (time.perf_counter() - t0) * 1000.0, r.status
    except Exception as e:
        return (time.perf_counter() - t0) * 1000.0, f"ERR:{e}"


async def load_tier(n, distinct=True, inflight=200):
    clear_keys()
    sem = asyncio.Semaphore(inflight)
    conn = aiohttp.TCPConnector(limit=inflight)

    async def bounded(uid):
        async with sem:
            return await fire(s, uid)

    async with aiohttp.ClientSession(connector=conn) as s:
        t0 = time.perf_counter()
        tasks = [bounded(f"load_{i}" if distinct else "load_same") for i in range(n)]
        results = await asyncio.gather(*tasks)
        wall = time.perf_counter() - t0
    lat = [r[0] for r in results]
    codes = {}
    for _, c in results:
        codes[c] = codes.get(c, 0) + 1
    qlen = R.llen(QUEUE_KEY)
    print(f"\n--- {n} POST /api/garmin/sync (inflight<=200, distinct={distinct}) ---")
    print(f"  wall={wall:.2f}s  throughput={n/wall:.0f} req/s")
    print(f"  API latency ms: p50={pct(lat,50):.1f} p95={pct(lat,95):.1f} p99={pct(lat,99):.1f} max={max(lat):.1f}")
    print(f"  status codes: {codes}")
    print(f"  queue length right after burst: {qlen}")
    return wall, qlen


async def worker_drain(n):
    """Enqueue n distinct jobs, then measure how fast the worker drains them."""
    clear_keys()
    async def bounded_drain(uid):
        async with sem:
            return await fire(s, uid)
    sem = asyncio.Semaphore(200)
    conn = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=conn) as s:
        await asyncio.gather(*[bounded_drain(f"drain_{i}") for i in range(n)])
    start = time.perf_counter()
    last = R.llen(QUEUE_KEY)
    while True:
        await asyncio.sleep(0.5)
        q = R.llen(QUEUE_KEY)
        if q == 0:
            break
        if time.perf_counter() - start > 120:
            print("  DRAIN TIMEOUT (>120s), remaining:", q)
            break
    dur = time.perf_counter() - start
    print(f"\n--- worker drain of {n} jobs ---")
    print(f"  drain_time={dur:.2f}s  effective_throughput={n/dur:.0f} jobs/s")
    return dur


async def dedup_test():
    clear_keys()
    sem = asyncio.Semaphore(200)
    conn = aiohttp.TCPConnector(limit=100)

    async def bounded_d(uid):
        async with sem:
            return await fire(s, uid)

    async with aiohttp.ClientSession(connector=conn) as s:
        results = await asyncio.gather(*[bounded_d("dedup_user") for _ in range(50)])
    # read bodies again to classify
    async with aiohttp.ClientSession() as s:
        bodies = []
        for _ in range(1):
            pass
    qlen = R.llen(QUEUE_KEY)
    print("\n--- dedup: 50 concurrent syncs for SAME user ---")
    print(f"  queue length (should be ~1): {qlen}")
    print(f"  pending key present: {bool(R.exists('sync_pending:dedup_user'))}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"

    async def run():
        if arg.isdigit():
            await load_tier(int(arg), inflight=100)
            return
        if arg in ("all", "load"):
            for n in (10, 50, 100, 500, 1000):
                await load_tier(n, inflight=100)
        if arg in ("all", "drain"):
            await worker_drain(500)
        if arg in ("all", "dedup"):
            await dedup_test()

    asyncio.run(run())
    print("[done]")
