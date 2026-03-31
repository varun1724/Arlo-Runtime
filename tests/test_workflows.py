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
