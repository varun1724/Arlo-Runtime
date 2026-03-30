import pytest


@pytest.mark.asyncio
async def test_no_token_returns_403(unauthed_client):
    r = await unauthed_client.get("/jobs")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_wrong_token_returns_401(unauthed_client):
    r = await unauthed_client.get(
        "/jobs", headers={"Authorization": "Bearer wrong-token"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_correct_token_succeeds(client):
    r = await client.get("/jobs")
    assert r.status_code == 200
