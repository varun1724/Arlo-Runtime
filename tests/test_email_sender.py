"""Tests for the Round 5 email sender wrapper.

Pure unit tests that mock ``aiosmtplib.send`` and inspect the
``email.message.Message`` object that would have been sent. We don't
need a real SMTP server — the wrapper's only job is to build a
well-formed MIME message and call ``aiosmtplib.send`` with the right
kwargs.
"""

from __future__ import annotations

from email.message import Message
from unittest.mock import AsyncMock, patch

import pytest

from app.services.email_sender import send_email


def _extract_sent_message(mock_send: AsyncMock) -> Message:
    """Pull the Message arg out of a mocked ``aiosmtplib.send`` call."""
    assert mock_send.call_count == 1
    args, kwargs = mock_send.call_args
    # First positional arg is the message
    assert args, "aiosmtplib.send was called without positional args"
    return args[0]


def _walk_parts(msg: Message) -> list[Message]:
    """Return all non-multipart parts of a MIME message."""
    return [p for p in msg.walk() if not p.is_multipart()]


@pytest.mark.asyncio
async def test_send_email_builds_mime_with_html_and_text():
    with patch("app.services.email_sender.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_email(
            to="me@example.com",
            subject="Test subject",
            html_body="<p>Hello <b>world</b></p>",
            text_fallback="Hello world",
        )

    msg = _extract_sent_message(mock_send)
    assert msg["To"] == "me@example.com"
    assert msg["Subject"] == "Test subject"
    assert msg["From"]  # populated from settings

    parts = _walk_parts(msg)
    text_parts = [p for p in parts if p.get_content_type() == "text/plain"]
    html_parts = [p for p in parts if p.get_content_type() == "text/html"]
    assert len(text_parts) == 1
    assert len(html_parts) == 1
    assert "Hello world" in text_parts[0].get_payload(decode=True).decode()
    assert "<b>world</b>" in html_parts[0].get_payload(decode=True).decode()


@pytest.mark.asyncio
async def test_send_email_attaches_pdf():
    pdf_bytes = b"%PDF-1.7\n fake pdf content"
    with patch("app.services.email_sender.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_email(
            to="me@example.com",
            subject="With attachment",
            html_body="<p>see attached</p>",
            text_fallback="see attached",
            attachments=[("report.pdf", pdf_bytes, "application/pdf")],
        )

    msg = _extract_sent_message(mock_send)
    parts = _walk_parts(msg)
    pdf_parts = [p for p in parts if p.get_content_type() == "application/pdf"]
    assert len(pdf_parts) == 1
    pdf = pdf_parts[0]
    assert pdf.get_payload(decode=True) == pdf_bytes
    assert 'filename="report.pdf"' in pdf["Content-Disposition"]


@pytest.mark.asyncio
async def test_send_email_uses_starttls_and_config():
    with patch("app.services.email_sender.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_email(
            to="me@example.com",
            subject="s",
            html_body="<p>x</p>",
            text_fallback="x",
        )
    _, kwargs = mock_send.call_args
    assert kwargs.get("start_tls") is True
    # Hostname and port come from settings (defaults: smtp.gmail.com:587)
    assert kwargs.get("hostname")
    assert kwargs.get("port") == 587


@pytest.mark.asyncio
async def test_send_email_passes_none_for_blank_credentials():
    """When smtp_username/smtp_password are blank (unset), we pass None
    so aiosmtplib doesn't attempt authentication."""
    with patch("app.services.email_sender.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_email(
            to="me@example.com",
            subject="s",
            html_body="<p>x</p>",
            text_fallback="x",
        )
    _, kwargs = mock_send.call_args
    # Default config has blank credentials
    assert kwargs.get("username") is None
    assert kwargs.get("password") is None


@pytest.mark.asyncio
async def test_send_email_multiple_attachments():
    with patch("app.services.email_sender.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await send_email(
            to="me@example.com",
            subject="s",
            html_body="<p>x</p>",
            text_fallback="x",
            attachments=[
                ("a.pdf", b"pdf1", "application/pdf"),
                ("b.txt", b"text", "text/plain"),
            ],
        )
    msg = _extract_sent_message(mock_send)
    dispositions = [
        p["Content-Disposition"]
        for p in msg.walk()
        if p["Content-Disposition"] and "attachment" in p["Content-Disposition"]
    ]
    assert any("a.pdf" in d for d in dispositions)
    assert any("b.txt" in d for d in dispositions)
