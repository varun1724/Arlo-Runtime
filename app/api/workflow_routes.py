from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.auth import verify_token
from app.db.engine import get_db
from app.db.models import JobRow
from app.models.job import JobResponse
from app.models.workflow import (
    ApproveStepRequest,
    CreateWorkflowFromTemplateRequest,
    CreateWorkflowRequest,
    StepDefinition,
    WorkflowListResponse,
    WorkflowProgressEvent,
    WorkflowResponse,
    WorkflowStatus,
    TERMINAL_WORKFLOW_STATUSES,
)
from app.services import workflow_service
from app.workflows.templates import TEMPLATES

router = APIRouter(prefix="/workflows", tags=["workflows"], dependencies=[Depends(verify_token)])


async def _workflow_to_response(row, db: AsyncSession | None = None) -> WorkflowResponse:
    """Convert a WorkflowRow to a WorkflowResponse.

    Round 3: when a session is supplied, also computes the workflow's
    aggregated token usage and estimated USD cost from its child jobs.
    The session is optional so legacy callers (and sync paths that
    can't await) still work — totals are simply omitted.
    """
    totals_input: int | None = None
    totals_output: int | None = None
    totals_cost: float | None = None
    if db is not None:
        result = await db.execute(
            select(
                func.sum(JobRow.tokens_input),
                func.sum(JobRow.tokens_output),
                func.sum(JobRow.estimated_cost_usd),
            ).where(JobRow.workflow_id == row.id)
        )
        totals_input, totals_output, totals_cost = result.one()

    return WorkflowResponse(
        id=row.id,
        name=row.name,
        template_id=row.template_id,
        status=WorkflowStatus(row.status),
        context=json.loads(row.context),
        step_definitions=[StepDefinition.model_validate(s) for s in json.loads(row.step_definitions)],
        current_step_index=row.current_step_index,
        error_message=row.error_message,
        total_tokens_input=totals_input,
        total_tokens_output=totals_output,
        total_estimated_cost_usd=float(totals_cost) if totals_cost is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    body: CreateWorkflowRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    row = await workflow_service.create_workflow(db, body)
    return await _workflow_to_response(row, db)


@router.post("/from-template/{template_id}", response_model=WorkflowResponse, status_code=201)
async def create_workflow_from_template(
    template_id: str,
    body: CreateWorkflowFromTemplateRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    template = TEMPLATES.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    # Check required context
    for key in template.get("required_context", []):
        if key not in body.initial_context:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required context key: '{key}'. Required: {template['required_context']}",
            )

    request = CreateWorkflowRequest(
        name=template["name"],
        template_id=template_id,
        steps=[StepDefinition.model_validate(s) for s in template["steps"]],
        initial_context=body.initial_context,
    )
    row = await workflow_service.create_workflow(db, request)
    return await _workflow_to_response(row, db)


@router.post("/{workflow_id}/retry", response_model=WorkflowResponse)
async def retry_workflow_step(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Retry the current failed step of a workflow."""
    try:
        row = await workflow_service.retry_step(db, workflow_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _workflow_to_response(row, db)


@router.post("/{workflow_id}/cancel", response_model=WorkflowResponse)
async def cancel_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Cancel a running workflow and all its queued jobs."""
    try:
        row = await workflow_service.cancel_workflow(db, workflow_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _workflow_to_response(row, db)


@router.get("/templates")
async def list_templates():
    return {
        tid: {
            "template_id": t["template_id"],
            "name": t["name"],
            "description": t["description"],
            "required_context": t.get("required_context", []),
            "optional_context": t.get("optional_context", []),
            "step_count": len(t["steps"]),
        }
        for tid, t in TEMPLATES.items()
    }


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> WorkflowListResponse:
    rows, total = await workflow_service.list_workflows(db, limit=limit, offset=offset)
    workflows = [await _workflow_to_response(r, db) for r in rows]
    return WorkflowListResponse(workflows=workflows, count=total)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    row = await workflow_service.get_workflow(db, workflow_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return await _workflow_to_response(row, db)


@router.post("/{workflow_id}/approve", response_model=WorkflowResponse)
async def approve_workflow_step(
    workflow_id: uuid.UUID,
    body: ApproveStepRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Approve or skip the current step that's awaiting approval."""
    try:
        row = await workflow_service.approve_step(
            db,
            workflow_id,
            approved=body.approved,
            context_overrides=body.context_overrides or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _workflow_to_response(row, db)


@router.get("/{workflow_id}/jobs")
async def get_workflow_jobs(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    row = await workflow_service.get_workflow(db, workflow_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    jobs = await workflow_service.get_workflow_jobs(db, workflow_id)
    return {
        "workflow_id": str(workflow_id),
        "jobs": [JobResponse.model_validate(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/{workflow_id}/stream")
async def stream_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    row = await workflow_service.get_workflow(db, workflow_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    async def event_generator():
        from app.db.engine import async_session

        while True:
            async with async_session() as session:
                wf = await workflow_service.get_workflow(session, workflow_id)
                if wf is None:
                    break

                step_defs = json.loads(wf.step_definitions)
                current_step_name = None
                if wf.current_step_index < len(step_defs):
                    current_step_name = step_defs[wf.current_step_index].get("name")

                # Get current job's progress
                jobs = await workflow_service.get_workflow_jobs(session, workflow_id)
                progress_msg = None
                if jobs:
                    latest_job = jobs[-1]
                    progress_msg = latest_job.progress_message

                event = WorkflowProgressEvent(
                    workflow_id=wf.id,
                    status=WorkflowStatus(wf.status),
                    current_step_index=wf.current_step_index,
                    current_step_name=current_step_name,
                    progress_message=progress_msg,
                )
                yield {"data": event.model_dump_json()}

                if wf.status in TERMINAL_WORKFLOW_STATUSES:
                    yield {"event": "complete", "data": event.model_dump_json()}
                    break

            await asyncio.sleep(5)

    return EventSourceResponse(event_generator())
