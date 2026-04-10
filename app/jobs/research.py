from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow, WorkflowRow
from app.jobs.prompts import build_research_prompt
from app.models.job import JobStatus, JobStopReason
from app.models.research import ResearchReport
from app.models.workflow import StepDefinition
from app.services.claude_runner import (
    ClaudeRunError,
    ClaudeTimeoutError,
    extract_usage,
    run_claude,
)
from app.services.job_service import finalize_job, update_job_progress
from app.workflows.schemas import get_schema

logger = logging.getLogger("arlo.jobs.research")


def _friendly_validation_error(err: ValidationError) -> str:
    """Translate a Pydantic ValidationError into a one-line user-facing string.

    Round 3: the raw Pydantic error string is verbose and confusing. Users
    seeing this in workflow.error_message want to know two things: WHICH
    field is wrong, and WHY. We extract the first error and format it.
    The full error is still available via the chained ``__cause__`` and
    in the structured logs.
    """
    errs = err.errors()
    if not errs:
        return str(err)
    first = errs[0]
    path_parts = first.get("loc", ())
    path = ".".join(str(p) for p in path_parts) if path_parts else "(root)"
    msg = first.get("msg", "validation error")
    extra = ""
    if len(errs) > 1:
        extra = f" (and {len(errs) - 1} more)"
    return f"Field '{path}': {msg}{extra}"


async def execute_research_job(session: AsyncSession, job: JobRow) -> None:
    """Execute a research job using Claude Code CLI with web search."""
    is_workflow_job = job.workflow_id is not None

    try:
        # Step 1: Prepare
        await update_job_progress(
            session,
            job.id,
            current_step="preparing",
            progress_message="Building research prompt",
            iteration_count=1,
        )

        # Workflow jobs already have their prompt rendered; standalone jobs need wrapping
        if is_workflow_job:
            prompt = job.prompt
        else:
            prompt = build_research_prompt(job.prompt)

        # Resolve the output schema for this step (if any)
        schema_cls: type[BaseModel] | None = None
        timeout_override: int | None = None
        if is_workflow_job:
            step = await _load_step_definition(session, job)
            if step is not None:
                schema_cls = get_schema(step.output_schema)
                timeout_override = step.timeout_override

        # Step 2: Run Claude Code
        await update_job_progress(
            session,
            job.id,
            current_step="researching",
            progress_message="Claude Code is researching (this may take a few minutes)",
            iteration_count=2,
        )

        result = await run_claude(
            prompt,
            allow_permissions=True,
            model=settings.research_model,
            timeout=timeout_override,
        )

        # Step 3: Parse and store
        await update_job_progress(
            session,
            job.id,
            current_step="parsing",
            progress_message="Parsing research results",
            iteration_count=3,
        )

        result_json, preview = _extract_result(result, is_workflow_job, schema_cls)

        # Round 3: extract token usage for cost visibility
        usage = extract_usage(result)

        await finalize_job(
            session,
            job.id,
            status=JobStatus.SUCCEEDED,
            result_preview=preview,
            result_data=result_json,
            tokens_input=usage["input_tokens"],
            tokens_output=usage["output_tokens"],
            estimated_cost_usd=usage["estimated_cost_usd"],
        )
        logger.info(
            "Research job %s completed (tokens: %s in / %s out, est $%s)",
            job.id, usage["input_tokens"], usage["output_tokens"],
            usage["estimated_cost_usd"],
        )

    except ClaudeTimeoutError:
        logger.warning("Research job %s timed out", job.id)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message="Research timed out — Claude Code took too long",
            stop_reason=JobStopReason.TIMEOUT.value,
        )

    except ClaudeRunError as e:
        logger.error("Research job %s failed — Claude error: %s", job.id, e)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=f"Claude Code error: {e}",
            stop_reason=JobStopReason.ERROR.value,
        )

    except Exception as e:
        logger.exception("Research job %s failed unexpectedly", job.id)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=str(e),
            stop_reason=JobStopReason.ERROR.value,
        )


def _extract_result(
    claude_output: dict,
    raw_mode: bool,
    schema_cls: type[BaseModel] | None = None,
) -> tuple[str, str]:
    """Extract result JSON and preview from Claude output.

    Three modes (in order of strictness):

    1. **Strict workflow mode** (``raw_mode=True``, ``schema_cls`` set): JSON
       must parse AND must validate against ``schema_cls``. Either failure
       raises ``ClaudeRunError``, which the caller maps to a job FAILED with
       ``stop_reason=ERROR``. The workflow's ``max_retries`` then retries.
       The stored JSON is the *normalized* dump of the validated model so
       downstream steps see clean input.

    2. **Loose workflow mode** (``raw_mode=True``, ``schema_cls=None``):
       Legacy behavior for templates that haven't opted into validation.
       JSON parse failures fall back to storing the raw cleaned string.

    3. **Standalone mode** (``raw_mode=False``): Validates against
       ``ResearchReport`` (the original standalone schema). Used by
       non-workflow research jobs.

    Returns ``(result_json_string, preview_string)``.
    """
    content = claude_output.get("result", claude_output)

    # Parse string content to JSON
    if isinstance(content, str):
        cleaned = content.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            content = json.loads(cleaned)
        except json.JSONDecodeError as e:
            if raw_mode and schema_cls is not None:
                # Strict mode: JSON parse failure is a hard error
                raise ClaudeRunError(
                    f"Output validation failed: response was not valid JSON ({e}). "
                    f"First 200 chars: {cleaned[:200]}"
                ) from e
            if not raw_mode:
                # Standalone mode also expects valid JSON for ResearchReport
                raise ClaudeRunError(
                    f"Output validation failed: response was not valid JSON ({e}). "
                    f"First 200 chars: {cleaned[:200]}"
                ) from e
            # Loose workflow mode: legacy fallback
            return cleaned, cleaned[:200]

    if raw_mode:
        if schema_cls is not None:
            # Strict workflow mode: validate against the registered schema
            try:
                model = schema_cls.model_validate(content)
            except ValidationError as e:
                # Round 3: surface a friendly one-liner; full error is logged
                # via the exception handler in execute_research_job.
                raise ClaudeRunError(
                    f"{schema_cls.__name__} validation failed — "
                    f"{_friendly_validation_error(e)}"
                ) from e
            result_json = model.model_dump_json()
            preview = _build_raw_preview(model.model_dump())
            return result_json, preview
        # Loose workflow mode: store raw JSON, build simple preview
        result_json = json.dumps(content)
        preview = _build_raw_preview(content)
        return result_json, preview

    # Standalone mode: validate as ResearchReport
    try:
        report = ResearchReport.model_validate(content)
    except ValidationError as e:
        raise ClaudeRunError(
            f"ResearchReport validation failed — {_friendly_validation_error(e)}"
        ) from e
    return report.model_dump_json(), _build_report_preview(report)


async def _load_step_definition(
    session: AsyncSession, job: JobRow
) -> StepDefinition | None:
    """Fetch the StepDefinition for a workflow job.

    Returns None if the job is not part of a workflow, the workflow row
    can't be found, or the step_index is out of range. Failures are
    intentionally non-fatal — we fall back to legacy loose-mode behavior
    so a missing definition never blocks job execution.
    """
    if job.workflow_id is None or job.step_index is None:
        return None
    try:
        workflow = await session.get(WorkflowRow, job.workflow_id)
        if workflow is None:
            return None
        step_dicts = json.loads(workflow.step_definitions)
        if job.step_index >= len(step_dicts):
            return None
        return StepDefinition.model_validate(step_dicts[job.step_index])
    except Exception:
        logger.exception(
            "Failed to load step definition for job %s (workflow %s, step %s)",
            job.id, job.workflow_id, job.step_index,
        )
        return None


def _build_report_preview(report: ResearchReport) -> str:
    """Build preview from a validated ResearchReport."""
    lines = [f"Market: {report.market_overview[:150]}..."]
    lines.append(f"Found {len(report.opportunities)} opportunities, {len(report.trends)} trends, {len(report.risks)} risks.")
    if report.top_recommendations:
        top = report.top_recommendations[0]
        lines.append(f"Top pick: {top.name}")
    return "\n".join(lines)


def _build_raw_preview(content: dict) -> str:
    """Build a simple preview from raw JSON content."""
    if isinstance(content, dict):
        # Try to find a summary-like field
        for key in ("summary", "top_pick", "name", "result"):
            if key in content:
                return str(content[key])[:300]
        # Fall back to listing keys
        return f"Result with keys: {', '.join(list(content.keys())[:10])}"
    return str(content)[:300]
