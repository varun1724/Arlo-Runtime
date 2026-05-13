"""Widen paper_trades.status to VARCHAR(32)

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-13

The 0009 schema put status at VARCHAR(16), which fits 'open',
'closed_win', 'closed_loss', 'closed_stale', 'closed_other',
'closed_resolved' — but NOT 'closed_signal_dropped' (21 chars).

When a paper trade's source signal went is_live=False, the engine
tried to write the longer value and Postgres raised
StringDataRightTruncationError. The exception poisoned the
SQLAlchemy session; the rollback-on-finalize fallback also failed
(PendingRollbackError), so the workflow row stayed status='running'
and the trade row stayed status='open'. Every subsequent 5-minute
cycle picked up the same poisoned state and crashed at the same
spot — never reaching the entry pass — which is why no new trades
got entered for several hours of valid Polymarket signals.

This widening hot-fix was applied on the production DB before this
migration was written, so this file is mostly for parity with the
local copy + future fresh deploys.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "paper_trades",
        "status",
        existing_type=sa.String(16),
        type_=sa.String(32),
        existing_nullable=False,
        existing_server_default="open",
    )


def downgrade() -> None:
    op.alter_column(
        "paper_trades",
        "status",
        existing_type=sa.String(32),
        type_=sa.String(16),
        existing_nullable=False,
        existing_server_default="open",
    )
