"""Unit tests for the Round 4 execute_n8n_job rewrite.

Tests the behavior of the job executor with a mocked N8nClient and a
real (in-memory) async DB session so the previous-step-lookup helpers
exercise the actual SQL they'd run in production.

Scope: the happy paths for create+activate (deploy step) and
webhook-trigger (test step), plus the error paths for missing
workflow JSON, missing webhook URL, and API errors.

Mocking gotcha: ``patch("app.jobs.n8n.N8nClient", return_value=...)``
replaces the whole class reference in the executor module, including
static methods. The executor calls
``N8nClient.extract_webhook_url_from_workflow(...)`` as a static
method — if we don't forward that call to the real implementation,
the patched class returns a MagicMock for it, which then gets stored
in ``result`` and crashes ``json.dumps`` at the finalize step. The
``_patch_n8n_client`` helper below delegates the static method to the
real implementation so tests don't have to think about it.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.n8n import N8nClient as _RealN8nClient


@contextmanager
def _patch_n8n_client(mock_instance):
    """Patch the executor's N8nClient reference while keeping the real
    static methods working.

    Returns a context manager that patches ``app.jobs.n8n.N8nClient``
    so that (a) instantiating it returns ``mock_instance`` and
    (b) accessing static methods on the class forwards to the real
    implementations. Without (b), calls like
    ``N8nClient.extract_webhook_url_from_workflow(wf)`` hit a MagicMock
    and return junk that pollutes the job result dict.
    """
    with patch("app.jobs.n8n.N8nClient") as patched_cls:
        patched_cls.return_value = mock_instance
        # Delegate static methods to the real implementation so calls
        # like N8nClient.extract_webhook_url_from_workflow(...) return
        # real URLs instead of MagicMocks that break json.dumps.
        patched_cls.extract_webhook_url_from_workflow = (
            _RealN8nClient.extract_webhook_url_from_workflow
        )
        patched_cls.validate_workflow_json = (
            _RealN8nClient.validate_workflow_json
        )
        yield patched_cls


@pytest.mark.asyncio
async def test_create_step_extracts_and_stores_webhook_url():
    """Deploy step: the executor should call create_workflow, activate,
    then pull the webhook URL out of the workflow JSON and store it in
    the job result so the test step can find it."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.jobs.n8n import execute_n8n_job

    wf_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Create workflow + deploy job row
    async with async_session() as session:
        wf = WorkflowRow(
            id=wf_id,
            name="exec-test",
            status="running",
            context="{}",
            step_definitions="[]",
            current_step_index=0,
        )
        session.add(wf)
        await session.commit()

    inline_workflow = {
        "name": "side-hustle-test",
        "nodes": [
            {
                "id": "1",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "test-slug"},
            },
        ],
        "connections": {},
    }
    instructions = {
        "action": "create",
        "activate": True,
        "workflow_json": inline_workflow,
    }

    async with async_session() as session:
        job = JobRow(
            id=job_id,
            job_type="n8n",
            status="running",
            prompt=json.dumps(instructions),
            workflow_id=wf_id,
            step_index=0,
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)
        await session.commit()

        # Mock the N8nClient to avoid real HTTP
        mock_client = AsyncMock()
        mock_client.create_workflow = AsyncMock(
            return_value={"id": "n8n-wf-abc", "name": "side-hustle-test"}
        )
        mock_client.activate_workflow = AsyncMock(return_value={"active": True})

        with _patch_n8n_client(mock_client):
            # Re-fetch the job because the executor takes a JobRow
            from sqlalchemy import select
            result = await session.execute(select(JobRow).where(JobRow.id == job_id))
            job_row = result.scalars().first()
            await execute_n8n_job(session, job_row)

        # Verify the result
        result = await session.execute(select(JobRow).where(JobRow.id == job_id))
        updated = result.scalars().first()
        assert updated.status == "succeeded"

        payload = json.loads(updated.result_data)
        assert payload["n8n_workflow_id"] == "n8n-wf-abc"
        assert payload["activated"] is True
        assert payload["webhook_url"].endswith("/webhook/test-slug")

    mock_client.create_workflow.assert_awaited_once()
    mock_client.activate_workflow.assert_awaited_once_with("n8n-wf-abc")


@pytest.mark.asyncio
async def test_execute_step_reads_webhook_url_from_previous_deploy():
    """Test step: the executor should find the previous n8n deploy
    job in the same workflow, read its webhook_url from result_data,
    and POST the test_payload.json contents to it."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.jobs.n8n import execute_n8n_job

    wf_id = uuid.uuid4()
    deploy_job_id = uuid.uuid4()
    build_job_id = uuid.uuid4()
    test_job_id = uuid.uuid4()

    async with async_session() as session:
        wf = WorkflowRow(
            id=wf_id,
            name="exec-test-2",
            status="running",
            context="{}",
            step_definitions="[]",
            current_step_index=2,
        )
        session.add(wf)
        await session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        (workspace / "test_payload.json").write_text(
            json.dumps({"input_value": 99})
        )

        async with async_session() as session:
            # Earlier builder job with workspace containing test_payload
            build_job = JobRow(
                id=build_job_id,
                job_type="builder",
                status="succeeded",
                prompt="build",
                workflow_id=wf_id,
                step_index=0,
                workspace_path=str(workspace),
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add(build_job)
            # Earlier n8n deploy job with webhook_url in result_data
            deploy_job = JobRow(
                id=deploy_job_id,
                job_type="n8n",
                status="succeeded",
                prompt=json.dumps({"action": "create"}),
                workflow_id=wf_id,
                step_index=1,
                result_data=json.dumps({
                    "n8n_workflow_id": "n8n-wf-xyz",
                    "webhook_url": "http://n8n:5678/webhook/test-slug",
                }),
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add(deploy_job)
            await session.commit()

            # Create the test_run job
            test_job = JobRow(
                id=test_job_id,
                job_type="n8n",
                status="running",
                prompt=json.dumps({
                    "action": "execute",
                    "from_previous_deploy": True,
                }),
                workflow_id=wf_id,
                step_index=2,
                started_at=datetime.now(timezone.utc),
            )
            session.add(test_job)
            await session.commit()

            # Mock trigger_webhook to return a happy response and
            # get_latest_execution_for_workflow to return None so the
            # executor's "no execution row found" branch fires (which
            # reports success based on the webhook 2xx). Without this
            # explicit mock, the attribute access on AsyncMock returns
            # a nested mock and the polling block stores it in result,
            # which then crashes json.dumps at finalize.
            mock_client = AsyncMock()
            mock_client.trigger_webhook = AsyncMock(
                return_value={"_status_code": 200, "ok": True}
            )
            mock_client.get_latest_execution_for_workflow = AsyncMock(
                return_value=None
            )

            with _patch_n8n_client(mock_client):
                from sqlalchemy import select
                result = await session.execute(
                    select(JobRow).where(JobRow.id == test_job_id)
                )
                job_row = result.scalars().first()
                await execute_n8n_job(session, job_row)

            result = await session.execute(
                select(JobRow).where(JobRow.id == test_job_id)
            )
            updated = result.scalars().first()
            assert updated.status == "succeeded"
            payload = json.loads(updated.result_data)
            assert payload["webhook_url"] == "http://n8n:5678/webhook/test-slug"
            assert payload["webhook_status_code"] == 200
            assert payload["execution_status"] == "success"

        # Verify trigger_webhook was called with the test_payload.json contents
        mock_client.trigger_webhook.assert_awaited_once()
        args, kwargs = mock_client.trigger_webhook.call_args
        assert args[0] == "http://n8n:5678/webhook/test-slug"
        # Second positional arg is the payload
        assert args[1] == {"input_value": 99}


@pytest.mark.asyncio
async def test_execute_step_fails_when_no_webhook_url():
    """If there's no deploy job with a webhook URL, the test step
    should fail cleanly with a clear error message."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.jobs.n8n import execute_n8n_job

    wf_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async with async_session() as session:
        wf = WorkflowRow(
            id=wf_id,
            name="no-webhook-test",
            status="running",
            context="{}",
            step_definitions="[]",
            current_step_index=0,
        )
        session.add(wf)
        await session.commit()

    async with async_session() as session:
        job = JobRow(
            id=job_id,
            job_type="n8n",
            status="running",
            prompt=json.dumps({
                "action": "execute",
                "from_previous_deploy": True,
            }),
            workflow_id=wf_id,
            step_index=0,
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)
        await session.commit()

        mock_client = AsyncMock()
        with _patch_n8n_client(mock_client):
            from sqlalchemy import select
            result = await session.execute(select(JobRow).where(JobRow.id == job_id))
            job_row = result.scalars().first()
            await execute_n8n_job(session, job_row)

        result = await session.execute(select(JobRow).where(JobRow.id == job_id))
        updated = result.scalars().first()
        assert updated.status == "failed"
        assert "webhook URL" in updated.error_message


@pytest.mark.asyncio
async def test_execute_step_fails_when_webhook_returns_non_2xx():
    """A 500 from the webhook should fail the job with execution_status=error."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.jobs.n8n import execute_n8n_job

    wf_id = uuid.uuid4()
    job_id = uuid.uuid4()
    deploy_job_id = uuid.uuid4()

    async with async_session() as session:
        wf = WorkflowRow(
            id=wf_id,
            name="500-test",
            status="running",
            context="{}",
            step_definitions="[]",
            current_step_index=1,
        )
        session.add(wf)
        await session.commit()

    async with async_session() as session:
        deploy_job = JobRow(
            id=deploy_job_id,
            job_type="n8n",
            status="succeeded",
            prompt="deploy",
            workflow_id=wf_id,
            step_index=0,
            result_data=json.dumps({
                "n8n_workflow_id": "wf-1",
                "webhook_url": "http://n8n:5678/webhook/bad",
            }),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(deploy_job)
        job = JobRow(
            id=job_id,
            job_type="n8n",
            status="running",
            prompt=json.dumps({
                "action": "execute",
                "from_previous_deploy": True,
            }),
            workflow_id=wf_id,
            step_index=1,
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)
        await session.commit()

        mock_client = AsyncMock()
        mock_client.trigger_webhook = AsyncMock(
            return_value={"_status_code": 500, "error": "upstream failure"}
        )
        with _patch_n8n_client(mock_client):
            from sqlalchemy import select
            result = await session.execute(select(JobRow).where(JobRow.id == job_id))
            job_row = result.scalars().first()
            await execute_n8n_job(session, job_row)

        result = await session.execute(select(JobRow).where(JobRow.id == job_id))
        updated = result.scalars().first()
        assert updated.status == "failed"
        payload = json.loads(updated.result_data)
        assert payload["execution_status"] == "error"
        assert payload["webhook_status_code"] == 500


@pytest.mark.asyncio
async def test_create_step_fails_with_no_workflow_json():
    """Deploy step with neither inline workflow_json nor a previous
    builder should fail cleanly."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.jobs.n8n import execute_n8n_job

    wf_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async with async_session() as session:
        wf = WorkflowRow(
            id=wf_id,
            name="no-wf-json-test",
            status="running",
            context="{}",
            step_definitions="[]",
            current_step_index=0,
        )
        session.add(wf)
        await session.commit()

    async with async_session() as session:
        job = JobRow(
            id=job_id,
            job_type="n8n",
            status="running",
            prompt=json.dumps({"action": "create"}),
            workflow_id=wf_id,
            step_index=0,
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)
        await session.commit()

        mock_client = AsyncMock()
        with _patch_n8n_client(mock_client):
            from sqlalchemy import select
            result = await session.execute(select(JobRow).where(JobRow.id == job_id))
            job_row = result.scalars().first()
            await execute_n8n_job(session, job_row)

        result = await session.execute(select(JobRow).where(JobRow.id == job_id))
        updated = result.scalars().first()
        assert updated.status == "failed"
        assert "workflow_json" in updated.error_message


@pytest.mark.asyncio
async def test_invalid_prompt_json_fails_cleanly():
    """If the prompt isn't valid JSON, the executor should fail the
    job with a clear error rather than crashing."""
    from app.db.engine import async_session
    from app.db.models import JobRow
    from app.jobs.n8n import execute_n8n_job

    job_id = uuid.uuid4()
    async with async_session() as session:
        job = JobRow(
            id=job_id,
            job_type="n8n",
            status="running",
            prompt="not valid json at all {",
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)
        await session.commit()

        mock_client = AsyncMock()
        with _patch_n8n_client(mock_client):
            from sqlalchemy import select
            result = await session.execute(select(JobRow).where(JobRow.id == job_id))
            job_row = result.scalars().first()
            await execute_n8n_job(session, job_row)

        result = await session.execute(select(JobRow).where(JobRow.id == job_id))
        updated = result.scalars().first()
        assert updated.status == "failed"
        assert "valid JSON" in updated.error_message


# ─────────────────────────────────────────────────────────────────────
# Round 5.A3: execution row lookup fallback + verification audit field
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_sets_audit_field_on_webhook_only_fallback():
    """Round 5.A3: when get_latest_execution_for_workflow returns
    None for all retries, the executor falls back to webhook-2xx-only
    success AND sets result.execution_verification = 'webhook_2xx_only'
    so downstream consumers can distinguish a verified run from a
    webhook-accept-only signal."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.jobs.n8n import execute_n8n_job

    wf_id = uuid.uuid4()
    deploy_job_id = uuid.uuid4()
    test_job_id = uuid.uuid4()

    async with async_session() as session:
        session.add(WorkflowRow(
            id=wf_id, name="a3-fallback",
            status="running", context="{}",
            step_definitions="[]", current_step_index=1,
        ))
        await session.commit()

    async with async_session() as session:
        session.add(JobRow(
            id=deploy_job_id,
            job_type="n8n",
            status="succeeded",
            prompt="deploy",
            workflow_id=wf_id,
            step_index=0,
            result_data=json.dumps({
                "n8n_workflow_id": "wf-abc",
                "webhook_url": "http://n8n:5678/webhook/a3",
            }),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        ))
        session.add(JobRow(
            id=test_job_id,
            job_type="n8n",
            status="running",
            prompt=json.dumps({
                "action": "execute",
                "from_previous_deploy": True,
            }),
            workflow_id=wf_id,
            step_index=1,
            started_at=datetime.now(timezone.utc),
        ))
        await session.commit()

        mock_client = AsyncMock()
        mock_client.trigger_webhook = AsyncMock(
            return_value={"_status_code": 200, "message": "Workflow was started"}
        )
        # Always return None → fallback path fires
        mock_client.get_latest_execution_for_workflow = AsyncMock(return_value=None)

        with _patch_n8n_client(mock_client), \
             patch("app.jobs.n8n.asyncio.sleep", new=AsyncMock()):
            from sqlalchemy import select
            row_result = await session.execute(
                select(JobRow).where(JobRow.id == test_job_id)
            )
            job_row = row_result.scalars().first()
            await execute_n8n_job(session, job_row)

        row_result = await session.execute(
            select(JobRow).where(JobRow.id == test_job_id)
        )
        updated = row_result.scalars().first()
        assert updated.status == "succeeded"
        payload = json.loads(updated.result_data)
        assert payload["execution_status"] == "success"
        assert payload["execution_verification"] == "webhook_2xx_only"

    # Round 5.A3 bumped retries from 3 to 6
    from app.jobs.n8n import _POLL_EXECUTION_ROW_RETRIES
    assert _POLL_EXECUTION_ROW_RETRIES == 6
    assert mock_client.get_latest_execution_for_workflow.await_count == _POLL_EXECUTION_ROW_RETRIES


# ─────────────────────────────────────────────────────────────────────
# Round 5.A4: json.dumps sanitization for exotic webhook responses
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_sanitizes_datetime_in_webhook_response():
    """Round 5.A4: if trigger_webhook returns a dict containing a
    non-JSON-serializable value (datetime, Decimal, custom object),
    the finalize step's json.dumps would crash. The _sanitize_for_json
    fallback must coerce the value to a string and let the job
    succeed."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.jobs.n8n import execute_n8n_job

    wf_id = uuid.uuid4()
    deploy_job_id = uuid.uuid4()
    test_job_id = uuid.uuid4()

    async with async_session() as session:
        session.add(WorkflowRow(
            id=wf_id, name="a4-sanitize",
            status="running", context="{}",
            step_definitions="[]", current_step_index=1,
        ))
        await session.commit()

    async with async_session() as session:
        session.add(JobRow(
            id=deploy_job_id,
            job_type="n8n",
            status="succeeded",
            prompt="deploy",
            workflow_id=wf_id,
            step_index=0,
            result_data=json.dumps({
                "n8n_workflow_id": "wf-xyz",
                "webhook_url": "http://n8n:5678/webhook/a4",
            }),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        ))
        session.add(JobRow(
            id=test_job_id,
            job_type="n8n",
            status="running",
            prompt=json.dumps({
                "action": "execute",
                "from_previous_deploy": True,
            }),
            workflow_id=wf_id,
            step_index=1,
            started_at=datetime.now(timezone.utc),
        ))
        await session.commit()

        # Webhook response contains a datetime — json.dumps would crash
        # without the sanitizer fallback.
        exotic_timestamp = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)
        mock_client = AsyncMock()
        mock_client.trigger_webhook = AsyncMock(
            return_value={
                "_status_code": 200,
                "created_at": exotic_timestamp,
                "items": [1, 2, 3],
            }
        )
        mock_client.get_latest_execution_for_workflow = AsyncMock(return_value=None)

        with _patch_n8n_client(mock_client), \
             patch("app.jobs.n8n.asyncio.sleep", new=AsyncMock()):
            from sqlalchemy import select
            row_result = await session.execute(
                select(JobRow).where(JobRow.id == test_job_id)
            )
            job_row = row_result.scalars().first()
            await execute_n8n_job(session, job_row)

        row_result = await session.execute(
            select(JobRow).where(JobRow.id == test_job_id)
        )
        updated = row_result.scalars().first()
        # The job must succeed despite the exotic value
        assert updated.status == "succeeded"
        # The datetime must be stringified in the stored result_data
        payload = json.loads(updated.result_data)
        assert "webhook_response" in payload
        wh = payload["webhook_response"]
        # After sanitization the datetime is a string
        assert isinstance(wh["created_at"], str)
        assert "2026" in wh["created_at"]
        # Non-exotic values are preserved
        assert wh["items"] == [1, 2, 3]


# ─────────────────────────────────────────────────────────────────────
# Round 6.A3: _sanitize_for_json handles circular references
# ─────────────────────────────────────────────────────────────────────


def test_sanitize_for_json_handles_self_referential_dict():
    """Round 6.A3: a dict that contains itself as a value (e.g. a
    webhook response built dynamically with a 'self' link) must NOT
    blow the stack with RecursionError. The sanitizer should detect
    the cycle and replace the second visit with a marker string."""
    from app.jobs.n8n import _sanitize_for_json

    cyclic: dict = {"name": "outer", "items": [1, 2, 3]}
    cyclic["self"] = cyclic  # immediate self-reference

    result = _sanitize_for_json(cyclic)

    # No crash, returns a dict, primitives preserved
    assert isinstance(result, dict)
    assert result["name"] == "outer"
    assert result["items"] == [1, 2, 3]
    # The cyclic edge is replaced with a marker, not the original dict
    assert result["self"] == "<circular reference>"


def test_sanitize_for_json_handles_nested_cycle_in_list():
    """A cycle that goes dict → list → back to the same dict must
    also terminate cleanly."""
    from app.jobs.n8n import _sanitize_for_json

    inner: dict = {"id": "abc"}
    container: dict = {"children": [inner]}
    inner["parent"] = container  # back-reference closes the cycle

    result = _sanitize_for_json(container)

    assert isinstance(result, dict)
    assert isinstance(result["children"], list)
    child = result["children"][0]
    assert child["id"] == "abc"
    assert child["parent"] == "<circular reference>"


def test_sanitize_for_json_does_not_mark_repeated_independent_objects():
    """Two distinct dicts with identical content must NOT be flagged
    as cyclic — _seen tracks ids on the current branch, not all
    objects ever seen. The id() set is local to one recursive call."""
    from app.jobs.n8n import _sanitize_for_json

    shared = {"a": 1}
    parent = {"first": shared, "second": shared}

    result = _sanitize_for_json(parent)

    # The same object reused at the same depth is fine — only an
    # ancestor reference counts as a cycle. Both copies should be
    # rendered fully (not as the marker).
    assert result == {"first": {"a": 1}, "second": {"a": 1}}


# ─────────────────────────────────────────────────────────────────────
# Round 6.A4: sanitizer exception path stores diagnostic fallback
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_falls_back_when_sanitizer_itself_raises():
    """Round 6.A4: if json.dumps(result) raises TypeError AND the
    follow-up _sanitize_for_json call also raises (e.g. an exotic
    __str__ method blew up), the finalize block must still produce
    a valid JSON result_data via a last-ditch dict — never let the
    exception escape to the outer catch-all that reports a generic
    'n8n job failed unexpectedly'."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.jobs.n8n import execute_n8n_job

    wf_id = uuid.uuid4()
    deploy_job_id = uuid.uuid4()
    test_job_id = uuid.uuid4()

    async with async_session() as session:
        session.add(WorkflowRow(
            id=wf_id, name="a4-double-fallback",
            status="running", context="{}",
            step_definitions="[]", current_step_index=1,
        ))
        await session.commit()

    async with async_session() as session:
        session.add(JobRow(
            id=deploy_job_id,
            job_type="n8n",
            status="succeeded",
            prompt="deploy",
            workflow_id=wf_id,
            step_index=0,
            result_data=json.dumps({
                "n8n_workflow_id": "wf-double-fallback",
                "webhook_url": "http://n8n:5678/webhook/double",
            }),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        ))
        session.add(JobRow(
            id=test_job_id,
            job_type="n8n",
            status="running",
            prompt=json.dumps({
                "action": "execute",
                "from_previous_deploy": True,
            }),
            workflow_id=wf_id,
            step_index=1,
            started_at=datetime.now(timezone.utc),
        ))
        await session.commit()

        # Webhook response contains a datetime so json.dumps(result)
        # raises TypeError, forcing the executor into the sanitize
        # branch. We then patch _sanitize_for_json itself to raise
        # so the inner try/except A4 wraps gets exercised.
        exotic_timestamp = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)
        mock_client = AsyncMock()
        mock_client.trigger_webhook = AsyncMock(
            return_value={
                "_status_code": 200,
                "created_at": exotic_timestamp,
            }
        )
        mock_client.get_latest_execution_for_workflow = AsyncMock(return_value=None)

        from sqlalchemy import select
        row_result = await session.execute(
            select(JobRow).where(JobRow.id == test_job_id)
        )
        job_row = row_result.scalars().first()

        with _patch_n8n_client(mock_client), \
             patch("app.jobs.n8n.asyncio.sleep", new=AsyncMock()), \
             patch(
                 "app.jobs.n8n._sanitize_for_json",
                 side_effect=ValueError("simulated sanitizer crash"),
             ):
            await execute_n8n_job(session, job_row)

        row_result = await session.execute(
            select(JobRow).where(JobRow.id == test_job_id)
        )
        updated = row_result.scalars().first()

        # The job must NOT crash with the outer catch-all. Either it
        # succeeded with the diagnostic payload, or it was finalized
        # with execution_status=error — but in both cases result_data
        # must be a valid JSON string with the A4 marker fields.
        assert updated.result_data is not None
        payload = json.loads(updated.result_data)
        assert payload.get("_sanitizer_failed") is True
        assert "simulated sanitizer crash" in payload.get("_sanitizer_error", "")
