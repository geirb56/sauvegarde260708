"""Mock worker for reliable-queue crash tests.

Claims ONE job (BLMOVE queue -> processing, records claim time) then sleeps
forever, simulating a worker stuck mid-execution. The test kill -9's it while
it holds the job in the processing list, so recover_orphans() can prove the job
is neither lost nor duplicated.

Run: python -m tests._mock_worker   (cwd = /app/backend)
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from jobs.queue import claim_job


async def main() -> None:
    claimed = await claim_job(timeout=10)
    if not claimed:
        print("MOCK_WORKER no job claimed", flush=True)
        return
    _raw, job = claimed
    print(f"MOCK_WORKER claimed id={job['id']}", flush=True)
    # Simulate a long-running job; the test will kill -9 us here.
    await asyncio.sleep(600)


if __name__ == "__main__":
    asyncio.run(main())
