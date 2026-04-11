"""Async client for the n8n REST API.

Round 4 rewrite (side hustle pipeline): the previous implementation
used v1-era endpoints that no longer exist in n8n v2.x. This rewrite
targets n8n v2.15.0 specifically. The user-confirmed facts driving the
rewrite:

- The X-N8N-API-KEY header auth works (verified empirically)
- Activation changed from PATCH /workflows/{id} {"active": true} to
  POST /workflows/{id}/activate
- The public REST API has no general-purpose "execute this workflow"
  endpoint. External execution must go through a Webhook trigger node
  inside the workflow + a direct HTTP POST to {base}/webhook/{path}
- Execution response shape in v2 may differ from v1

Several endpoint paths in this file are marked ``TODO(phase0)`` because
they're educated guesses based on n8n v2 conventions rather than
verified against the running instance. Phase 0 of the Round 4 plan
(empirical curl probe) will verify each one before deployment. Until
then, assume any TODO(phase0) line may need to change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("arlo.tools.n8n")


# ─────────────────────────────────────────────────────────────────────
# Default timeouts. Overridable per call via the ``timeout=`` kwarg.
# ─────────────────────────────────────────────────────────────────────

_DEFAULT_GET_TIMEOUT = 5.0       # Reads and polls should be fast
_DEFAULT_POST_TIMEOUT = 60.0     # State-changing requests get more room
_DEFAULT_WEBHOOK_TIMEOUT = 30.0  # Webhook triggers are bounded by the workflow

# Retry-with-backoff tuning. One retry by default: the first request
# might hit a transient 5xx or connection reset, but two in a row is
# almost always a persistent problem that more retries won't fix.
_DEFAULT_RETRIES = 1
_DEFAULT_RETRY_DELAY = 2.0

# Progress callback type — mirrors the ProgressCallback type alias in
# claude_runner.py. Receives a snapshot dict; implementations should
# handle their own throttling.
N8nProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


# ─────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────


class N8nError(Exception):
    """Base error for n8n operations."""


class N8nTimeoutError(N8nError):
    """Raised when an n8n execution or HTTP request exceeds its timeout."""


class N8nAPIError(N8nError):
    """Raised when the n8n API returns an error status."""

    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class N8nWorkflowValidationError(N8nError):
    """Raised when a workflow JSON fails structural validation.

    Round 3: this is raised by ``N8nClient.validate_workflow_json`` and
    caught by ``app/jobs/builder.py``, which wraps it in
    ``ClaudeRunError`` to feed the auto-retry path. The error message
    always points at a specific field path (e.g.
    ``workflow.nodes[2].parameters.path``) so Claude's next attempt
    has a clear target.
    """


# ─────────────────────────────────────────────────────────────────────
# Status normalization
# ─────────────────────────────────────────────────────────────────────


# Terminal statuses — the poll loop returns when it sees any of these.
_TERMINAL_STATUSES = frozenset({"success", "error", "failed", "canceled", "crashed"})
# Success statuses — used by callers to decide if the run was OK.
_SUCCESS_STATUSES = frozenset({"success"})


def _normalize_execution_status(execution: dict[str, Any]) -> str:
    """Collapse n8n's version-specific execution status fields into a
    stable set: ``success | error | waiting | running | unknown``.

    n8n's execution JSON has changed shape across versions:
    - v0.x returned ``status: success|error|crashed``
    - v1.x added ``finished: bool`` alongside status
    - v2.x (our target) uses ``status`` with values varying by release

    This helper tries multiple paths and falls back to ``unknown``. The
    ``finished`` field is used as a tiebreaker — if it's set to true
    and the status field is missing or unknown, we treat the run as a
    success so the poll loop terminates.

    TODO(phase0): verify the actual v2.15.0 execution response shape
    and simplify this helper to match. Right now it's defensively
    trying multiple shapes.
    """
    if not isinstance(execution, dict):
        return "unknown"

    raw_status = (execution.get("status") or "").lower().strip()

    # Normalize common aliases
    if raw_status in ("success", "succeeded", "completed"):
        return "success"
    if raw_status in ("error", "failed", "crashed", "canceled", "cancelled"):
        return "error"
    if raw_status in ("waiting", "new"):
        return "waiting"
    if raw_status in ("running", "in_progress", "processing"):
        return "running"

    # Fallback via the finished boolean
    finished = execution.get("finished")
    if finished is True:
        # Finished but no recognizable status → probably success
        return "success"
    if finished is False:
        return "running"

    return "unknown"


def _status_is_terminal(status: str) -> bool:
    return status in _TERMINAL_STATUSES or status == "success"


# ─────────────────────────────────────────────────────────────────────
# N8nClient
# ─────────────────────────────────────────────────────────────────────


class N8nClient:
    """Async client for the n8n REST API (v2.15.0 target).

    All state-changing methods go through ``_request`` which supports
    per-call timeouts and retry-with-backoff. Read-only methods
    (list, get) use a shorter default timeout.

    Auth: X-N8N-API-KEY header, populated from ``settings.n8n_api_key``.
    User has verified this header works against their running v2.15.0
    instance.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self._base_url = (base_url or settings.n8n_base_url).rstrip("/")
        self._api_key = api_key or settings.n8n_api_key
        self._headers = {
            "X-N8N-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

    # ─────────────────────────────────────────────────────────────
    # Core request helper
    # ─────────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        timeout: float | None = None,
        retries: int = _DEFAULT_RETRIES,
        retry_delay: float = _DEFAULT_RETRY_DELAY,
        expect_json: bool = True,
    ) -> dict | list | None:
        """HTTP request with per-call timeout and retry-with-backoff.

        Retries only on 5xx status codes and connection-level errors
        (timeout, connect error, read error). 4xx errors are raised
        immediately as ``N8nAPIError`` — retrying a 400 won't help.

        Args:
            method: HTTP verb (GET, POST, PATCH, DELETE)
            path: Path relative to the base URL (e.g. "/api/v1/workflows")
            json: Optional JSON body
            timeout: Per-request timeout in seconds. Defaults based on
                method: 5s for GET, 60s for POST/PATCH/DELETE.
            retries: Number of retry attempts on transient errors.
            retry_delay: Seconds to wait between retries.
            expect_json: If True (default), parses and returns the
                response body as JSON. If False, returns None (useful
                for DELETE which often returns 204 No Content).

        Raises:
            N8nTimeoutError: Request timed out after all retries.
            N8nAPIError: Server returned a 4xx/5xx after all retries.
        """
        if timeout is None:
            timeout = (
                _DEFAULT_GET_TIMEOUT if method.upper() == "GET"
                else _DEFAULT_POST_TIMEOUT
            )

        url = f"{self._base_url}{path}"
        attempt = 0
        last_exc: Exception | None = None

        while attempt <= retries:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(
                        method, url, headers=self._headers, json=json
                    )

                if 500 <= response.status_code < 600:
                    # Retryable server error
                    last_exc = N8nAPIError(
                        f"n8n {method} {path} returned {response.status_code}",
                        status_code=response.status_code,
                        body=response.text[:500],
                    )
                    if attempt < retries:
                        logger.warning(
                            "n8n %s %s returned %d, retrying in %.1fs (%d/%d)",
                            method, path, response.status_code, retry_delay,
                            attempt + 1, retries,
                        )
                        await asyncio.sleep(retry_delay)
                        attempt += 1
                        continue
                    raise last_exc

                if response.status_code >= 400:
                    # Non-retryable client error
                    raise N8nAPIError(
                        f"n8n {method} {path} returned {response.status_code}: "
                        f"{response.text[:500]}",
                        status_code=response.status_code,
                        body=response.text,
                    )

                if not expect_json or not response.content:
                    return None
                return response.json()

            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
                last_exc = e
                if attempt < retries:
                    logger.warning(
                        "n8n %s %s transient error (%s), retrying in %.1fs (%d/%d)",
                        method, path, type(e).__name__, retry_delay,
                        attempt + 1, retries,
                    )
                    await asyncio.sleep(retry_delay)
                    attempt += 1
                    continue
                if isinstance(e, httpx.TimeoutException):
                    raise N8nTimeoutError(
                        f"n8n {method} {path} timed out after {timeout}s"
                    ) from e
                raise N8nAPIError(
                    f"n8n {method} {path} connection error: {e}"
                ) from e

        # Shouldn't reach here, but satisfy the type checker
        if last_exc is not None:
            raise last_exc
        return None

    # ─────────────────────────────────────────────────────────────
    # Workflow CRUD
    # ─────────────────────────────────────────────────────────────

    async def list_workflows(self) -> list[dict]:
        """List all workflows. Returns the ``data`` array from n8n's
        paginated response, or an empty list if the response shape
        is unexpected.

        TODO(phase0): verify v2.15.0 still uses /api/v1/workflows (the
        n8n team has kept v1 as a stable contract across versions, but
        worth confirming).
        """
        result = await self._request("GET", "/api/v1/workflows")
        if isinstance(result, dict):
            return result.get("data", [])
        if isinstance(result, list):
            return result
        return []

    async def create_workflow(self, workflow_json: dict) -> dict:
        """Create a new workflow. Returns the created workflow dict
        including its ``id``.

        Round 4 Phase 0 finding: n8n v2.15.0 **requires** a top-level
        ``settings`` field on the create payload. Posting a workflow
        without one 400s with ``request/body must have required
        property 'settings'``. The build prompt should always include
        it, but we inject an empty settings object here as defense-
        in-depth so clients that forget don't hit an opaque 400.

        See docs/n8n_v2_api_findings.md §2-3 for the full contract.
        """
        # Defense in depth: never let a missing settings field reach
        # the server. The builder prompt also requires it, but if a
        # future caller forgets we'd rather ship an empty object than
        # a 400 the caller can't easily debug.
        if isinstance(workflow_json, dict) and "settings" not in workflow_json:
            workflow_json = {**workflow_json, "settings": {}}

        result = await self._request(
            "POST", "/api/v1/workflows", json=workflow_json
        )
        logger.info("Created n8n workflow: %s", (result or {}).get("id"))
        return result or {}

    async def get_workflow(self, workflow_id: str) -> dict:
        """Get a workflow by ID."""
        result = await self._request("GET", f"/api/v1/workflows/{workflow_id}")
        return result or {}

    async def activate_workflow(self, workflow_id: str) -> dict:
        """Activate a workflow so triggers fire.

        Round 4: the v1-era pattern ``PATCH /workflows/{id}`` body
        ``{"active": true}`` was deprecated in n8n ~v0.218. The current
        contract is ``POST /workflows/{id}/activate``.

        TODO(phase0): verify the exact v2.15.0 path — it may still be
        under /api/v1/ (most likely) or under /api/v2/ (less likely).
        """
        result = await self._request(
            "POST", f"/api/v1/workflows/{workflow_id}/activate"
        )
        logger.info("Activated n8n workflow: %s", workflow_id)
        return result or {}

    async def deactivate_workflow(self, workflow_id: str) -> dict:
        """Deactivate a workflow so triggers stop firing.

        TODO(phase0): verify the exact v2.15.0 path.
        """
        result = await self._request(
            "POST", f"/api/v1/workflows/{workflow_id}/deactivate"
        )
        logger.info("Deactivated n8n workflow: %s", workflow_id)
        return result or {}

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete a workflow.

        Round 4 Phase 0 finding: n8n v2.15.0's DELETE returns 200 with
        the full deleted workflow body (including a ``shared`` array
        with project ownership info), NOT 204 No Content. We accept
        and discard the body via ``expect_json=True``.
        """
        await self._request(
            "DELETE", f"/api/v1/workflows/{workflow_id}"
        )
        logger.info("Deleted n8n workflow: %s", workflow_id)

    # ─────────────────────────────────────────────────────────────
    # Executions
    # ─────────────────────────────────────────────────────────────

    async def get_execution(self, execution_id: str) -> dict:
        """Fetch an execution by ID. The returned dict is passed to
        ``_normalize_execution_status`` by ``poll_execution``; callers
        that just want the status can go through poll_execution.
        """
        result = await self._request(
            "GET", f"/api/v1/executions/{execution_id}"
        )
        return result or {}

    async def list_executions(
        self, workflow_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        """List recent executions, optionally filtered by workflow.

        Used to find the execution that just ran after a webhook
        trigger, since n8n's default webhook response returns
        ``{"message": "Workflow was started"}`` immediately without
        the execution ID.

        Round 4 Phase 0 finding: the response is
        ``{data: [executions], nextCursor: null}``. The
        ``?workflowId=X`` filter was not explicitly probed but is the
        camelCase convention matching the response field name. If
        it's wrong at runtime the list falls through to all executions
        and the caller can filter client-side via the ``workflowId``
        field on each row.
        """
        path = f"/api/v1/executions?limit={limit}"
        if workflow_id:
            path += f"&workflowId={workflow_id}"
        result = await self._request("GET", path)
        if isinstance(result, dict):
            return result.get("data", [])
        if isinstance(result, list):
            return result
        return []

    async def get_latest_execution_for_workflow(
        self, workflow_id: str
    ) -> dict | None:
        """Find the most recent execution for a specific workflow.

        Used by the test_run step: after ``trigger_webhook`` returns
        (which just queues the execution), we need to find the newly
        created execution row and poll it for the real completion
        status. This helper does the lookup.

        The n8n API's ``workflowId`` filter may or may not work
        depending on version — we try it first, then fall back to
        listing all recent executions and filtering client-side.
        Returns None if no execution matching the workflow is found
        (e.g. the webhook was queued but n8n hasn't persisted the
        execution row yet — caller should retry after a short delay).
        """
        # First try the server-side filter
        filtered = await self.list_executions(workflow_id=workflow_id, limit=5)
        if filtered:
            # If the server actually filtered, all rows should match
            for row in filtered:
                if row.get("workflowId") == workflow_id:
                    return row

        # Fallback: grab the last 20 executions and scan client-side
        all_recent = await self.list_executions(limit=20)
        for row in all_recent:
            if row.get("workflowId") == workflow_id:
                return row

        return None

    async def poll_execution(
        self,
        execution_id: str,
        timeout: int | None = None,
        interval: int | None = None,
        on_progress: N8nProgressCallback | None = None,
    ) -> dict:
        """Poll an execution until it reaches a terminal status.

        Calls ``on_progress`` once per poll interval with a snapshot
        dict so callers can update the job's progress_message column.

        Raises ``N8nTimeoutError`` if the execution doesn't terminate
        before the timeout.
        """
        if timeout is None:
            timeout = settings.n8n_execution_timeout_seconds
        if interval is None:
            interval = settings.n8n_poll_interval_seconds

        elapsed = 0
        while elapsed < timeout:
            execution = await self.get_execution(execution_id)
            status = _normalize_execution_status(execution)

            if on_progress is not None:
                snapshot = {
                    "execution_id": execution_id,
                    "elapsed_seconds": elapsed,
                    "status": status,
                }
                try:
                    await on_progress(snapshot)
                except Exception:
                    logger.exception("n8n poll on_progress raised; continuing")

            if _status_is_terminal(status):
                logger.info(
                    "n8n execution %s terminated with status: %s",
                    execution_id, status,
                )
                return execution

            await asyncio.sleep(interval)
            elapsed += interval

        raise N8nTimeoutError(
            f"n8n execution {execution_id} did not finish within {timeout}s"
        )

    # ─────────────────────────────────────────────────────────────
    # Webhook triggering (the new external-execution path)
    # ─────────────────────────────────────────────────────────────

    async def trigger_webhook(
        self,
        webhook_url: str,
        payload: dict | None = None,
        timeout: float = _DEFAULT_WEBHOOK_TIMEOUT,
    ) -> dict:
        """POST to an n8n webhook URL and return the response.

        Round 4: this replaces the non-existent "execute workflow"
        endpoint. In n8n the only externally-triggerable path is via
        a Webhook trigger node. The deploy step extracts the webhook
        URL via ``extract_webhook_url_from_workflow`` and stores it
        in the job result; the test step reads it back out and calls
        this method.

        Returns the response body parsed as JSON, or a dict
        ``{"_raw_body": str, "_status_code": int}`` if the response
        wasn't valid JSON. Never raises on non-2xx; callers can check
        the returned dict's ``_status_code`` key (only present for
        non-JSON responses or errors).
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    webhook_url,
                    json=payload or {},
                    headers={"Content-Type": "application/json"},
                )
        except httpx.TimeoutException as e:
            raise N8nTimeoutError(
                f"Webhook POST to {webhook_url} timed out after {timeout}s"
            ) from e
        except (httpx.ConnectError, httpx.ReadError) as e:
            raise N8nAPIError(
                f"Webhook POST to {webhook_url} connection error: {e}"
            ) from e

        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                parsed["_status_code"] = response.status_code
                return parsed
            return {"_data": parsed, "_status_code": response.status_code}
        except ValueError:
            return {
                "_raw_body": response.text[:2000],
                "_status_code": response.status_code,
            }

    # ─────────────────────────────────────────────────────────────
    # Webhook URL extraction
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def validate_workflow_json(workflow_json: dict) -> None:
        """Validate a workflow dict against n8n v2.15.0's structural contract.

        Round 3 safety net: the builder's ``required_artifacts`` check
        (Round 4) proves ``workflow.json`` EXISTS; this method proves
        it's a VALID n8n workflow. Raises
        ``N8nWorkflowValidationError`` with a specific field path on
        any failure; the builder wraps the exception in
        ``ClaudeRunError`` to trigger the auto-retry path so Claude
        gets another attempt with a clear error message.

        Checks (all required by n8n v2.15.0's create endpoint, or by
        the side hustle test_run step that triggers via webhook):

        - Is a dict with ``nodes``, ``connections``, ``settings`` fields
          (Round 4 Phase 0 empirically verified n8n v2.15.0 rejects
          workflow creation without ``settings`` with a 400)
        - ``nodes`` is a non-empty list
        - Every node has ``id``, ``name``, ``type``, ``parameters``
        - ``type`` is a non-empty string without whitespace
        - Exactly one webhook trigger node (type containing
          ``"webhook"`` but not ``"respond"``) — the test_run step
          requires this to execute the workflow
        - The webhook trigger has ``parameters.path`` as a non-empty
          string so ``extract_webhook_url_from_workflow`` succeeds

        Intentionally minimal. Node-specific parameter validation
        (e.g. whether an HTTP Request node has a valid URL) is n8n's
        job, not ours. The goal is to catch structural problems that
        would make n8n return an opaque 400 during the deploy step.

        Multi-trigger workflows (webhook + schedule) are also
        rejected for now — the side hustle test_run step would pick
        the wrong trigger. Document this limitation if a future
        feature needs to lift it.

        See docs/n8n_v2_api_findings.md §2-3 for the empirical
        contract this mirrors.
        """
        if not isinstance(workflow_json, dict):
            raise N8nWorkflowValidationError(
                f"workflow must be a JSON object, got "
                f"{type(workflow_json).__name__}"
            )

        for field in ("nodes", "connections", "settings"):
            if field not in workflow_json:
                raise N8nWorkflowValidationError(
                    f"workflow missing required top-level field "
                    f"'{field}' (n8n v2.15.0 rejects workflows "
                    f"without this)"
                )

        nodes = workflow_json["nodes"]
        if not isinstance(nodes, list) or len(nodes) == 0:
            raise N8nWorkflowValidationError(
                "workflow.nodes must be a non-empty list"
            )

        webhook_trigger_indices: list[int] = []
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                raise N8nWorkflowValidationError(
                    f"workflow.nodes[{idx}] must be an object, got "
                    f"{type(node).__name__}"
                )
            for required in ("id", "name", "type", "parameters"):
                if required not in node:
                    raise N8nWorkflowValidationError(
                        f"workflow.nodes[{idx}] missing required "
                        f"field '{required}'"
                    )
            node_type = node.get("type", "")
            if not isinstance(node_type, str) or not node_type.strip():
                raise N8nWorkflowValidationError(
                    f"workflow.nodes[{idx}].type must be a non-empty string"
                )
            if any(ch.isspace() for ch in node_type):
                raise N8nWorkflowValidationError(
                    f"workflow.nodes[{idx}].type contains whitespace: "
                    f"{node_type!r}"
                )
            # Track webhook triggers but SKIP respondToWebhook
            # (that's a response node, not a trigger). Match "webhook"
            # anywhere in the type so community webhook triggers work.
            lower_type = node_type.lower()
            if "webhook" in lower_type and "respond" not in lower_type:
                webhook_trigger_indices.append(idx)

        if len(webhook_trigger_indices) == 0:
            raise N8nWorkflowValidationError(
                "workflow has no webhook trigger node. Round 4 "
                "requires exactly one n8n-nodes-base.webhook trigger "
                "so the test_run step can execute the workflow via "
                "its webhook URL. Add a Webhook node as the entry "
                "point (not Schedule or Manual)."
            )
        if len(webhook_trigger_indices) > 1:
            raise N8nWorkflowValidationError(
                f"workflow has {len(webhook_trigger_indices)} webhook "
                f"trigger nodes; must have exactly one. Found at "
                f"indices: {webhook_trigger_indices}. Multi-trigger "
                f"workflows are not supported by the side hustle "
                f"test_run step."
            )

        webhook_idx = webhook_trigger_indices[0]
        webhook_node = nodes[webhook_idx]
        params = webhook_node.get("parameters") or {}
        if not isinstance(params, dict):
            raise N8nWorkflowValidationError(
                f"workflow.nodes[{webhook_idx}].parameters must be "
                f"an object, got {type(params).__name__}"
            )
        path = params.get("path")
        if not isinstance(path, str) or not path.strip():
            raise N8nWorkflowValidationError(
                f"workflow.nodes[{webhook_idx}].parameters.path must "
                f"be a non-empty string — the test_run step uses "
                f"this to build the webhook URL"
            )

    @staticmethod
    def extract_webhook_url_from_workflow(
        workflow_json: dict,
        base_url: str | None = None,
    ) -> str | None:
        """Walk a workflow's nodes list, find the first webhook trigger
        node, and return its production webhook URL.

        n8n's webhook node types include:
        - ``n8n-nodes-base.webhook`` (the canonical one)
        - ``n8n-nodes-base.respondToWebhook`` (response node, not a trigger)
        - Plus version suffixes on the type string

        The production webhook URL is ``{base}/webhook/{path}`` where
        ``path`` comes from the node's ``parameters.path`` field. Some
        older versions also use the node's webhookId; we prefer path
        because it's stable and human-readable.

        TODO(phase0): verify the exact webhook URL format for v2.15.0.
        Some versions also need the HTTP method embedded in the URL
        (e.g. /webhook/GET/path). Verify empirically.

        Args:
            workflow_json: The full workflow definition (as returned
                by create_workflow or loaded from a builder workspace).
            base_url: Override for the n8n base URL. Defaults to
                ``settings.n8n_base_url``.

        Returns:
            The webhook URL as a string, or None if no webhook trigger
            node was found.
        """
        if not isinstance(workflow_json, dict):
            return None
        nodes = workflow_json.get("nodes")
        if not isinstance(nodes, list):
            return None

        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_type = (node.get("type") or "").lower()
            # Match webhook triggers but NOT respondToWebhook (not a trigger)
            if "webhook" not in node_type:
                continue
            if "respond" in node_type:
                continue

            params = node.get("parameters") or {}
            path = params.get("path")
            if not path:
                continue

            base = (base_url or settings.n8n_base_url).rstrip("/")
            return f"{base}/webhook/{path}"

        return None
