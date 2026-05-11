"""Add apartment_listings and saved_apartments tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-10

Supports the apartment_search pipeline: a recurring scan that
ingests SF rental listings from multiple sites, scores them against
the user's criteria, and persists ranked results for the iOS app.

apartment_listings is the canonical store keyed by a stable
listing_id (sha1 of the canonical URL). Re-ingest on each scan: if
the URL is already known, last_seen_at is bumped and is_active stays
true; if a previously-seen URL drops out of the scan for more than
the staleness window the persist job sets is_active=false.

saved_apartments is the user's bookmark list, keyed by listing_id.
A separate table (rather than a flag on apartment_listings) so a
saved listing can survive a wipe-and-rebuild of the listings table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "apartment_listings",
        sa.Column("listing_id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("neighborhood", sa.String(64), nullable=True),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("rent_usd", sa.Integer, nullable=True),
        sa.Column("beds", sa.Integer, nullable=True),
        sa.Column("baths", sa.Float, nullable=True),
        sa.Column("sqft", sa.Integer, nullable=True),
        sa.Column("bike_time_min", sa.Integer, nullable=True),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        sa.Column("score_breakdown", JSONB, nullable=True),
        sa.Column("amenities", JSONB, nullable=True),
        sa.Column("photos", JSONB, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=True),
        sa.Column("raw", JSONB, nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_apartment_listings_is_active_score", "apartment_listings", ["is_active", "score"])
    op.create_index("ix_apartment_listings_last_seen_at", "apartment_listings", ["last_seen_at"])

    op.create_table(
        "saved_apartments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "listing_id",
            sa.String(64),
            sa.ForeignKey("apartment_listings.listing_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_email", sa.String(256), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("listing_id", "user_email", name="uq_saved_apartments_listing_user"),
    )
    op.create_index("ix_saved_apartments_user_email", "saved_apartments", ["user_email"])


def downgrade() -> None:
    op.drop_index("ix_saved_apartments_user_email", table_name="saved_apartments")
    op.drop_table("saved_apartments")
    op.drop_index("ix_apartment_listings_last_seen_at", table_name="apartment_listings")
    op.drop_index("ix_apartment_listings_is_active_score", table_name="apartment_listings")
    op.drop_table("apartment_listings")
