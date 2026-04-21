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
    """Maximum number of times the ``loop_to`` step is allowed to execute,
    INCLUDING its initial run.

    Set to ``2`` for "run once, then loop back at most once more (= 2 total
    executions of the loop_to step)". Set to ``1`` to effectively disable
    looping (the step runs once and the loop never fires because the
    counter immediately equals max).

    Note: this counts executions of the ``loop_to`` step itself, NOT
    iterations of the loop body. With Round 3's ``loop_condition``, the
    loop only fires when both the condition is true AND the count is
    below this maximum. See ``advance_workflow`` in
    ``app/services/workflow_service.py`` for the exact check.
    """
    requires_approval: bool = False  # if True, workflow pauses before this step
    max_retries: int = 0  # auto-retry this step N times before failing the workflow
    model_override: str | None = None
    """Per-step Claude model override (e.g. ``"claude-opus-4-7"``, ``"sonnet"``).

    When set, this value is passed to the Claude CLI ``--model`` flag instead
    of the global ``settings.research_model`` (or ``settings.builder_model``)
    default. Used to run individual pipeline steps on a stronger model
    without affecting other pipelines that share the research executor.
    Defaults to None — steps use the configured global model.
    """
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
    loop_condition: StepCondition | None = None
    """Round 3: gate ``loop_to`` on a condition evaluated after the step
    completes successfully.

    Without this field, ``loop_to``+``max_loop_count`` always loops back
    until the count is exhausted. With it, the loop only fires when the
    condition evaluates true. This lets contrarian_analysis loop back to
    landscape_scan ONLY when the survivor count is below a threshold.
    Defaults to None — when None, the existing unconditional loop behavior
    is preserved for backward compatibility (e.g. strategy_evolution).
    """
    required_artifacts: list[str] | None = None
    """Round 4 (side hustle): per-step list of filenames the builder must
    produce in its workspace. If any are missing, ``execute_builder_job``
    raises ``ClaudeRunError``, which feeds the existing ``max_retries``
    auto-retry path.

    When None (default), the builder falls back to the module-level
    ``REQUIRED_BUILDER_ARTIFACTS`` tuple (``README.md``, ``BUILD_DECISIONS.md``)
    which was originally set for the startup pipeline. This lets each
    pipeline define its own enforcement list without changing the builder's
    fallback behavior — e.g. the side hustle ``build_n8n_workflow`` step
    requires ``workflow.json`` and ``test_payload.json`` on top of the
    common README/BUILD_DECISIONS pair.
    """


# --- Request models ---


class CreateWorkflowRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    template_id: str | None = None
    steps: list[StepDefinition] = Field(..., min_length=1)
    initial_context: dict = Field(default_factory=dict)


class CreateWorkflowFromTemplateRequest(BaseModel):
    initial_context: dict = Field(default_factory=dict)
    deep_research_mode: bool = False
    """Round 5: Claude Max opt-in for more generous research. When true,
    the pipeline runs with bumped ``max_loop_count`` on the recovery
    loop, a longer initial landscape timeout, and a ``deep_mode="true"``
    context variable that the prompts check to broaden their search
    scope. Default is False — the normal pipeline is unchanged for
    API-billed users who pay per-token. Recommended ON for users with
    a Claude Max subscription where token cost is effectively zero."""


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
    # Round 3: aggregated cost across all jobs in this workflow.
    # Computed in the API serializer; nullable when no jobs report usage.
    total_tokens_input: int | None = None
    total_tokens_output: int | None = None
    total_estimated_cost_usd: float | None = None
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
    # Round 4: live cost visibility during long runs. Populated from the
    # latest job's row, which is updated every ~5 seconds by the streaming
    # progress callback in research.py / builder.py.
    current_job_id: uuid.UUID | None = None
    tokens_input_so_far: int | None = None
    tokens_output_so_far: int | None = None
    cost_so_far_usd: float | None = None
