"""Add user_bankroll table for Polymarket bet sizing

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-13

Stores the user's current Polymarket bankroll so the signals API can
compute a recommended bet size per signal (quarter-Kelly with a 70%
confidence discount, capped at 15% of bankroll). One row per user
email — single-user app today, but the schema is keyed by email so
the same shape works for multi-user later.

The user updates this manually after each trade resolves (POST/PUT to
/bankroll with the new balance). We deliberately do NOT track each
individual bet here — that would require either a live Polymarket
account integration or a clunky "log every bet" UX. A single
balance + manual update is the lowest-friction loop that still gives
the sizing logic something real to work with.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_bankroll",
        sa.Column("user_email", sa.String(256), primary_key=True),
        sa.Column("balance_usd", sa.Float, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("notes", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("user_bankroll")
