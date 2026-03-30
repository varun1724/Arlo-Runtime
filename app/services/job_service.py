from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobRow
from app.models.job import CreateJobRequest, JobStatus


async def create_job(
    session: AsyncSession,
    request: CreateJobRequest,
    *,
    workflow_id: uuid.UUID | None = None,
    step_index: int | None = None,
) -> JobRow:
    row = JobRow(
        job_type=request.job_type.value,
        status=JobStatus.QUEUED.value,
        prompt=request.prompt,
        workflow_id=workflow_id,
        step_index=step_index,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> JobRow | None:
    return await session.get(JobRow, job_id)


async def list_jobs(
    session: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[list[JobRow], int]:
    count_result = await session.execute(select(func.count()).select_from(JobRow))
    total = count_result.scalar_one()

    rows_result = await session.execute(
        select(JobRow).order_by(JobRow.created_at.desc()).limit(limit).offset(offset)
    )
    rows = list(rows_result.scalars().all())
    return rows, total


async def claim_next_job(session: AsyncSession, worker_id: str) -> JobRow | None:
    result = await session.execute(
        text("""
            UPDATE jobs
            SET status = :running,
                worker_id = :worker_id,
                started_at = now(),
                updated_at = now()
            WHERE id = (
                SELECT id FROM jobs
                WHERE status = :queued
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
        """),
        {"running": JobStatus.RUNNING.value, "queued": JobStatus.QUEUED.value, "worker_id": worker_id},
    )
    row = result.fetchone()
    await session.commit()
    if row is None:
        return None
    # Re-fetch as ORM object
    return await session.get(JobRow, row.id)


async def update_job_progress(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    current_step: str | None = None,
    progress_message: str | None = None,
    iteration_count: int | None = None,
) -> None:
    values: dict = {"updated_at": datetime.now(timezone.utc)}
    if current_step is not None:
        values["current_step"] = current_step
    if progress_message is not None:
        values["progress_message"] = progress_message
    if iteration_count is not None:
        values["iteration_count"] = iteration_count

    await session.execute(update(JobRow).where(JobRow.id == job_id).values(**values))
    await session.commit()


async def finalize_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    status: JobStatus,
    result_preview: str | None = None,
    result_data: str | None = None,
    error_message: str | None = None,
    stop_reason: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    values: dict = {
        "status": status.value,
        "updated_at": now,
        "completed_at": now,
    }
    if result_preview is not None:
        values["result_preview"] = result_preview
    if result_data is not None:
        values["result_data"] = result_data
    if error_message is not None:
        values["error_message"] = error_message
    if stop_reason is not None:
        values["stop_reason"] = stop_reason

    await session.execute(update(JobRow).where(JobRow.id == job_id).values(**values))
    await session.commit()
