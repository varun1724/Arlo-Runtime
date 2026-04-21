"""Tests for the per-workflow cost cap safety fence.

Workflows created via ``POST /workflows/from-template/{id}`` can pass
``max_cost_usd`` to abort the workflow before creating any further step
job once committed spend (``SUM(jobs.estimated_cost_usd)``) meets or
exceeds the cap.

Uses direct DB manipulation to simulate a job's reported cost and then
drives the advance path via ``_create_step_job`` to verify the cap
short-circuits before a second job is queued.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_cost_cap_aborts_before_creating_next_job(client):
    """A workflow with max_cost_usd=0.50 whose first job reports $1.00
    must be aborted by the next _create_step_job call."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.models.job import JobStatus
    from app.models.workflow import StepDefinition, WorkflowStatus
    from app.services.workflow_service import _create_step_job

    # Create a minimal workflow with the cap stashed in context
    create = await client.post(
        "/workflows",
        json={
            "name": "cost_cap_abort_test",
            "steps": [
                {
                    "name": "step_one",
                    "job_type": "research",
                    "prompt_template": "x",
                    "output_key": "out",
                },
                {
                    "name": "step_two",
                    "job_type": "research",
                    "prompt_template": "y",
                    "output_key": "out2",
                },
            ],
            "initial_context": {"_max_cost_usd": 0.50},
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = uuid.UUID(create.json()["id"])

    async with async_session() as session:
        # Mark the auto-created first job as having spent $1.00 — over
        # the cap. The cap enforcement should fire when we try to create
        # the step_two job.
        first_job = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().one()
        first_job.estimated_cost_usd = 1.00
        first_job.status = JobStatus.SUCCEEDED.value
        first_job.completed_at = datetime.now(timezone.utc)
        await session.commit()

        # Simulate the advance path calling _create_step_job for step_two
        step_two = StepDefinition(
            name="step_two",
            job_type="research",
            prompt_template="y",
            output_key="out2",
        )
        await _create_step_job(
            session,
            workflow_id,
            1,
            step_two,
            {"_max_cost_usd": 0.50},
        )

    # Workflow should now be FAILED with the cap abort message
    r = await client.get(f"/workflows/{workflow_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == WorkflowStatus.FAILED.value
    assert "max_cost_usd" in (body.get("error_message") or "")
    assert "1.00" in (body.get("error_message") or "")
    assert "0.50" in (body.get("error_message") or "")

    # Critically: no step_two job should have been queued. If the cap
    # fired correctly, there's only one job on the workflow.
    async with async_session() as session:
        jobs = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].step_index == 0


@pytest.mark.asyncio
async def test_cost_cap_allows_job_when_under_cap(client):
    """A workflow with max_cost_usd=10.00 whose first job reports $1.00
    should proceed — the cap does NOT trip when spent < cap."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import JobRow
    from app.models.job import JobStatus
    from app.models.workflow import StepDefinition, WorkflowStatus
    from app.services.workflow_service import _create_step_job

    create = await client.post(
        "/workflows",
        json={
            "name": "cost_cap_allow_test",
            "steps": [
                {"name": "s1", "job_type": "research", "prompt_template": "x", "output_key": "a"},
                {"name": "s2", "job_type": "research", "prompt_template": "y", "output_key": "b"},
            ],
            "initial_context": {"_max_cost_usd": 10.00},
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = uuid.UUID(create.json()["id"])

    async with async_session() as session:
        first = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().one()
        first.estimated_cost_usd = 1.00
        first.status = JobStatus.SUCCEEDED.value
        first.completed_at = datetime.now(timezone.utc)
        await session.commit()

        step_two = StepDefinition(
            name="s2",
            job_type="research",
            prompt_template="y",
            output_key="b",
        )
        await _create_step_job(
            session,
            workflow_id,
            1,
            step_two,
            {"_max_cost_usd": 10.00},
        )

    r = await client.get(f"/workflows/{workflow_id}")
    body = r.json()
    assert body["status"] != WorkflowStatus.FAILED.value
    # Step two should have been queued
    async with async_session() as session:
        jobs = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().all()
        assert len(jobs) == 2


@pytest.mark.asyncio
async def test_cost_cap_omitted_does_not_gate(client):
    """No cap in context means normal behavior — no abort, no limit."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import JobRow
    from app.models.job import JobStatus
    from app.models.workflow import StepDefinition, WorkflowStatus
    from app.services.workflow_service import _create_step_job

    create = await client.post(
        "/workflows",
        json={
            "name": "cost_cap_omitted_test",
            "steps": [
                {"name": "s1", "job_type": "research", "prompt_template": "x", "output_key": "a"},
                {"name": "s2", "job_type": "research", "prompt_template": "y", "output_key": "b"},
            ],
            "initial_context": {},
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = uuid.UUID(create.json()["id"])

    async with async_session() as session:
        first = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == workflow_id)
            )
        ).scalars().one()
        first.estimated_cost_usd = 9999.00  # astronomical, but no cap is set
        first.status = JobStatus.SUCCEEDED.value
        first.completed_at = datetime.now(timezone.utc)
        await session.commit()

        step_two = StepDefinition(
            name="s2",
            job_type="research",
            prompt_template="y",
            output_key="b",
        )
        await _create_step_job(session, workflow_id, 1, step_two, {})

    r = await client.get(f"/workflows/{workflow_id}")
    body = r.json()
    assert body["status"] != WorkflowStatus.FAILED.value
