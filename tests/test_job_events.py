import pytest


@pytest.mark.asyncio
async def test_job_creation_logs_event(client):
    create_r = await client.post("/jobs", json={"job_type": "research", "prompt": "Test events"})
    job_id = create_r.json()["id"]

    r = await client.get(f"/jobs/{job_id}/logs")
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) >= 1
    assert events[0]["event_type"] == "created"


@pytest.mark.asyncio
async def test_cancel_logs_event(client):
    create_r = await client.post("/jobs", json={"job_type": "research", "prompt": "Cancel events"})
    job_id = create_r.json()["id"]
    await client.post(f"/jobs/{job_id}/cancel")

    r = await client.get(f"/jobs/{job_id}/logs")
    assert r.status_code == 200
    events = r.json()["events"]
    event_types = [e["event_type"] for e in events]
    assert "created" in event_types
    assert "canceled" in event_types


@pytest.mark.asyncio
async def test_job_logs_not_found(client):
    r = await client.get("/jobs/00000000-0000-0000-0000-000000000000/logs")
    assert r.status_code == 404
