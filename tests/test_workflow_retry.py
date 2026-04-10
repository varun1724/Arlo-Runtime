"""Tests for the auto-retry behavior in advance_workflow.

Two layers:

1. **Unit tests for ``_should_retry_step``**: pure decision function,
   runs without a DB. Verifies the retry math (max_retries=2 means 3
   total attempts allowed, etc.).

2. **Integration tests for ``advance_workflow``**: uses the existing
   API client fixture, creates a real workflow in Postgres, manually
   inserts FAILED jobs to simulate the retry path, and asserts the
   workflow either advances to a new attempt or fails terminally.
   These tests require Postgres and run inside docker compose.

The integration tests are gated by ``pytest.importorskip`` on the
``client`` fixture so the unit tests can still run when Postgres is
unavailable (e.g. local pre-commit ``--noconftest`` runs).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.services.workflow_service import _should_retry_step

# ─────────────────────────────────────────────────────────────────────
# Unit tests — pure decision logic, no DB
# ─────────────────────────────────────────────────────────────────────


def test_no_retries_with_max_zero():
    """max_retries=0 means a single attempt and no retries (default for legacy steps)."""
    assert _should_retry_step(max_retries=0, attempt_count=1) is False


def test_no_retries_with_negative_max():
    """Defensive: negative max_retries treated as 0."""
    assert _should_retry_step(max_retries=-1, attempt_count=1) is False


def test_first_retry_after_initial_failure():
    """max_retries=2: first attempt failed → attempt_count=1 → should retry."""
    assert _should_retry_step(max_retries=2, attempt_count=1) is True


def test_second_retry_allowed():
    """max_retries=2: second attempt failed → attempt_count=2 → still retry."""
    assert _should_retry_step(max_retries=2, attempt_count=2) is True


def test_third_attempt_exhausts_retries():
    """max_retries=2: third attempt failed → attempt_count=3 → no more retries.
    Total allowed = max_retries + 1 = 3 attempts."""
    assert _should_retry_step(max_retries=2, attempt_count=3) is False


def test_one_retry_allowed_with_max_one():
    """max_retries=1: 2 total attempts allowed."""
    assert _should_retry_step(max_retries=1, attempt_count=1) is True
    assert _should_retry_step(max_retries=1, attempt_count=2) is False


def test_high_retry_count():
    assert _should_retry_step(max_retries=10, attempt_count=5) is True
    assert _should_retry_step(max_retries=10, attempt_count=10) is True
    assert _should_retry_step(max_retries=10, attempt_count=11) is False


# ─────────────────────────────────────────────────────────────────────
# Integration tests — require Postgres via the existing client fixture
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_step_with_max_retries_creates_retry_job(client):
    """End-to-end: failed job + max_retries > 0 → advance_workflow creates a new job."""
    # Avoid pulling DB-bound modules at import time so unit tests above can
    # run with --noconftest. Imports happen inside the test body.
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.models.job import JobStatus
    from app.models.workflow import WorkflowStatus
    from app.services.workflow_service import advance_workflow

    # Create a workflow via the API (uses the real DB the client is configured for)
    create = await client.post(
        "/workflows",
        json={
            "name": "retry_test_with_retries",
            "steps": [
                {
                    "name": "flaky",
                    "job_type": "research",
                    "prompt_template": "Do something",
                    "output_key": "result",
                    "max_retries": 2,
                }
            ],
            "initial_context": {},
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = uuid.UUID(create.json()["id"])

    async with async_session() as session:
        # Find the auto-created first job and flip it to FAILED to simulate the failure
        jobs = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().all()
        assert len(jobs) == 1
        first_job = jobs[0]
        first_job.status = JobStatus.FAILED.value
        first_job.error_message = "simulated failure"
        first_job.completed_at = datetime.now(timezone.utc)
        await session.commit()

        # Trigger the workflow advancement
        await advance_workflow(session, workflow_id)

        # A second job should now exist for the same step
        jobs_after = (
            await session.execute(
                select(JobRow)
                .where(JobRow.workflow_id == workflow_id)
                .order_by(JobRow.created_at)
            )
        ).scalars().all()
        assert len(jobs_after) == 2, "expected a retry job to be created"
        assert jobs_after[1].step_index == 0
        assert jobs_after[1].status == JobStatus.QUEUED.value

        # Workflow should still be running, not failed
        workflow = await session.get(WorkflowRow, workflow_id)
        assert workflow is not None
        assert workflow.status == WorkflowStatus.RUNNING.value


@pytest.mark.asyncio
async def test_failed_step_no_retries_fails_workflow(client):
    """max_retries=0 (default): single failure terminates the workflow."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.models.job import JobStatus
    from app.models.workflow import WorkflowStatus
    from app.services.workflow_service import advance_workflow

    create = await client.post(
        "/workflows",
        json={
            "name": "retry_test_no_retries",
            "steps": [
                {
                    "name": "no_retry",
                    "job_type": "research",
                    "prompt_template": "Do something",
                    "output_key": "result",
                    # max_retries defaults to 0
                }
            ],
            "initial_context": {},
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = uuid.UUID(create.json()["id"])

    async with async_session() as session:
        first_job = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().one()
        first_job.status = JobStatus.FAILED.value
        first_job.error_message = "simulated failure"
        first_job.completed_at = datetime.now(timezone.utc)
        await session.commit()

        await advance_workflow(session, workflow_id)

        # No retry job created
        jobs = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().all()
        assert len(jobs) == 1

        # Workflow is FAILED with a clear error message
        workflow = await session.get(WorkflowRow, workflow_id)
        assert workflow.status == WorkflowStatus.FAILED.value
        assert workflow.error_message is not None
        assert "no_retry" in workflow.error_message
        assert "1 attempt" in workflow.error_message


@pytest.mark.asyncio
async def test_failed_step_exhausted_retries_fails_workflow(client):
    """After max_retries+1 attempts all fail, workflow fails terminally."""
    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.models.job import JobStatus
    from app.models.workflow import WorkflowStatus
    from app.services.workflow_service import advance_workflow

    create = await client.post(
        "/workflows",
        json={
            "name": "retry_test_exhausted",
            "steps": [
                {
                    "name": "always_fails",
                    "job_type": "research",
                    "prompt_template": "Do something",
                    "output_key": "result",
                    "max_retries": 2,  # 3 total attempts allowed
                }
            ],
            "initial_context": {},
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = uuid.UUID(create.json()["id"])

    async with async_session() as session:
        # Simulate 3 failed attempts back-to-back, calling advance_workflow each time
        for attempt in range(1, 4):
            jobs = (
                await session.execute(
                    select(JobRow)
                    .where(JobRow.workflow_id == workflow_id)
                    .order_by(JobRow.created_at)
                )
            ).scalars().all()
            assert len(jobs) == attempt
            latest = jobs[-1]
            latest.status = JobStatus.FAILED.value
            latest.error_message = f"failure {attempt}"
            latest.completed_at = datetime.now(timezone.utc)
            await session.commit()

            await advance_workflow(session, workflow_id)

        # Workflow should now be FAILED, no 4th job created
        workflow = await session.get(WorkflowRow, workflow_id)
        assert workflow.status == WorkflowStatus.FAILED.value
        assert "3 attempt" in workflow.error_message

        all_jobs = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().all()
        assert len(all_jobs) == 3, "should not exceed max_retries+1 attempts"
