"""REST routes for the iOS Polymarket-signals tab.

Reads ``polymarket_signals`` (populated by the polymarket_scan job).
Bearer-auth via the standard ``verify_token`` dependency.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import verify_token
from app.db.engine import get_db
from app.db.models import PolymarketSignalRow

router = APIRouter(
    prefix="/signals",
    tags=["polymarket"],
    dependencies=[Depends(verify_token)],
)


class PolymarketHolder(BaseModel):
    """One top-trader's position in a signal. Used for the detail view's
    'who's in this trade' list."""

    wallet: str
    pseudonym: str
    avg_price: float
    current_value: float
    pnl_pct: float


class PolymarketSignalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_id: str
    condition_id: str
    event_id: str | None = None
    title: str
    outcome: str
    outcome_index: int
    slug: str | None = None
    event_slug: str | None = None
    icon_url: str | None = None
    end_date: datetime | None = None

    n_holders: int
    avg_entry_price: float
    cur_price: float
    target_exit_price: float
    upside_pct: float
    avg_pnl_pct: float
    total_size_usd: float
    days_to_resolution: float | None = None
    edge_score: float
    recommended_action: str | None = None
    polymarket_url: str = Field(default="")

    holders: list[PolymarketHolder] = Field(default_factory=list)

    first_seen_at: datetime
    last_scan_at: datetime
    is_live: bool


class PolymarketSignalListResponse(BaseModel):
    signals: list[PolymarketSignalResponse]
    count: int


def _to_response(row: PolymarketSignalRow) -> PolymarketSignalResponse:
    slug = row.event_slug or row.slug or ""
    # /us/event/* matches Polymarket's apple-app-site-association applinks
    # path pattern, so tapping the link on iOS opens the Polymarket app
    # (Universal Link). Without the /us/ prefix iOS just opens Safari.
    url = f"https://polymarket.com/us/event/{slug}" if slug else "https://polymarket.com"
    return PolymarketSignalResponse(
        asset_id=row.asset_id,
        condition_id=row.condition_id,
        event_id=row.event_id,
        title=row.title,
        outcome=row.outcome,
        outcome_index=row.outcome_index,
        slug=row.slug,
        event_slug=row.event_slug,
        icon_url=row.icon_url,
        end_date=row.end_date,
        n_holders=row.n_holders,
        avg_entry_price=row.avg_entry_price,
        cur_price=row.cur_price,
        target_exit_price=row.target_exit_price,
        upside_pct=row.upside_pct,
        avg_pnl_pct=row.avg_pnl_pct,
        total_size_usd=row.total_size_usd,
        days_to_resolution=row.days_to_resolution,
        edge_score=row.edge_score,
        recommended_action=row.recommended_action,
        polymarket_url=url,
        holders=[PolymarketHolder(**h) for h in (row.holders or [])],
        first_seen_at=row.first_seen_at,
        last_scan_at=row.last_scan_at,
        is_live=row.is_live,
    )


@router.get("", response_model=PolymarketSignalListResponse)
async def list_signals(
    limit: int = Query(default=25, ge=1, le=100),
    live_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> PolymarketSignalListResponse:
    """Return signals sorted by edge_score desc. By default only the
    live (currently-qualifying) signals; pass ``live_only=false`` to
    include recently-stale signals too (useful for "history" tab)."""
    stmt = select(PolymarketSignalRow)
    if live_only:
        stmt = stmt.where(PolymarketSignalRow.is_live.is_(True))
    stmt = stmt.order_by(desc(PolymarketSignalRow.edge_score)).limit(limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return PolymarketSignalListResponse(
        signals=[_to_response(r) for r in rows],
        count=len(rows),
    )


@router.get("/{asset_id}", response_model=PolymarketSignalResponse)
async def get_signal(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
) -> PolymarketSignalResponse:
    """Fetch a single signal's full detail (holders list, recommended
    action, etc.). Returns 404-via-empty if not found — iOS treats the
    missing case the same as a stale signal."""
    row = await db.get(PolymarketSignalRow, asset_id)
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="signal not found")
    return _to_response(row)
