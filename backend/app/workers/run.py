from __future__ import annotations

import asyncio

from arq.worker import create_worker

from app.workers.main import WorkerSettings


async def main() -> None:
    worker = create_worker(WorkerSettings)
    try:
        await worker.async_run()
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
