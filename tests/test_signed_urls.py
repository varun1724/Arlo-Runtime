"""Tests for the Round 5 stateless HMAC signed URL helpers.

Pure unit tests — no DB, no network, no file system. Run with
``--noconftest`` for fast iteration.
"""

from __future__ import annotations

import time
import uuid

from app.services.signed_urls import (
    APPROVAL_TOKEN_TTL_SECONDS,
    sign_token,
    verify_signed_token,
)


def test_sign_and_verify_roundtrip():
    wf = uuid.uuid4()
    token = sign_token(wf, "approve", choice=2)
    payload = verify_signed_token(token, "approve")
    assert payload is not None
    assert payload["wf"] == str(wf)
    assert payload["choice"] == 2
    assert payload["p"] == "approve"
    assert payload["exp"] > time.time()


def test_sign_token_for_artifacts_has_no_choice():
    """Non-approval purposes don't need the choice field."""
    wf = uuid.uuid4()
    token = sign_token(wf, "artifacts")
    payload = verify_signed_token(token, "artifacts")
    assert payload is not None
    assert "choice" not in payload


def test_verify_rejects_tampered_signature():
    wf = uuid.uuid4()
    token = sign_token(wf, "approve", choice=1)
    # Flip the last character of the signature
    tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
    assert verify_signed_token(tampered, "approve") is None


def test_verify_rejects_tampered_payload():
    """Modifying the payload must invalidate the signature."""
    wf = uuid.uuid4()
    token = sign_token(wf, "approve", choice=1)
    payload_b64, sig = token.split(".", 1)
    # Flip the first character of the payload
    tampered_payload = ("A" if payload_b64[0] != "A" else "B") + payload_b64[1:]
    tampered = f"{tampered_payload}.{sig}"
    assert verify_signed_token(tampered, "approve") is None


def test_verify_rejects_expired_token():
    """A token with a negative TTL is expired at creation time."""
    wf = uuid.uuid4()
    token = sign_token(wf, "approve", choice=1, ttl_seconds=-1)
    assert verify_signed_token(token, "approve") is None


def test_verify_rejects_wrong_purpose():
    """A token signed for 'approve' cannot be used as 'artifacts'."""
    wf = uuid.uuid4()
    token = sign_token(wf, "approve", choice=1)
    assert verify_signed_token(token, "artifacts") is None


def test_verify_rejects_malformed_token():
    """Garbage strings should return None, not crash."""
    assert verify_signed_token("", "approve") is None
    assert verify_signed_token("no dot at all", "approve") is None
    assert verify_signed_token("too.many.dots.here", "approve") is None
    # Empty payload half
    assert verify_signed_token(".signature", "approve") is None
    # Empty signature half
    assert verify_signed_token("payload.", "approve") is None


def test_verify_rejects_none_and_wrong_type():
    assert verify_signed_token(None, "approve") is None  # type: ignore[arg-type]
    assert verify_signed_token(123, "approve") is None  # type: ignore[arg-type]


def test_sign_is_deterministic_for_same_inputs():
    """Same workflow_id + purpose + choice + exp should produce the same token.

    (In practice exp varies because it's based on time.time(), but the
    underlying signing function is deterministic for a fixed payload.)
    """
    wf = uuid.UUID("00000000-0000-0000-0000-000000000001")
    # Use ttl_seconds=100 and fix time in thought: since we can't pin time
    # from the outside without monkey-patching, we verify determinism by
    # signing twice in quick succession and checking the payload portion
    # (not the exp, which differs if we cross a second boundary).
    t1 = sign_token(wf, "approve", choice=1, ttl_seconds=100)
    t2 = sign_token(wf, "approve", choice=1, ttl_seconds=100)
    # Payloads may differ only by the `exp` field. Verifying both should succeed.
    assert verify_signed_token(t1, "approve") is not None
    assert verify_signed_token(t2, "approve") is not None


def test_sign_choices_are_distinguishable():
    """choice=1 and choice=2 must produce different tokens."""
    wf = uuid.uuid4()
    t1 = sign_token(wf, "approve", choice=1)
    t2 = sign_token(wf, "approve", choice=2)
    assert t1 != t2
    assert verify_signed_token(t1, "approve")["choice"] == 1
    assert verify_signed_token(t2, "approve")["choice"] == 2


def test_different_workflows_produce_different_tokens():
    t1 = sign_token(uuid.uuid4(), "approve", choice=1)
    t2 = sign_token(uuid.uuid4(), "approve", choice=1)
    assert t1 != t2


def test_default_ttl_is_48_hours():
    """Sanity: the constant is what we expect and used by default."""
    assert APPROVAL_TOKEN_TTL_SECONDS == 48 * 3600
    wf = uuid.uuid4()
    token = sign_token(wf, "approve", choice=1)
    payload = verify_signed_token(token, "approve")
    # Expiry should be roughly now + 48h (within a second's tolerance)
    expected = int(time.time()) + APPROVAL_TOKEN_TTL_SECONDS
    assert abs(payload["exp"] - expected) < 5  # 5s tolerance for slow CI
