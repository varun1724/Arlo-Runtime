import pytest


@pytest.mark.asyncio
async def test_list_templates(client):
    r = await client.get("/workflows/templates")
    assert r.status_code == 200
    data = r.json()
    assert "startup_idea_pipeline" in data
    assert "side_hustle_pipeline" in data
    assert "strategy_evolution" in data


@pytest.mark.asyncio
async def test_create_workflow_from_template(client):
    r = await client.post(
        "/workflows/from-template/startup_idea_pipeline",
        json={"initial_context": {"domain": "test domain", "focus_areas": "testing"}},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "running"
    assert data["template_id"] == "startup_idea_pipeline"
    assert data["context"]["domain"] == "test domain"


@pytest.mark.asyncio
async def test_create_workflow_from_nonexistent_template(client):
    r = await client.post(
        "/workflows/from-template/does_not_exist",
        json={"initial_context": {}},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_workflow_missing_required_context(client):
    # startup_idea_pipeline requires "domain"
    r = await client.post(
        "/workflows/from-template/startup_idea_pipeline",
        json={"initial_context": {"not_domain": "test"}},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_workflows(client):
    await client.post(
        "/workflows/from-template/startup_idea_pipeline",
        json={"initial_context": {"domain": "list test"}},
    )
    r = await client.get("/workflows")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


@pytest.mark.asyncio
async def test_get_workflow(client):
    create_r = await client.post(
        "/workflows/from-template/startup_idea_pipeline",
        json={"initial_context": {"domain": "get test"}},
    )
    wf_id = create_r.json()["id"]
    r = await client.get(f"/workflows/{wf_id}")
    assert r.status_code == 200
    assert r.json()["id"] == wf_id


@pytest.mark.asyncio
async def test_get_workflow_not_found(client):
    r = await client.get("/workflows/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_startup_pipeline_research_steps_have_output_schemas():
    """Round 2: every research step in startup_idea_pipeline must have
    an output_schema set, otherwise validation silently degrades."""
    from app.workflows.templates import STARTUP_IDEA_PIPELINE

    research_steps = [
        s for s in STARTUP_IDEA_PIPELINE["steps"]
        if s["job_type"] == "research" and not s.get("requires_approval", False)
    ]

    for step in research_steps:
        assert step.get("output_schema") is not None, (
            f"step {step['name']} is a research step but has no output_schema"
        )
        assert step.get("max_retries", 0) > 0, (
            f"step {step['name']} is a research step but has no auto-retry configured"
        )


def test_startup_pipeline_build_mvp_has_context_inputs():
    """Round 2: build_mvp must prune context to only the synthesis key."""
    from app.workflows.templates import STARTUP_IDEA_PIPELINE

    build_mvp = next(s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "build_mvp")
    assert build_mvp["context_inputs"] == ["synthesis"]
