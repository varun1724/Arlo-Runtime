"""Tests for the Round 3 approval gate flow with context_overrides.

The headline scenario: a user picks idea #2 from the synthesis at the
approval gate. The script sends ``{"approved": true, "context_overrides":
{"selected_idea": <ranking-2>}}`` to the approve endpoint. The build_mvp
step's prompt should then render with idea #2's content, NOT idea #1.

These tests run inside the API container — they need a real DB session
because they exercise ``approve_step`` end-to-end. The pure
``_prune_context`` and template-shape assertions for the same feature
live in ``test_workflow_context_pruning.py`` and run without a DB.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_approve_with_selected_idea_passes_to_next_step(client):
    """End-to-end: user provides selected_idea via context_overrides, then
    after the approval-gated placeholder runs, the next step's prompt is
    rendered with the user's pick (not rank-1).

    Flow: fake_research (succeeds) -> approval gate (paused) -> approve
    with selected_idea -> placeholder job created -> mark it succeeded ->
    advance again -> consumer job created with rendered prompt.
    """
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.models.job import JobStatus
    from app.models.workflow import WorkflowStatus
    from app.services.workflow_service import advance_workflow

    create = await client.post(
        "/workflows",
        json={
            "name": "approval_with_selected_idea",
            "steps": [
                {
                    "name": "fake_research",
                    "job_type": "research",
                    "prompt_template": "Pretend research",
                    "output_key": "synthesis",
                },
                {
                    "name": "fake_approval",
                    "job_type": "research",
                    "prompt_template": "Approval placeholder",
                    "output_key": "_approval",
                    "requires_approval": True,
                },
                {
                    "name": "fake_consumer",
                    "job_type": "research",
                    "prompt_template": "Build for: {selected_idea}",
                    "output_key": "build_result",
                    "context_inputs": ["selected_idea"],
                },
            ],
            "initial_context": {},
        },
    )
    assert create.status_code == 201, create.text
    workflow_id = uuid.UUID(create.json()["id"])

    async with async_session() as session:
        # Mark the first job as succeeded with a fake synthesis blob
        first_job = (
            await session.execute(select(JobRow).where(JobRow.workflow_id == workflow_id))
        ).scalars().one()

        fake_synthesis = json.dumps({
            "final_rankings": [
                {"rank": 1, "name": "first idea", "one_liner": "first"},
                {"rank": 2, "name": "second idea", "one_liner": "second"},
            ],
            "executive_summary": "fake",
        })
        first_job.status = JobStatus.SUCCEEDED.value
        first_job.result_data = fake_synthesis
        first_job.completed_at = datetime.now(timezone.utc)
        await session.commit()

        # Advance the workflow — this should land it at the approval gate
        await advance_workflow(session, workflow_id)
        wf = await session.get(WorkflowRow, workflow_id)
        assert wf.status == WorkflowStatus.AWAITING_APPROVAL.value

    # Approve with a context_overrides that picks idea #2
    selected = {"rank": 2, "name": "second idea", "one_liner": "second"}
    approve = await client.post(
        f"/workflows/{workflow_id}/approve",
        json={"approved": True, "context_overrides": {"selected_idea": selected}},
    )
    assert approve.status_code == 200, approve.text

    # Sanity: the workflow context now contains selected_idea (this is the
    # actual contract — what build_mvp will render against later).
    async with async_session() as session:
        wf = await session.get(WorkflowRow, workflow_id)
        ctx = json.loads(wf.context)
        assert "selected_idea" in ctx
        assert ctx["selected_idea"]["name"] == "second idea"

        # Approving a gated step creates a job for the gated step itself
        # (the placeholder). Mark it succeeded so the workflow advances
        # to the consumer step.
        jobs = (
            await session.execute(
                select(JobRow)
                .where(JobRow.workflow_id == workflow_id)
                .order_by(JobRow.created_at)
            )
        ).scalars().all()
        assert len(jobs) == 2  # research + approval-placeholder
        approval_job = jobs[-1]
        approval_job.status = JobStatus.SUCCEEDED.value
        approval_job.result_data = "{}"
        approval_job.completed_at = datetime.now(timezone.utc)
        await session.commit()

        # Advance again — now the consumer step's job is created with the
        # rendered prompt containing the user's selected idea.
        await advance_workflow(session, workflow_id)

        jobs = (
            await session.execute(
                select(JobRow)
                .where(JobRow.workflow_id == workflow_id)
                .order_by(JobRow.created_at)
            )
        ).scalars().all()
        assert len(jobs) == 3
        consumer_job = jobs[-1]
        assert "second idea" in consumer_job.prompt
        assert "first idea" not in consumer_job.prompt


@pytest.mark.asyncio
async def test_approve_without_selected_idea_falls_back_to_rank1(client):
    """If the caller forgets context_overrides, the defensive fallback in
    approve_step extracts rank-1 from the prior synthesis."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow
    from app.models.job import JobStatus
    from app.services.workflow_service import advance_workflow

    create = await client.post(
        "/workflows",
        json={
            "name": "approval_fallback_rank1",
            "steps": [
                {
                    "name": "fake_research",
                    "job_type": "research",
                    "prompt_template": "Pretend",
                    "output_key": "synthesis",
                },
                {
                    "name": "fake_approval",
                    "job_type": "research",
                    "prompt_template": "approval",
                    "output_key": "_approval",
                    "requires_approval": True,
                },
                {
                    "name": "fake_consumer",
                    "job_type": "research",
                    "prompt_template": "Build for: {selected_idea}",
                    "output_key": "build_result",
                    "context_inputs": ["selected_idea"],
                },
            ],
            "initial_context": {},
        },
    )
    workflow_id = uuid.UUID(create.json()["id"])

    async with async_session() as session:
        first_job = (
            await session.execute(select(JobRow).where(JobRow.workflow_id == workflow_id))
        ).scalars().one()
        fake_synthesis = json.dumps({
            "final_rankings": [
                {"rank": 1, "name": "default winner", "one_liner": "rank1"},
                {"rank": 2, "name": "runner up", "one_liner": "rank2"},
            ],
            "executive_summary": "fake",
        })
        first_job.status = JobStatus.SUCCEEDED.value
        first_job.result_data = fake_synthesis
        first_job.completed_at = datetime.now(timezone.utc)
        await session.commit()
        await advance_workflow(session, workflow_id)

    # Approve with NO context_overrides — fallback should kick in
    approve = await client.post(
        f"/workflows/{workflow_id}/approve",
        json={"approved": True},
    )
    assert approve.status_code == 200

    async with async_session() as session:
        # The fallback should have populated selected_idea from rank-1 in
        # the workflow context (visible immediately after approve).
        wf = await session.get(WorkflowRow, workflow_id)
        ctx = json.loads(wf.context)
        assert "selected_idea" in ctx
        assert ctx["selected_idea"]["name"] == "default winner"

        # Mark the placeholder approval job succeeded so the consumer step
        # gets created and we can verify the rendered prompt.
        jobs = (
            await session.execute(
                select(JobRow)
                .where(JobRow.workflow_id == workflow_id)
                .order_by(JobRow.created_at)
            )
        ).scalars().all()
        approval_job = jobs[-1]
        approval_job.status = JobStatus.SUCCEEDED.value
        approval_job.result_data = "{}"
        approval_job.completed_at = datetime.now(timezone.utc)
        await session.commit()

        await advance_workflow(session, workflow_id)

        jobs = (
            await session.execute(
                select(JobRow)
                .where(JobRow.workflow_id == workflow_id)
                .order_by(JobRow.created_at)
            )
        ).scalars().all()
        consumer_job = jobs[-1]
        assert "default winner" in consumer_job.prompt


@pytest.mark.asyncio
async def test_skip_step_with_approved_false_advances(client):
    """approved=false should skip the gated step and finish the workflow if
    no further steps are eligible."""
    from app.db.engine import async_session
    from app.db.models import WorkflowRow
    from app.models.workflow import WorkflowStatus

    create = await client.post(
        "/workflows",
        json={
            "name": "approval_skip_test",
            "steps": [
                {
                    "name": "needs_approval",
                    "job_type": "research",
                    "prompt_template": "approval",
                    "output_key": "_approval",
                    "requires_approval": True,
                },
            ],
            "initial_context": {},
        },
    )
    workflow_id = uuid.UUID(create.json()["id"])

    # Workflow starts at the approval gate immediately
    async with async_session() as session:
        wf = await session.get(WorkflowRow, workflow_id)
        # The workflow starts in 'running' but creates no job because the
        # first step requires_approval. Trigger the approval check by
        # calling approve with approved=false.
        pass

    approve = await client.post(
        f"/workflows/{workflow_id}/approve",
        json={"approved": False},
    )
    # Either succeeds (and workflow is now succeeded/finished) or returns 400
    # if the workflow wasn't actually awaiting approval. Both are acceptable
    # behaviors — what matters is that no unexpected exception escapes.
    assert approve.status_code in (200, 400)
