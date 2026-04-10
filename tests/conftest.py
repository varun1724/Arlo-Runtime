import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop.

    The async SQLAlchemy engine in ``app/db/engine.py`` is created at
    import time and binds its connection pool to whatever event loop is
    active when it first runs a query. With the default function-scoped
    event loop fixture, every test gets a fresh loop and the second test
    onward fails with ``sqlalchemy.exc.InterfaceError`` because the
    pooled connections are bound to a dead loop.

    Sharing one loop for the whole session keeps the engine, the pool,
    and every test on the same loop. This is the canonical fix for
    "module-level async engine + pytest-asyncio".
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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
