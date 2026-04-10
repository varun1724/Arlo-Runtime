from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.SUCCEEDED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELED,
}


class StepCondition(BaseModel):
    """Simple condition evaluated against workflow context."""

    field: str
    operator: str  # "exists", "not_empty", "contains", "equals"
    value: str | None = None


class StepDefinition(BaseModel):
    name: str
    job_type: str  # "research" or "builder"
    prompt_template: str
    output_key: str
    condition: StepCondition | None = None
    timeout_override: int | None = None
    loop_to: int | None = None
    max_loop_count: int | None = None
    requires_approval: bool = False  # if True, workflow pauses before this step
    max_retries: int = 0  # auto-retry this step N times before failing the workflow
    output_schema: str | None = None
    """Name of a Pydantic model in app.workflows.schemas.STEP_OUTPUT_SCHEMAS.

    When set on a research step, the job's output JSON is validated against
    this schema. Validation failures raise ClaudeRunError, which feeds the
    existing max_retries auto-retry path. Defaults to None for backward
    compatibility — old templates retain their loose-mode behavior.
    """
    context_inputs: list[str] | None = None
    """Whitelist of context keys to pass when rendering this step's prompt.

    When set, only these keys are passed to the prompt formatter. The full
    workflow context is still saved to the workflow row for debugging.
    Defaults to None (= pass all keys, current behavior).
    """


# --- Request models ---


class CreateWorkflowRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    template_id: str | None = None
    steps: list[StepDefinition] = Field(..., min_length=1)
    initial_context: dict = Field(default_factory=dict)


class CreateWorkflowFromTemplateRequest(BaseModel):
    initial_context: dict = Field(default_factory=dict)


class ApproveStepRequest(BaseModel):
    """Approve or skip a step that requires approval."""
    approved: bool = True
    context_overrides: dict = Field(default_factory=dict)  # inject/override context before this step runs


# --- Response models ---


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    template_id: str | None = None
    status: WorkflowStatus
    context: dict
    step_definitions: list[StepDefinition]
    current_step_index: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowResponse]
    count: int


# --- SSE event model ---


class WorkflowProgressEvent(BaseModel):
    workflow_id: uuid.UUID
    status: WorkflowStatus
    current_step_index: int
    current_step_name: str | None = None
    progress_message: str | None = None
