import asyncio
import logging
import platform
import uuid

from app.core.config import settings
from app.db.base import Base
from app.db.engine import async_session, engine
from app.db.models import JobRow, WorkflowRow  # noqa: F401 — ensure models are registered
from app.services.job_service import claim_next_job
from app.workers.executor import execute_job

logger = logging.getLogger("arlo.worker")
WORKER_ID = f"worker-{platform.node()}-{uuid.uuid4().hex[:8]}"


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
    while True:
        try:
            async with async_session() as session:
                job = await claim_next_job(session, WORKER_ID)
                if job:
                    logger.info("Claimed job %s (type=%s)", job.id, job.job_type)
                    await execute_job(session, job)
                    logger.info("Finished job %s", job.id)
                else:
                    await asyncio.sleep(settings.worker_poll_interval_seconds)
        except Exception:
            logger.exception("Error in poll loop")
            await asyncio.sleep(settings.worker_poll_interval_seconds)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(poll_loop())


if __name__ == "__main__":
    main()
