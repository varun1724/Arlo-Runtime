from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobRow, WorkflowRow
from app.models.job import CreateJobRequest, JobStatus, JobType
from app.models.workflow import (
    CreateWorkflowRequest,
    StepCondition,
    StepDefinition,
    WorkflowStatus,
)
from app.services.job_service import create_job

logger = logging.getLogger("arlo.workflow")


# Round 3 (side hustle): the approval-gate fallback in ``approve_step``
# walks this tuple when deciding which ``selected_*`` context key(s)
# to populate from rank-1. ``selected_idea`` is the startup pipeline's
# convention; ``selected_hustle`` is the side hustle + freelance
# scanner convention. Adding a new approval-gated pipeline with its
# own key? Append it here.
_APPROVAL_FALLBACK_KEYS: tuple[str, ...] = ("selected_idea", "selected_hustle")


async def create_workflow(
    session: AsyncSession, request: CreateWorkflowRequest
) -> WorkflowRow:
    """Create a workflow and kick off its first step."""
    step_defs_json = json.dumps([s.model_dump() for s in request.steps])
    context_json = json.dumps(request.initial_context)

    row = WorkflowRow(
        name=request.name,
        template_id=request.template_id,
        status=WorkflowStatus.RUNNING.value,
        context=context_json,
        step_definitions=step_defs_json,
        current_step_index=0,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    # Create the first job
    first_step = request.steps[0]
    context = request.initial_context
    prompt = _render_prompt(first_step.prompt_template, context)

    job_request = CreateJobRequest(
        job_type=JobType(first_step.job_type),
        prompt=prompt,
    )
    await create_job(session, job_request, workflow_id=row.id, step_index=0)

    logger.info("Created workflow %s (%s) with %d steps", row.id, row.name, len(request.steps))
    return row


async def get_workflow(session: AsyncSession, workflow_id: uuid.UUID) -> WorkflowRow | None:
    return await session.get(WorkflowRow, workflow_id)


async def cancel_workflow(session: AsyncSession, workflow_id: uuid.UUID) -> WorkflowRow:
    """Cancel a workflow and all its queued jobs."""
    workflow = await session.get(WorkflowRow, workflow_id)
    if workflow is None:
        raise ValueError(f"Workflow {workflow_id} not found")

    if workflow.status in (
        WorkflowStatus.SUCCEEDED.value,
        WorkflowStatus.FAILED.value,
        WorkflowStatus.CANCELED.value,
    ):
        raise ValueError(f"Workflow {workflow_id} is already {workflow.status}")

    now = datetime.now(timezone.utc)

    # Cancel the workflow
    await session.execute(
        update(WorkflowRow)
        .where(WorkflowRow.id == workflow_id)
        .values(status=WorkflowStatus.CANCELED.value, updated_at=now, completed_at=now)
    )

    # Cancel all queued jobs belonging to this workflow
    await session.execute(
        update(JobRow)
        .where(JobRow.workflow_id == workflow_id, JobRow.status == "queued")
        .values(status="canceled", stop_reason="workflow_canceled", updated_at=now, completed_at=now)
    )

    await session.commit()
    await session.refresh(workflow)
    logger.info("Canceled workflow %s and its queued jobs", workflow_id)
    return workflow


async def list_workflows(
    session: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[list[WorkflowRow], int]:
    count_result = await session.execute(select(func.count()).select_from(WorkflowRow))
    total = count_result.scalar_one()

    rows_result = await session.execute(
        select(WorkflowRow).order_by(WorkflowRow.created_at.desc()).limit(limit).offset(offset)
    )
    rows = list(rows_result.scalars().all())
    return rows, total


async def get_workflow_jobs(session: AsyncSession, workflow_id: uuid.UUID) -> list[JobRow]:
    result = await session.execute(
        select(JobRow)
        .where(JobRow.workflow_id == workflow_id)
        .order_by(JobRow.step_index.asc(), JobRow.created_at.asc())
    )
    return list(result.scalars().all())


async def advance_workflow(session: AsyncSession, workflow_id: uuid.UUID) -> None:
    """Advance a workflow after a job completes.

    This is the core orchestration function. Called by the worker after
    any job belonging to a workflow finishes.
    """
    workflow = await session.get(WorkflowRow, workflow_id)
    if workflow is None:
        logger.error("advance_workflow: workflow %s not found", workflow_id)
        return

    if workflow.status in (
        WorkflowStatus.SUCCEEDED.value,
        WorkflowStatus.FAILED.value,
        WorkflowStatus.CANCELED.value,
    ):
        logger.info("Workflow %s already in terminal state: %s", workflow_id, workflow.status)
        return

    step_defs = [StepDefinition.model_validate(s) for s in json.loads(workflow.step_definitions)]
    context = json.loads(workflow.context)
    current_index = workflow.current_step_index

    # Find the job that just completed for the current step
    result = await session.execute(
        select(JobRow)
        .where(JobRow.workflow_id == workflow_id, JobRow.step_index == current_index)
        .order_by(JobRow.created_at.desc())
        .limit(1)
    )
    completed_job = result.scalars().first()

    if completed_job is None:
        logger.error("No job found for workflow %s step %d", workflow_id, current_index)
        return

    # If the job failed, check for auto-retry before failing the workflow
    if completed_job.status == JobStatus.FAILED.value:
        current_step = step_defs[current_index]

        # Count how many attempts have been made for this step
        attempt_count_result = await session.execute(
            select(func.count())
            .select_from(JobRow)
            .where(JobRow.workflow_id == workflow_id, JobRow.step_index == current_index)
        )
        attempt_count = attempt_count_result.scalar_one()

        if _should_retry_step(current_step.max_retries, attempt_count):
            # Auto-retry: create a new job for the same step
            logger.info(
                "Workflow %s: auto-retrying step %d (%s), attempt %d/%d",
                workflow_id, current_index, current_step.name, attempt_count, current_step.max_retries + 1,
            )
            await _create_step_job(session, workflow_id, current_index, current_step, context)
            return

        # No retries left — fail the workflow
        now = datetime.now(timezone.utc)
        await session.execute(
            update(WorkflowRow)
            .where(WorkflowRow.id == workflow_id)
            .values(
                status=WorkflowStatus.FAILED.value,
                error_message=f"Step {current_index} ({current_step.name}) failed after {attempt_count} attempt(s): {completed_job.error_message}",
                updated_at=now,
                completed_at=now,
            )
        )
        await session.commit()
        logger.warning("Workflow %s failed at step %d after %d attempts", workflow_id, current_index, attempt_count)
        # Round 5: fire the failure notification (no-op if email not configured)
        from app.services import notifications
        await notifications.notify(session, workflow_id, "workflow_failed")
        return

    # If the job is not yet succeeded, do nothing (still running or queued)
    if completed_job.status != JobStatus.SUCCEEDED.value:
        return

    # Merge result into context
    current_step = step_defs[current_index]
    if completed_job.result_data:
        context[current_step.output_key] = completed_job.result_data

    # Determine next step
    next_index = current_index + 1
    if current_step.loop_to is not None and current_step.max_loop_count is not None:
        # Round 3: gate the loop on loop_condition (when set). Without a
        # loop_condition the existing unconditional behavior is preserved.
        should_loop = (
            current_step.loop_condition is None
            or _evaluate_condition(current_step.loop_condition, context)
        )
        if should_loop:
            # Check how many times we've looped
            loop_count_result = await session.execute(
                select(func.count())
                .select_from(JobRow)
                .where(JobRow.workflow_id == workflow_id, JobRow.step_index == current_step.loop_to)
            )
            loop_count = loop_count_result.scalar_one()
            if loop_count < current_step.max_loop_count:
                next_index = current_step.loop_to
                # Inject a flag so the looped-back step knows it's a retry
                # (used by landscape_scan to broaden its search). Stored as
                # the literal string "true" because context values are
                # rendered with str() — keeping this consistent with how
                # JSON-string outputs are stored.
                context["previous_attempt_killed_all"] = "true"
                logger.info(
                    "Workflow %s: loop_condition fired, looping step %d -> %d",
                    workflow_id, current_index, current_step.loop_to,
                )

    # Skip steps whose conditions fail
    while next_index < len(step_defs):
        next_step = step_defs[next_index]
        if next_step.condition is None or _evaluate_condition(next_step.condition, context):
            break
        logger.info(
            "Workflow %s: skipping step %d (%s) — condition not met",
            workflow_id, next_index, next_step.name,
        )
        next_index += 1

    # Check if workflow is done
    if next_index >= len(step_defs):
        now = datetime.now(timezone.utc)
        await session.execute(
            update(WorkflowRow)
            .where(WorkflowRow.id == workflow_id)
            .values(
                status=WorkflowStatus.SUCCEEDED.value,
                context=json.dumps(context),
                current_step_index=current_index,
                updated_at=now,
                completed_at=now,
            )
        )
        await session.commit()
        logger.info("Workflow %s completed successfully", workflow_id)
        # Round 6.A1: fire build_complete when the just-completed step is
        # the pipeline's registered terminal step. Each user-facing
        # pipeline registers its terminal step in
        # notifications._TERMINAL_STEP_BY_TEMPLATE. Pipelines NOT in that
        # map (e.g. strategy_evolution) never fire — opt-in by template_id.
        # Round 5 hardcoded ``current_step.name == "build_mvp"`` here,
        # which meant side hustle (terminates at ``test_run``) and
        # freelance scanner (terminates at ``deploy_scanner``) never
        # got the build-complete notification.
        from app.services import notifications
        wf_row = await session.get(WorkflowRow, workflow_id)
        template_id = (wf_row.template_id or "").strip() if wf_row else ""
        expected_terminal = notifications._TERMINAL_STEP_BY_TEMPLATE.get(template_id)
        if expected_terminal and current_step.name == expected_terminal:
            await notifications.notify(session, workflow_id, "build_complete")
        return

    # Check if next step requires approval
    next_step = step_defs[next_index]
    if next_step.requires_approval:
        await session.execute(
            update(WorkflowRow)
            .where(WorkflowRow.id == workflow_id)
            .values(
                status=WorkflowStatus.AWAITING_APPROVAL.value,
                context=json.dumps(context),
                current_step_index=next_index,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        logger.info(
            "Workflow %s paused — step %d (%s) requires approval",
            workflow_id, next_index, next_step.name,
        )
        # Round 5: fire the approval notification hook. The notification
        # dispatcher renders the synthesis into HTML+PDF and emails the
        # user with signed approval URLs. No-op if email not configured.
        from app.services import notifications
        await notifications.notify(session, workflow_id, "awaiting_approval")
        return

    # Create the next job
    await _create_step_job(session, workflow_id, next_index, next_step, context)
    logger.info(
        "Workflow %s advanced to step %d (%s)",
        workflow_id, next_index, next_step.name,
    )


async def approve_step(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    *,
    approved: bool = True,
    context_overrides: dict | None = None,
) -> WorkflowRow:
    """Approve (or skip) a step that's awaiting approval.

    If approved=True, creates the job for the current step and resumes the workflow.
    If approved=False, skips the step and advances to the next one (or completes).
    context_overrides lets the user inject or modify context before the step runs.
    """
    workflow = await session.get(WorkflowRow, workflow_id)
    if workflow is None:
        raise ValueError(f"Workflow {workflow_id} not found")

    if workflow.status != WorkflowStatus.AWAITING_APPROVAL.value:
        raise ValueError(f"Workflow {workflow_id} is not awaiting approval (status={workflow.status})")

    step_defs = [StepDefinition.model_validate(s) for s in json.loads(workflow.step_definitions)]
    context = json.loads(workflow.context)
    current_index = workflow.current_step_index

    # Apply context overrides
    if context_overrides:
        context.update(context_overrides)

    if approved:
        # Create the job and resume
        current_step = step_defs[current_index]

        # Defensive fallback: if any downstream step needs a `selected_*`
        # key (via context_inputs) but the caller didn't provide one in
        # context_overrides, default to the rank-1 entry from the prior
        # synthesis. Round 3: pipeline-aware across `selected_idea`
        # (startup) and `selected_hustle` (side hustle + freelance
        # scanner). A workflow that somehow needs both gets both.
        # This keeps direct API callers and legacy scripts working
        # without forcing them to pick.
        #
        # Note: we walk *forward* from the current step. The current step
        # is the approval gate itself (a placeholder with no context_inputs),
        # so checking only the current step misses the point — the consumer
        # is the step that comes AFTER the approval.
        needed_keys: set[str] = set()
        for downstream in step_defs[current_index:]:
            if downstream.context_inputs is None:
                continue
            for key in _APPROVAL_FALLBACK_KEYS:
                if key in downstream.context_inputs and key not in context:
                    needed_keys.add(key)

        if needed_keys:
            try:
                synthesis_raw = context.get("synthesis")
                synthesis_dict = (
                    json.loads(synthesis_raw)
                    if isinstance(synthesis_raw, str)
                    else synthesis_raw
                )
                rankings = (synthesis_dict or {}).get("final_rankings") or []
                if rankings:
                    rank_one = rankings[0]
                    for key in needed_keys:
                        context[key] = rank_one
                    logger.info(
                        "Workflow %s: no %s provided, defaulting to rank-1",
                        workflow_id, sorted(needed_keys),
                    )
            except (json.JSONDecodeError, TypeError, KeyError):
                logger.warning(
                    "Workflow %s: could not extract default %s from synthesis",
                    workflow_id, sorted(needed_keys),
                )
        await session.execute(
            update(WorkflowRow)
            .where(WorkflowRow.id == workflow_id)
            .values(
                status=WorkflowStatus.RUNNING.value,
                context=json.dumps(context),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        await _create_step_job(session, workflow_id, current_index, current_step, context)
        logger.info("Workflow %s: step %d approved, resuming", workflow_id, current_index)
    else:
        # Skip this step, try to advance
        next_index = current_index + 1

        # Skip any further steps whose conditions fail
        while next_index < len(step_defs):
            next_step = step_defs[next_index]
            if next_step.condition is None or _evaluate_condition(next_step.condition, context):
                break
            next_index += 1

        if next_index >= len(step_defs):
            # Workflow done
            now = datetime.now(timezone.utc)
            await session.execute(
                update(WorkflowRow)
                .where(WorkflowRow.id == workflow_id)
                .values(
                    status=WorkflowStatus.SUCCEEDED.value,
                    context=json.dumps(context),
                    updated_at=now,
                    completed_at=now,
                )
            )
            await session.commit()
            logger.info("Workflow %s: step skipped, workflow completed", workflow_id)
        else:
            next_step = step_defs[next_index]
            if next_step.requires_approval:
                await session.execute(
                    update(WorkflowRow)
                    .where(WorkflowRow.id == workflow_id)
                    .values(
                        status=WorkflowStatus.AWAITING_APPROVAL.value,
                        context=json.dumps(context),
                        current_step_index=next_index,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                logger.info("Workflow %s: skipped to step %d, also requires approval", workflow_id, next_index)
            else:
                await session.execute(
                    update(WorkflowRow)
                    .where(WorkflowRow.id == workflow_id)
                    .values(
                        status=WorkflowStatus.RUNNING.value,
                        context=json.dumps(context),
                        current_step_index=next_index,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                await _create_step_job(session, workflow_id, next_index, next_step, context)
                logger.info("Workflow %s: step skipped, advanced to step %d", workflow_id, next_index)

    await session.refresh(workflow)
    return workflow


async def retry_step(session: AsyncSession, workflow_id: uuid.UUID) -> WorkflowRow:
    """Retry the current failed step of a workflow.

    Only works when workflow status is 'failed'. Creates a new job for
    the failed step and sets workflow back to 'running'.
    """
    workflow = await session.get(WorkflowRow, workflow_id)
    if workflow is None:
        raise ValueError(f"Workflow {workflow_id} not found")

    if workflow.status != WorkflowStatus.FAILED.value:
        raise ValueError(f"Workflow {workflow_id} is not failed (status={workflow.status})")

    step_defs = [StepDefinition.model_validate(s) for s in json.loads(workflow.step_definitions)]
    context = json.loads(workflow.context)
    current_index = workflow.current_step_index
    current_step = step_defs[current_index]

    # Set workflow back to running
    await session.execute(
        update(WorkflowRow)
        .where(WorkflowRow.id == workflow_id)
        .values(
            status=WorkflowStatus.RUNNING.value,
            error_message=None,
            completed_at=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    # Create a new job for the same step
    await _create_step_job(session, workflow_id, current_index, current_step, context)
    logger.info("Workflow %s: retrying step %d (%s)", workflow_id, current_index, current_step.name)

    await session.refresh(workflow)
    return workflow


async def _check_cost_cap(
    session: AsyncSession, workflow_id: uuid.UUID, context: dict
) -> tuple[bool, float, float] | None:
    """Enforce the per-workflow cost cap before a new step job is created.

    Reads the cap from ``context["_max_cost_usd"]`` (injected at workflow
    creation via the ``max_cost_usd`` field on
    ``CreateWorkflowFromTemplateRequest``). If the cap is unset, returns
    None — the caller should proceed without gating.

    Returns ``(exceeded, spent_so_far, cap)`` when the cap IS set, where
    ``exceeded`` is True iff the summed ``JobRow.estimated_cost_usd`` across
    this workflow has already reached or passed the cap. Callers that
    receive ``exceeded=True`` should mark the workflow failed rather than
    creating the next job.

    Only the cost that has *already been committed* counts — we can't
    predict what the next Opus call will cost, so this is a post-hoc
    circuit breaker, not a pre-flight estimate.
    """
    cap = context.get("_max_cost_usd")
    if cap is None:
        return None
    try:
        cap_f = float(cap)
    except (TypeError, ValueError):
        logger.warning("Workflow %s has non-numeric _max_cost_usd=%r; ignoring", workflow_id, cap)
        return None

    spent_result = await session.execute(
        select(func.coalesce(func.sum(JobRow.estimated_cost_usd), 0.0))
        .where(JobRow.workflow_id == workflow_id)
    )
    spent = float(spent_result.scalar_one() or 0.0)
    return (spent >= cap_f, spent, cap_f)


async def _abort_workflow_for_cost_cap(
    session: AsyncSession, workflow_id: uuid.UUID, spent: float, cap: float
) -> None:
    """Fail the workflow because its committed cost has hit the cap."""
    now = datetime.now(timezone.utc)
    msg = (
        f"Aborted: committed cost ${spent:.2f} reached the "
        f"max_cost_usd cap of ${cap:.2f} before creating the next step. "
        f"No further jobs will be queued."
    )
    await session.execute(
        update(WorkflowRow)
        .where(WorkflowRow.id == workflow_id)
        .values(
            status=WorkflowStatus.FAILED.value,
            error_message=msg,
            updated_at=now,
            completed_at=now,
        )
    )
    await session.commit()
    logger.warning("Workflow %s aborted for cost cap (%s)", workflow_id, msg)
    # Fire the standard failure notification — the operator cares just
    # as much about a cap abort as about a Claude error.
    from app.services import notifications
    await notifications.notify(session, workflow_id, "workflow_failed")


async def _create_step_job(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    step_index: int,
    step: StepDefinition,
    context: dict,
) -> None:
    """Create a job for a workflow step and update workflow state.

    If ``step.context_inputs`` is set, only those keys are passed to the
    prompt renderer (the full context is still saved on the workflow row
    for debugging and approval-step display). This prevents prompt bloat
    on steps that only need a subset of prior outputs (e.g. ``build_mvp``
    only needs ``synthesis``, not the full landscape/deep_dive/contrarian
    chain).

    Before creating the job, the per-workflow cost cap (if configured)
    is enforced: any call here that would queue a job after the cap has
    been reached aborts the workflow instead of spending more tokens.
    """
    cap_check = await _check_cost_cap(session, workflow_id, context)
    if cap_check is not None:
        exceeded, spent, cap = cap_check
        if exceeded:
            await _abort_workflow_for_cost_cap(session, workflow_id, spent, cap)
            return

    render_context = _prune_context(context, step.context_inputs)
    prompt = _render_prompt(step.prompt_template, render_context)

    job_request = CreateJobRequest(
        job_type=JobType(step.job_type),
        prompt=prompt,
    )
    await create_job(session, job_request, workflow_id=workflow_id, step_index=step_index)

    await session.execute(
        update(WorkflowRow)
        .where(WorkflowRow.id == workflow_id)
        .values(
            context=json.dumps(context),
            current_step_index=step_index,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


def _should_retry_step(max_retries: int, attempt_count: int) -> bool:
    """Decide whether a failed step should be retried.

    ``attempt_count`` is the number of jobs that already exist for this
    step (including the just-failed one). ``max_retries`` is the number
    of *additional* attempts allowed beyond the first try.

    Total allowed attempts = ``max_retries + 1``. So we retry as long as
    ``attempt_count <= max_retries``. The check ``max_retries > 0`` is
    redundant when ``attempt_count`` starts at 1 but kept for clarity:
    a step with ``max_retries=0`` never retries.

    Pure function — no DB or workflow state. Extracted from
    ``advance_workflow`` so the decision can be unit tested directly.
    """
    if max_retries <= 0:
        return False
    return attempt_count <= max_retries


def _prune_context(context: dict, context_inputs: list[str] | None) -> dict:
    """Filter a workflow context dict to a whitelist of keys.

    If ``context_inputs`` is None, returns ``context`` unchanged (this is
    the legacy behavior — every key is passed to the prompt renderer).
    If it is a list, only the listed keys are included; missing keys are
    silently dropped (the renderer's ``defaultdict`` fallback then
    substitutes ``{unknown}`` so the prompt is still well-formed).

    Pure function — no DB or workflow state involved. Extracted from
    ``_create_step_job`` so it can be unit tested directly.
    """
    if context_inputs is None:
        return context
    return {k: context[k] for k in context_inputs if k in context}


def _stringify_for_prompt(value) -> str:
    """Convert a context value to a prompt-safe string.

    Round 4 bug fix: Existing step outputs are JSON strings (from
    ``result_data``) and pass through ``str()`` unchanged. But Round 3's
    ``selected_idea`` injects raw dicts via ``context_overrides``, which
    would render as Python repr (``{'k': 'v'}``) if we naively str()'d
    them — invalid JSON, breaking downstream parsing in build_mvp.

    JSON-encode dicts and lists so the prompt receives valid JSON in
    both cases. Strings, ints, and other primitives pass through str().
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return str(value)


def _render_prompt(template: str, context: dict) -> str:
    """Render a prompt template with workflow context.

    Uses str.format_map with a defaultdict fallback so missing keys
    render as {key_name} instead of raising KeyError.
    """
    safe_context = defaultdict(
        lambda: "{unknown}",
        {k: _stringify_for_prompt(v) for k, v in context.items()},
    )
    try:
        return template.format_map(safe_context)
    except (KeyError, ValueError, IndexError):
        # If format_map fails for any reason, return template with what we can substitute
        result = template
        for key, value in context.items():
            result = result.replace(f"{{{key}}}", _stringify_for_prompt(value))
        return result


def _evaluate_condition(condition: StepCondition, context: dict) -> bool:
    """Evaluate a step condition against workflow context."""
    value = context.get(condition.field)

    if condition.operator == "exists":
        return value is not None
    elif condition.operator == "not_empty":
        return bool(value)
    elif condition.operator == "contains":
        return condition.value is not None and condition.value in str(value or "")
    elif condition.operator == "equals":
        return str(value) == str(condition.value)
    elif condition.operator == "survivor_count_below":
        # Round 3: Used by contrarian_analysis loop_condition. Counts the
        # opportunities in `contrarian_analyses` whose verdict is NOT 'killed'
        # and returns True when the count is below the threshold (a string
        # representation of an integer in `value`).
        try:
            threshold = int(condition.value or "0")
        except (TypeError, ValueError):
            logger.warning(
                "survivor_count_below: invalid threshold %r", condition.value
            )
            return False
        survivors = _count_survivors(value)
        result = survivors < threshold
        logger.info(
            "survivor_count_below: counted %d survivors (threshold %d, fires=%s)",
            survivors, threshold, result,
        )
        return result
    else:
        logger.warning("Unknown condition operator: %s", condition.operator)
        return True  # unknown operators pass by default


def _count_survivors(contrarian_value) -> int:
    """Count opportunities in a contrarian output whose verdict is not 'killed'.

    The value may be a JSON string (the on-disk format used by
    ``advance_workflow``) or already a parsed dict. Both forms are supported.
    Returns 0 on any parsing error.
    """
    if contrarian_value is None:
        return 0
    if isinstance(contrarian_value, str):
        try:
            contrarian_value = json.loads(contrarian_value)
        except (json.JSONDecodeError, TypeError):
            return 0
    if not isinstance(contrarian_value, dict):
        return 0
    analyses = contrarian_value.get("contrarian_analyses") or []
    if not isinstance(analyses, list):
        return 0
    return sum(
        1
        for a in analyses
        if isinstance(a, dict) and a.get("verdict") in ("survives", "weakened")
    )
