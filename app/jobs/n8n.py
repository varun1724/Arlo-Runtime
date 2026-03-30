from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobRow
from app.models.job import JobStatus, JobStopReason
from app.services.job_service import finalize_job, update_job_progress
from app.tools.n8n import N8nAPIError, N8nClient, N8nTimeoutError

logger = logging.getLogger("arlo.jobs.n8n")


async def execute_n8n_job(session: AsyncSession, job: JobRow) -> None:
    """Execute an n8n job: create, execute, or create_and_execute a workflow."""
    client = N8nClient()

    try:
        # Parse the job prompt as JSON instructions
        try:
            instructions = json.loads(job.prompt)
        except json.JSONDecodeError as e:
            raise ValueError(f"n8n job prompt is not valid JSON: {e}")

        action = instructions.get("action", "create")
        workflow_json = instructions.get("workflow_json")
        n8n_workflow_id = instructions.get("n8n_workflow_id")
        activate = instructions.get("activate", False)
        execution_data = instructions.get("execution_data")

        # Extract workflow JSON from builder result if flagged
        if instructions.get("workflow_json_from_build") and not workflow_json:
            build_result = instructions.get("build_result", "")
            workflow_json = _extract_workflow_json_from_build(build_result)

            # If not found in result data, try reading from the builder's workspace
            if workflow_json is None and job.workflow_id:
                workflow_json = await _read_workflow_from_workspace(session, job.workflow_id)

        # Extract workflow ID from deploy result if flagged
        if instructions.get("n8n_workflow_id_from_deploy") and not n8n_workflow_id:
            deploy_result = instructions.get("deploy_result", "")
            n8n_workflow_id = _extract_workflow_id_from_deploy(deploy_result)

        result = {}

        # Step 1: Create workflow if needed
        if action in ("create", "create_and_execute"):
            if workflow_json is None:
                raise ValueError("action requires 'workflow_json' but none provided")

            await update_job_progress(
                session,
                job.id,
                current_step="creating",
                progress_message="Creating n8n workflow",
                iteration_count=1,
            )

            created = await client.create_workflow(workflow_json)
            n8n_workflow_id = created.get("id")
            result["n8n_workflow_id"] = n8n_workflow_id
            result["n8n_workflow_name"] = created.get("name", "")
            logger.info("n8n job %s: created workflow %s", job.id, n8n_workflow_id)

        # Step 2: Activate if requested
        if activate and n8n_workflow_id:
            await update_job_progress(
                session,
                job.id,
                current_step="activating",
                progress_message="Activating n8n workflow",
                iteration_count=2,
            )
            await client.activate_workflow(n8n_workflow_id)
            result["activated"] = True

        # Step 3: Execute if needed
        if action in ("execute", "create_and_execute"):
            if n8n_workflow_id is None:
                raise ValueError("Cannot execute: no n8n_workflow_id")

            await update_job_progress(
                session,
                job.id,
                current_step="executing",
                progress_message="Running n8n workflow",
                iteration_count=3,
            )

            execution = await client.execute_workflow(n8n_workflow_id, execution_data)
            execution_id = execution.get("id")

            if execution_id:
                await update_job_progress(
                    session,
                    job.id,
                    current_step="polling",
                    progress_message="Waiting for n8n execution to complete",
                    iteration_count=4,
                )
                final = await client.poll_execution(str(execution_id))
                result["execution_id"] = str(execution_id)
                result["execution_status"] = final.get("status", "unknown")
                result["execution_data"] = final.get("data")
            else:
                # Some n8n endpoints return results directly
                result["execution_status"] = "completed"
                result["execution_data"] = execution

        # Finalize
        result_json = json.dumps(result)
        preview = _build_preview(result)

        await finalize_job(
            session,
            job.id,
            status=JobStatus.SUCCEEDED,
            result_preview=preview,
            result_data=result_json,
        )
        logger.info("n8n job %s succeeded", job.id)

    except N8nTimeoutError as e:
        logger.warning("n8n job %s timed out: %s", job.id, e)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=f"n8n execution timed out: {e}",
            stop_reason=JobStopReason.TIMEOUT.value,
        )

    except N8nAPIError as e:
        logger.error("n8n job %s API error: %s", job.id, e)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=f"n8n API error: {e}",
            stop_reason=JobStopReason.ERROR.value,
        )

    except Exception as e:
        logger.exception("n8n job %s failed unexpectedly", job.id)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=str(e),
            stop_reason=JobStopReason.ERROR.value,
        )


async def _read_workflow_from_workspace(session: AsyncSession, workflow_id) -> dict | None:
    """Find the builder job's workspace and read workflow.json from it."""
    from pathlib import Path
    from sqlalchemy import select

    # Find the most recent builder job in this workflow
    result = await session.execute(
        select(JobRow)
        .where(JobRow.workflow_id == workflow_id, JobRow.job_type == "builder")
        .order_by(JobRow.created_at.desc())
        .limit(1)
    )
    builder_job = result.scalars().first()
    if not builder_job or not builder_job.workspace_path:
        return None

    # Look for workflow.json in the workspace
    workspace = Path(builder_job.workspace_path)
    for name in ("workflow.json", "n8n-workflow.json"):
        wf_path = workspace / name
        if wf_path.exists():
            try:
                content = json.loads(wf_path.read_text())
                logger.info("Read workflow JSON from %s", wf_path)
                return content
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read %s: %s", wf_path, e)

    # Search recursively for any workflow.json
    for wf_path in workspace.rglob("workflow.json"):
        try:
            content = json.loads(wf_path.read_text())
            logger.info("Read workflow JSON from %s", wf_path)
            return content
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", wf_path, e)

    logger.warning("No workflow.json found in workspace %s", workspace)
    return None


def _extract_workflow_json_from_build(build_result: str) -> dict | None:
    """Extract n8n workflow JSON from a builder job's result_data."""
    try:
        data = json.loads(build_result) if isinstance(build_result, str) else build_result
    except json.JSONDecodeError:
        return None

    # Check for workflow_json key in arlo_manifest
    if isinstance(data, dict) and "workflow_json" in data:
        wf = data["workflow_json"]
        return json.loads(wf) if isinstance(wf, str) else wf

    # Check for artifacts list — look for workflow.json content
    if isinstance(data, dict) and "artifacts" in data:
        for artifact in data.get("artifacts", []):
            if artifact.get("path", "").endswith("workflow.json"):
                # The actual content isn't in the artifact list, just metadata
                break

    return None


def _extract_workflow_id_from_deploy(deploy_result: str) -> str | None:
    """Extract n8n workflow ID from a deploy job's result_data."""
    try:
        data = json.loads(deploy_result) if isinstance(deploy_result, str) else deploy_result
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict):
        return data.get("n8n_workflow_id")
    return None


def _build_preview(result: dict) -> str:
    """Build a preview from n8n job results."""
    parts = []
    if result.get("n8n_workflow_id"):
        parts.append(f"Workflow: {result['n8n_workflow_id']}")
    if result.get("n8n_workflow_name"):
        parts.append(f"({result['n8n_workflow_name']})")
    if result.get("activated"):
        parts.append("— activated")
    if result.get("execution_status"):
        parts.append(f"— execution: {result['execution_status']}")
    return " ".join(parts) if parts else "n8n job completed"
