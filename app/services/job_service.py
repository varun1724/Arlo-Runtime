from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobEventRow, JobRow
from app.models.job import CreateJobRequest, JobStatus, TERMINAL_STATUSES


async def emit_job_event(
    session: AsyncSession,
    job_id: uuid.UUID,
    event_type: str,
    message: str | None = None,
    metadata_json: str | None = None,
) -> None:
    """Record a job lifecycle event."""
    event = JobEventRow(
        job_id=job_id,
        event_type=event_type,
        message=message,
        metadata_json=metadata_json,
    )
    session.add(event)
    await session.commit()


async def get_job_events(session: AsyncSession, job_id: uuid.UUID) -> list[JobEventRow]:
    """Get all events for a job, ordered by time."""
    result = await session.execute(
        select(JobEventRow)
        .where(JobEventRow.job_id == job_id)
        .order_by(JobEventRow.created_at.asc())
    )
    return list(result.scalars().all())


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
    await emit_job_event(session, row.id, "created", f"Job created: {request.job_type}")
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
    job = await session.get(JobRow, row.id)
    if job:
        await emit_job_event(session, job.id, "claimed", f"Claimed by {worker_id}")
    return job


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
    msg = error_message if status == JobStatus.FAILED else result_preview
    await emit_job_event(session, job_id, status.value, msg)


async def cancel_job(session: AsyncSession, job_id: uuid.UUID) -> JobRow:
    """Cancel a queued or running job.

    Raises ValueError if the job is already in a terminal state.
    """
    job = await session.get(JobRow, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")

    if job.status in TERMINAL_STATUSES:
        raise ValueError(f"Job {job_id} is already {job.status}")

    now = datetime.now(timezone.utc)
    await session.execute(
        update(JobRow)
        .where(JobRow.id == job_id)
        .values(
            status=JobStatus.CANCELED.value,
            stop_reason="manual",
            updated_at=now,
            completed_at=now,
        )
    )
    await session.commit()
    await emit_job_event(session, job_id, "canceled", "Job canceled manually")
    await session.refresh(job)
    return job
