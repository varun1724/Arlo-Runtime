"""REST routes for the iOS Paper Trading section.

Reads ``paper_bankroll`` + ``paper_trades`` (populated by the
paper_trade_engine job). Bearer-auth.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import verify_token
from app.db.engine import get_db
from app.db.models import PaperBankrollRow, PaperTradeRow

router = APIRouter(
    prefix="/paper-trading",
    tags=["paper-trading"],
    dependencies=[Depends(verify_token)],
)

SCOPE = "default"


class PaperTradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: str
    condition_id: str
    title: str
    outcome: str
    slug: str | None = None
    event_slug: str | None = None
    end_date: datetime | None = None
    entry_price: float
    target_exit_price: float
    edge_score_at_entry: float
    stake_usd: float
    shares: float
    cur_price: float
    cur_value_usd: float
    unrealized_pnl_usd: float
    status: str
    opened_at: datetime
    last_refreshed_at: datetime
    closed_at: datetime | None = None
    realized_pnl_usd: float | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    # Convenience: link out to the Polymarket app via Universal Link.
    polymarket_url: str = ""


class PaperBankrollResponse(BaseModel):
    scope: str
    initial_balance_usd: float
    current_balance_usd: float
    started_at: datetime
    ends_at: datetime | None = None
    total_realized_pnl_usd: float
    total_unrealized_pnl_usd: float
    trade_count: int
    win_count: int
    loss_count: int
    status: str
    # Derived
    open_trade_count: int
    days_remaining: float | None = None


class PaperTradingStateResponse(BaseModel):
    bankroll: PaperBankrollResponse | None = None
    open_trades: list[PaperTradeResponse] = Field(default_factory=list)
    closed_trades: list[PaperTradeResponse] = Field(default_factory=list)


class PaperTradingStartRequest(BaseModel):
    initial_balance_usd: float = Field(default=40.0, ge=1, le=10_000)
    duration_days: int = Field(default=7, ge=1, le=90)


def _to_trade_response(row: PaperTradeRow) -> PaperTradeResponse:
    slug = row.event_slug or row.slug or ""
    url = f"https://polymarket.com/us/event/{slug}" if slug else "https://polymarket.com"
    return PaperTradeResponse(
        id=row.id,
        asset_id=row.asset_id,
        condition_id=row.condition_id,
        title=row.title,
        outcome=row.outcome,
        slug=row.slug,
        event_slug=row.event_slug,
        end_date=row.end_date,
        entry_price=row.entry_price,
        target_exit_price=row.target_exit_price,
        edge_score_at_entry=row.edge_score_at_entry,
        stake_usd=row.stake_usd,
        shares=row.shares,
        cur_price=row.cur_price,
        cur_value_usd=row.cur_value_usd,
        unrealized_pnl_usd=row.unrealized_pnl_usd,
        status=row.status,
        opened_at=row.opened_at,
        last_refreshed_at=row.last_refreshed_at,
        closed_at=row.closed_at,
        realized_pnl_usd=row.realized_pnl_usd,
        exit_price=row.exit_price,
        exit_reason=row.exit_reason,
        polymarket_url=url,
    )


@router.get("", response_model=PaperTradingStateResponse)
async def get_state(db: AsyncSession = Depends(get_db)) -> PaperTradingStateResponse:
    """Full paper-trading state: bankroll summary + open positions +
    recent closed positions. iOS calls this once on tab open and on
    pull-to-refresh."""
    bankroll = await db.get(PaperBankrollRow, SCOPE)

    open_q = await db.execute(
        select(PaperTradeRow)
        .where(PaperTradeRow.status == "open")
        .order_by(desc(PaperTradeRow.opened_at))
    )
    open_trades = [_to_trade_response(r) for r in open_q.scalars().all()]

    closed_q = await db.execute(
        select(PaperTradeRow)
        .where(PaperTradeRow.status != "open")
        .order_by(desc(PaperTradeRow.closed_at))
        .limit(50)
    )
    closed_trades = [_to_trade_response(r) for r in closed_q.scalars().all()]

    bankroll_resp: PaperBankrollResponse | None = None
    if bankroll is not None:
        # Aggregate unrealized P&L across open trades, computed live so
        # we don't have to keep the bankroll row in sync with every tick.
        total_unreal = sum(t.unrealized_pnl_usd for t in open_trades)
        days_remaining: float | None = None
        if bankroll.ends_at is not None:
            delta = bankroll.ends_at - datetime.now(timezone.utc)
            days_remaining = max(0.0, delta.total_seconds() / 86400.0)
        bankroll_resp = PaperBankrollResponse(
            scope=bankroll.scope,
            initial_balance_usd=bankroll.initial_balance_usd,
            current_balance_usd=bankroll.current_balance_usd,
            started_at=bankroll.started_at,
            ends_at=bankroll.ends_at,
            total_realized_pnl_usd=bankroll.total_realized_pnl_usd,
            total_unrealized_pnl_usd=round(total_unreal, 4),
            trade_count=bankroll.trade_count,
            win_count=bankroll.win_count,
            loss_count=bankroll.loss_count,
            status=bankroll.status,
            open_trade_count=len(open_trades),
            days_remaining=days_remaining,
        )

    return PaperTradingStateResponse(
        bankroll=bankroll_resp,
        open_trades=open_trades,
        closed_trades=closed_trades,
    )


@router.post("/start", response_model=PaperBankrollResponse)
async def start_session(
    body: PaperTradingStartRequest,
    db: AsyncSession = Depends(get_db),
) -> PaperBankrollResponse:
    """Initialize (or reset) the default paper bankroll. Upserts the
    single 'default' scope row, setting initial + current balance to
    the same value and ends_at to start + duration_days. Resetting
    discards prior bankroll state but does NOT delete closed trades —
    history is preserved for review."""
    now = datetime.now(timezone.utc)
    ends_at = now + timedelta(days=body.duration_days)

    stmt = (
        pg_insert(PaperBankrollRow)
        .values(
            scope=SCOPE,
            initial_balance_usd=body.initial_balance_usd,
            current_balance_usd=body.initial_balance_usd,
            started_at=now,
            ends_at=ends_at,
            total_realized_pnl_usd=0.0,
            trade_count=0,
            win_count=0,
            loss_count=0,
            status="active",
        )
        .on_conflict_do_update(
            index_elements=["scope"],
            set_={
                "initial_balance_usd": body.initial_balance_usd,
                "current_balance_usd": body.initial_balance_usd,
                "started_at": now,
                "ends_at": ends_at,
                "total_realized_pnl_usd": 0.0,
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "status": "active",
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
    row = await db.get(PaperBankrollRow, SCOPE)
    assert row is not None
    return PaperBankrollResponse(
        scope=row.scope,
        initial_balance_usd=row.initial_balance_usd,
        current_balance_usd=row.current_balance_usd,
        started_at=row.started_at,
        ends_at=row.ends_at,
        total_realized_pnl_usd=row.total_realized_pnl_usd,
        total_unrealized_pnl_usd=0.0,
        trade_count=row.trade_count,
        win_count=row.win_count,
        loss_count=row.loss_count,
        status=row.status,
        open_trade_count=0,
        days_remaining=float(body.duration_days),
    )


@router.post("/stop", response_model=PaperBankrollResponse)
async def stop_session(db: AsyncSession = Depends(get_db)) -> PaperBankrollResponse:
    """Halt the engine without resetting state. The engine job sees
    status != 'active' and exits early; open trades stay where they
    are. Set status back to 'active' via POST /start (with the same
    balance) to resume."""
    row = await db.get(PaperBankrollRow, SCOPE)
    if row is None:
        raise HTTPException(status_code=404, detail="No paper bankroll to stop")
    row.status = "stopped"
    await db.commit()
    state = await get_state(db)
    assert state.bankroll is not None
    return state.bankroll