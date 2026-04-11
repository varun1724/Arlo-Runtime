from __future__ import annotations

import asyncio
import io
import json
import tarfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
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
from app.services.signed_urls import verify_signed_token
from app.workflows.templates import TEMPLATES, _apply_deep_research_mode

router = APIRouter(prefix="/workflows", tags=["workflows"], dependencies=[Depends(verify_token)])

# Round 5: public signed-URL endpoints (approve-by-link + artifact
# download). These do NOT go through verify_token — the HMAC signature
# on the URL is the auth. They live on a separate router so FastAPI's
# dependency injection doesn't require a bearer header.
public_router = APIRouter(prefix="/workflows", tags=["workflows-public"])

# Round 3 (side hustle): map a workflow's template_id to the
# ``context_overrides`` key that ``approve_via_link`` should set when
# the user clicks an approval link. Adding a new approval-gated
# pipeline? Add its template_id here and map it to the appropriate
# selected-* key. Unknown templates fall back to ``selected_idea``
# which matches pre-Round-3 behavior.
_TEMPLATE_OVERRIDE_KEY: dict[str, str] = {
    "startup_idea_pipeline": "selected_idea",
    "side_hustle_pipeline": "selected_hustle",
    "freelance_scanner": "selected_hustle",
}


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

    # Round 5: apply deep_research_mode modifier before validation. This
    # mutates step dicts (bumps max_loop_count etc.) and injects the
    # deep_mode context key without touching the original template.
    steps_raw = list(template["steps"])
    initial_context = dict(body.initial_context)
    if body.deep_research_mode:
        steps_raw, initial_context = _apply_deep_research_mode(steps_raw, initial_context)

    request = CreateWorkflowRequest(
        name=template["name"],
        template_id=template_id,
        steps=[StepDefinition.model_validate(s) for s in steps_raw],
        initial_context=initial_context,
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
                current_job_id = None
                tokens_input_so_far = None
                tokens_output_so_far = None
                cost_so_far_usd = None
                if jobs:
                    latest_job = jobs[-1]
                    progress_msg = latest_job.progress_message
                    # Round 4: surface the latest job's identity and live
                    # token/cost data so SSE clients can show real progress.
                    current_job_id = latest_job.id
                    tokens_input_so_far = latest_job.tokens_input
                    tokens_output_so_far = latest_job.tokens_output
                    cost_so_far_usd = latest_job.estimated_cost_usd

                event = WorkflowProgressEvent(
                    workflow_id=wf.id,
                    status=WorkflowStatus(wf.status),
                    current_step_index=wf.current_step_index,
                    current_step_name=current_step_name,
                    progress_message=progress_msg,
                    current_job_id=current_job_id,
                    tokens_input_so_far=tokens_input_so_far,
                    tokens_output_so_far=tokens_output_so_far,
                    cost_so_far_usd=cost_so_far_usd,
                )
                yield {"data": event.model_dump_json()}

                if wf.status in TERMINAL_WORKFLOW_STATUSES:
                    yield {"event": "complete", "data": event.model_dump_json()}
                    break

            await asyncio.sleep(5)

    return EventSourceResponse(event_generator())


# ─────────────────────────────────────────────────────────────────────
# Round 5: public signed-URL endpoints (no bearer auth)
# ─────────────────────────────────────────────────────────────────────


def _success_page(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arlo — success</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f5f5f7; padding: 40px 20px; color: #1a1a1a; }}
  .card {{ max-width: 480px; margin: 0 auto; background: #fff; padding: 32px; border-radius: 12px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.08); text-align: center; }}
  h1 {{ font-size: 22px; color: #4a6cf7; margin: 0 0 12px 0; }}
  p {{ font-size: 15px; line-height: 1.5; color: #555; }}
</style></head><body>
<div class="card">
  <h1>✓ Approved</h1>
  <p>{message}</p>
</div>
</body></html>
"""


def _error_page(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arlo — error</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f5f5f7; padding: 40px 20px; color: #1a1a1a; }}
  .card {{ max-width: 480px; margin: 0 auto; background: #fff; padding: 32px; border-radius: 12px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.08); text-align: center; border-top: 4px solid #dc3545; }}
  h1 {{ font-size: 22px; color: #dc3545; margin: 0 0 12px 0; }}
  p {{ font-size: 15px; line-height: 1.5; color: #555; }}
</style></head><body>
<div class="card">
  <h1>✗ Error</h1>
  <p>{message}</p>
</div>
</body></html>
"""


@public_router.get("/{workflow_id}/approve-link/{token}", include_in_schema=False)
async def approve_via_link(
    workflow_id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Approve a workflow via a signed URL (clicked from an email).

    No bearer auth required — the HMAC signature on the token IS the
    auth. Returns a human-readable HTML page (not JSON) since this is
    clicked from an email client.
    """
    payload = verify_signed_token(token, expected_purpose="approve")
    if payload is None:
        return HTMLResponse(
            _error_page("Invalid or expired approval link."),
            status_code=401,
        )
    if payload.get("wf") != str(workflow_id):
        return HTMLResponse(
            _error_page("Token does not match this workflow."),
            status_code=400,
        )

    choice = int(payload.get("choice", 0))
    try:
        if choice == 0:
            await workflow_service.approve_step(db, workflow_id, approved=False)
            return HTMLResponse(
                _success_page("Skipped. Workflow ended without building."),
            )
        # Look up the chosen ranking from the workflow's stored synthesis
        wf = await workflow_service.get_workflow(db, workflow_id)
        if wf is None:
            return HTMLResponse(_error_page("Workflow not found."), status_code=404)
        ctx = json.loads(wf.context)
        synthesis_raw = ctx.get("synthesis", "{}")
        if isinstance(synthesis_raw, str):
            try:
                synthesis = json.loads(synthesis_raw)
            except json.JSONDecodeError:
                synthesis = {}
        else:
            synthesis = synthesis_raw or {}
        rankings = (synthesis or {}).get("final_rankings") or []
        selected = next((r for r in rankings if r.get("rank") == choice), None)
        if selected is None and 1 <= choice <= len(rankings):
            # Positional fallback if rank numbers don't line up
            selected = rankings[choice - 1]
        if selected is None:
            return HTMLResponse(
                _error_page(f"Choice #{choice} not found in synthesis."),
                status_code=400,
            )
        # Round 3: pick the context override key based on the template.
        # Startup uses selected_idea; side hustle + freelance scanner
        # use selected_hustle. Unknown templates fall back to
        # selected_idea (matches pre-Round-3 behavior).
        override_key = _TEMPLATE_OVERRIDE_KEY.get(
            wf.template_id or "",
            "selected_idea",
        )
        await workflow_service.approve_step(
            db,
            workflow_id,
            approved=True,
            context_overrides={override_key: selected},
        )
        idea_name = selected.get("name", f"idea #{choice}")
        return HTMLResponse(
            _success_page(
                f"Building idea #{choice}: <strong>{idea_name}</strong>. "
                f"You'll get another email when the build is done."
            ),
        )
    except ValueError as e:
        return HTMLResponse(_error_page(str(e)), status_code=400)


@public_router.get("/{workflow_id}/artifacts.tar.gz", include_in_schema=False)
async def download_workspace(
    workflow_id: uuid.UUID,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Stream the build_mvp workspace as a gzipped tarball.

    Auth is the signed token in the ``token`` query param (same
    mechanism as the approve-by-link endpoint, different purpose).
    The token is minted by the build-complete notification email.
    """
    payload = verify_signed_token(token, expected_purpose="artifacts")
    if payload is None or payload.get("wf") != str(workflow_id):
        raise HTTPException(status_code=401, detail="Invalid or expired download link")

    # Find the latest job for this workflow that has a workspace_path set
    jobs = await workflow_service.get_workflow_jobs(db, workflow_id)
    build_job = None
    for j in reversed(jobs):
        if j.workspace_path:
            build_job = j
            break
    if build_job is None or not build_job.workspace_path:
        raise HTTPException(status_code=404, detail="No build artifacts found for this workflow")

    workspace = Path(build_job.workspace_path)
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="Workspace directory missing")

    def iter_tar():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(str(workspace), arcname=workspace.name, recursive=True)
        buf.seek(0)
        while True:
            chunk = buf.read(64 * 1024)
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        iter_tar(),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="workflow-{workflow_id}.tar.gz"'
        },
    )
