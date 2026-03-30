from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow
from app.models.job import TERMINAL_STATUSES
from app.workspace.manager import delete_workspace

logger = logging.getLogger("arlo.cleanup")


async def cleanup_old_workspaces(session: AsyncSession) -> int:
    """Delete workspaces for completed/failed jobs older than the retention period.

    Returns the number of workspaces deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.workspace_retention_hours)

    result = await session.execute(
        select(JobRow).where(
            JobRow.workspace_path.isnot(None),
            JobRow.workspace_pinned == False,  # noqa: E712
            JobRow.status.in_([s.value for s in TERMINAL_STATUSES]),
            JobRow.completed_at < cutoff,
        )
    )
    jobs = list(result.scalars().all())

    deleted = 0
    for job in jobs:
        if job.workspace_path and delete_workspace(job.workspace_path):
            deleted += 1

    if deleted:
        logger.info("Cleaned up %d old workspaces (cutoff: %s)", deleted, cutoff.isoformat())

    return deleted
