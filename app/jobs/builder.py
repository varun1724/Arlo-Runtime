from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow
from app.jobs.prompts import build_builder_prompt
from app.models.builder import BuilderArtifact, BuilderResult
from app.models.job import JobStatus, JobStopReason
from app.services.claude_runner import ClaudeRunError, ClaudeTimeoutError, run_claude
from app.services.job_service import finalize_job, update_job_progress
from app.workspace.manager import create_job_workspace, scan_workspace_artifacts

logger = logging.getLogger("arlo.jobs.builder")


async def execute_builder_job(session: AsyncSession, job: JobRow) -> None:
    """Execute a builder job using Claude Code CLI in a sandboxed workspace."""
    workspace_path = None
    try:
        # Step 1: Create workspace
        await update_job_progress(
            session,
            job.id,
            current_step="preparing",
            progress_message="Creating workspace",
            iteration_count=1,
        )
        workspace_path = create_job_workspace(str(job.id))
        logger.info("Builder job %s: workspace at %s", job.id, workspace_path)

        # Step 2: Run Claude Code in the workspace
        await update_job_progress(
            session,
            job.id,
            current_step="building",
            progress_message="Claude Code is building (this may take several minutes)",
            iteration_count=2,
        )

        prompt = build_builder_prompt(job.prompt)
        result = await run_claude(
            prompt,
            cwd=workspace_path,
            timeout=settings.builder_timeout_seconds,
            allow_permissions=True,
            model=settings.builder_model,
        )

        # Step 3: Scan workspace for created artifacts
        await update_job_progress(
            session,
            job.id,
            current_step="scanning",
            progress_message="Scanning workspace artifacts",
            iteration_count=3,
        )

        fs_artifacts = scan_workspace_artifacts(workspace_path)
        logger.info("Builder job %s: found %d files in workspace", job.id, len(fs_artifacts))

        # Step 4: Parse manifest file, fall back to CLI output, then filesystem scan
        builder_result = _extract_builder_result(workspace_path, result, fs_artifacts)
        preview = _build_preview(builder_result)
        result_json = builder_result.model_dump_json()

        await finalize_job(
            session,
            job.id,
            status=JobStatus.SUCCEEDED,
            result_preview=preview,
            result_data=result_json,
        )

        # Update workspace_path on the job row
        from sqlalchemy import update as sa_update

        await session.execute(
            sa_update(JobRow).where(JobRow.id == job.id).values(workspace_path=workspace_path)
        )
        await session.commit()

        logger.info(
            "Builder job %s completed: %d artifacts",
            job.id,
            len(builder_result.artifacts),
        )

    except ClaudeTimeoutError:
        logger.warning("Builder job %s timed out", job.id)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=f"Build timed out after {settings.builder_timeout_seconds}s",
            stop_reason=JobStopReason.TIMEOUT.value,
        )

    except ClaudeRunError as e:
        logger.error("Builder job %s failed — Claude error: %s", job.id, e)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=f"Claude Code error: {e}",
            stop_reason=JobStopReason.ERROR.value,
        )

    except Exception as e:
        logger.exception("Builder job %s failed unexpectedly", job.id)
        await finalize_job(
            session,
            job.id,
            status=JobStatus.FAILED,
            error_message=str(e),
            stop_reason=JobStopReason.ERROR.value,
        )


def _extract_builder_result(
    workspace_path: str, claude_output: dict, fs_artifacts: list[dict]
) -> BuilderResult:
    """Extract BuilderResult from manifest file, CLI output, or filesystem scan.

    Priority:
    1. arlo_manifest.json file in workspace (most reliable)
    2. Claude CLI JSON output
    3. Filesystem scan fallback
    """
    # Try 1: Read arlo_manifest.json from workspace
    manifest_path = Path(workspace_path) / "arlo_manifest.json"
    if manifest_path.exists():
        try:
            content = json.loads(manifest_path.read_text())
            result = BuilderResult.model_validate(content)
            logger.info("Parsed builder result from arlo_manifest.json")
            return result
        except Exception as e:
            logger.warning("Failed to parse arlo_manifest.json: %s", e)

    # Try 2: Parse from Claude CLI JSON output
    content = claude_output.get("result", claude_output)
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
            content = None

    if isinstance(content, dict):
        try:
            result = BuilderResult.model_validate(content)
            logger.info("Parsed builder result from CLI output")
            return result
        except Exception:
            pass

    # Try 3: Fall back to filesystem scan
    logger.info("Falling back to filesystem scan for builder result")
    return _result_from_filesystem(fs_artifacts)


def _result_from_filesystem(fs_artifacts: list[dict]) -> BuilderResult:
    """Build a BuilderResult purely from the filesystem scan."""
    artifacts = [
        BuilderArtifact(
            path=a["path"],
            artifact_type="directory" if a["is_dir"] else "file",
            description="",
        )
        for a in fs_artifacts
        if not a["is_dir"]  # only list files
    ]
    return BuilderResult(
        summary=f"Built project with {len(artifacts)} files (parsed from filesystem scan)",
        artifacts=artifacts,
        build_commands_run=[],
        notes="Claude output could not be parsed as structured JSON. Artifact list generated from filesystem scan.",
    )


def _build_preview(result: BuilderResult) -> str:
    """Build a short human-readable preview from a builder result."""
    lines = [result.summary]
    file_count = sum(1 for a in result.artifacts if a.artifact_type != "directory")
    lines.append(f"{file_count} files created.")
    if result.notes:
        lines.append(f"Notes: {result.notes[:200]}")
    return "\n".join(lines)
