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
    template_id: str | None = None,
) -> MagicMock:
    """Build a MagicMock that quacks like a WorkflowRow for these tests.

    Round 5.B2: ``template_id`` defaults to None (preserves pre-Round-5
    test behavior — the dispatcher falls back to startup for an unset
    template_id) but can be set explicitly for pipeline-aware
    dispatch tests.
    """
    row = MagicMock()
    row.id = workflow_id
    row.name = name
    row.context = json.dumps(context or {})
    row.error_message = error_message
    row.template_id = template_id
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
    # Round 6.A1: explicit template_id so the dispatch picks the
    # startup pipeline's "MVP ready" subject. Fake workflows that
    # leave template_id=None now route to the generic "Build ready"
    # fallback (intentional — every real production workflow is
    # created from a template and always has a template_id set).
    row = _fake_workflow_row(
        wf_id,
        context={"selected_idea": selected},
        template_id="startup_idea_pipeline",
    )
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


# ─────────────────────────────────────────────────────────────────────
# Round 5.B2/B3: pipeline-aware dispatcher
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_uses_side_hustle_renderer_for_side_hustle_template():
    """Round 5.B2: a workflow with template_id='side_hustle_pipeline'
    must route to render_side_hustle_synthesis_report, not the startup
    renderer."""
    from tests.fixtures.side_hustle_fixtures import VALID_SIDE_HUSTLE_SYNTHESIS

    wf_id = uuid.uuid4()
    row = _fake_workflow_row(
        wf_id,
        context={"synthesis": json.dumps(VALID_SIDE_HUSTLE_SYNTHESIS)},
        template_id="side_hustle_pipeline",
    )
    session = _fake_session(row, cost_total=0.4275)

    # Patch both renderers so we can see which one got called
    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"), \
         patch.object(
             notifications.report_renderer,
             "render_side_hustle_synthesis_report",
             return_value=("<html>side hustle html</html>", "side hustle text", b"%PDF-sh"),
         ) as sh_mock, \
         patch.object(
             notifications.report_renderer,
             "render_startup_synthesis_report",
             return_value=("<html>startup html</html>", "startup text", b"%PDF-st"),
         ) as st_mock, \
         patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
        # Round 5.B2 dispatch dicts are evaluated at module-load time,
        # so re-bind them to the freshly-patched callables.
        with patch.dict(
            notifications._RENDERER_BY_TEMPLATE,
            {
                "side_hustle_pipeline": sh_mock,
                "startup_idea_pipeline": st_mock,
            },
            clear=False,
        ):
            await notifications.notify(session, wf_id, "awaiting_approval")

    # Side hustle renderer was called, startup was NOT
    sh_mock.assert_called_once()
    st_mock.assert_not_called()

    # Subject prefix routed correctly
    assert send_mock.call_count == 1
    subject = send_mock.call_args.kwargs["subject"]
    assert "side hustle" in subject.lower()
    assert "Pick an idea to build" not in subject


@pytest.mark.asyncio
async def test_dispatcher_uses_startup_renderer_for_startup_template():
    """Round 5.B2 regression: explicit startup template_id still picks
    the startup renderer. The existing default-path test covers None,
    this one covers the explicit case."""
    wf_id = uuid.uuid4()
    row = _fake_workflow_row(
        wf_id,
        context={"synthesis": json.dumps(VALID_SYNTHESIS)},
        template_id="startup_idea_pipeline",
    )
    session = _fake_session(row, cost_total=0.08)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"), \
         patch.object(
             notifications.report_renderer,
             "render_side_hustle_synthesis_report",
             return_value=("<html>side hustle</html>", "sh text", b"%PDF-sh"),
         ) as sh_mock, \
         patch.object(
             notifications.report_renderer,
             "render_startup_synthesis_report",
             return_value=("<html>startup</html>", "st text", b"%PDF-st"),
         ) as st_mock, \
         patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
        with patch.dict(
            notifications._RENDERER_BY_TEMPLATE,
            {
                "side_hustle_pipeline": sh_mock,
                "startup_idea_pipeline": st_mock,
            },
            clear=False,
        ):
            await notifications.notify(session, wf_id, "awaiting_approval")

    st_mock.assert_called_once()
    sh_mock.assert_not_called()

    assert send_mock.call_count == 1
    subject = send_mock.call_args.kwargs["subject"]
    assert "Pick an idea to build" in subject


@pytest.mark.asyncio
async def test_dispatcher_falls_back_to_startup_for_unknown_template():
    """Round 5.B2: unknown template_id falls back to the startup
    renderer (matching the Round 3 _TEMPLATE_OVERRIDE_KEY pattern).
    No crash, just a warning log."""
    wf_id = uuid.uuid4()
    row = _fake_workflow_row(
        wf_id,
        context={"synthesis": json.dumps(VALID_SYNTHESIS)},
        template_id="some_future_pipeline_we_havent_registered",
    )
    session = _fake_session(row)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"), \
         patch.object(
             notifications.report_renderer,
             "render_startup_synthesis_report",
             return_value=("<html>fallback</html>", "fallback text", b"%PDF-fb"),
         ) as st_mock, \
         patch.object(notifications.email_sender, "send_email", new=AsyncMock()):
        with patch.dict(
            notifications._RENDERER_BY_TEMPLATE,
            {"startup_idea_pipeline": st_mock},
            clear=False,
        ):
            await notifications.notify(session, wf_id, "awaiting_approval")

    # The startup renderer was called as the fallback — no crash
    st_mock.assert_called_once()


# ─────────────────────────────────────────────────────────────────────
# Round 6.A5: cross-dict consistency
# ─────────────────────────────────────────────────────────────────────


def test_dispatch_dicts_have_consistent_template_ids():
    """Round 6.A5: every pipeline-dispatch dict in the codebase must
    list the SAME set of template_ids. _TEMPLATE_OVERRIDE_KEY (in
    workflow_routes.py) is the canonical source — every other dict
    must match its keys exactly. A future pipeline added to one but
    not all of these would silently misbehave (wrong renderer, wrong
    subject, no terminal notification, build-complete email reads
    the wrong context key, etc.), so this test enforces consistency
    at import time."""
    from app.api.workflow_routes import _TEMPLATE_OVERRIDE_KEY
    from app.services.notifications import (
        _BUILD_COMPLETE_HEADLINE_BY_TEMPLATE,
        _BUILD_COMPLETE_SUBJECT_BY_TEMPLATE,
        _RENDERER_BY_TEMPLATE,
        _SUBJECT_BY_TEMPLATE,
        _TERMINAL_STEP_BY_TEMPLATE,
    )

    canonical = set(_TEMPLATE_OVERRIDE_KEY.keys())
    other_dicts = {
        "_RENDERER_BY_TEMPLATE": _RENDERER_BY_TEMPLATE,
        "_SUBJECT_BY_TEMPLATE": _SUBJECT_BY_TEMPLATE,
        "_TERMINAL_STEP_BY_TEMPLATE": _TERMINAL_STEP_BY_TEMPLATE,
        "_BUILD_COMPLETE_HEADLINE_BY_TEMPLATE": _BUILD_COMPLETE_HEADLINE_BY_TEMPLATE,
        "_BUILD_COMPLETE_SUBJECT_BY_TEMPLATE": _BUILD_COMPLETE_SUBJECT_BY_TEMPLATE,
    }
    for name, d in other_dicts.items():
        assert set(d.keys()) == canonical, (
            f"{name} keys drifted from _TEMPLATE_OVERRIDE_KEY:\n"
            f"  canonical:  {sorted(canonical)}\n"
            f"  {name}: {sorted(d.keys())}\n"
            f"Add the missing template_ids to whichever dict is short."
        )


# ─────────────────────────────────────────────────────────────────────
# Round 6.A2: whitespace template_id is stripped before dispatch lookup
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_strips_whitespace_from_template_id():
    """Round 6.A2: a workflow with whitespace-padded template_id (e.g.
    '  side_hustle_pipeline  ' from a config typo) must still route to
    the correct renderer. Without .strip() the dict lookup falls back
    silently to the startup renderer."""
    from tests.fixtures.side_hustle_fixtures import VALID_SIDE_HUSTLE_SYNTHESIS

    wf_id = uuid.uuid4()
    row = _fake_workflow_row(
        wf_id,
        context={"synthesis": json.dumps(VALID_SIDE_HUSTLE_SYNTHESIS)},
        template_id="  side_hustle_pipeline  ",
    )
    session = _fake_session(row, cost_total=0.1)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"), \
         patch.object(
             notifications.report_renderer,
             "render_side_hustle_synthesis_report",
             return_value=("<html>side hustle</html>", "sh text", b"%PDF-sh"),
         ) as sh_mock, \
         patch.object(
             notifications.report_renderer,
             "render_startup_synthesis_report",
             return_value=("<html>startup</html>", "st text", b"%PDF-st"),
         ) as st_mock, \
         patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
        with patch.dict(
            notifications._RENDERER_BY_TEMPLATE,
            {
                "side_hustle_pipeline": sh_mock,
                "startup_idea_pipeline": st_mock,
            },
            clear=False,
        ):
            await notifications.notify(session, wf_id, "awaiting_approval")

    sh_mock.assert_called_once()
    st_mock.assert_not_called()
    assert send_mock.call_count == 1
    assert "side hustle" in send_mock.call_args.kwargs["subject"].lower()


# ─────────────────────────────────────────────────────────────────────
# Round 6.A1: build-complete email is pipeline-aware
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_complete_uses_selected_hustle_for_side_hustle_template():
    """Round 6.A1: the build-complete email for a side_hustle_pipeline
    workflow must read from ``selected_hustle`` (not ``selected_idea``)
    and use the side hustle headline + subject prefix."""
    wf_id = uuid.uuid4()
    selected = {"name": "Reddit deal scanner"}
    row = _fake_workflow_row(
        wf_id,
        context={"selected_hustle": selected},
        template_id="side_hustle_pipeline",
    )
    session = _fake_session(row, cost_total=0.42)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, wf_id, "build_complete")

    assert send_mock.call_count == 1
    kwargs = send_mock.call_args.kwargs
    # Subject prefix is the side-hustle one, not the startup "MVP ready"
    assert "Side hustle automation ready" in kwargs["subject"]
    assert "Reddit deal scanner" in kwargs["subject"]
    # H1 in the body is the side-hustle headline
    assert "Your side hustle automation is ready" in kwargs["html_body"]
    # The text fallback echoes the side-hustle headline + the picked name
    assert "side hustle" in kwargs["text_fallback"].lower()
    assert "Reddit deal scanner" in kwargs["text_fallback"]


@pytest.mark.asyncio
async def test_build_complete_uses_selected_idea_for_startup_template():
    """Round 6.A1 regression: explicit startup template_id still uses
    selected_idea + 'MVP ready' subject + 'Your MVP is ready' headline.
    The Round 5 test path covered the implicit None case; this one
    pins the explicit case so the dispatch can't drift."""
    wf_id = uuid.uuid4()
    selected = {"name": "Build pipeline analytics"}
    row = _fake_workflow_row(
        wf_id,
        context={"selected_idea": selected},
        template_id="startup_idea_pipeline",
    )
    session = _fake_session(row, cost_total=0.5)

    with patch.object(notifications.settings, "approval_recipient_email", "me@example.com"):
        with patch.object(notifications.email_sender, "send_email", new=AsyncMock()) as send_mock:
            await notifications.notify(session, wf_id, "build_complete")

    assert send_mock.call_count == 1
    kwargs = send_mock.call_args.kwargs
    assert "MVP ready" in kwargs["subject"]
    assert "Build pipeline analytics" in kwargs["subject"]
    assert "Your MVP is ready" in kwargs["html_body"]
    # Make sure the side-hustle copy did NOT leak in
    assert "side hustle" not in kwargs["html_body"].lower()
