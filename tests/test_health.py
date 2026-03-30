import pytest


@pytest.mark.asyncio
async def test_health(unauthed_client):
    r = await unauthed_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
