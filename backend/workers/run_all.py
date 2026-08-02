"""Single-process entrypoint that runs ALL Garmin workers together.

Intended for a single Railway service (instead of 4 supervisor programs):
  - sync_worker      (consumes the Redis job queue, runs gccli sync)
  - event_worker     (fan-out ACTIVITY_CREATED stream -> workouts + feed cache)
  - scheduler_worker (enqueues incremental syncs; Redis leader-locked)
  - monitor_worker   (queue-health alerts; Redis leader-locked)

Each worker keeps its own Mongo/Redis connections and its own async loop; here
we just run their main() coroutines concurrently and restart any that crash.

Start with:  python -m workers.run_all      (cwd = /app/backend)

NOTE: this file is ADDITIVE and does not change any existing worker or the
running app. It is not referenced by the preview supervisor.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from workers.sync_worker import main as sync_main
from workers.event_worker import main as event_main
from workers.scheduler_worker import main as scheduler_main
from workers.monitor_worker import main as monitor_main
from garmin.bootstrap import ensure_gccli_installed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("run_all")


async def _supervise(name: str, coro_factory) -> None:
    """Run a worker main() forever, restarting it with backoff if it crashes."""
    while True:
        try:
            log.info("[run_all] starting worker=%s", name)
            await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep the other workers alive
            log.error("[run_all] worker=%s crashed: %s — restart in 5s", name, exc)
            await asyncio.sleep(5)


async def main() -> None:
    try:
        ensure_gccli_installed()
    except Exception as exc:  # best-effort
        log.warning("[run_all] gccli bootstrap skipped: %s", exc)

    await asyncio.gather(
        _supervise("sync", sync_main),
        _supervise("event", event_main),
        _supervise("scheduler", scheduler_main),
        _supervise("monitor", monitor_main),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
