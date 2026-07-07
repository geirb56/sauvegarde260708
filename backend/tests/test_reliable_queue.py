"""SRE resilience tests for the Reliable Queue (at-least-once delivery).

Proves, without any mocking of Redis itself:
  1. WORKER kill -9 mid-job  -> job recovered by the watchdog (no loss, no dup)
  2. Normal success (ACK)     -> job removed exactly once, nothing left behind
  3. REDIS restart            -> in-flight jobs survive (AOF) and are recovered

Everything uses a short ORPHAN_TIMEOUT so the run finishes in seconds. The
ORPHAN_TIMEOUT env MUST be set before importing jobs.queue (read at import).

Run:  cd /app/backend && python -m tests.test_reliable_queue
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# Short orphan timeout for a fast test; read at import time by jobs.queue.
os.environ["SYNC_ORPHAN_TIMEOUT"] = "2"

from jobs.queue import (  # noqa: E402
    QUEUE_KEY,
    PROCESSING_KEY,
    CLAIMS_KEY,
    ORPHAN_TIMEOUT,
    claim_job,
    ack_job,
    recover_orphans,
)
from jobs.redis_client import get_redis  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fail(msg: str):
    print(f"  ❌ {msg}", flush=True)
    raise AssertionError(msg)


def _ok(msg: str):
    print(f"  ✅ {msg}", flush=True)


async def _flush(r):
    await r.delete(QUEUE_KEY, PROCESSING_KEY, CLAIMS_KEY)


async def _counts(r):
    return (
        await r.llen(QUEUE_KEY),
        await r.llen(PROCESSING_KEY),
        await r.hlen(CLAIMS_KEY),
    )


def _make_job(user_id="mock-user"):
    return {
        "id": uuid.uuid4().hex,
        "type": "SYNC_USER",
        "user_id": user_id,
        "attempts": 0,
        "enqueued_at": time.time(),
    }


async def test_worker_kill9_recovery(r):
    print("\n[TEST 1] worker kill -9 mid-job -> watchdog recovery", flush=True)
    await _flush(r)

    job = _make_job()
    await r.lpush(QUEUE_KEY, json.dumps(job))

    # Spawn a mock worker that claims the job and hangs.
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests._mock_worker"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Wait until the job is in the processing list (claimed).
    for _ in range(100):
        q, p, c = await _counts(r)
        if p == 1:
            break
        await asyncio.sleep(0.1)
    else:
        proc.kill()
        _fail("mock worker never claimed the job")

    q, p, c = await _counts(r)
    if not (q == 0 and p == 1 and c == 1):
        proc.kill()
        _fail(f"unexpected state after claim: queue={q} processing={p} claims={c}")
    _ok("job claimed: queue=0 processing=1 claims=1")

    # Hard-kill the worker while it holds the job (simulates crash).
    proc.kill()
    proc.wait(timeout=5)
    _ok("worker killed with SIGKILL while holding the job")

    # Job must still be safe in the processing list (NOT lost).
    q, p, c = await _counts(r)
    if p != 1:
        _fail(f"job lost after crash! processing={p}")
    _ok("job survived the crash (still in processing list)")

    # Wait past the orphan timeout, then run the watchdog.
    await asyncio.sleep(ORPHAN_TIMEOUT + 1)
    recovered = await recover_orphans()
    if recovered != 1:
        _fail(f"watchdog recovered {recovered} jobs, expected 1")

    q, p, c = await _counts(r)
    if not (q == 1 and p == 0 and c == 0):
        _fail(f"post-recovery state wrong: queue={q} processing={p} claims={c}")

    # Same job id back in the queue -> no loss, no duplicate.
    raw = await r.lindex(QUEUE_KEY, 0)
    recovered_id = json.loads(raw)["id"]
    if recovered_id != job["id"]:
        _fail(f"recovered a different job id={recovered_id}")
    _ok(f"exactly-one recovered id={recovered_id} (no loss, no duplicate)")


async def test_ack_removes_once(r):
    print("\n[TEST 2] normal success -> ACK removes the job exactly once", flush=True)
    await _flush(r)

    job = _make_job()
    await r.lpush(QUEUE_KEY, json.dumps(job))

    claimed = await claim_job(timeout=5)
    if not claimed:
        _fail("claim_job returned nothing")
    raw, claimed_job = claimed
    q, p, c = await _counts(r)
    if not (q == 0 and p == 1 and c == 1):
        _fail(f"state after claim wrong: queue={q} processing={p} claims={c}")
    _ok("claimed into processing")

    await ack_job(raw, claimed_job["id"])
    q, p, c = await _counts(r)
    if not (q == 0 and p == 0 and c == 0):
        _fail(f"state after ack wrong: queue={q} processing={p} claims={c}")
    _ok("ACK cleared processing + claims; watchdog leaves nothing behind")

    if await recover_orphans() != 0:
        _fail("watchdog wrongly recovered an already-acked job")
    _ok("no phantom recovery after ACK")


async def test_redis_restart_durability(r):
    print("\n[TEST 3] Redis restart -> in-flight job survives (AOF)", flush=True)
    await _flush(r)

    job = _make_job()
    await r.lpush(QUEUE_KEY, json.dumps(job))
    claimed = await claim_job(timeout=5)
    if not claimed:
        _fail("claim_job returned nothing")
    _ok("job claimed and in-flight before restart")

    # Force an AOF rewrite so the current state is on disk, then restart Redis.
    try:
        await r.bgrewriteaof()
    except Exception:
        pass
    await asyncio.sleep(1)

    subprocess.run(["sudo", "supervisorctl", "restart", "redis"], check=True,
                   capture_output=True, text=True)
    await asyncio.sleep(3)

    # Fresh connection to the restarted server.
    from jobs import redis_client
    redis_client._redis = None
    r2 = get_redis()
    for _ in range(30):
        try:
            await r2.ping()
            break
        except Exception:
            await asyncio.sleep(0.5)

    p = await r2.llen(PROCESSING_KEY)
    if p != 1:
        _fail(f"in-flight job did NOT survive redis restart (processing={p}). "
              f"Check AOF persistence in the redis supervisor config.")
    _ok("in-flight job survived redis restart")

    await asyncio.sleep(ORPHAN_TIMEOUT + 1)
    if await recover_orphans() != 1:
        _fail("watchdog failed to recover the job after restart")
    q = await r2.llen(QUEUE_KEY)
    if q != 1:
        _fail(f"job not requeued after restart recovery: queue={q}")
    _ok("job recovered and requeued after restart (no loss)")
    await _flush(r2)


async def main() -> int:
    print(f"Reliable Queue resilience tests (ORPHAN_TIMEOUT={ORPHAN_TIMEOUT}s)", flush=True)
    # Stop the live worker so it doesn't compete for our test jobs.
    subprocess.run(["sudo", "supervisorctl", "stop", "sync-worker"],
                   capture_output=True, text=True)
    await asyncio.sleep(1)
    r = get_redis()
    await r.ping()
    failed = 0
    try:
        for test in (test_worker_kill9_recovery, test_ack_removes_once, test_redis_restart_durability):
            try:
                await test(r)
            except AssertionError:
                failed += 1
            except Exception as exc:
                print(f"  ❌ unexpected error in {test.__name__}: {exc}", flush=True)
                failed += 1
        await _flush(get_redis())
    finally:
        subprocess.run(["sudo", "supervisorctl", "start", "sync-worker"],
                       capture_output=True, text=True)
    print(f"\n{'='*50}\nRESULT: {'ALL PASSED ✅' if failed == 0 else f'{failed} TEST(S) FAILED ❌'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
