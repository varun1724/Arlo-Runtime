import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

# NOTE: pytest-asyncio 1.x ignores the legacy event_loop fixture override.
# Loop scope is configured in pyproject.toml under [tool.pytest.ini_options]:
#   asyncio_default_fixture_loop_scope = "session"
#   asyncio_default_test_loop_scope = "session"
# This is the canonical fix for "module-level async engine + pytest-asyncio".


@pytest.fixture(autouse=True)
async def _isolate_db_writes():
    """Round 5.5 hotfix: snapshot existing workflow/job IDs before each
    test and delete anything new afterwards.

    The DB-bound tests in this repo run against whatever ``DATABASE_URL``
    points at — inside the docker test container, that's the live
    production database (the worker is reading the same rows!). There
    is no separate test DB and no transactional rollback. Without this
    fixture, every test that creates a workflow leaves it behind, and
    the worker happily picks them up and burns Claude calls on garbage
    test prompts.

    This fixture is autouse so it applies to ALL tests, including pure
    unit tests that never touch the DB (the snapshot/diff is a few
    milliseconds and the delete is a no-op when nothing changed).

    Long-term fix: a real test database created by a session-scoped
    fixture that points ``DATABASE_URL`` at ``arlo_test`` and runs
    alembic against it. Tracked as Round 6 work.
    """
    from sqlalchemy import delete, select

    from app.db.engine import async_session
    from app.db.models import JobRow, WorkflowRow

    try:
        async with async_session() as session:
            existing_wf = set(
                (await session.execute(select(WorkflowRow.id))).scalars().all()
            )
            existing_jobs = set(
                (await session.execute(select(JobRow.id))).scalars().all()
            )
    except Exception:
        # If the DB isn't reachable (pure-unit test environment), skip
        # the snapshot — the test won't be writing to it anyway.
        existing_wf = None
        existing_jobs = None

    yield

    if existing_wf is None:
        return

    try:
        async with async_session() as session:
            # Jobs first (FK depends on workflows)
            await session.execute(
                delete(JobRow).where(JobRow.id.notin_(existing_jobs))
            )
            await session.execute(
                delete(WorkflowRow).where(WorkflowRow.id.notin_(existing_wf))
            )
            await session.commit()
    except Exception:
        # Cleanup is best-effort. Never let it fail a test.
        pass


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
