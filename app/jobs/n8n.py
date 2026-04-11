"""Executor for ``job_type == "n8n"`` jobs.

Round 4 rewrite: the previous implementation relied on two mistakes
that together made the side hustle pipeline's deploy + test_run steps
fail in production:

1. **Prompt-embedded previous-step results.** The step templates
   interpolated ``{build_result}`` and ``{deploy_result}`` via
   ``str.format_map`` into a JSON instruction blob. When the build
   result contained any quote or backslash, the resulting prompt
   was no longer valid JSON and this executor died with "n8n job
   prompt is not valid JSON." Fix: the executor now reads previous
   step results directly from the database (``JobRow.result_data``)
   looked up by ``workflow_id`` + job_type. Templates become small
   static JSON like ``{"action": "create", "from_previous_build": true}``
   with no substitution at all.

2. **Non-existent execute endpoint.** The old code called
   ``POST /api/v1/workflows/{id}/run`` which never existed in
   n8n's public REST API. The only externally-triggerable path is
   via a Webhook trigger node inside the workflow + a direct call
   to ``{base}/webhook/{path}``. Fix: the deploy step now extracts
   the webhook URL from the workflow JSON and records it in its
   ``result_data``. The test step reads the webhook URL back out,
   loads ``test_payload.json`` from the builder's workspace, and
   POSTs it to the webhook via ``N8nClient.trigger_webhook``.

The high-level step orchestration (parse instructions → maybe create
→ maybe activate → maybe execute → finalize) is unchanged. Only the
"how each phase talks to n8n" layer moved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow
from app.models.job import JobStatus, JobStopReason
from app.services.job_service import finalize_job, update_job_progress
from app.tools.n8n import (
    N8nAPIError,
    N8nClient,
    N8nTimeoutError,
    N8nUnknownStatusError,
    _normalize_execution_status,
)

logger = logging.getLogger("arlo.jobs.n8n")


# Round 5.A3: knobs for the "wait for the execution row to appear"
# loop after trigger_webhook returns 2xx. n8n's default webhook
# responseMode is "onReceived", which queues the execution and
# returns immediately — so we have to poll list_executions to find
# the newly created row before polling it to terminal status.
# The original Round 4 values (3 retries × 1s = ~3s total) were
# too tight for an n8n instance under load; silently reported
# "success" based on webhook 2xx alone. Doubled to 6 retries so the
# loop gives n8n ~6s to persist the row before giving up.
_POLL_EXECUTION_ROW_RETRIES = 6
_POLL_EXECUTION_ROW_DELAY = 1.0


def _sanitize_for_json(obj, _seen: set[int] | None = None):
    """Round 5.A4: defensive pass to coerce any non-JSON-serializable
    values to str so the finalize step never crashes on exotic webhook
    responses.

    Walks dicts and lists, leaves primitives alone, stringifies unknown
    types. Prevents ``json.dumps(result)`` from raising TypeError when
    a webhook response contains values like ``datetime``, ``Decimal``,
    ``bytes``, or custom objects that slipped through httpx's ``.json()``
    parser.

    This is called only from the fallback path of the finalize step —
    if the initial ``json.dumps(result)`` succeeds, we never walk the
    result dict. That keeps the happy path cheap.

    Round 6.A3: ``_seen`` is a set of container ``id()`` values walked
    on the current branch. If a container is encountered twice (a
    cycle), it's replaced with the string ``"<circular reference>"``
    instead of recursing forever and blowing the Python stack with a
    RecursionError. The original Round 5 implementation didn't track
    visited objects, so a webhook response with a self-reference (e.g.
    ``r = {}; r["self"] = r``) would crash the executor with an opaque
    error that escapes the TypeError handler in finalize.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if _seen is None:
        _seen = set()
    obj_id = id(obj)
    if obj_id in _seen:
        return "<circular reference>"

    if isinstance(obj, dict):
        _seen.add(obj_id)
        try:
            return {
                str(k): _sanitize_for_json(v, _seen) for k, v in obj.items()
            }
        finally:
            _seen.discard(obj_id)
    if isinstance(obj, (list, tuple)):
        _seen.add(obj_id)
        try:
            return [_sanitize_for_json(v, _seen) for v in obj]
        finally:
            _seen.discard(obj_id)
    return str(obj)


def _extract_execution_status(execution: dict) -> str:
    """Thin wrapper around ``_normalize_execution_status`` that also
    coerces any non-success status into ``error`` for the side hustle
    test step's boolean success/failure contract. Used only by
    ``execute_n8n_job``."""
    raw = _normalize_execution_status(execution)
    return raw if raw == "success" else "error"


async def execute_n8n_job(session: AsyncSession, job: JobRow) -> None:
    """Execute an n8n job: create, activate, and/or trigger a workflow.

    The job's prompt is a small static JSON instruction blob:

    .. code-block:: json

        {
          "action": "create|execute|create_and_execute",
          "activate": true|false,
          "from_previous_build": true|false,
          "from_previous_deploy": true|false,
          "workflow_json": {...} | null,
          "n8n_workflow_id": "..." | null,
          "webhook_url": "..." | null,
          "execution_data": {...} | null
        }

    ``from_previous_build=true`` tells the executor to find the most
    recent builder job in the same workflow and extract workflow_json
    from its result_data. ``from_previous_deploy=true`` does the same
    for the most recent n8n deploy result, pulling out n8n_workflow_id
    and webhook_url. These replace the old template-interpolated
    ``{build_result}`` and ``{deploy_result}`` placeholders that
    corrupted the prompt JSON on any quote/backslash in the result.
    """
    client = N8nClient()

    try:
        # Parse the instruction JSON
        try:
            instructions = json.loads(job.prompt)
        except json.JSONDecodeError as e:
            raise ValueError(f"n8n job prompt is not valid JSON: {e}")

        action = instructions.get("action", "create")
        activate = instructions.get("activate", False)
        execution_data = instructions.get("execution_data")

        # Resolve workflow_json: inline override > previous build step
        workflow_json = instructions.get("workflow_json")
        if not workflow_json and instructions.get("from_previous_build"):
            workflow_json = await _read_workflow_from_previous_build(session, job)

        # Resolve n8n_workflow_id + webhook_url: inline override > previous deploy step
        n8n_workflow_id = instructions.get("n8n_workflow_id")
        webhook_url = instructions.get("webhook_url")
        if instructions.get("from_previous_deploy"):
            prev_deploy = await _read_previous_deploy_result(session, job)
            if prev_deploy:
                n8n_workflow_id = n8n_workflow_id or prev_deploy.get("n8n_workflow_id")
                webhook_url = webhook_url or prev_deploy.get("webhook_url")

        result: dict = {}

        # ─── Create phase ───
        if action in ("create", "create_and_execute"):
            if not workflow_json:
                raise ValueError(
                    "Cannot create: no workflow_json available. Either inline "
                    "workflow_json in the instructions or set from_previous_build=true "
                    "and ensure a builder step ran earlier in the workflow."
                )

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

            # Extract the webhook URL from the workflow JSON now so the
            # test step (and any downstream consumer) can find it by
            # reading this job's result_data. Doing it here means we
            # don't have to re-parse the workflow later.
            extracted = N8nClient.extract_webhook_url_from_workflow(
                workflow_json, base_url=settings.n8n_base_url
            )
            if extracted:
                result["webhook_url"] = extracted
                logger.info("n8n job %s: webhook URL %s", job.id, extracted)
            else:
                logger.warning(
                    "n8n job %s: no webhook trigger node found in workflow — "
                    "the test_run step will not be able to execute this workflow",
                    job.id,
                )

        # ─── Activate phase ───
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

        # ─── Execute phase ───
        if action in ("execute", "create_and_execute"):
            if not webhook_url:
                raise ValueError(
                    "Cannot execute: no webhook URL available. The workflow "
                    "must have a Webhook trigger node and the deploy step "
                    "must have stored its URL in result_data. Check the "
                    "workflow's node list for a n8n-nodes-base.webhook node."
                )

            # Resolve the payload: inline override > test_payload.json
            # in the builder's workspace > empty dict.
            payload = execution_data
            if payload is None:
                payload = await _read_test_payload_from_previous_build(session, job)
            if payload is None:
                payload = {}
                logger.info(
                    "n8n job %s: no test_payload.json found; triggering with empty body",
                    job.id,
                )

            await update_job_progress(
                session,
                job.id,
                current_step="triggering",
                progress_message=f"Triggering webhook {webhook_url}",
                iteration_count=3,
            )

            webhook_response = await client.trigger_webhook(webhook_url, payload)
            result["webhook_url"] = webhook_url
            result["webhook_response"] = webhook_response
            result["webhook_status_code"] = webhook_response.get("_status_code")

            # Phase 0 finding: n8n's default webhook responseMode is
            # "onReceived", which returns
            # ``{"message": "Workflow was started"}`` immediately once
            # the webhook queues the execution — BEFORE the workflow
            # has actually run. A 2xx on the webhook only means "n8n
            # accepted the request", not "the workflow succeeded".
            #
            # To get the real execution result we must poll the
            # execution row that n8n just created. We give it up to
            # ~3 seconds to appear, then poll its status to terminal.
            status_code = webhook_response.get("_status_code") or 0
            if not (200 <= status_code < 300):
                result["execution_status"] = "error"
            elif n8n_workflow_id:
                # Look up the newly created execution row and poll it
                # to completion. Round 5.A3: bumped from 3 retries
                # to _POLL_EXECUTION_ROW_RETRIES with better logging
                # and a new `execution_verification` audit field.
                await asyncio.sleep(_POLL_EXECUTION_ROW_DELAY)
                execution = None
                for attempt in range(_POLL_EXECUTION_ROW_RETRIES):
                    execution = await client.get_latest_execution_for_workflow(
                        n8n_workflow_id
                    )
                    if execution:
                        break
                    logger.debug(
                        "n8n job %s: execution row not yet visible for "
                        "workflow %s (attempt %d/%d)",
                        job.id, n8n_workflow_id,
                        attempt + 1, _POLL_EXECUTION_ROW_RETRIES,
                    )
                    await asyncio.sleep(_POLL_EXECUTION_ROW_DELAY)

                if execution is None:
                    total_wait = (
                        _POLL_EXECUTION_ROW_RETRIES * _POLL_EXECUTION_ROW_DELAY
                    )
                    logger.warning(
                        "n8n job %s: webhook accepted but no execution row "
                        "found for workflow %s within %.0fs — falling back "
                        "to webhook-2xx-only success. The actual execution "
                        "result was NOT verified.",
                        job.id, n8n_workflow_id, total_wait,
                    )
                    result["execution_status"] = "success"
                    result["execution_verification"] = "webhook_2xx_only"
                else:
                    exec_id = execution.get("id")
                    if exec_id is None:
                        result["execution_status"] = "success"
                        result["execution_verification"] = "webhook_2xx_only"
                    else:
                        # Live progress: throttled 5s updates during the poll.
                        progress_state = {
                            "last_update": 0.0,
                            "start": time.monotonic(),
                        }

                        async def execution_progress_cb(snapshot: dict) -> None:
                            now = time.monotonic()
                            if now - progress_state["last_update"] < 5.0:
                                return
                            progress_state["last_update"] = now
                            elapsed = int(now - progress_state["start"])
                            try:
                                await update_job_progress(
                                    session,
                                    job.id,
                                    progress_message=(
                                        f"Polling execution {exec_id} "
                                        f"({elapsed}s elapsed, "
                                        f"status: {snapshot.get('status', 'running')})"
                                    ),
                                )
                            except Exception:
                                logger.exception(
                                    "n8n execution progress_cb failed; continuing"
                                )

                        try:
                            terminal = await client.poll_execution(
                                str(exec_id),
                                on_progress=execution_progress_cb,
                            )
                            result["execution_id"] = str(exec_id)
                            result["execution"] = terminal
                            normalized = _extract_execution_status(terminal)
                            result["execution_status"] = normalized
                            # Round 5.A3: audit field distinguishes a
                            # verified-via-polling success from the
                            # webhook-2xx-only fallback case.
                            result["execution_verification"] = "execution_polled"
                        except N8nTimeoutError as e:
                            # Execution exceeded the poll timeout. Record
                            # the state and treat as an error so the
                            # workflow's auto-retry can kick in.
                            result["execution_id"] = str(exec_id)
                            result["execution_status"] = "error"
                            result["execution_verification"] = "poll_timeout"
                            logger.warning(
                                "n8n job %s: execution %s poll timed out: %s",
                                job.id, exec_id, e,
                            )
                        except N8nUnknownStatusError as e:
                            # Round 5.A6: n8n returned an unrecognized
                            # status repeatedly. Surface as an error so
                            # auto-retry fires AND log a clear diagnostic
                            # so the operator knows to update the
                            # _normalize_execution_status helper.
                            result["execution_id"] = str(exec_id)
                            result["execution_status"] = "error"
                            result["execution_verification"] = "unknown_status"
                            logger.error(
                                "n8n job %s: execution %s returned "
                                "unrecognized status: %s",
                                job.id, exec_id, e,
                            )
            else:
                # No workflow id to look up — best we can do is trust
                # the webhook's 2xx.
                result["execution_status"] = "success"

        # ─── Finalize ───
        # Round 5.A4: wrap json.dumps in try/except TypeError so a
        # webhook response containing exotic types (datetime, Decimal,
        # bytes, custom objects) doesn't crash the executor. The
        # happy path skips the sanitizer entirely; the fallback walks
        # the result dict and str()-ifies anything non-primitive.
        try:
            result_json = json.dumps(result)
        except TypeError as e:
            logger.warning(
                "n8n job %s: result contained non-serializable "
                "values, coercing to str: %s",
                job.id, e,
            )
            try:
                result_json = json.dumps(_sanitize_for_json(result))
            except Exception as sanitize_exc:
                # Round 6.A4: the sanitizer itself failed (an exotic
                # __str__ raised, a circular ref slipped through, etc).
                # Without this guard the exception would escape to the
                # outer ``except Exception`` handler at the bottom of
                # the function, which reports a generic "n8n job failed
                # unexpectedly" — losing the actual diagnostic context.
                # Last-ditch fallback: emit a minimal valid JSON blob
                # that preserves the original TypeError + the sanitizer
                # error so an operator can diagnose via logs/result_data.
                logger.error(
                    "n8n job %s: sanitizer also failed (%s: %s); "
                    "storing minimal result_data so finalize can proceed",
                    job.id, type(sanitize_exc).__name__, sanitize_exc,
                )
                result_json = json.dumps({
                    "_sanitizer_failed": True,
                    "_original_error": str(e)[:500],
                    "_sanitizer_error": str(sanitize_exc)[:500],
                    "execution_status": result.get("execution_status", "error"),
                })
        preview = _build_preview(result)

        # If the execute phase ran and returned a non-2xx, fail the job
        # so the workflow doesn't progress past a broken test run.
        if result.get("execution_status") == "error":
            await finalize_job(
                session,
                job.id,
                status=JobStatus.FAILED,
                result_preview=preview,
                result_data=result_json,
                error_message=(
                    f"Webhook returned {result.get('webhook_status_code')}; "
                    f"see result_data.webhook_response for details"
                ),
                stop_reason=JobStopReason.ERROR.value,
            )
            logger.warning(
                "n8n job %s webhook returned %d",
                job.id, result.get("webhook_status_code"),
            )
            return

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
            error_message=f"n8n timed out: {e}",
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


# ─────────────────────────────────────────────────────────────────────
# Previous-step data lookups (replaces {build_result} interpolation)
# ─────────────────────────────────────────────────────────────────────


async def _find_previous_job_by_type(
    session: AsyncSession,
    current_job: JobRow,
    job_type: str,
) -> JobRow | None:
    """Find the most recent completed job of ``job_type`` in the same
    workflow as ``current_job``. Returns None if not found.

    Walks by ``workflow_id`` + ``step_index < current_job.step_index``
    + ``job_type == job_type``, ordered by created_at descending.
    """
    if current_job.workflow_id is None or current_job.step_index is None:
        return None

    stmt = (
        select(JobRow)
        .where(
            JobRow.workflow_id == current_job.workflow_id,
            JobRow.step_index < current_job.step_index,
            JobRow.job_type == job_type,
            JobRow.status == JobStatus.SUCCEEDED.value,
        )
        .order_by(JobRow.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def _read_workflow_from_previous_build(
    session: AsyncSession, job: JobRow
) -> dict | None:
    """Find the most recent builder job in the same workflow and pull
    the n8n workflow JSON from it.

    Three strategies in order:
    1. Parse the builder's ``result_data`` and look for an
       ``arlo_manifest.json`` style payload with a ``workflow_json`` key.
    2. Fall back to the legacy ``_extract_workflow_json_from_build``
       for backward compatibility with older builders.
    3. Fall back to ``_read_workflow_from_workspace`` which reads
       ``workflow.json`` directly off disk.
    """
    builder_job = await _find_previous_job_by_type(session, job, "builder")
    if builder_job is None:
        logger.warning(
            "n8n job %s: no successful builder job found in workflow %s",
            job.id, job.workflow_id,
        )
        return None

    # 1. Try the result_data JSON
    if builder_job.result_data:
        wf = _extract_workflow_json_from_build(builder_job.result_data)
        if wf is not None:
            return wf

    # 2. Fall back to reading workflow.json off disk
    if builder_job.workspace_path:
        wf = _read_workflow_from_workspace_path(builder_job.workspace_path)
        if wf is not None:
            return wf

    logger.warning(
        "n8n job %s: builder job %s has neither workflow_json in "
        "result_data nor a readable workflow.json in the workspace",
        job.id, builder_job.id,
    )
    return None


async def _read_previous_deploy_result(
    session: AsyncSession, job: JobRow
) -> dict | None:
    """Find the most recent n8n deploy job in the same workflow and
    return its parsed ``result_data`` dict (containing n8n_workflow_id,
    webhook_url, etc.).
    """
    deploy_job = await _find_previous_job_by_type(session, job, "n8n")
    if deploy_job is None or not deploy_job.result_data:
        return None
    try:
        return json.loads(deploy_job.result_data)
    except json.JSONDecodeError:
        logger.warning(
            "n8n job %s: previous deploy job %s has unparseable result_data",
            job.id, deploy_job.id,
        )
        return None


async def _read_test_payload_from_previous_build(
    session: AsyncSession, job: JobRow
) -> dict | None:
    """Find the most recent builder job in the same workflow and read
    ``test_payload.json`` from its workspace directory. Returns None
    if the file doesn't exist or can't be parsed as JSON.
    """
    builder_job = await _find_previous_job_by_type(session, job, "builder")
    if builder_job is None or not builder_job.workspace_path:
        return None

    payload_path = Path(builder_job.workspace_path) / "test_payload.json"
    if not payload_path.exists():
        return None
    try:
        return json.loads(payload_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "n8n job %s: failed to read test_payload.json from %s: %s",
            job.id, payload_path, e,
        )
        return None


# ─────────────────────────────────────────────────────────────────────
# Legacy helpers kept for backward compat with older builder output
# ─────────────────────────────────────────────────────────────────────


def _extract_workflow_json_from_build(build_result: str) -> dict | None:
    """Pull n8n workflow JSON out of a builder job's ``result_data``.

    The builder stores its result as a JSON string. Inside that, if the
    builder wrote an ``arlo_manifest.json`` with a ``workflow_json`` key,
    we return the parsed workflow. Otherwise we return None and the
    caller falls back to reading from disk.
    """
    try:
        data = json.loads(build_result) if isinstance(build_result, str) else build_result
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict) and "workflow_json" in data:
        wf = data["workflow_json"]
        if isinstance(wf, str):
            try:
                return json.loads(wf)
            except json.JSONDecodeError:
                return None
        if isinstance(wf, dict):
            return wf

    return None


def _read_workflow_from_workspace_path(workspace_path: str) -> dict | None:
    """Read ``workflow.json`` (or ``n8n-workflow.json``) from the given
    workspace directory. Returns None if not found or unreadable.
    """
    workspace = Path(workspace_path)
    if not workspace.is_dir():
        return None

    for name in ("workflow.json", "n8n-workflow.json"):
        wf_path = workspace / name
        if wf_path.exists():
            try:
                return json.loads(wf_path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("n8n: failed to read %s: %s", wf_path, e)

    # Last resort: recursively search for workflow.json
    for wf_path in workspace.rglob("workflow.json"):
        try:
            return json.loads(wf_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("n8n: failed to read %s: %s", wf_path, e)

    return None


# ─────────────────────────────────────────────────────────────────────
# Preview builder
# ─────────────────────────────────────────────────────────────────────


def _build_preview(result: dict) -> str:
    """Build a short human-readable preview from an n8n job result."""
    parts: list[str] = []
    if result.get("n8n_workflow_id"):
        parts.append(f"Workflow: {result['n8n_workflow_id']}")
    if result.get("n8n_workflow_name"):
        parts.append(f"({result['n8n_workflow_name']})")
    if result.get("activated"):
        parts.append("— activated")
    if result.get("webhook_url"):
        parts.append(f"— webhook: {result['webhook_url']}")
    if result.get("execution_status"):
        parts.append(f"— execution: {result['execution_status']}")
    return " ".join(parts) if parts else "n8n job completed"
