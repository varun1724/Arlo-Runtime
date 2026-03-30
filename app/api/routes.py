from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.auth import verify_token
from app.db.engine import get_db
from app.models.job import (
    CreateJobRequest,
    JobEventResponse,
    JobListResponse,
    JobProgressEvent,
    JobResponse,
    TERMINAL_STATUSES,
)
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(verify_token)])


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    body: CreateJobRequest,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    row = await job_service.create_job(db, body)
    return JobResponse.model_validate(row)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    rows, total = await job_service.list_jobs(db, limit=limit, offset=offset)
    return JobListResponse(
        jobs=[JobResponse.model_validate(r) for r in rows],
        count=total,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    row = await job_service.get_job(db, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(row)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Cancel a queued or running job."""
    try:
        row = await job_service.cancel_job(db, job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JobResponse.model_validate(row)


@router.post("/{job_id}/pin")
async def pin_job_workspace(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Pin a job's workspace so it's excluded from automatic cleanup."""
    row = await job_service.get_job(db, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not row.workspace_path:
        raise HTTPException(status_code=400, detail="No workspace for this job")

    from sqlalchemy import update
    from app.db.models import JobRow as JR

    await db.execute(update(JR).where(JR.id == job_id).values(workspace_pinned=True))
    await db.commit()
    return {"job_id": str(job_id), "workspace_pinned": True}


@router.post("/{job_id}/unpin")
async def unpin_job_workspace(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Unpin a job's workspace, allowing automatic cleanup."""
    row = await job_service.get_job(db, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    from sqlalchemy import update
    from app.db.models import JobRow as JR

    await db.execute(update(JR).where(JR.id == job_id).values(workspace_pinned=False))
    await db.commit()
    return {"job_id": str(job_id), "workspace_pinned": False}


@router.get("/{job_id}/logs")
async def get_job_logs(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return the event log for a job."""
    row = await job_service.get_job(db, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    events = await job_service.get_job_events(db, job_id)
    return {
        "job_id": str(job_id),
        "events": [JobEventResponse.model_validate(e) for e in events],
        "count": len(events),
    }


@router.get("/{job_id}/artifacts")
async def get_job_artifacts(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return the list of artifacts for a builder job's workspace."""
    row = await job_service.get_job(db, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not row.workspace_path:
        return {"job_id": str(job_id), "artifacts": [], "message": "No workspace for this job"}

    from app.workspace.manager import scan_workspace_artifacts

    artifacts = scan_workspace_artifacts(row.workspace_path)
    return {
        "job_id": str(job_id),
        "workspace_path": row.workspace_path,
        "artifacts": artifacts,
        "count": len(artifacts),
    }


@router.delete("/{job_id}/workspace")
async def delete_job_workspace(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a job's workspace directory."""
    row = await job_service.get_job(db, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not row.workspace_path:
        raise HTTPException(status_code=404, detail="No workspace for this job")

    from app.workspace.manager import delete_workspace

    deleted = delete_workspace(row.workspace_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found on disk")

    return {"job_id": str(job_id), "deleted": True}


@router.get("/{job_id}/stream")
async def stream_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    # Verify job exists before starting stream
    row = await job_service.get_job(db, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        from app.db.engine import async_session

        while True:
            # Fresh session each poll to see committed changes from the worker
            async with async_session() as session:
                row = await job_service.get_job(session, job_id)
                if row is None:
                    break

                event = JobProgressEvent(
                    job_id=row.id,
                    status=row.status,
                    current_step=row.current_step,
                    progress_message=row.progress_message,
                    iteration_count=row.iteration_count,
                )
                yield {"data": event.model_dump_json()}

                if row.status in TERMINAL_STATUSES:
                    yield {"event": "complete", "data": event.model_dump_json()}
                    break

            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())
