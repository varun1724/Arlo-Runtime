import pytest

from app.models.workflow import (
    CreateWorkflowRequest,
    StepCondition,
    StepDefinition,
    WorkflowResponse,
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
