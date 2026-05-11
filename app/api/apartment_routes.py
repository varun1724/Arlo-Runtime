"""REST routes for the iOS apartment-search tab.

Reads apartment_listings (populated by the apartment_search pipeline's
persist step) and saved_apartments (the iOS app's bookmark list).
Bearer-auth via the standard ``verify_token`` dependency.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import verify_token
from app.core.config import settings
from app.db.engine import get_db
from app.db.models import ApartmentListingRow, SavedApartmentRow

router = APIRouter(
    prefix="/apartments",
    tags=["apartments"],
    dependencies=[Depends(verify_token)],
)


class ApartmentSourceLink(BaseModel):
    """One URL that the group has been seen at. Populated from the
    other (lower-score) listings in the same listing_group_id."""

    source: str
    url: str
    score: float


class ApartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    listing_id: str
    listing_group_id: str | None = None
    source: str
    url: str
    title: str
    neighborhood: str | None = None
    address: str | None = None
    canonical_address: str | None = None
    unit: str | None = None
    building_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rent_usd: int | None = None
    beds: int | None = None
    baths: float | None = None
    sqft: int | None = None
    bike_time_min: int | None = None
    score: float
    score_breakdown: dict | None = None
    amenities: list[str] | None = None
    photos: list[str] | None = None
    summary: str | None = None
    is_active: bool
    is_saved: bool = False
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    # Multi-source crosspost. Includes only OTHER listings in the same
    # group — the canonical row's own URL is in ``url`` above.
    also_seen_on: list[ApartmentSourceLink] = Field(default_factory=list)


class ApartmentListResponse(BaseModel):
    apartments: list[ApartmentResponse]
    count: int


class ToggleSaveRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class ToggleSaveResponse(BaseModel):
    listing_id: str
    is_saved: bool


def _default_user_email() -> str:
    """The Arlo app is single-user — saved listings are scoped to the
    configured approval recipient email. iOS doesn't pass a user
    identity today; if/when it does, swap to a request-scoped value."""
    return settings.approval_recipient_email or "default@arlo.local"


def _to_response(
    row: ApartmentListingRow,
    *,
    is_saved: bool,
    also_seen_on: list[ApartmentSourceLink] | None = None,
) -> ApartmentResponse:
    return ApartmentResponse(
        listing_id=row.listing_id,
        listing_group_id=row.listing_group_id,
        source=row.source,
        url=row.url,
        title=row.title,
        neighborhood=row.neighborhood,
        address=row.address,
        canonical_address=row.canonical_address,
        unit=row.unit,
        building_name=row.building_name,
        latitude=row.latitude,
        longitude=row.longitude,
        rent_usd=row.rent_usd,
        beds=row.beds,
        baths=row.baths,
        sqft=row.sqft,
        bike_time_min=row.bike_time_min,
        score=row.score,
        score_breakdown=row.score_breakdown,
        amenities=row.amenities or [],
        photos=row.photos or [],
        summary=row.summary,
        is_active=row.is_active,
        is_saved=is_saved,
        first_seen_at=row.first_seen_at.isoformat() if row.first_seen_at else None,
        last_seen_at=row.last_seen_at.isoformat() if row.last_seen_at else None,
        also_seen_on=also_seen_on or [],
    )


def _group_apartments_by_group_id(
    rows: list[ApartmentListingRow],
) -> tuple[list[ApartmentListingRow], dict[str, list[ApartmentSourceLink]]]:
    """Collapse rows to one-per-group keeping the highest-scoring as the
    canonical representative. Rows without a group_id are passed
    through individually (each becomes its own "group of one").

    Returns:
        (canonical_rows, sibling_links_by_listing_id) — the canonical
        list preserves input order (already score-desc from the
        caller's query). The sibling map keys each canonical row's
        listing_id to the OTHER URLs that share its group_id.
    """
    # Bucket by group_id (None gets the row's own listing_id so
    # ungrouped rows don't collapse together).
    buckets: dict[str, list[ApartmentListingRow]] = {}
    for r in rows:
        key = r.listing_group_id or f"__solo__{r.listing_id}"
        buckets.setdefault(key, []).append(r)

    canonical_rows: list[ApartmentListingRow] = []
    siblings: dict[str, list[ApartmentSourceLink]] = {}
    seen_canonical_ids: set[str] = set()

    # Walk the input order so the score-desc sort is preserved. The
    # first row we see in each bucket wins as canonical.
    for r in rows:
        key = r.listing_group_id or f"__solo__{r.listing_id}"
        if key in seen_canonical_ids:
            continue
        seen_canonical_ids.add(key)
        canonical_rows.append(r)
        bucket = buckets[key]
        if len(bucket) > 1:
            siblings[r.listing_id] = [
                ApartmentSourceLink(source=other.source, url=other.url, score=other.score)
                for other in bucket
                if other.listing_id != r.listing_id
            ]
    return canonical_rows, siblings


@router.get("", response_model=ApartmentListResponse)
async def list_apartments(
    limit: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(False),
    min_score: float = Query(0.0, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
) -> ApartmentListResponse:
    """List apartments ranked by score, deduplicated by listing_group_id.

    Rows sharing a group_id are collapsed to one canonical entry
    (highest-scoring), with the other site URLs surfaced in
    ``also_seen_on``. Over-fetch by 3x then trim post-dedup so we
    still return roughly ``limit`` distinct apartments even when a
    chunk of rows are crossposts.
    """
    # Over-fetch so post-dedup we still have ``limit`` distinct groups.
    # 3x covers the realistic crosspost rate (most apts on 1-2 sites,
    # some on 3-4) without blowing up query cost.
    overfetch = min(limit * 3, 600)
    stmt = select(ApartmentListingRow).where(ApartmentListingRow.score >= min_score)
    if not include_inactive:
        stmt = stmt.where(ApartmentListingRow.is_active.is_(True))
    stmt = stmt.order_by(
        desc(ApartmentListingRow.score),
        desc(ApartmentListingRow.last_seen_at),
    ).limit(overfetch)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    canonical, siblings = _group_apartments_by_group_id(rows)
    canonical = canonical[:limit]

    saved_ids = await _saved_ids_for_listings(db, [r.listing_id for r in canonical])
    return ApartmentListResponse(
        apartments=[
            _to_response(
                r,
                is_saved=r.listing_id in saved_ids,
                also_seen_on=siblings.get(r.listing_id, []),
            )
            for r in canonical
        ],
        count=len(canonical),
    )


@router.get("/saved", response_model=ApartmentListResponse)
async def list_saved_apartments(
    db: AsyncSession = Depends(get_db),
) -> ApartmentListResponse:
    """List the user's saved apartments, most-recently saved first.

    Saves are scoped to the specific URL the user bookmarked
    (intentional — they may have saved the Craigslist version of a
    crosspost because that one had a better photo). But the
    ``also_seen_on`` field still surfaces sibling URLs in case they
    want to compare or share a different listing.
    """
    user_email = _default_user_email()
    stmt = (
        select(ApartmentListingRow, SavedApartmentRow.saved_at)
        .join(
            SavedApartmentRow,
            SavedApartmentRow.listing_id == ApartmentListingRow.listing_id,
        )
        .where(SavedApartmentRow.user_email == user_email)
        .order_by(desc(SavedApartmentRow.saved_at))
    )
    result = await db.execute(stmt)
    saved_pairs = list(result.all())
    saved_rows = [pair[0] for pair in saved_pairs]
    siblings_map = await _siblings_for_rows(db, saved_rows)
    return ApartmentListResponse(
        apartments=[
            _to_response(r, is_saved=True, also_seen_on=siblings_map.get(r.listing_id, []))
            for r in saved_rows
        ],
        count=len(saved_rows),
    )


@router.get("/{listing_id}", response_model=ApartmentResponse)
async def get_apartment(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApartmentResponse:
    row = await db.get(ApartmentListingRow, listing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Apartment not found")
    saved_ids = await _saved_ids_for_listings(db, [listing_id])
    siblings_map = await _siblings_for_rows(db, [row])
    return _to_response(
        row,
        is_saved=listing_id in saved_ids,
        also_seen_on=siblings_map.get(listing_id, []),
    )


@router.post("/{listing_id}/save", response_model=ToggleSaveResponse)
async def toggle_save_apartment(
    listing_id: str,
    body: ToggleSaveRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ToggleSaveResponse:
    """Toggle whether a listing is saved. Idempotent: calling twice
    saves then unsaves. Notes are stored on save only."""
    row = await db.get(ApartmentListingRow, listing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Apartment not found")

    user_email = _default_user_email()

    existing_stmt = select(SavedApartmentRow).where(
        SavedApartmentRow.listing_id == listing_id,
        SavedApartmentRow.user_email == user_email,
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()

    if existing is not None:
        await db.execute(
            delete(SavedApartmentRow).where(SavedApartmentRow.id == existing.id)
        )
        await db.commit()
        return ToggleSaveResponse(listing_id=listing_id, is_saved=False)

    saved = SavedApartmentRow(
        id=uuid.uuid4(),
        listing_id=listing_id,
        user_email=user_email,
        notes=(body.notes if body else None),
    )
    db.add(saved)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent save raced us to the unique constraint. Net intent
        # of both clicks was "save," so report success rather than 500.
        await db.rollback()
    return ToggleSaveResponse(listing_id=listing_id, is_saved=True)


async def _saved_ids_for_listings(
    db: AsyncSession, listing_ids: list[str]
) -> set[str]:
    if not listing_ids:
        return set()
    user_email = _default_user_email()
    result = await db.execute(
        select(SavedApartmentRow.listing_id).where(
            SavedApartmentRow.listing_id.in_(listing_ids),
            SavedApartmentRow.user_email == user_email,
        )
    )
    return {row for row in result.scalars().all()}


async def _siblings_for_rows(
    db: AsyncSession, rows: list[ApartmentListingRow]
) -> dict[str, list[ApartmentSourceLink]]:
    """Fetch all OTHER rows that share a listing_group_id with the given
    rows, keyed by the input row's listing_id.

    Used by the detail + saved endpoints to surface crossposts even
    when the canonical row wasn't the one the user navigated to.
    Skipped for rows without a group_id.
    """
    group_ids = {r.listing_group_id for r in rows if r.listing_group_id}
    if not group_ids:
        return {}
    result = await db.execute(
        select(ApartmentListingRow).where(
            ApartmentListingRow.listing_group_id.in_(group_ids)
        )
    )
    all_in_groups = list(result.scalars().all())
    by_group: dict[str, list[ApartmentListingRow]] = {}
    for r in all_in_groups:
        by_group.setdefault(r.listing_group_id, []).append(r)

    out: dict[str, list[ApartmentSourceLink]] = {}
    for r in rows:
        if r.listing_group_id is None:
            continue
        siblings = [
            other
            for other in by_group.get(r.listing_group_id, [])
            if other.listing_id != r.listing_id
        ]
        if siblings:
            out[r.listing_id] = [
                ApartmentSourceLink(source=s.source, url=s.url, score=s.score)
                for s in siblings
            ]
    return out
