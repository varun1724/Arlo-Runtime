import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

# NOTE: pytest-asyncio 1.x ignores the legacy event_loop fixture override.
# Loop scope is configured in pyproject.toml under [tool.pytest.ini_options]:
#   asyncio_default_fixture_loop_scope = "session"
#   asyncio_default_test_loop_scope = "session"
# This is the canonical fix for "module-level async engine + pytest-asyncio".


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers["Authorization"] = f"Bearer {settings.arlo_auth_token}"
        yield ac


@pytest.fixture
async def unauthed_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
