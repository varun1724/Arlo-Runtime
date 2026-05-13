import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobRow
from app.jobs.apartments import execute_apartments_persist_job
from app.jobs.builder import execute_builder_job
from app.jobs.local_optimizer import execute_optimize_job
from app.jobs.n8n import execute_n8n_job
from app.jobs.paper_trading import execute_paper_trade_engine_job
from app.jobs.polymarket import execute_polymarket_scan_job
from app.jobs.research import execute_research_job
from app.jobs.trading import execute_trading_job
from app.models.job import JobStatus, JobStopReason
from app.services.job_service import finalize_job

logger = logging.getLogger("arlo.worker.executor")


async def execute_job(session: AsyncSession, job: JobRow) -> None:
    """Route job execution based on job type, then advance workflow if applicable."""
    # Execute the job
    if job.job_type == "research":
        await execute_research_job(session, job)
    elif job.job_type == "builder":
        await execute_builder_job(session, job)
    elif job.job_type == "n8n":
        await execute_n8n_job(session, job)
    elif job.job_type == "trading":
        await execute_trading_job(session, job)
    elif job.job_type == "optimize":
        await execute_optimize_job(session, job)
    elif job.job_type == "apartments_persist":
        await execute_apartments_persist_job(session, job)
    elif job.job_type == "polymarket_scan":
        await execute_polymarket_scan_job(session, job)
    elif job.job_type == "paper_trade_engine":
        await execute_paper_trade_engine_job(session, job)
    else:
        logger.error("Unknown job type: %s", job.job_type)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=f"Unknown job type: {job.job_type}",
            stop_reason=JobStopReason.ERROR.value,
        )

    # If this job belongs to a workflow, advance to the next step
    if job.workflow_id is not None:
        from app.services.workflow_service import advance_workflow

        try:
            await advance_workflow(session, job.workflow_id)
        except Exception:
            logger.exception(
                "Failed to advance workflow %s after job %s", job.workflow_id, job.id
            )
