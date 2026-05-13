"""Add polymarket_signals table for copy-trade signals

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-12

The polymarket_signals pipeline scans the public Polymarket leaderboard
(top ~50 wallets by monthly+weekly profit/volume) and aggregates their
currently-open positions. A row in this table represents one outcome
asset (a specific Yes/No or named outcome on a specific market) that is
held by enough top traders to qualify as a "common signal" worth
surfacing.

The whole signal lifecycle is rebuilt on each scan — we don't track
historical price drift here. Rows persist across scans for two reasons:
(a) so the iOS app can show "first surfaced 3 days ago," and (b) so the
notification step can avoid re-emailing the same signal. ``is_live`` is
flipped to False when a scan no longer sees the asset (either it dropped
below the threshold or the market resolved).

``holders`` is JSONB because the shape is wide and rarely queried —
it's mostly for UI display ("which traders are in this?") and audit.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "polymarket_signals",
        sa.Column("asset_id", sa.String(80), primary_key=True),
        sa.Column("condition_id", sa.String(80), nullable=False),
        sa.Column("event_id", sa.String(40), nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("outcome_index", sa.Integer, nullable=False),
        sa.Column("slug", sa.String(256), nullable=True),
        sa.Column("event_slug", sa.String(256), nullable=True),
        sa.Column("icon_url", sa.Text, nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),

        sa.Column("n_holders", sa.Integer, nullable=False),
        sa.Column("avg_entry_price", sa.Float, nullable=False),
        sa.Column("cur_price", sa.Float, nullable=False),
        sa.Column("target_exit_price", sa.Float, nullable=False),
        sa.Column("upside_pct", sa.Float, nullable=False),
        sa.Column("avg_pnl_pct", sa.Float, nullable=False),
        sa.Column("total_size_usd", sa.Float, nullable=False),
        sa.Column("days_to_resolution", sa.Float, nullable=True),
        sa.Column("edge_score", sa.Float, nullable=False),
        sa.Column("recommended_action", sa.Text, nullable=True),

        sa.Column("holders", JSONB, nullable=False),

        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_scan_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("is_live", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_polymarket_signals_is_live",
        "polymarket_signals",
        ["is_live"],
    )
    op.create_index(
        "ix_polymarket_signals_edge_score",
        "polymarket_signals",
        ["edge_score"],
    )
    op.create_index(
        "ix_polymarket_signals_end_date",
        "polymarket_signals",
        ["end_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_polymarket_signals_end_date", table_name="polymarket_signals")
    op.drop_index("ix_polymarket_signals_edge_score", table_name="polymarket_signals")
    op.drop_index("ix_polymarket_signals_is_live", table_name="polymarket_signals")
    op.drop_table("polymarket_signals")
