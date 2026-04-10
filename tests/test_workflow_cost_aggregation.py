"""Tests for the Round 3 workflow cost aggregation, hardened in Round 4.

The Round 3 endpoint ``GET /workflows/{id}`` runs ``SUM(jobs.tokens_input)``
and friends to populate ``WorkflowResponse.total_estimated_cost_usd``.
These tests verify two edge cases that weren't covered originally:

1. When all jobs report NULL token counts (e.g. an old Claude CLI version
   or a job that crashed before usage was extracted), the totals should
   be ``None`` — NOT 0. The user-visible difference matters: 0 implies
   "I know it cost zero", None implies "unknown".

2. When jobs report real token counts, the totals sum correctly.

Both tests are DB-bound and run inside the docker test container.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_workflow_cost_aggregation_sums_jobs(client):
    """Two jobs reporting real costs should aggregate correctly on the
    workflow response."""
    from sqlalchemy import select, update

    from app.db.engine import async_session
    from app.db.models import JobRow
    from app.models.job import JobStatus

    create = await client.post(
        "/workflows",
        json={
            "name": "cost_agg_sum_test",
            "steps": [
                {
                    "name": "fake_research",
                    "job_type": "research",
                    "prompt_template": "x",
                    "output_key": "out",
                },
            ],
            "initial_context": {},
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = create.json()["id"]

    # Inject token usage onto the auto-created first job, then create a
    # second fake job under the same workflow with more usage.
    async with async_session() as session:
        first_job = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == uuid.UUID(workflow_id))
            )
        ).scalars().one()
        first_job.tokens_input = 1000
        first_job.tokens_output = 500
        first_job.estimated_cost_usd = 0.01
        first_job.status = JobStatus.SUCCEEDED.value
        first_job.completed_at = datetime.now(timezone.utc)

        # A second sibling job under the same workflow
        second = JobRow(
            id=uuid.uuid4(),
            job_type="research",
            status=JobStatus.SUCCEEDED.value,
            prompt="x",
            workflow_id=uuid.UUID(workflow_id),
            step_index=0,
            tokens_input=2000,
            tokens_output=1500,
            estimated_cost_usd=0.02,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(second)
        await session.commit()

    # Fetch the workflow and verify aggregates
    r = await client.get(f"/workflows/{workflow_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["total_tokens_input"] == 3000
    assert body["total_tokens_output"] == 2000
    # Float comparison with a small tolerance
    assert body["total_estimated_cost_usd"] == pytest.approx(0.03, rel=1e-6)


@pytest.mark.asyncio
async def test_workflow_cost_aggregation_returns_none_when_all_null(client):
    """A workflow whose jobs all have NULL token counts should report
    None for the totals — NOT 0. The distinction matters: None means
    'unknown', 0 means 'known to be zero'."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import JobRow
    from app.models.job import JobStatus

    create = await client.post(
        "/workflows",
        json={
            "name": "cost_agg_null_test",
            "steps": [
                {
                    "name": "fake_research",
                    "job_type": "research",
                    "prompt_template": "x",
                    "output_key": "out",
                },
            ],
            "initial_context": {},
        },
    )
    assert create.status_code == 201
    workflow_id = create.json()["id"]

    # Mark the auto-created first job as succeeded but leave token columns NULL
    async with async_session() as session:
        first_job = (
            await session.execute(
                select(JobRow).where(JobRow.workflow_id == uuid.UUID(workflow_id))
            )
        ).scalars().one()
        first_job.status = JobStatus.SUCCEEDED.value
        first_job.completed_at = datetime.now(timezone.utc)
        # tokens_input/output/estimated_cost_usd remain None
        await session.commit()

    r = await client.get(f"/workflows/{workflow_id}")
    assert r.status_code == 200
    body = r.json()
    # The aggregates must be None, not 0
    assert body["total_tokens_input"] is None
    assert body["total_tokens_output"] is None
    assert body["total_estimated_cost_usd"] is None
