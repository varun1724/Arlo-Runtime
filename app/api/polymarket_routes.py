"""REST routes for the iOS Polymarket-signals tab.

Reads ``polymarket_signals`` (populated by the polymarket_scan job).
Bearer-auth via the standard ``verify_token`` dependency.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import verify_token
from app.core.config import settings
from app.db.engine import get_db
from app.db.models import PolymarketSignalRow, UserBankrollRow

router = APIRouter(
    prefix="/signals",
    tags=["polymarket"],
    dependencies=[Depends(verify_token)],
)

bankroll_router = APIRouter(
    prefix="/bankroll",
    tags=["polymarket"],
    dependencies=[Depends(verify_token)],
)


# ─────────────────────────── sizing logic ───────────────────────────

# How much we trust the cohort's target_exit_price as a true probability
# estimate. 0.7 means: "if the top traders converged on this, there's a
# 70% chance the price ends near the target — and 30% chance it stays
# flat at cur_price." Lowering this number = smaller bets across the
# board; raising it = more aggressive. Quarter Kelly is the *additional*
# safety margin on top of this discount.
_CONFIDENCE = 0.70
_KELLY_FRACTION = 0.25
# Hard cap so a single bet can't blow up the bankroll. With $40 starting
# capital, 15% = $6 per bet — survives a 6-trade losing streak.
_MAX_BET_FRACTION = 0.15
_MIN_BET_USD = 1.0
_MIN_EDGE_SCORE_TO_SUGGEST = 18.0


def _suggested_bet_usd(
    *, bankroll: float, edge_score: float, cur_price: float, target_exit_price: float
) -> float:
    """Quarter-Kelly bet size with a 70% confidence discount on the
    cohort's price target, capped at 15% of bankroll.

    Returns 0.0 when:
      - no bankroll set (defaults to 0)
      - edge_score below the notify-worthy threshold
      - cur_price is at/past the target (no upside left)
      - Kelly comes out negative (rare; happens when discounted prob is
        below cur_price)
    """
    if bankroll <= 0 or edge_score < _MIN_EDGE_SCORE_TO_SUGGEST:
        return 0.0
    if cur_price <= 0 or cur_price >= 1 or target_exit_price <= cur_price:
        return 0.0
    # Adjusted "true" probability used in Kelly: weighted average of
    # "cohort is right (price hits target)" and "cohort is wrong (price
    # stays where it is)".
    p = _CONFIDENCE * target_exit_price + (1 - _CONFIDENCE) * cur_price
    # Kelly for a Polymarket Yes/No paying $1: f* = (p - c) / (c * (1 - c))
    variance = cur_price * (1 - cur_price)
    if variance <= 0:
        return 0.0
    full_kelly = (p - cur_price) / variance
    if full_kelly <= 0:
        return 0.0
    fraction = min(_KELLY_FRACTION * full_kelly, _MAX_BET_FRACTION)
    raw = bankroll * fraction
    return max(_MIN_BET_USD, round(raw, 2))


def _default_user_email() -> str:
    """Single-user app; bankroll is scoped to the configured approval
    recipient email (same convention as saved_apartments)."""
    return settings.approval_recipient_email or "default@arlo.local"


async def _current_bankroll(db: AsyncSession) -> float:
    row = await db.get(UserBankrollRow, _default_user_email())
    return float(row.balance_usd) if row else 0.0


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
    # Bankroll-aware bet size for this signal. Zero when no bankroll set
    # or when the signal doesn't clear the suggestion threshold. iOS
    # renders "$X.XX" prominently in the row + detail view.
    suggested_bet_usd: float = 0.0
    suggested_bet_pct_of_bankroll: float = 0.0

    holders: list[PolymarketHolder] = Field(default_factory=list)

    first_seen_at: datetime
    last_scan_at: datetime
    is_live: bool


class PolymarketSignalListResponse(BaseModel):
    signals: list[PolymarketSignalResponse]
    count: int
    # Echoed so the iOS list view can show the bankroll badge without a
    # separate /bankroll fetch on every refresh.
    bankroll_usd: float = 0.0


class BankrollResponse(BaseModel):
    balance_usd: float
    updated_at: datetime | None = None
    notes: str | None = None


class BankrollUpdateRequest(BaseModel):
    balance_usd: float = Field(ge=0)
    notes: str | None = Field(default=None, max_length=2000)


def _to_response(row: PolymarketSignalRow, *, bankroll: float) -> PolymarketSignalResponse:
    slug = row.event_slug or row.slug or ""
    # /us/event/* matches Polymarket's apple-app-site-association applinks
    # path pattern, so tapping the link on iOS opens the Polymarket app
    # (Universal Link). Without the /us/ prefix iOS just opens Safari.
    url = f"https://polymarket.com/us/event/{slug}" if slug else "https://polymarket.com"
    bet_usd = _suggested_bet_usd(
        bankroll=bankroll,
        edge_score=row.edge_score,
        cur_price=row.cur_price,
        target_exit_price=row.target_exit_price,
    )
    bet_pct = round((bet_usd / bankroll) * 100, 1) if bankroll > 0 else 0.0
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
        suggested_bet_usd=bet_usd,
        suggested_bet_pct_of_bankroll=bet_pct,
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
    include recently-stale signals too (useful for "history" tab).

    Bankroll is read once per request and used to compute
    ``suggested_bet_usd`` on every signal row + echoed at the top
    level so the iOS app's badge doesn't need a second roundtrip.
    """
    bankroll = await _current_bankroll(db)
    stmt = select(PolymarketSignalRow)
    if live_only:
        stmt = stmt.where(PolymarketSignalRow.is_live.is_(True))
    stmt = stmt.order_by(desc(PolymarketSignalRow.edge_score)).limit(limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return PolymarketSignalListResponse(
        signals=[_to_response(r, bankroll=bankroll) for r in rows],
        count=len(rows),
        bankroll_usd=bankroll,
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
    bankroll = await _current_bankroll(db)
    return _to_response(row, bankroll=bankroll)


# ─────────────────────────── bankroll ───────────────────────────


@bankroll_router.get("", response_model=BankrollResponse)
async def get_bankroll(db: AsyncSession = Depends(get_db)) -> BankrollResponse:
    """Current Polymarket bankroll for the configured user. Returns
    zeros (with updated_at=null) when no row exists yet — iOS reads
    that as 'tap to set up'."""
    row = await db.get(UserBankrollRow, _default_user_email())
    if row is None:
        return BankrollResponse(balance_usd=0.0, updated_at=None, notes=None)
    return BankrollResponse(
        balance_usd=float(row.balance_usd),
        updated_at=row.updated_at,
        notes=row.notes,
    )


@bankroll_router.put("", response_model=BankrollResponse)
async def update_bankroll(
    body: BankrollUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> BankrollResponse:
    """Set / update the bankroll. Idempotent — upserts a single row
    keyed by the configured user email."""
    email = _default_user_email()
    stmt = (
        pg_insert(UserBankrollRow)
        .values(user_email=email, balance_usd=body.balance_usd, notes=body.notes)
        .on_conflict_do_update(
            index_elements=["user_email"],
            set_={"balance_usd": body.balance_usd, "notes": body.notes},
        )
    )
    await db.execute(stmt)
    await db.commit()
    row = await db.get(UserBankrollRow, email)
    assert row is not None  # we just upserted it
    return BankrollResponse(
        balance_usd=float(row.balance_usd),
        updated_at=row.updated_at,
        notes=row.notes,
    )
