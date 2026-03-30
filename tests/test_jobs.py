import pytest


@pytest.mark.asyncio
async def test_create_job(client):
    r = await client.post("/jobs", json={"job_type": "research", "prompt": "Test prompt"})
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "queued"
    assert data["job_type"] == "research"
    assert data["prompt"] == "Test prompt"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_job_invalid_type(client):
    r = await client.post("/jobs", json={"job_type": "invalid", "prompt": "Test"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_job_empty_prompt(client):
    r = await client.post("/jobs", json={"job_type": "research", "prompt": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_job(client):
    create_r = await client.post("/jobs", json={"job_type": "builder", "prompt": "Build something"})
    job_id = create_r.json()["id"]

    r = await client.get(f"/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["id"] == job_id
    assert r.json()["job_type"] == "builder"


@pytest.mark.asyncio
async def test_get_job_not_found(client):
    r = await client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_jobs(client):
    # Create 3 jobs
    for i in range(3):
        await client.post("/jobs", json={"job_type": "research", "prompt": f"Prompt {i}"})

    r = await client.get("/jobs")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 3
    assert len(data["jobs"]) >= 3


@pytest.mark.asyncio
async def test_list_jobs_pagination(client):
    r = await client.get("/jobs?limit=1&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert len(data["jobs"]) <= 1
