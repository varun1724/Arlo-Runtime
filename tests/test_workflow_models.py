import pytest

from app.models.workflow import (
    CreateWorkflowRequest,
    StepCondition,
    StepDefinition,
    WorkflowStatus,
)


SAMPLE_STEPS = [
    {
        "name": "research",
        "job_type": "research",
        "prompt_template": "Research {domain}",
        "output_key": "research_report",
    },
    {
        "name": "build",
        "job_type": "builder",
        "prompt_template": "Build MVP from {research_report}",
        "output_key": "mvp_result",
        "condition": {"field": "research_report", "operator": "not_empty"},
    },
]


@pytest.mark.asyncio
async def test_step_definition_parses():
    step = StepDefinition.model_validate(SAMPLE_STEPS[0])
    assert step.name == "research"
    assert step.condition is None
    assert step.loop_to is None


@pytest.mark.asyncio
async def test_step_with_condition():
    step = StepDefinition.model_validate(SAMPLE_STEPS[1])
    assert step.condition is not None
    assert step.condition.field == "research_report"
    assert step.condition.operator == "not_empty"


@pytest.mark.asyncio
async def test_create_workflow_request():
    req = CreateWorkflowRequest(
        name="Test Pipeline",
        steps=[StepDefinition.model_validate(s) for s in SAMPLE_STEPS],
        initial_context={"domain": "AI tools"},
    )
    assert len(req.steps) == 2
    assert req.initial_context["domain"] == "AI tools"


@pytest.mark.asyncio
async def test_create_workflow_requires_steps():
    with pytest.raises(Exception):
        CreateWorkflowRequest(name="Empty", steps=[])


@pytest.mark.asyncio
async def test_step_with_loop_to():
    step = StepDefinition(
        name="evolve",
        job_type="research",
        prompt_template="Evolve",
        output_key="evolved",
        loop_to=2,
        max_loop_count=10,
    )
    assert step.loop_to == 2
    assert step.max_loop_count == 10


@pytest.mark.asyncio
async def test_step_with_max_retries():
    step = StepDefinition(
        name="risky",
        job_type="research",
        prompt_template="Risky step",
        output_key="result",
        max_retries=3,
    )
    assert step.max_retries == 3


@pytest.mark.asyncio
async def test_step_with_requires_approval():
    step = StepDefinition(
        name="approval",
        job_type="research",
        prompt_template="Needs approval",
        output_key="approved",
        requires_approval=True,
    )
    assert step.requires_approval is True


@pytest.mark.asyncio
async def test_step_with_loop_condition():
    """Round 3: loop_to gated by loop_condition (used by contrarian recovery loop)."""
    step = StepDefinition(
        name="contrarian",
        job_type="research",
        prompt_template="...",
        output_key="contrarian",
        loop_to=0,
        max_loop_count=2,
        loop_condition=StepCondition(
            field="contrarian",
            operator="survivor_count_below",
            value="3",
        ),
    )
    assert step.loop_to == 0
    assert step.loop_condition is not None
    assert step.loop_condition.operator == "survivor_count_below"
    assert step.loop_condition.value == "3"


@pytest.mark.asyncio
async def test_step_loop_condition_defaults_to_none():
    """Backward compat: existing templates without loop_condition keep working."""
    step = StepDefinition(
        name="x",
        job_type="research",
        prompt_template="...",
        output_key="x",
        loop_to=1,
        max_loop_count=10,
    )
    assert step.loop_condition is None


# ─────────────────────────────────────────────────────────────────────
# Round 4 (side hustle): StepDefinition.required_artifacts
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_step_definition_accepts_required_artifacts():
    """Round 4: per-step builder enforcement list. The side hustle
    build_n8n_workflow step requires workflow.json and test_payload.json
    on top of the default README/BUILD_DECISIONS pair."""
    step = StepDefinition(
        name="build_n8n_workflow",
        job_type="builder",
        prompt_template="build the workflow",
        output_key="build_result",
        required_artifacts=[
            "workflow.json",
            "README.md",
            "BUILD_DECISIONS.md",
            "test_payload.json",
        ],
    )
    assert step.required_artifacts == [
        "workflow.json",
        "README.md",
        "BUILD_DECISIONS.md",
        "test_payload.json",
    ]


@pytest.mark.asyncio
async def test_step_definition_required_artifacts_defaults_to_none():
    """Backward compat: existing templates without required_artifacts
    keep their current behavior (builder falls back to REQUIRED_BUILDER_ARTIFACTS)."""
    step = StepDefinition(
        name="build_mvp",
        job_type="builder",
        prompt_template="build",
        output_key="mvp_result",
    )
    assert step.required_artifacts is None
