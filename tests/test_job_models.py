"""Tests for the Pydantic request/response models in app/models/job.py.

Round 5.6: added after the first real deep_research_mode run tripped
the CreateJobRequest.prompt 100k character cap at the synthesis step.
These tests lock in the new 1M cap so we don't regress and also verify
the cap still catches absurdly large prompts (the bound exists to
catch real bugs, not to block legitimate deep-research outputs).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.job import CreateJobRequest, JobType


def test_create_job_request_accepts_normal_prompt():
    req = CreateJobRequest(job_type=JobType.RESEARCH, prompt="small prompt")
    assert req.prompt == "small prompt"


def test_create_job_request_rejects_empty_prompt():
    with pytest.raises(ValidationError):
        CreateJobRequest(job_type=JobType.RESEARCH, prompt="")


def test_create_job_request_accepts_large_deep_research_prompt():
    """Regression: deep_research_mode stacks landscape + deep_dive +
    contrarian into the synthesis prompt. First real deep run hit
    ~197k chars at the synthesis step. The new cap must comfortably
    accept that with room to grow."""
    large_prompt = "x" * 500_000  # 500KB — well above the old 100k cap
    req = CreateJobRequest(job_type=JobType.RESEARCH, prompt=large_prompt)
    assert len(req.prompt) == 500_000


def test_create_job_request_accepts_prompt_at_new_cap():
    """The cap is 1M characters. Exactly at the cap should pass."""
    prompt_at_cap = "x" * 1_000_000
    req = CreateJobRequest(job_type=JobType.RESEARCH, prompt=prompt_at_cap)
    assert len(req.prompt) == 1_000_000


def test_create_job_request_rejects_prompt_over_new_cap():
    """One character over the cap should still be rejected — the cap
    exists to catch runaway prompts (e.g. a template that accidentally
    interpolates a circular reference)."""
    prompt_over_cap = "x" * 1_000_001
    with pytest.raises(ValidationError):
        CreateJobRequest(job_type=JobType.RESEARCH, prompt=prompt_over_cap)
