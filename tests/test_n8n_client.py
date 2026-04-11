"""Unit tests for the Round 4 N8nClient rewrite.

Pure unit tests with mocked httpx. Cover: every method hits the
verified v2 endpoint path (for Round 4, "verified" is the best-guess
path pending the Phase 0 empirical probe — tests pin the exact path
so if Phase 0 reveals a different path we see a failure and update
both the code and the test in the same commit).

The retry-with-backoff tests mock ``asyncio.sleep`` to a no-op so
the test suite doesn't actually wait between retries.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.tools.n8n import (
    N8nAPIError,
    N8nClient,
    N8nTimeoutError,
    _normalize_execution_status,
    _status_is_terminal,
)


def _mock_response(
    status_code: int = 200,
    json_body: dict | list | None = None,
    text: str = "",
) -> MagicMock:
    """Build a minimal httpx.Response-shaped mock."""
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_body is not None:
        response.json = MagicMock(return_value=json_body)
        response.content = b"{}"
    else:
        response.json = MagicMock(side_effect=ValueError("no body"))
        response.content = b""
    return response


def _mock_httpx_client(response_or_exc):
    """Patch httpx.AsyncClient so calls to request() return or raise
    whatever we specify.

    Returns a context manager that replaces ``httpx.AsyncClient`` in
    ``app.tools.n8n`` with a mock whose ``request`` method is an
    AsyncMock backed by ``response_or_exc``.
    """
    mock_client = AsyncMock()
    if isinstance(response_or_exc, Exception):
        mock_client.request = AsyncMock(side_effect=response_or_exc)
    else:
        mock_client.request = AsyncMock(return_value=response_or_exc)
    # The context manager protocol
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock(return_value=mock_client)
    return patch("app.tools.n8n.httpx.AsyncClient", factory), mock_client


# ─────────────────────────────────────────────────────────────────────
# Workflow CRUD endpoint paths (TODO(phase0): verify against v2.15.0)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_workflows_hits_correct_endpoint():
    ctx, mock = _mock_httpx_client(
        _mock_response(200, json_body={"data": [{"id": "wf-1"}]})
    )
    with ctx:
        client = N8nClient(base_url="http://n8n:5678", api_key="test-key")
        result = await client.list_workflows()

    mock.request.assert_called_once()
    args, kwargs = mock.request.call_args
    assert args[0] == "GET"
    assert args[1] == "http://n8n:5678/api/v1/workflows"
    assert kwargs["headers"]["X-N8N-API-KEY"] == "test-key"
    assert result == [{"id": "wf-1"}]


@pytest.mark.asyncio
async def test_create_workflow_hits_correct_endpoint():
    """Pass a workflow WITH settings so this test is about the endpoint
    path, not the Round 4 Phase 0 settings injection. The injection
    behavior has dedicated tests further down
    (test_create_workflow_injects_empty_settings_when_missing)."""
    ctx, mock = _mock_httpx_client(
        _mock_response(200, json_body={"id": "new-wf", "name": "test"})
    )
    with ctx:
        client = N8nClient()
        result = await client.create_workflow(
            {"name": "test", "nodes": [], "settings": {}}
        )

    args, kwargs = mock.request.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/api/v1/workflows")
    assert kwargs["json"] == {"name": "test", "nodes": [], "settings": {}}
    assert result["id"] == "new-wf"


@pytest.mark.asyncio
async def test_activate_workflow_uses_v2_post_endpoint():
    """Round 4: n8n v2 activation is POST to /activate, NOT the v1-era
    PATCH with {"active": true}. Pin the path so if Phase 0 reveals
    a different shape we get a clear failure here."""
    ctx, mock = _mock_httpx_client(_mock_response(200, json_body={"active": True}))
    with ctx:
        client = N8nClient()
        await client.activate_workflow("wf-123")

    args, _kwargs = mock.request.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/api/v1/workflows/wf-123/activate")


@pytest.mark.asyncio
async def test_deactivate_workflow_uses_v2_post_endpoint():
    ctx, mock = _mock_httpx_client(_mock_response(200, json_body={"active": False}))
    with ctx:
        client = N8nClient()
        await client.deactivate_workflow("wf-123")

    args, _kwargs = mock.request.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/api/v1/workflows/wf-123/deactivate")


@pytest.mark.asyncio
async def test_delete_workflow_hits_correct_endpoint():
    ctx, mock = _mock_httpx_client(_mock_response(204))
    with ctx:
        client = N8nClient()
        await client.delete_workflow("wf-123")

    args, _kwargs = mock.request.call_args
    assert args[0] == "DELETE"
    assert args[1].endswith("/api/v1/workflows/wf-123")


# ─────────────────────────────────────────────────────────────────────
# Execution polling + status normalization
# ─────────────────────────────────────────────────────────────────────


def test_normalize_execution_status_success_aliases():
    assert _normalize_execution_status({"status": "success"}) == "success"
    assert _normalize_execution_status({"status": "succeeded"}) == "success"
    assert _normalize_execution_status({"status": "completed"}) == "success"
    assert _normalize_execution_status({"status": "SUCCESS"}) == "success"


def test_normalize_execution_status_error_aliases():
    assert _normalize_execution_status({"status": "error"}) == "error"
    assert _normalize_execution_status({"status": "failed"}) == "error"
    assert _normalize_execution_status({"status": "crashed"}) == "error"
    assert _normalize_execution_status({"status": "canceled"}) == "error"


def test_normalize_execution_status_finished_fallback():
    """When status is missing but finished=True, treat as success."""
    assert _normalize_execution_status({"finished": True}) == "success"
    assert _normalize_execution_status({"finished": False}) == "running"


def test_normalize_execution_status_unknown_defaults_to_unknown():
    assert _normalize_execution_status({}) == "unknown"
    assert _normalize_execution_status({"status": "weird-new-value"}) == "unknown"
    assert _normalize_execution_status(None) == "unknown"  # type: ignore[arg-type]


def test_status_is_terminal():
    assert _status_is_terminal("success") is True
    assert _status_is_terminal("error") is True
    assert _status_is_terminal("running") is False
    assert _status_is_terminal("waiting") is False
    assert _status_is_terminal("unknown") is False


@pytest.mark.asyncio
async def test_poll_execution_returns_when_terminal():
    """First response is running, second is success — poll should
    return after seeing success."""
    responses = [
        _mock_response(200, json_body={"status": "running"}),
        _mock_response(200, json_body={"status": "success", "data": {"out": 1}}),
    ]
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)), \
         patch("app.tools.n8n.asyncio.sleep", new=AsyncMock()):
        client = N8nClient()
        result = await client.poll_execution("exec-1", timeout=60, interval=1)

    assert result["status"] == "success"
    assert result["data"] == {"out": 1}
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_poll_execution_calls_on_progress_callback():
    responses = [
        _mock_response(200, json_body={"status": "running"}),
        _mock_response(200, json_body={"status": "success"}),
    ]
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    snapshots: list[dict] = []

    async def progress_cb(snap: dict) -> None:
        snapshots.append(dict(snap))

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)), \
         patch("app.tools.n8n.asyncio.sleep", new=AsyncMock()):
        client = N8nClient()
        await client.poll_execution(
            "exec-1", timeout=60, interval=1, on_progress=progress_cb,
        )

    assert len(snapshots) == 2
    assert snapshots[0]["status"] == "running"
    assert snapshots[1]["status"] == "success"


@pytest.mark.asyncio
async def test_poll_execution_raises_on_timeout():
    """Always returns running → eventually times out."""
    response = _mock_response(200, json_body={"status": "running"})
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)), \
         patch("app.tools.n8n.asyncio.sleep", new=AsyncMock()):
        client = N8nClient()
        with pytest.raises(N8nTimeoutError) as exc_info:
            await client.poll_execution("exec-1", timeout=3, interval=1)
        assert "exec-1" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────
# Retry-with-backoff
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_retries_on_5xx_then_succeeds():
    """First response 503, second response 200 — should return the 200."""
    responses = [
        _mock_response(503, text="upstream error"),
        _mock_response(200, json_body={"data": []}),
    ]
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)), \
         patch("app.tools.n8n.asyncio.sleep", new=AsyncMock()):
        client = N8nClient()
        result = await client.list_workflows()

    assert result == []
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_request_does_not_retry_on_4xx():
    """A 400 should NOT be retried — bad input won't become good."""
    responses = [_mock_response(400, text="bad request")]
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)):
        client = N8nClient()
        with pytest.raises(N8nAPIError) as exc_info:
            await client.list_workflows()
        assert exc_info.value.status_code == 400

    assert mock_client.request.call_count == 1


@pytest.mark.asyncio
async def test_request_retries_on_connect_error():
    """Transient ConnectError should retry."""
    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return _mock_response(200, json_body={"data": []})

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=side_effect)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)), \
         patch("app.tools.n8n.asyncio.sleep", new=AsyncMock()):
        client = N8nClient()
        result = await client.list_workflows()

    assert result == []
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_request_timeout_raises_n8n_timeout():
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("slow"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)), \
         patch("app.tools.n8n.asyncio.sleep", new=AsyncMock()):
        client = N8nClient()
        with pytest.raises(N8nTimeoutError):
            await client.list_workflows()


# ─────────────────────────────────────────────────────────────────────
# trigger_webhook
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_webhook_posts_and_returns_json():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=_mock_response(200, json_body={"ok": True})
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)):
        client = N8nClient()
        result = await client.trigger_webhook(
            "http://n8n:5678/webhook/test", payload={"input": 42}
        )

    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "http://n8n:5678/webhook/test"
    assert kwargs["json"] == {"input": 42}
    assert result["ok"] is True
    assert result["_status_code"] == 200


@pytest.mark.asyncio
async def test_trigger_webhook_returns_raw_body_on_non_json():
    """Webhook responses aren't always JSON — plain text should be
    captured as _raw_body."""
    response = _mock_response(200)
    response.text = "plain text response"
    response.json = MagicMock(side_effect=ValueError("not json"))

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)):
        client = N8nClient()
        result = await client.trigger_webhook("http://n8n:5678/webhook/test")

    assert result["_raw_body"] == "plain text response"
    assert result["_status_code"] == 200


@pytest.mark.asyncio
async def test_trigger_webhook_raises_on_timeout():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("slow"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tools.n8n.httpx.AsyncClient", MagicMock(return_value=mock_client)):
        client = N8nClient()
        with pytest.raises(N8nTimeoutError):
            await client.trigger_webhook("http://n8n:5678/webhook/slow")


# ─────────────────────────────────────────────────────────────────────
# extract_webhook_url_from_workflow
# ─────────────────────────────────────────────────────────────────────


def test_extract_webhook_url_finds_webhook_node():
    workflow = {
        "name": "test",
        "nodes": [
            {
                "id": "1",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {"path": "my-slug"},
            },
            {
                "id": "2",
                "name": "Set",
                "type": "n8n-nodes-base.set",
                "parameters": {},
            },
        ],
        "connections": {},
    }
    url = N8nClient.extract_webhook_url_from_workflow(
        workflow, base_url="http://n8n:5678"
    )
    assert url == "http://n8n:5678/webhook/my-slug"


def test_extract_webhook_url_returns_none_when_no_webhook_node():
    workflow = {
        "nodes": [
            {
                "type": "n8n-nodes-base.manualTrigger",
                "parameters": {},
            },
            {
                "type": "n8n-nodes-base.set",
                "parameters": {},
            },
        ],
        "connections": {},
    }
    assert N8nClient.extract_webhook_url_from_workflow(workflow) is None


def test_extract_webhook_url_ignores_respond_to_webhook_node():
    """respondToWebhook is a RESPONSE node, not a trigger. The URL
    should come from the webhook trigger node, not this one."""
    workflow = {
        "nodes": [
            {
                "type": "n8n-nodes-base.respondToWebhook",
                "parameters": {"path": "wrong-node"},
            },
            {
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "correct-trigger"},
            },
        ],
        "connections": {},
    }
    url = N8nClient.extract_webhook_url_from_workflow(
        workflow, base_url="http://n8n:5678"
    )
    assert url == "http://n8n:5678/webhook/correct-trigger"


def test_extract_webhook_url_returns_none_for_malformed_workflow():
    assert N8nClient.extract_webhook_url_from_workflow({}) is None
    assert N8nClient.extract_webhook_url_from_workflow({"nodes": "not-a-list"}) is None  # type: ignore[arg-type]
    assert N8nClient.extract_webhook_url_from_workflow(None) is None  # type: ignore[arg-type]


def test_extract_webhook_url_skips_webhook_node_without_path():
    """A webhook node that somehow has no parameters.path should be
    skipped, not returned as None-ish URL."""
    workflow = {
        "nodes": [
            {
                "type": "n8n-nodes-base.webhook",
                "parameters": {},  # no path
            },
        ],
        "connections": {},
    }
    assert N8nClient.extract_webhook_url_from_workflow(workflow) is None


# ─────────────────────────────────────────────────────────────────────
# Phase 0 findings: create_workflow injects settings, execution id
# shape, get_latest_execution_for_workflow
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_workflow_injects_empty_settings_when_missing():
    """Phase 0 finding: n8n v2.15.0 REQUIRES the `settings` field on
    create (returns 400 "request/body must have required property
    'settings'" without it). The client injects an empty dict as
    defense-in-depth so callers that forget don't hit an opaque 400."""
    ctx, mock = _mock_httpx_client(
        _mock_response(200, json_body={"id": "new-wf"})
    )
    with ctx:
        client = N8nClient()
        # Pass a workflow WITHOUT settings
        await client.create_workflow({"name": "test", "nodes": [], "connections": {}})

    _args, kwargs = mock.request.call_args
    sent = kwargs["json"]
    assert "settings" in sent
    assert sent["settings"] == {}


@pytest.mark.asyncio
async def test_create_workflow_preserves_provided_settings():
    """If the caller DOES provide settings, we must not overwrite it."""
    ctx, mock = _mock_httpx_client(
        _mock_response(200, json_body={"id": "new-wf"})
    )
    with ctx:
        client = N8nClient()
        await client.create_workflow({
            "name": "test",
            "nodes": [],
            "connections": {},
            "settings": {"callerPolicy": "workflowsFromSameOwner"},
        })

    _args, kwargs = mock.request.call_args
    sent = kwargs["json"]
    assert sent["settings"] == {"callerPolicy": "workflowsFromSameOwner"}


def test_normalize_execution_status_with_phase0_real_response():
    """Pin the exact execution response shape observed in Phase 0
    empirical probe against n8n v2.15.0."""
    real_response = {
        "id": "1",
        "finished": True,
        "mode": "webhook",
        "retryOf": None,
        "retrySuccessId": None,
        "status": "success",
        "createdAt": "2026-04-11T03:34:58.155Z",
        "startedAt": "2026-04-11T03:34:58.162Z",
        "stoppedAt": "2026-04-11T03:34:58.185Z",
        "deletedAt": None,
        "workflowId": "cfwWwcRoLtI253lD",
        "waitTill": None,
        "storedAt": "db",
    }
    assert _normalize_execution_status(real_response) == "success"


@pytest.mark.asyncio
async def test_get_latest_execution_for_workflow_returns_first_matching():
    """Phase 0: after triggering a webhook, we need to find the newly
    created execution row and poll it for the real result."""
    executions = [
        {"id": "1", "workflowId": "target-wf", "status": "success"},
        {"id": "2", "workflowId": "other-wf", "status": "running"},
    ]
    ctx, _mock = _mock_httpx_client(
        _mock_response(200, json_body={"data": executions, "nextCursor": None})
    )
    with ctx:
        client = N8nClient()
        found = await client.get_latest_execution_for_workflow("target-wf")

    assert found is not None
    assert found["id"] == "1"
    assert found["workflowId"] == "target-wf"


@pytest.mark.asyncio
async def test_get_latest_execution_for_workflow_returns_none_when_no_match():
    """If the workflow has no executions yet (e.g. caller polled too
    early after triggering), return None so the caller can retry or
    fall back."""
    ctx, _mock = _mock_httpx_client(
        _mock_response(200, json_body={"data": [], "nextCursor": None})
    )
    with ctx:
        client = N8nClient()
        found = await client.get_latest_execution_for_workflow("target-wf")

    assert found is None
