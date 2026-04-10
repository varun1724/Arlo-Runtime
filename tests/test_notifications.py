"""Tests for the Round 5 notification dispatcher.

Pure unit tests — we mock ``email_sender.send_email`` and the DB
lookups so we can verify the dispatcher logic without touching SMTP
or a real database. The integration with ``advance_workflow`` is
tested separately in ``test_workflow_retry.py``.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import notifications
from tests.fixtures.startup_pipeline_fixtures import VALID_SYNTHESIS


def _fake_workflow_row(
    workflow_id: uuid.UUID,
    context: dict | None = None,
    name: str = "test-workflow",
    error_message: str | None = None,
) -> MagicMock:
    """Build a MagicMock that quacks like a WorkflowRow for these tests."""
    row = MagicMock()
    row.id = workflow_id
    row.name = name
    row.context = json.dumps(context or {})
    row.error_message = error_message
    return row


def _fake_session(workflow_row=None, cost_total: float | None = None) -> MagicMock:
    """Build an AsyncMock session whose `.get` returns the workflow row
    and whose `.execute` returns a cost total scalar."""
    session = MagicMock()
    session.get = AsyncMock(return_value=workflow_row)
    # Mock the cost SUM query
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=cost_total)
    session.execute = AsyncMock(return_value=scalar_result)
    return session


# ─────────────────────────────────────────────────────────────────────
# Opt-in switch
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_noop_when_recipient_blank():
    """The single opt-in switch: blank approval_recipient_email means
    the dispatcher is a complete no-op."""
    with patch.object(notifications.settings, "approval_recipient_email", ""):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(None, uuid.uuid4(), "awaiting_approval")
    assert send_mock.call_count == 0


# ─────────────────────────────────────────────────────────────────────
# awaiting_approval event
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_awaiting_approval_sends_email_with_pdf():
    wf_id = uuid.uuid4()
    row = _fake_workflow_row(wf_id, context={"synthesis": json.dumps(VALID_SYNTHESIS)})
    session = _fake_session(row, cost_total=0.0832)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, wf_id, "awaiting_approval")

    assert send_mock.call_count == 1
    kwargs = send_mock.call_args.kwargs
    assert kwargs["to"] == "me@example.com"
    assert "Pick an idea" in kwargs["subject"]
    # The HTML body contains the approval links (one per ranking)
    html = kwargs["html_body"]
    assert f"/workflows/{wf_id}/approve-link/" in html
    # The text fallback is plain text
    assert "ARLO" in kwargs["text_fallback"]
    # PDF attachment
    attachments = kwargs.get("attachments") or []
    assert any(name.endswith(".pdf") and mime == "application/pdf" for name, _, mime in attachments)


@pytest.mark.asyncio
async def test_notify_awaiting_approval_noop_when_workflow_missing():
    """If the workflow doesn't exist, notify logs and returns without crashing."""
    session = _fake_session(workflow_row=None)
    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, uuid.uuid4(), "awaiting_approval")
    assert send_mock.call_count == 0


@pytest.mark.asyncio
async def test_notify_awaiting_approval_handles_empty_rankings():
    """Still sends an email (so the user knows research finished) but
    without any approval links."""
    wf_id = uuid.uuid4()
    empty_synthesis = {"final_rankings": [], "executive_summary": "all killed"}
    row = _fake_workflow_row(wf_id, context={"synthesis": json.dumps(empty_synthesis)})
    session = _fake_session(row)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, wf_id, "awaiting_approval")

    assert send_mock.call_count == 1


@pytest.mark.asyncio
async def test_notify_awaiting_approval_includes_cost_when_available():
    wf_id = uuid.uuid4()
    row = _fake_workflow_row(wf_id, context={"synthesis": json.dumps(VALID_SYNTHESIS)})
    session = _fake_session(row, cost_total=0.1234)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, wf_id, "awaiting_approval")

    html = send_mock.call_args.kwargs["html_body"]
    assert "$0.1234" in html


# ─────────────────────────────────────────────────────────────────────
# build_complete event
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_build_complete_includes_download_link():
    wf_id = uuid.uuid4()
    selected = {"rank": 2, "name": "AI test suite generator"}
    row = _fake_workflow_row(wf_id, context={"selected_idea": selected})
    session = _fake_session(row, cost_total=0.5)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, wf_id, "build_complete")

    assert send_mock.call_count == 1
    kwargs = send_mock.call_args.kwargs
    assert "MVP ready" in kwargs["subject"]
    assert "AI test suite generator" in kwargs["subject"]
    html = kwargs["html_body"]
    assert f"/workflows/{wf_id}/artifacts.tar.gz" in html
    assert "token=" in html
    # Cost shown
    assert "$0.5000" in html


@pytest.mark.asyncio
async def test_notify_build_complete_handles_missing_selected_idea():
    """If selected_idea isn't in context, fall back to a generic name."""
    wf_id = uuid.uuid4()
    row = _fake_workflow_row(wf_id, context={})
    session = _fake_session(row)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, wf_id, "build_complete")

    kwargs = send_mock.call_args.kwargs
    # The email still sends, just with a generic subject
    assert send_mock.call_count == 1
    assert "selected idea" in kwargs["subject"] or "MVP ready" in kwargs["subject"]


# ─────────────────────────────────────────────────────────────────────
# workflow_failed event
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_workflow_failed_includes_error_message():
    wf_id = uuid.uuid4()
    row = _fake_workflow_row(
        wf_id,
        name="startup research",
        error_message="Step 2 (contrarian_analysis) failed after 3 attempts: ClaudeRunError",
    )
    session = _fake_session(row)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, wf_id, "workflow_failed")

    kwargs = send_mock.call_args.kwargs
    assert "failed" in kwargs["subject"].lower()
    assert "ClaudeRunError" in kwargs["html_body"]
    assert "ClaudeRunError" in kwargs["text_fallback"]


# ─────────────────────────────────────────────────────────────────────
# Failure policy: notification errors never break the workflow
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_swallows_send_email_exceptions():
    """If the SMTP send raises, notify() must NOT re-raise."""
    wf_id = uuid.uuid4()
    row = _fake_workflow_row(wf_id, context={"synthesis": json.dumps(VALID_SYNTHESIS)})
    session = _fake_session(row)

    send_mock = AsyncMock(side_effect=RuntimeError("SMTP exploded"))
    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=send_mock):
            # Must not raise
            await notifications.notify(session, wf_id, "awaiting_approval")
    assert send_mock.call_count == 1


@pytest.mark.asyncio
async def test_notify_unknown_event_type_is_ignored():
    session = _fake_session()
    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, uuid.uuid4(), "not_a_real_event")  # type: ignore[arg-type]
    assert send_mock.call_count == 0
