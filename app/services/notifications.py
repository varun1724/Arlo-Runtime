"""Workflow event notification dispatcher for Round 5.

Fires on three workflow state transitions:

1. ``awaiting_approval`` — when ``advance_workflow`` moves to a step
   with ``requires_approval=True``. The email contains the ranked
   synthesis + clickable approval links, one per idea.
2. ``build_complete`` — when the ``build_mvp`` step succeeds. The email
   contains a signed link to download the workspace as a tar.gz.
3. ``workflow_failed`` — when a workflow fails terminally (retries
   exhausted). Short error email with the workflow id and error message.

**The single opt-in.** If ``settings.approval_recipient_email`` is
blank, ``notify()`` is a no-op. This is the switch that turns the
entire notification system on or off. The user sets one env var to
start receiving emails; blank means "I don't want any of this".

**Failure policy.** Every dispatch is wrapped in try/except. A failed
SMTP send must never break workflow advancement. Notification errors
are logged at ERROR level for debugging but swallowed.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow, WorkflowRow
from app.services import email_sender, report_renderer
from app.services.signed_urls import APPROVAL_TOKEN_TTL_SECONDS, sign_token

logger = logging.getLogger("arlo.notifications")

EventType = Literal["awaiting_approval", "build_complete", "workflow_failed"]


# Round 5.B2: pipeline-aware rendering dispatch. Each template_id
# maps to the renderer that knows how to format that pipeline's
# synthesis shape. Unknown templates fall back to the startup
# renderer (matching the Round 3 _TEMPLATE_OVERRIDE_KEY pattern —
# zero regression for any pipeline that doesn't register here).
# Adding a new pipeline with its own synthesis shape? Add a new
# renderer in report_renderer.py and register its template_id here.
_RENDERER_BY_TEMPLATE: dict[str, object] = {
    "startup_idea_pipeline": report_renderer.render_startup_synthesis_report,
    "side_hustle_pipeline": report_renderer.render_side_hustle_synthesis_report,
    "freelance_scanner": report_renderer.render_side_hustle_synthesis_report,
}

# Round 5.B3: email subject line per pipeline. Side hustle users
# getting "Pick an idea to build" would be confusing — the subject
# should match the pipeline's output ("Pick a side hustle to
# automate"). Same fallback strategy as the renderer dict.
_SUBJECT_BY_TEMPLATE: dict[str, str] = {
    "startup_idea_pipeline": "Pick an idea to build",
    "side_hustle_pipeline": "Pick a side hustle to automate",
    "freelance_scanner": "Pick a scanner to deploy",
}


async def notify(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    event_type: EventType,
) -> None:
    """Dispatch a notification for a workflow event.

    Always wraps the actual send in try/except so notification failures
    never break the workflow. If email isn't configured (i.e. the
    opt-in env var ``approval_recipient_email`` is blank), this is a
    no-op.
    """
    if not settings.approval_recipient_email:
        return
    try:
        if event_type == "awaiting_approval":
            await _send_approval_email(session, workflow_id)
        elif event_type == "build_complete":
            await _send_build_complete_email(session, workflow_id)
        elif event_type == "workflow_failed":
            await _send_failure_email(session, workflow_id)
        else:
            logger.warning("Unknown notification event type: %r", event_type)
    except Exception:
        logger.exception(
            "Notification dispatch failed for workflow %s event %s; continuing",
            workflow_id, event_type,
        )


# ─────────────────────────────────────────────────────────────────────
# Individual event handlers
# ─────────────────────────────────────────────────────────────────────


async def _send_approval_email(session: AsyncSession, workflow_id: uuid.UUID) -> None:
    """Render the synthesis report and send the approval-gate email."""
    workflow = await session.get(WorkflowRow, workflow_id)
    if workflow is None:
        logger.warning("Approval notification: workflow %s not found", workflow_id)
        return

    context = json.loads(workflow.context)
    synthesis_raw = context.get("synthesis", "{}")
    if isinstance(synthesis_raw, str):
        try:
            synthesis = json.loads(synthesis_raw)
        except json.JSONDecodeError:
            logger.warning(
                "Approval notification: synthesis for workflow %s is not valid JSON",
                workflow_id,
            )
            synthesis = {}
    else:
        synthesis = synthesis_raw or {}

    rankings = synthesis.get("final_rankings") or []
    if not rankings:
        logger.warning(
            "Approval notification: workflow %s has no rankings to show",
            workflow_id,
        )
        # Still send the email (user should know research finished with no ideas)

    # Build one signed approval link per ranking + a skip link
    approval_links: dict[int, str] = {}
    for ranking in rankings:
        rank = ranking.get("rank")
        if rank is None:
            continue
        token = sign_token(workflow_id, "approve", choice=int(rank))
        approval_links[int(rank)] = (
            f"{settings.notification_base_url.rstrip('/')}"
            f"/workflows/{workflow_id}/approve-link/{token}"
        )
    skip_token = sign_token(workflow_id, "approve", choice=0)
    skip_link = (
        f"{settings.notification_base_url.rstrip('/')}"
        f"/workflows/{workflow_id}/approve-link/{skip_token}"
    )

    # Compute total cost from jobs (mirrors _workflow_to_response logic)
    workflow_cost_usd = await _sum_workflow_cost(session, workflow_id)

    # Round 5.B2/B3: pick the renderer and subject line based on the
    # workflow's template_id. Unknown templates log a warning and
    # fall back to the startup renderer for zero-regression.
    template_id = workflow.template_id or ""
    renderer = _RENDERER_BY_TEMPLATE.get(
        template_id, report_renderer.render_startup_synthesis_report
    )
    subject_prefix = _SUBJECT_BY_TEMPLATE.get(
        template_id, "Pick an idea to build"
    )
    if template_id and template_id not in _RENDERER_BY_TEMPLATE:
        logger.warning(
            "Approval notification: unknown template_id %r for workflow "
            "%s; falling back to startup renderer. Register the template "
            "in _RENDERER_BY_TEMPLATE if it has its own synthesis shape.",
            template_id, workflow_id,
        )

    html_body, text_fallback, pdf_bytes = renderer(
        synthesis,
        workflow_id,
        approval_links,
        skip_link,
        workflow_cost_usd,
    )

    attachments: list[tuple[str, bytes, str]] = []
    if pdf_bytes:
        attachments.append(
            (f"synthesis-{workflow_id}.pdf", pdf_bytes, "application/pdf")
        )

    subject_label = (workflow.name or "workflow").strip()[:60]
    await email_sender.send_email(
        to=settings.approval_recipient_email,
        subject=f"[arlo] {subject_prefix} — {subject_label}",
        html_body=html_body,
        text_fallback=text_fallback,
        attachments=attachments,
    )
    logger.info("Sent approval email for workflow %s", workflow_id)


async def _send_build_complete_email(
    session: AsyncSession, workflow_id: uuid.UUID
) -> None:
    """Send the build-complete email with a signed link to download the workspace."""
    workflow = await session.get(WorkflowRow, workflow_id)
    if workflow is None:
        logger.warning("Build-complete notification: workflow %s not found", workflow_id)
        return

    token = sign_token(workflow_id, "artifacts")
    download_link = (
        f"{settings.notification_base_url.rstrip('/')}"
        f"/workflows/{workflow_id}/artifacts.tar.gz?token={token}"
    )

    # Pull the selected idea from context for the subject line
    context = json.loads(workflow.context)
    selected = context.get("selected_idea") or {}
    if isinstance(selected, str):
        try:
            selected = json.loads(selected)
        except json.JSONDecodeError:
            selected = {}
    idea_name = (selected or {}).get("name", "your selected idea") if isinstance(selected, dict) else "your selected idea"

    workflow_cost_usd = await _sum_workflow_cost(session, workflow_id)
    cost_line = (
        f"<p>Total cost (API-equivalent): <strong>${workflow_cost_usd:.4f}</strong></p>"
        if workflow_cost_usd is not None
        else ""
    )

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, sans-serif; color: #1a1a1a; background: #f5f5f7; padding: 20px; }}
  .container {{ max-width: 560px; margin: 0 auto; background: #fff; padding: 24px; border-radius: 10px; }}
  h1 {{ font-size: 20px; margin: 0 0 12px 0; }}
  .button {{ display: inline-block; background: #4a6cf7; color: #ffffff !important; text-decoration: none;
             padding: 12px 22px; border-radius: 8px; font-weight: 600; margin: 16px 0; }}
  p {{ font-size: 14px; line-height: 1.5; }}
  .meta {{ color: #888; font-size: 12px; }}
</style>
</head><body>
  <div class="container">
    <h1>Your MVP is ready</h1>
    <p>Arlo finished building <strong>{idea_name}</strong>. Download the full project below.</p>
    <p><a href="{download_link}" class="button">Download tar.gz →</a></p>
    {cost_line}
    <p class="meta">The link is valid for 48 hours. Workflow {workflow_id}.</p>
  </div>
</body></html>
"""
    text_fallback = (
        f"Arlo finished building {idea_name}.\n\n"
        f"Download: {download_link}\n\n"
        f"The link is valid for 48 hours.\n"
        f"Workflow {workflow_id}.\n"
    )
    if workflow_cost_usd is not None:
        text_fallback += f"\nTotal cost (API-equivalent): ${workflow_cost_usd:.4f}\n"

    await email_sender.send_email(
        to=settings.approval_recipient_email,
        subject=f"[arlo] MVP ready — {idea_name}"[:80],
        html_body=html_body,
        text_fallback=text_fallback,
    )
    logger.info("Sent build-complete email for workflow %s", workflow_id)


async def _send_failure_email(session: AsyncSession, workflow_id: uuid.UUID) -> None:
    """Short failure email for terminal workflow failures."""
    workflow = await session.get(WorkflowRow, workflow_id)
    if workflow is None:
        logger.warning("Failure notification: workflow %s not found", workflow_id)
        return

    error = workflow.error_message or "(no error message available)"
    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head><body style="font-family: sans-serif; padding: 20px;">
<h2>Workflow failed</h2>
<p><strong>Workflow:</strong> {workflow.name} <code>({workflow_id})</code></p>
<p><strong>Error:</strong> {error}</p>
<p style="color: #888; font-size: 12px;">Check the container logs for the full traceback.</p>
</body></html>
"""
    text_fallback = (
        f"Workflow failed\n"
        f"Workflow: {workflow.name} ({workflow_id})\n"
        f"Error: {error}\n"
        f"Check the container logs for the full traceback.\n"
    )
    await email_sender.send_email(
        to=settings.approval_recipient_email,
        subject=f"[arlo] Workflow failed — {(workflow.name or '')[:40]}",
        html_body=html_body,
        text_fallback=text_fallback,
    )
    logger.info("Sent failure email for workflow %s", workflow_id)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _sum_workflow_cost(
    session: AsyncSession, workflow_id: uuid.UUID
) -> float | None:
    """Sum the estimated_cost_usd across all jobs in a workflow.

    Returns None when no jobs have populated the cost column (same
    semantics as ``_workflow_to_response`` in the API layer).
    """
    result = await session.execute(
        select(func.sum(JobRow.estimated_cost_usd)).where(
            JobRow.workflow_id == workflow_id
        )
    )
    total = result.scalar_one_or_none()
    return float(total) if total is not None else None
