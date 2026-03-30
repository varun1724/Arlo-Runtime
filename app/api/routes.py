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
