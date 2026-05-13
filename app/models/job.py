from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class JobType(StrEnum):
    RESEARCH = "research"
    BUILDER = "builder"
    N8N = "n8n"
    TRADING = "trading"
    OPTIMIZE = "optimize"
    APARTMENTS_PERSIST = "apartments_persist"
    POLYMARKET_SCAN = "polymarket_scan"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    STOPPED_BY_POLICY = "stopped_by_policy"


class JobStopReason(StrEnum):
    TIMEOUT = "timeout"
    ITERATION_LIMIT = "iteration_limit"
    POLICY = "policy"
    ERROR = "error"
    MANUAL = "manual"


TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELED,
    JobStatus.STOPPED_BY_POLICY,
}


# --- Request models ---


class CreateJobRequest(BaseModel):
    job_type: JobType
    # Round 5.6 hotfix: deep_research_mode produces landscape + deep_dive +
    # contrarian outputs that the synthesis step stacks into a single prompt
    # via {landscape}{deep_dive}{contrarian} substitution. First real deep
    # run hit ~197k chars at the synthesis step and tripped the old 100k
    # cap. The new limit (1M chars ≈ 250k tokens) sits well inside Claude
    # Sonnet 4.6's 200k-token context window while still catching runaway
    # prompts before they reach the CLI. Leave this as a validation limit,
    # not an unbounded field — the cap catches real bugs (e.g. a template
    # that accidentally interpolates a circular reference).
    prompt: str = Field(..., min_length=1, max_length=1_000_000)


# --- Response models ---


class JobResponse(BaseModel):
    id: uuid.UUID
    job_type: JobType
    status: JobStatus
    prompt: str
    current_step: str | None = None
    progress_message: str | None = None
    iteration_count: int = 0
    result_preview: str | None = None
    result_data: str | None = None
    error_message: str | None = None
    stop_reason: str | None = None
    workspace_path: str | None = None
    workspace_pinned: bool = False
    workflow_id: uuid.UUID | None = None
    step_index: int | None = None
    # Round 3: token usage and estimated cost (nullable for legacy rows
    # and Claude CLI versions that don't return usage data)
    tokens_input: int | None = None
    tokens_output: int | None = None
    estimated_cost_usd: float | None = None
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    count: int


# --- SSE event model ---


class JobProgressEvent(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    current_step: str | None = None
    progress_message: str | None = None
    iteration_count: int = 0


# --- Event log model ---


class JobEventResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    event_type: str
    message: str | None = None
    metadata_json: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
