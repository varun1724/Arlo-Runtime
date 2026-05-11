"""Add listing_group_id and dedup-signal columns to apartment_listings

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-10

The apartment_search pipeline now scans multiple rental sites (Craigslist,
Redfin, Zumper, Padmapper, plus soft Reddit signals). The same physical
apartment frequently appears on multiple sites with different URLs, so the
canonical row needs a stable identity beyond the URL hash.

``listing_group_id`` is a deterministic hash computed in the apartments_persist
job from a tiered match rule (codex Round 2 review):

  1. sha1(normalized_address + "|" + unit) — gold standard
  2. sha1(normalized_address + "|" + rent_bucket + "|" + beds) — strong when no unit
  3. sha1(lat_round_4dp + "|" + lon_round_4dp + "|" + rent_bucket + "|" + beds)
     — fallback for coord-only sources (~11m precision)
  4. sha1(canonical_url) — terminal fallback so unmergeable listings still get a
     unique group rather than colliding

Listings whose group_id matches are treated as the same physical apartment.
GET /apartments groups by listing_group_id and returns the highest-scoring
representative with an attached sources[] array showing every URL that
points at the same apartment. Notification fires on new GROUPS (not new
URLs), so finding a Craigslist+Zumper crosspost emails once, not twice.

The supporting signal columns (``canonical_address``, ``unit``,
``building_name``, ``latitude``, ``longitude``, ``photo_fingerprint``)
let the persist job's grouping function operate without re-parsing the
raw JSONB on every run, and let the iOS app surface "Building X, Unit
Y" cleanly.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # apartment_listing_groups: atomic newness tracking for groups.
    # The persist job INSERTs a row here ON CONFLICT DO NOTHING and uses
    # the RETURNING (xmax = 0) result to know "this scan was the first
    # to see this group" without a pre-load-then-decide race. Eliminates
    # the codex Round 2 race where two concurrent scans could each
    # classify the same brand-new group as new and double-notify.
    op.create_table(
        "apartment_listing_groups",
        sa.Column("group_id", sa.String(64), primary_key=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.add_column(
        "apartment_listings",
        sa.Column("listing_group_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "apartment_listings",
        sa.Column("canonical_address", sa.String(256), nullable=True),
    )
    op.add_column(
        "apartment_listings",
        sa.Column("unit", sa.String(32), nullable=True),
    )
    op.add_column(
        "apartment_listings",
        sa.Column("building_name", sa.String(128), nullable=True),
    )
    op.add_column(
        "apartment_listings",
        sa.Column("latitude", sa.Float, nullable=True),
    )
    op.add_column(
        "apartment_listings",
        sa.Column("longitude", sa.Float, nullable=True),
    )
    op.add_column(
        "apartment_listings",
        sa.Column("photo_fingerprint", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_apartment_listings_group_id",
        "apartment_listings",
        ["listing_group_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_apartment_listings_group_id", table_name="apartment_listings"
    )
    op.drop_column("apartment_listings", "photo_fingerprint")
    op.drop_column("apartment_listings", "longitude")
    op.drop_column("apartment_listings", "latitude")
    op.drop_column("apartment_listings", "building_name")
    op.drop_column("apartment_listings", "unit")
    op.drop_column("apartment_listings", "canonical_address")
    op.drop_column("apartment_listings", "listing_group_id")
    op.drop_table("apartment_listing_groups")
