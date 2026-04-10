"""Add token usage and cost columns to jobs

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-09

Round 3 of startup pipeline improvements: per-job token usage and
estimated USD cost. Populated by the job handlers after each Claude
CLI call. All three columns are nullable so existing rows are valid
without backfill.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("tokens_input", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("tokens_output", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("estimated_cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "estimated_cost_usd")
    op.drop_column("jobs", "tokens_output")
    op.drop_column("jobs", "tokens_input")
