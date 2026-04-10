"""Tests for the Round 5 workspace tar.gz download endpoint.

DB-bound tests (run inside the docker test container). They create a
workflow + a fake job with a tempdir workspace, mint a signed
artifacts token, and hit the public ``/artifacts.tar.gz`` endpoint
without a bearer header.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_download_workspace_with_valid_token_streams_tar(unauthed_client):
    """End-to-end: signed token + real workspace dir = tar.gz response."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.models.job import JobStatus
    from app.services.signed_urls import sign_token

    # Create a workflow with one job via raw DB insert (faster than going
    # through the API for this test)
    wf_id = uuid.uuid4()
    job_id = uuid.uuid4()

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        (workspace / "README.md").write_text("# test project\n")
        (workspace / "BUILD_DECISIONS.md").write_text("We chose Python because...\n")
        (workspace / "main.py").write_text("print('hello')\n")

        # Commit the workflow FIRST so the FK exists when we insert the
        # job. SQLAlchemy doesn't always order multi-table inserts by FK
        # dependency unless an ORM relationship() is declared.
        async with async_session() as session:
            wf = WorkflowRow(
                id=wf_id,
                name="download-test",
                status="succeeded",
                context="{}",
                step_definitions="[]",
                current_step_index=0,
                completed_at=datetime.now(timezone.utc),
            )
            session.add(wf)
            await session.commit()

        async with async_session() as session:
            job = JobRow(
                id=job_id,
                job_type="builder",
                status=JobStatus.SUCCEEDED.value,
                prompt="x",
                workflow_id=wf_id,
                step_index=0,
                workspace_path=str(workspace),
                completed_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.commit()

        # Mint a signed artifacts token
        token = sign_token(wf_id, "artifacts")

        # Hit the public endpoint WITHOUT bearer auth
        r = await unauthed_client.get(
            f"/workflows/{wf_id}/artifacts.tar.gz",
            params={"token": token},
        )

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/gzip"
    assert f"workflow-{wf_id}.tar.gz" in r.headers.get("content-disposition", "")

    # The body should be a valid gzipped tar containing our files
    body = r.content
    assert body[:2] == b"\x1f\x8b"  # gzip magic bytes

    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
        names = tar.getnames()
        # tar entries are prefixed with the workspace dir name; just
        # check that the three files we created are in there
        flat = "\n".join(names)
        assert "README.md" in flat
        assert "BUILD_DECISIONS.md" in flat
        assert "main.py" in flat


@pytest.mark.asyncio
async def test_download_workspace_invalid_token_returns_401(unauthed_client):
    wf_id = uuid.uuid4()
    r = await unauthed_client.get(
        f"/workflows/{wf_id}/artifacts.tar.gz",
        params={"token": "not.a.valid.token"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_download_workspace_mismatched_workflow_returns_401(unauthed_client):
    """A token signed for workflow A cannot be used on workflow B."""
    from app.services.signed_urls import sign_token

    wf_a = uuid.uuid4()
    wf_b = uuid.uuid4()
    token = sign_token(wf_a, "artifacts")
    r = await unauthed_client.get(
        f"/workflows/{wf_b}/artifacts.tar.gz",
        params={"token": token},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_download_workspace_wrong_purpose_token_rejected(unauthed_client):
    """An 'approve' token cannot be used on the artifacts endpoint."""
    from app.services.signed_urls import sign_token

    wf = uuid.uuid4()
    token = sign_token(wf, "approve", choice=1)
    r = await unauthed_client.get(
        f"/workflows/{wf}/artifacts.tar.gz",
        params={"token": token},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_download_workspace_missing_workspace_returns_404(unauthed_client):
    """Valid token but no job with a workspace_path = 404."""
    from app.db.engine import async_session
    from app.db.models import WorkflowRow
    from app.services.signed_urls import sign_token

    wf_id = uuid.uuid4()
    async with async_session() as session:
        wf = WorkflowRow(
            id=wf_id,
            name="no-workspace",
            status="succeeded",
            context="{}",
            step_definitions="[]",
            current_step_index=0,
        )
        session.add(wf)
        await session.commit()

    token = sign_token(wf_id, "artifacts")
    r = await unauthed_client.get(
        f"/workflows/{wf_id}/artifacts.tar.gz",
        params={"token": token},
    )
    assert r.status_code == 404
