"""Add paper_bankroll and paper_trades for sim-mode validation

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-13

Before deploying real money on Polymarket signals, run a week of
paper trading to validate the signal quality + sizing math. The
paper money loop is fully separate from the user's real-bankroll
table (added in 0008) — no overlap, no risk of cross-contamination.

paper_bankroll holds one row per "session" keyed by ``scope``. The
default scope is what the auto-engine uses; the schema leaves room
to run multiple simultaneous strategies later (e.g., a more
conservative variant). Each session has a start time, an optional
end time (used to auto-stop a fixed-duration paper run), and
running totals.

paper_trades is one row per open-and-then-closed position. The
engine writes a row when entering, refreshes ``cur_price`` +
``unrealized_pnl_usd`` every cycle, and flips status from "open"
to a closed_* variant on exit. ``shares = stake_usd / entry_price``
(Polymarket shares pay out $1 each on resolution, so shares × price
= USD value at any time).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_bankroll",
        sa.Column("scope", sa.String(32), primary_key=True),
        sa.Column("initial_balance_usd", sa.Float, nullable=False),
        sa.Column("current_balance_usd", sa.Float, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_realized_pnl_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("trade_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("win_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("loss_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )

    op.create_table(
        "paper_trades",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(32), nullable=False, server_default="default"),
        sa.Column("asset_id", sa.String(80), nullable=False),
        sa.Column("condition_id", sa.String(80), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("outcome_index", sa.Integer, nullable=False),
        sa.Column("slug", sa.String(256), nullable=True),
        sa.Column("event_slug", sa.String(256), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),

        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("target_exit_price", sa.Float, nullable=False),
        sa.Column("edge_score_at_entry", sa.Float, nullable=False),
        sa.Column("stake_usd", sa.Float, nullable=False),
        sa.Column("shares", sa.Float, nullable=False),

        sa.Column("cur_price", sa.Float, nullable=False),
        sa.Column("cur_value_usd", sa.Float, nullable=False),
        sa.Column("unrealized_pnl_usd", sa.Float, nullable=False),

        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("realized_pnl_usd", sa.Float, nullable=True),
        sa.Column("exit_price", sa.Float, nullable=True),
        sa.Column("exit_reason", sa.Text, nullable=True),
    )
    op.create_index("ix_paper_trades_status", "paper_trades", ["status"])
    op.create_index("ix_paper_trades_asset_id", "paper_trades", ["asset_id"])
    op.create_index("ix_paper_trades_scope", "paper_trades", ["scope"])


def downgrade() -> None:
    op.drop_index("ix_paper_trades_scope", table_name="paper_trades")
    op.drop_index("ix_paper_trades_asset_id", table_name="paper_trades")
    op.drop_index("ix_paper_trades_status", table_name="paper_trades")
    op.drop_table("paper_trades")
    op.drop_table("paper_bankroll")
