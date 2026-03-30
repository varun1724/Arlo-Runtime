from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router as jobs_router
from app.api.workflow_routes import router as workflows_router
from app.db.base import Base
from app.db.engine import engine
from app.db.models import JobRow, WorkflowRow  # noqa: F401 — ensure models are registered


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: create tables if they don't exist.
    # In production, Alembic migrations are the source of truth.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Arlo Runtime", version="0.1.0", lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(workflows_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
