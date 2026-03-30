import asyncio
import logging
import platform
import signal
import time
import uuid

from app.core.config import settings
from app.db.base import Base
from app.db.engine import async_session, engine
from app.db.models import JobEventRow, JobRow, WorkflowRow  # noqa: F401 — ensure models registered
from app.services.cleanup_service import cleanup_old_workspaces
from app.services.job_service import claim_next_job
from app.workers.executor import execute_job

logger = logging.getLogger("arlo.worker")
WORKER_ID = f"worker-{platform.node()}-{uuid.uuid4().hex[:8]}"
CLEANUP_INTERVAL = 1800  # Run cleanup every 30 minutes

# Graceful shutdown
shutdown_event = asyncio.Event()


async def ensure_tables():
    """Create tables if they don't exist yet (same as API lifespan handler)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified")


async def poll_loop():
    await ensure_tables()
    logger.info(
        "Worker %s starting poll loop (interval=%ds)",
        WORKER_ID,
        settings.worker_poll_interval_seconds,
    )

    last_cleanup = time.monotonic()

    while not shutdown_event.is_set():
        # Periodic workspace cleanup
        if time.monotonic() - last_cleanup > CLEANUP_INTERVAL:
            try:
                async with async_session() as session:
                    deleted = await cleanup_old_workspaces(session)
                    if deleted:
                        logger.info("Cleanup: removed %d old workspaces", deleted)
            except Exception:
                logger.exception("Error during workspace cleanup")
            last_cleanup = time.monotonic()

        try:
            async with async_session() as session:
                job = await claim_next_job(session, WORKER_ID)
                if job:
                    # Re-check status in case job was canceled between claim and execution
                    await session.refresh(job)
                    if job.status == "canceled":
                        logger.info("Job %s was canceled, skipping", job.id)
                        continue
                    logger.info("Claimed job %s (type=%s)", job.id, job.job_type)
                    await execute_job(session, job)
                    logger.info("Finished job %s", job.id)
                else:
                    await asyncio.sleep(settings.worker_poll_interval_seconds)
        except Exception:
            logger.exception("Error in poll loop")
            await asyncio.sleep(settings.worker_poll_interval_seconds)

    logger.info("Worker %s shutting down gracefully", WORKER_ID)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    loop = asyncio.new_event_loop()

    # Register signal handlers for graceful shutdown
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_shutdown, sig)

    try:
        loop.run_until_complete(poll_loop())
    finally:
        loop.close()


def _handle_shutdown(sig):
    logger.info("Received signal %s, finishing current job then shutting down...", sig.name)
    shutdown_event.set()


if __name__ == "__main__":
    main()
