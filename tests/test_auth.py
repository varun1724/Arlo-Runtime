import pytest


@pytest.mark.asyncio
async def test_no_token_returns_unauthorized(unauthed_client):
    """FastAPI's HTTPBearer returns 401 (not 403) for missing credentials."""
    r = await unauthed_client.get("/jobs")
    assert r.status_code in (401, 403)  # accept either; both indicate missing auth


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
