from __future__ import annotations

import json
import logging
import re
import time

from pydantic import BaseModel, ValidationError
from sqlalchemy import update
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


# Round 5.5 hotfix: Claude often prefixes its JSON response with English
# explanation ("Now I have sufficient data... Let me compile..."), and
# sometimes wraps the JSON in a ```json fence with content before AND after.
# The previous code only handled fences at the start/end of the string, so
# any preamble text broke parsing. This regex finds the first fenced block
# anywhere in the string. The (?s) flag makes . match newlines.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

# Round 5.6 hotfix: Claude regularly emits trailing commas (`{"a": 1,}`)
# and JS-style line/block comments in deep JSON outputs. These are valid
# JavaScript but invalid JSON, and json.loads chokes with errors like
# "Expecting property name enclosed in double quotes" deep in the file.
# These two regexes strip those forms safely WITHOUT touching string
# contents (we walk the string character-by-character to skip anything
# inside double quotes).
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _build_parse_error_window(text: str, pos: int, radius: int = 120) -> str:
    """Round 6 followup: build a human-readable diagnostic showing what
    surrounds the JSON parse error position.

    Returns a one-line description that classifies the error as either
    truncation (parse position is within ``radius`` of the end) or a
    mid-document parse failure, and includes the actual characters
    immediately before the error position so the operator can see
    whether Claude wrote a half-string, a trailing comma, or simply
    stopped writing.
    """
    if not text:
        return "Window: <empty>"
    total = len(text)
    pos = max(0, min(pos, total))
    distance_from_end = total - pos
    is_truncation = distance_from_end <= radius

    start = max(0, pos - radius)
    end = min(total, pos + radius)
    before = text[start:pos].replace("\n", "\\n")
    after = text[pos:end].replace("\n", "\\n")

    classification = (
        f"LIKELY TRUNCATION ({distance_from_end} chars from end of {total})"
        if is_truncation
        else f"mid-document parse error ({distance_from_end} chars from end of {total})"
    )
    return (
        f"{classification} | "
        f"...{before!r} <<HERE>> {after!r}..."
    )


def _sanitize_json_payload(payload: str) -> str:
    """Strip Claude's JS-isms from an extracted JSON payload.

    Two transformations applied OUTSIDE of string literals only:
    1. Trailing commas before ``}`` or ``]`` are removed.
    2. ``// line comments`` and ``/* block comments */`` are removed.

    String contents are preserved exactly because we walk the payload
    character-by-character and only modify the regions outside double-
    quoted strings. A naive ``re.sub`` over the whole string would
    corrupt legitimate apostrophes, URLs, and forward slashes inside
    string values (e.g. ``"price": "$9 // unit"``).
    """
    # Build a list of (start, end) ranges that are INSIDE string literals
    # so we can skip them when applying the regexes.
    string_ranges: list[tuple[int, int]] = []
    in_string = False
    escape = False
    string_start = 0
    for i, ch in enumerate(payload):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            if in_string:
                string_ranges.append((string_start, i + 1))
                in_string = False
            else:
                in_string = True
                string_start = i

    def _in_string(pos: int) -> bool:
        for s, e in string_ranges:
            if s <= pos < e:
                return True
            if pos < s:
                return False
        return False

    # Apply each regex but skip matches that fall inside string literals.
    def _strip(pattern: re.Pattern, replacement: str, text: str) -> str:
        # Recompute string_ranges after each pass since indices shift.
        result_parts: list[str] = []
        last_end = 0
        for m in pattern.finditer(text):
            if _in_string(m.start()):
                continue
            result_parts.append(text[last_end:m.start()])
            result_parts.append(m.expand(replacement))
            last_end = m.end()
        result_parts.append(text[last_end:])
        return "".join(result_parts)

    # Strip block comments first (they can span multiple lines and contain
    # // sequences that the line-comment regex would otherwise mishandle).
    payload = _strip(_BLOCK_COMMENT_RE, "", payload)
    # Recompute string ranges since the payload changed.
    string_ranges = []
    in_string = False
    escape = False
    string_start = 0
    for i, ch in enumerate(payload):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            if in_string:
                string_ranges.append((string_start, i + 1))
                in_string = False
            else:
                in_string = True
                string_start = i

    payload = _strip(_LINE_COMMENT_RE, "", payload)
    # Recompute again before trailing comma pass.
    string_ranges = []
    in_string = False
    escape = False
    string_start = 0
    for i, ch in enumerate(payload):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            if in_string:
                string_ranges.append((string_start, i + 1))
                in_string = False
            else:
                in_string = True
                string_start = i

    payload = _strip(_TRAILING_COMMA_RE, r"\1", payload)
    return payload


def _extract_json_payload(content: str) -> str:
    """Pull a JSON object out of Claude's response, ignoring preamble text.

    Strategy in order of preference:
    1. Find the first ```json...``` (or ```...```) fenced block. Most
       reliable because it's how Claude is told to format JSON output.
    2. Find the first balanced ``{...}`` substring as a fallback. Handles
       cases where Claude forgets the fence entirely.
    3. Return the original (stripped) content. JSON parsing will then
       fail with a clear error and the auto-retry path kicks in.

    Round 5.6: in all three paths, the extracted payload is then
    sanitized to strip Claude's JS-isms (trailing commas, line/block
    comments). See ``_sanitize_json_payload``.
    """
    cleaned = content.strip()

    # 1. Try to find a fenced JSON block anywhere in the string
    match = _JSON_FENCE_RE.search(cleaned)
    if match:
        return _sanitize_json_payload(match.group(1).strip())

    # 2. No fence — try to find the first balanced { ... } block.
    # Walk character-by-character tracking brace depth, ignoring braces
    # inside strings. This handles preamble text before a bare JSON object.
    start = cleaned.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return _sanitize_json_payload(cleaned[start:i + 1])

    # 3. Last resort: return what we have. Will fail JSON parsing
    # with a clear error and trigger the auto-retry path.
    return _sanitize_json_payload(cleaned)


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

        # Round 4: throttled streaming progress callback. Updates the
        # JobRow's progress_message and live token/cost columns at most
        # every 5 seconds while Claude is generating output. The existing
        # /workflows/{id}/stream SSE endpoint surfaces these updates so
        # the user sees real progress instead of "researching..." for 30 min.
        progress_state = {"last_update": 0.0}

        async def progress_cb(snapshot: dict) -> None:
            now = time.monotonic()
            if now - progress_state["last_update"] < 5.0:
                return
            progress_state["last_update"] = now
            chars = snapshot.get("accumulated_chars", 0)
            usage = snapshot.get("usage") or {}
            model = snapshot.get("model")
            tool_activity = snapshot.get("tool_activity")  # Round 5
            output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0
            # Round 5: prepend tool activity (e.g. "Using WebSearch") to
            # the progress message when present, so the user sees what
            # Claude is actually doing during long research runs.
            activity_prefix = f"{tool_activity} — " if tool_activity else ""
            try:
                await update_job_progress(
                    session,
                    job.id,
                    progress_message=(
                        f"{activity_prefix}Streaming output "
                        f"({chars:,} chars, {output_tokens} tokens out)"
                    ),
                )
                if usage:
                    partial = extract_usage({"usage": usage, "model": model})
                    if partial["input_tokens"] is not None:
                        await session.execute(
                            update(JobRow).where(JobRow.id == job.id).values(
                                tokens_input=partial["input_tokens"],
                                tokens_output=partial["output_tokens"],
                                estimated_cost_usd=partial["estimated_cost_usd"],
                            )
                        )
                        await session.commit()
            except Exception:
                # Never let progress updates kill the run
                logger.exception("research progress_cb failed; continuing")

        result = await run_claude(
            prompt,
            allow_permissions=True,
            model=settings.research_model,
            timeout=timeout_override,
            on_progress=progress_cb,
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
        cleaned = _extract_json_payload(content)

        try:
            # Round 5.6: strict=False allows unescaped control characters
            # (literal \n, \t, etc.) inside string values. Claude regularly
            # writes multi-line descriptions as actual newlines instead of
            # \\n escape sequences, which strict JSON rejects. Production
            # failure was "Invalid control character at line 155 column
            # 109 (char 20794)" in a deep_dive opportunity's description.
            content = json.loads(cleaned, strict=False)
        except json.JSONDecodeError as e:
            # Round 6 followup: include a window AROUND the parse error
            # position so truncation is instantly diagnosable. Without
            # this, the error message only showed the first 200 chars
            # which is useless when a 33k-char output gets truncated
            # at char 33,226. Knowing whether the failure is at the
            # very end (truncation) vs. mid-string (escaping bug) tells
            # us whether to bump tokens or fix the prompt.
            error_window = _build_parse_error_window(cleaned, e.pos)
            if raw_mode and schema_cls is not None:
                # Strict mode: JSON parse failure is a hard error
                raise ClaudeRunError(
                    f"Output validation failed: response was not valid JSON ({e}). "
                    f"Total length: {len(cleaned)} chars. {error_window} "
                    f"First 200 chars: {cleaned[:200]}"
                ) from e
            if not raw_mode:
                # Standalone mode also expects valid JSON for ResearchReport
                raise ClaudeRunError(
                    f"Output validation failed: response was not valid JSON ({e}). "
                    f"Total length: {len(cleaned)} chars. {error_window} "
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
