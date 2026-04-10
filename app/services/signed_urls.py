"""Stateless HMAC-signed URLs for email-driven approval and artifact downloads.

Round 5: the notification emails need clickable links that don't require
the standard bearer token (you can't include HTTP headers in a mailto
link). We mint short-lived HMAC tokens carrying the workflow id, a
choice number, and a purpose tag ('approve' or 'artifacts'). The tokens
are verified by the corresponding HTTP endpoints.

**Why stateless?** No DB table, no cleanup job, no state to corrupt.
The signature IS the proof that we minted the token. The expiry is
embedded in the payload and verified server-side. Rotating
``arlo_auth_token`` (the HMAC secret) invalidates all in-flight tokens,
which is acceptable for a 48-hour TTL.

**Threat model.** HMAC-SHA256 with a 256-bit secret is infeasible to
forge by brute force. The link travels over TLS in the email. The
``notification_base_url`` is typically a Tailscale-only IP so the link
only works inside your private network. Acceptable for a personal tool.

**Token format:** ``<base64url-payload>.<hex-truncated-signature>``
where payload is the JSON dict shown in :func:`sign_approval_token`.
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import json
import time
import uuid

from app.core.config import settings

APPROVAL_TOKEN_TTL_SECONDS = 48 * 3600  # 48 hours — long enough to read an email on the next day


def _encode_payload(data: dict) -> str:
    """Compact-JSON then base64url-encode (no padding)."""
    payload_json = json.dumps(data, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")


def _decode_payload(b64: str) -> dict:
    """Inverse of ``_encode_payload``. Re-pads the base64 string as needed."""
    padded = b64 + "=" * (-len(b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode())


def _sign(payload_b64: str) -> str:
    """Compute the HMAC signature for a payload. Truncated to 32 hex chars
    (128 bits) — more than enough entropy for a 48-hour window and keeps
    URL length reasonable."""
    return hmac.new(
        settings.arlo_auth_token.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


def sign_token(
    workflow_id: uuid.UUID,
    purpose: str,
    *,
    choice: int | None = None,
    ttl_seconds: int = APPROVAL_TOKEN_TTL_SECONDS,
) -> str:
    """Mint a signed token for a workflow operation.

    Args:
        workflow_id: The workflow this token authorizes.
        purpose: What the token is for. Must be either ``"approve"``
            (for the approve-by-link endpoint) or ``"artifacts"`` (for
            the workspace download endpoint). The purpose is verified
            on the receiving side — a token signed for one purpose
            cannot be used for the other.
        choice: For ``purpose="approve"``, the selected ranking number
            (1-indexed), or 0 to skip the build. Ignored for other
            purposes.
        ttl_seconds: How long the token is valid (default 48 hours).

    Returns:
        A token string suitable for embedding in a URL:
        ``<payload>.<signature>``.
    """
    payload: dict = {
        "wf": str(workflow_id),
        "p": purpose,
        "exp": int(time.time()) + ttl_seconds,
    }
    if choice is not None:
        payload["choice"] = choice
    payload_b64 = _encode_payload(payload)
    signature = _sign(payload_b64)
    return f"{payload_b64}.{signature}"


def verify_signed_token(token: str, expected_purpose: str) -> dict | None:
    """Verify a signed token and return the payload if it's valid.

    Returns ``None`` if the token is malformed, the signature is
    invalid, the token is expired, or the purpose doesn't match.
    Callers must check the returned ``wf`` field matches the URL's
    workflow id (so a token for one workflow can't be replayed against
    another).

    Args:
        token: The full ``payload.signature`` string from the URL.
        expected_purpose: The purpose the caller wants to authorize.
            Must be exactly the string passed to ``sign_token``.
    """
    if not isinstance(token, str) or "." not in token:
        return None
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return None
    # Constant-time signature comparison to prevent timing attacks
    expected_sig = _sign(payload_b64)
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = _decode_payload(payload_b64)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    # Check expiry
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time():
        return None
    # Check purpose
    if payload.get("p") != expected_purpose:
        return None
    return payload
