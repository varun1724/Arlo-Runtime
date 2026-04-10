"""Async SMTP email sender for the Round 5 notification system.

Thin wrapper around ``aiosmtplib`` that takes a subject, HTML body,
text fallback, and optional attachments, builds a proper MIME message,
and sends via STARTTLS using the configured SMTP credentials.

All config comes from ``app.core.config.settings``:
- ``smtp_host``, ``smtp_port``, ``smtp_username``, ``smtp_password``
- ``email_from_address``

Callers pass the ``to`` address explicitly (usually
``settings.approval_recipient_email``) so tests don't need to patch
settings to send to a fake recipient.

**Why MIME multipart/alternative with text + HTML?** Some email clients
(especially mobile) render the text version; some render HTML. Providing
both gives the best chance of a readable message everywhere. Attachments
are added to the outer multipart/mixed container.
"""

from __future__ import annotations

import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger("arlo.email_sender")


async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    text_fallback: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    """Send a MIME email via SMTP.

    Args:
        to: The recipient email address.
        subject: The subject line.
        html_body: The HTML body (rendered inline by most email clients).
        text_fallback: A plaintext alternative for clients that don't render HTML.
        attachments: Optional list of ``(filename, content_bytes, mime_type)``
            tuples. Each becomes a MIME attachment. Typical use: PDF reports.

    Raises:
        aiosmtplib.SMTPException: On any SMTP protocol error. The caller
            (``notifications.notify``) catches these and logs without failing
            the workflow.
    """
    msg = MIMEMultipart("mixed")
    msg["From"] = settings.email_from_address
    msg["To"] = to
    msg["Subject"] = subject

    # Inner multipart/alternative: text + HTML bodies
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_fallback, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    # Attachments (PDFs, etc.)
    for filename, content, mime_type in attachments or []:
        # mime_type like "application/pdf" — split into maintype/subtype
        if "/" in mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        part = MIMEApplication(content, _subtype=subtype, name=filename)
        part["Content-Disposition"] = f'attachment; filename="{filename}"'
        msg.attach(part)

    logger.info(
        "Sending email to %s via %s:%d (subject=%r, attachments=%d)",
        to,
        settings.smtp_host,
        settings.smtp_port,
        subject,
        len(attachments or []),
    )

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or None,
        password=settings.smtp_password or None,
        start_tls=True,
    )
