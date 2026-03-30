from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow
from app.jobs.prompts import build_research_prompt
from app.models.job import JobStatus, JobStopReason
from app.models.research import ResearchReport
from app.services.claude_runner import ClaudeRunError, ClaudeTimeoutError, run_claude
from app.services.job_service import finalize_job, update_job_progress

logger = logging.getLogger("arlo.jobs.research")


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

        # Step 2: Run Claude Code
        await update_job_progress(
            session,
            job.id,
            current_step="researching",
            progress_message="Claude Code is researching (this may take a few minutes)",
            iteration_count=2,
        )

        result = await run_claude(prompt, allow_permissions=True, model=settings.research_model)

        # Step 3: Parse and store
        await update_job_progress(
            session,
            job.id,
            current_step="parsing",
            progress_message="Parsing research results",
            iteration_count=3,
        )

        result_json, preview = _extract_result(result, is_workflow_job)

        await finalize_job(
            session,
            job.id,
            status=JobStatus.SUCCEEDED,
            result_preview=preview,
            result_data=result_json,
        )
        logger.info("Research job %s completed", job.id)

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


def _extract_result(claude_output: dict, raw_mode: bool) -> tuple[str, str]:
    """Extract result JSON and preview from Claude output.

    In raw_mode (workflow jobs), stores whatever JSON Claude returns without
    validating against ResearchReport schema. For standalone research jobs,
    validates against ResearchReport.

    Returns (result_json_string, preview_string).
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
        except json.JSONDecodeError:
            # Store as raw string if not valid JSON
            return cleaned, cleaned[:200]

    if raw_mode:
        # Workflow job: store raw JSON, build simple preview
        result_json = json.dumps(content)
        preview = _build_raw_preview(content)
        return result_json, preview
    else:
        # Standalone job: validate as ResearchReport
        report = ResearchReport.model_validate(content)
        return report.model_dump_json(), _build_report_preview(report)


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
