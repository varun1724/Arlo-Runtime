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


class ApartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    listing_id: str
    source: str
    url: str
    title: str
    neighborhood: str | None = None
    address: str | None = None
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


def _to_response(row: ApartmentListingRow, *, is_saved: bool) -> ApartmentResponse:
    return ApartmentResponse(
        listing_id=row.listing_id,
        source=row.source,
        url=row.url,
        title=row.title,
        neighborhood=row.neighborhood,
        address=row.address,
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
    )


@router.get("", response_model=ApartmentListResponse)
async def list_apartments(
    limit: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(False),
    min_score: float = Query(0.0, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
) -> ApartmentListResponse:
    """List apartments ranked by score, newest scan first."""
    stmt = select(ApartmentListingRow).where(ApartmentListingRow.score >= min_score)
    if not include_inactive:
        stmt = stmt.where(ApartmentListingRow.is_active.is_(True))
    stmt = stmt.order_by(
        desc(ApartmentListingRow.score),
        desc(ApartmentListingRow.last_seen_at),
    ).limit(limit)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    saved_ids = await _saved_ids_for_listings(db, [r.listing_id for r in rows])
    return ApartmentListResponse(
        apartments=[_to_response(r, is_saved=r.listing_id in saved_ids) for r in rows],
        count=len(rows),
    )


@router.get("/saved", response_model=ApartmentListResponse)
async def list_saved_apartments(
    db: AsyncSession = Depends(get_db),
) -> ApartmentListResponse:
    """List the user's saved apartments, most-recently saved first."""
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
    rows = list(result.all())
    return ApartmentListResponse(
        apartments=[_to_response(r[0], is_saved=True) for r in rows],
        count=len(rows),
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
    return _to_response(row, is_saved=listing_id in saved_ids)


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
