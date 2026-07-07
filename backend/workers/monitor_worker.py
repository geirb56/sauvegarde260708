"""Dedicated queue-health monitor — a standalone process (NOT inside sync_worker).

Responsibilities:
  - periodically snapshot queue health (jobs.health.queue_health)
  - evaluate it (monitoring.alerts.evaluate_queue_health, pure)
  - emit alerts (monitoring.alerts.send_alert) ONLY on state changes (no spam)

Design:
  - Fully decoupled from gccli / sync logic: it only reads Redis, never touches
    the queue, the worker or FastAPI.
  - Adaptive interval: 30s (unhealthy) / 60s (degraded) / 120s (healthy).
  - Horizontally scalable: a Redis leader lock means only ONE monitor evaluates
    and alerts at a time; extra monitors run as hot standbys and take over if the
    leader dies. Alert streak-state + last-emitted level live in Redis so scaling
    never resets counters nor duplicates alerts.

Start with:  python -m workers.monitor_worker   (cwd = /app/backend)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from jobs.redis_client import get_redis
from jobs.health import queue_health
from monitoring.alerts import evaluate_queue_health, send_alert, AlertState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("monitor_worker")

# Adaptive intervals (seconds) by health status.
INTERVAL_UNHEALTHY = int(os.environ.get("MONITOR_INTERVAL_UNHEALTHY", "30"))
INTERVAL_DEGRADED = int(os.environ.get("MONITOR_INTERVAL_DEGRADED", "60"))
INTERVAL_HEALTHY = int(os.environ.get("MONITOR_INTERVAL_HEALTHY", "120"))
# Leader lock TTL must exceed the longest interval so the leader keeps ownership
# across a healthy (120s) tick; standbys poll this often to take over on failure.
LEADER_TTL = int(os.environ.get("MONITOR_LEADER_TTL", "150"))
STANDBY_POLL = int(os.environ.get("MONITOR_STANDBY_POLL", "20"))

LEADER_KEY = "cardiocoach:alert:leader"
STATE_KEY = "cardiocoach:alert:state"        # hash: unhealthy_streak, degraded_streak
LAST_LEVEL_KEY = "cardiocoach:alert:last_level"

OWNER = f"{os.uname().nodename}:{os.getpid()}"


def next_interval(status: str | None) -> int:
    if status == "unhealthy":
        return INTERVAL_UNHEALTHY
    if status == "degraded":
        return INTERVAL_DEGRADED
    return INTERVAL_HEALTHY


async def acquire_or_refresh_leadership(redis, owner: str = OWNER) -> bool:
    """Become leader (SET NX) or refresh our own leadership TTL. Standbys get False."""
    if await redis.set(LEADER_KEY, owner, nx=True, ex=LEADER_TTL):
        return True
    if await redis.get(LEADER_KEY) == owner:
        await redis.expire(LEADER_KEY, LEADER_TTL)
        return True
    return False


async def process_once(redis, payload: dict) -> str | None:
    """Evaluate one snapshot and emit an alert only when the state changes.

    Streak state + last emitted level are stored in Redis (shared across monitors).
    Returns the level emitted this tick (or None).
    """
    raw = await redis.hgetall(STATE_KEY)
    state = AlertState(
        unhealthy_streak=int(raw.get("unhealthy_streak") or 0),
        degraded_streak=int(raw.get("degraded_streak") or 0),
    )
    result = evaluate_queue_health(payload, state)
    await redis.hset(STATE_KEY, mapping={
        "unhealthy_streak": result.state.unhealthy_streak,
        "degraded_streak": result.state.degraded_streak,
    })

    prev = await redis.get(LAST_LEVEL_KEY)
    status = (payload or {}).get("status")

    if status == "healthy":
        if prev:  # recovered from an active alert -> notify once, then reset
            await send_alert("info", "Queue recovered: status healthy", payload)
            await redis.delete(LAST_LEVEL_KEY)
            return "info"
        return None

    if result.level and result.level != prev:  # crossed a threshold to a NEW level
        await send_alert(result.level, result.message, payload)
        await redis.set(LAST_LEVEL_KEY, result.level)
        return result.level

    return None  # below threshold or same level as last emitted -> no spam


async def main() -> None:
    redis = get_redis()
    logger.info(
        "[monitor] started owner=%s intervals=%s/%s/%s leader_ttl=%ss",
        OWNER, INTERVAL_UNHEALTHY, INTERVAL_DEGRADED, INTERVAL_HEALTHY, LEADER_TTL,
    )
    while True:
        try:
            if not await acquire_or_refresh_leadership(redis):
                await asyncio.sleep(STANDBY_POLL)  # hot standby
                continue

            payload = await queue_health()
            emitted = await process_once(redis, payload)
            interval = next_interval(payload.get("status"))
            logger.info(
                "[monitor] tick status=%s emitted=%s next=%ss",
                payload.get("status"), emitted, interval,
            )
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # keep the monitor alive no matter what
            logger.error("[monitor] loop error: %s", exc)
            await asyncio.sleep(INTERVAL_UNHEALTHY)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
