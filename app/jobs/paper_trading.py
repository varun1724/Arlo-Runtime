"""Paper-trading engine for Polymarket copy-trade signals.

Runs on a 5-minute cron (n8n) for the duration of a paper session.
Each invocation:

  1. Loads the active paper bankroll (scope='default').
  2. Marks the session ``status='completed'`` if past ``ends_at``.
  3. For every open trade, pulls the price HISTORY since the last
     refresh from clob.polymarket.com/prices-history (1-min fidelity).
     We don't just look at the latest tick — we scan the full window,
     because a 5-min cycle would otherwise miss intraday spikes that
     hit and reverted before our next poll. This simulates "I had a
     limit order in" rather than "I checked once":
       - If max_price during window >= target_exit_price → fill at
         target (best-case execution at the cross-over).
       - Else if min_price during window <= entry * STOP_LOSS_FRACTION
         → fill at stop_loss.
       - Else update cur_price to the latest tick.
  4. Auto-closes any open trade that meets an exit condition:
       - target hit (via window scan) → closed_win
       - stop loss hit (via window scan) → closed_loss
       - market resolved → closed_resolved
       - source signal is_live=False → closed_signal_dropped
       - open for >30 days → closed_stale
     Realized P&L credits the bankroll.
  5. Scans the latest polymarket_signals for FRESH entries:
     edge_score >= ENTRY_EDGE_THRESHOLD, not currently held, and the
     bankroll-aware suggested bet fits in current_balance_usd. Pulls
     the LATEST tick for the entry price so we're not buying at a
     stale signal-snapshot price. Opens a new paper_trade for each
     qualifying signal (capped at NEW_PER_RUN per cycle).

Sizing math matches what the live /signals API exposes — quarter
Kelly with a 70% confidence discount, capped at 15% of *paper*
bankroll. The user's real UserBankrollRow is never touched.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.polymarket_routes import _suggested_bet_usd
from app.db.models import (
    JobRow,
    PaperBankrollRow,
    PaperTradeRow,
    PolymarketSignalRow,
)
from app.models.job import JobStatus, JobStopReason
from app.services.job_service import finalize_job, update_job_progress

logger = logging.getLogger("arlo.jobs.paper_trading")


SCOPE = "default"

# Entry filter: be MORE selective than the notify threshold (18). We're
# committing capital, not just surfacing for review.
ENTRY_EDGE_THRESHOLD = 22.0

# Per-cycle caps so a freshly-seeded $40 bankroll doesn't burn through
# itself in one tick when 5 signals all qualify simultaneously.
NEW_PER_RUN = 2

# Exit: stop loss at half of entry. Polymarket binary prices don't go
# below 0, but a 50% drop is a strong "cohort was wrong" signal — cut
# losses rather than ride to resolution.
STOP_LOSS_FRACTION = 0.5

# Stale window: close any position open longer than this with no exit
# trigger fired. Capital lockup avoidance.
STALE_DAYS = 30

# Polymarket CLOB API — per-asset price history (1-min fidelity).
# We use this instead of the gamma `outcomePrices` snapshot so we can
# detect intraday spikes that the 5-min cron would otherwise miss.
_CLOB_PRICES_HISTORY_URL = "https://clob.polymarket.com/prices-history"

# Gamma fallback for market resolution status (history endpoint doesn't
# tell us if a market closed; we need that to flag closed_resolved).
_GAMMA_MARKET_URL = "https://gamma-api.polymarket.com/markets"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


async def execute_paper_trade_engine_job(session: AsyncSession, job: JobRow) -> None:
    """One cycle of the paper engine. Idempotent — safe to re-run."""
    try:
        await update_job_progress(
            session, job.id,
            current_step="loading_bankroll",
            progress_message="Loading paper bankroll",
            iteration_count=1,
        )

        bankroll = await session.get(PaperBankrollRow, SCOPE)
        if bankroll is None:
            await finalize_job(
                session, job.id,
                status=JobStatus.SUCCEEDED,
                result_preview="No active paper bankroll — start via POST /paper-trading/start",
                result_data=json.dumps({"skipped": "no_bankroll"}),
            )
            return

        if bankroll.status != "active":
            await finalize_job(
                session, job.id,
                status=JobStatus.SUCCEEDED,
                result_preview=f"Bankroll status is '{bankroll.status}' — engine idle",
                result_data=json.dumps({"skipped": f"status_{bankroll.status}"}),
            )
            return

        now = datetime.now(timezone.utc)
        # Auto-stop if past ends_at — refresh open trades one last time,
        # but don't open new ones, and flip status to 'completed'.
        session_expired = bankroll.ends_at is not None and now >= bankroll.ends_at

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
            timeout=httpx.Timeout(15.0, connect=8.0),
            follow_redirects=True,
        ) as client:
            # ─── refresh + auto-close pass ───
            await update_job_progress(
                session, job.id,
                current_step="refreshing_open_trades",
                progress_message="Refreshing open trade prices",
                iteration_count=2,
            )
            closed_count, refreshed_count, realized_total = await _refresh_and_close(
                session, client, now
            )

            # ─── entry pass (skip if session expired) ───
            entered_count = 0
            if not session_expired:
                await update_job_progress(
                    session, job.id,
                    current_step="opening_new_trades",
                    progress_message="Scanning signals for fresh entries",
                    iteration_count=3,
                )
                # Re-fetch the bankroll after refresh pass — current_balance
                # may have changed via realized P&L credits.
                bankroll = await session.get(PaperBankrollRow, SCOPE)
                assert bankroll is not None
                entered_count = await _open_fresh_entries(session, client, bankroll, now)

        # Final pass: update unrealized totals on the bankroll row + flip
        # status to 'completed' if the session window closed.
        await _refresh_bankroll_totals(session, now, session_expired)

        summary = {
            "refreshed_count": refreshed_count,
            "closed_count": closed_count,
            "entered_count": entered_count,
            "realized_pnl_this_cycle_usd": round(realized_total, 2),
            "session_expired": session_expired,
        }
        preview = (
            f"Paper engine: {refreshed_count} refreshed, {closed_count} closed "
            f"(realized ${realized_total:+.2f}), {entered_count} new entries."
        )
        await finalize_job(
            session, job.id,
            status=JobStatus.SUCCEEDED,
            result_preview=preview,
            result_data=json.dumps(summary),
        )
    except Exception as e:
        logger.exception("paper_trade_engine job %s crashed", job.id)
        await finalize_job(
            session, job.id,
            status=JobStatus.FAILED,
            error_message=f"{type(e).__name__}: {e}",
            stop_reason=JobStopReason.ERROR.value,
        )


# ───────────────────────── price fetching ─────────────────────────


async def _fetch_price_window(
    client: httpx.AsyncClient, asset_id: str, since_unix: int
) -> list[tuple[int, float]]:
    """Pull every 1-min price tick for ``asset_id`` since ``since_unix``.

    Returns a list of (timestamp_sec, price) sorted ascending. Empty
    list on fetch failure or no data.

    Polymarket's prices-history fidelity=1 gives ~60 points per hour;
    interval=1h is the smallest meaningful window. We filter to the
    cycle window ourselves so the engine can claim "I saw the spike at
    t+90s and would have filled at the limit price."
    """
    url = f"{_CLOB_PRICES_HISTORY_URL}?market={asset_id}&interval=1h&fidelity=1"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.warning("prices-history fetch failed for %s: %s", asset_id[:16], e)
        return []
    history = data.get("history") if isinstance(data, dict) else None
    if not isinstance(history, list):
        return []
    points: list[tuple[int, float]] = []
    for p in history:
        try:
            t = int(p["t"])
            v = float(p["p"])
        except (KeyError, TypeError, ValueError):
            continue
        if t >= since_unix:
            points.append((t, v))
    points.sort(key=lambda x: x[0])
    return points


async def _fetch_latest_price(client: httpx.AsyncClient, asset_id: str) -> float | None:
    """Most-recent tick from prices-history. Used for fresh entries so
    we're not buying at a stale signal-snapshot price."""
    points = await _fetch_price_window(client, asset_id, since_unix=0)
    return points[-1][1] if points else None


async def _is_market_closed(
    client: httpx.AsyncClient, condition_id: str
) -> bool:
    """True when Polymarket has marked the market resolved/closed."""
    url = f"{_GAMMA_MARKET_URL}?condition_ids={condition_id}"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return False
    if not isinstance(data, list) or not data:
        return False
    return bool(data[0].get("closed"))


async def _fetch_gamma_price(
    client: httpx.AsyncClient, condition_id: str, outcome_index: int
) -> float | None:
    """Fallback price source when prices-history returns empty.

    The CLOB prices-history endpoint occasionally has 1-3 minute gaps
    for low-volume markets. When it does, falling back to gamma's
    outcomePrices snapshot keeps mark-to-market alive — we just lose
    intraday spike detection for the cycle.
    """
    url = f"{_GAMMA_MARKET_URL}?condition_ids={condition_id}"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return None
    if not isinstance(data, list) or not data:
        return None
    prices_raw = data[0].get("outcomePrices")
    if isinstance(prices_raw, str):
        try:
            prices = json.loads(prices_raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(prices_raw, list):
        prices = prices_raw
    else:
        return None
    try:
        return float(prices[outcome_index])
    except (IndexError, TypeError, ValueError):
        return None


# ───────────────────────── refresh + close ─────────────────────────


async def _refresh_and_close(
    session: AsyncSession, client: httpx.AsyncClient, now: datetime
) -> tuple[int, int, float]:
    """For every open paper_trade: scan the price WINDOW since the last
    refresh (not just the latest tick), simulating limit-order fills if
    the price crossed our target or stop during the window. Update
    unrealized PnL on the not-yet-closed trades.

    Returns (closed_count, refreshed_count, realized_total).
    """
    open_q = await session.execute(
        select(PaperTradeRow).where(PaperTradeRow.status == "open")
    )
    open_trades = list(open_q.scalars().all())
    if not open_trades:
        return 0, 0, 0.0

    closed_count = 0
    refreshed_count = 0
    realized_total = 0.0

    for trade in open_trades:
        # Pull every tick since the last refresh. The lookback is at
        # least the cron interval (5m), but we don't enforce that — if
        # a cycle was skipped, the API gives us up to 60 min of data
        # and we scan all of it.
        since = int(trade.last_refreshed_at.timestamp())
        window = await _fetch_price_window(client, trade.asset_id, since)
        if not window:
            # Fallback: gamma snapshot. We lose the spike-detection
            # window-scan but at least keep mark-to-market correct.
            fallback = await _fetch_gamma_price(client, trade.condition_id, trade.outcome_index)
            if fallback is None:
                logger.warning(
                    "Both prices-history and gamma failed for %s [%s] — leaving stale",
                    trade.title[:30], trade.outcome,
                )
                continue
            # Synthesize a single-point "window" so the rest of the
            # loop computes mark-to-market correctly. No spike scan
            # possible from a single point — exit checks below still
            # run, just without the cross-detection.
            window = [(int(now.timestamp()), fallback)]

        latest_price = window[-1][1]
        stop_price = trade.entry_price * STOP_LOSS_FRACTION

        # Walk the window in chronological order and stop at the FIRST
        # tick to cross either threshold. This matters when both crossed
        # in the same cycle: if the price dipped to the stop at t+30s
        # and only later spiked to target at t+90s, the limit order
        # would have been stopped out first. Naïve "target wins" logic
        # double-counts winners.
        exit_reason: str | None = None
        fill_price: float | None = None
        for _t, p in window:
            if p >= trade.target_exit_price:
                exit_reason = "hit_target"
                fill_price = trade.target_exit_price
                break
            if p <= stop_price:
                exit_reason = "stop_loss"
                fill_price = stop_price
                break

        # No window-fill — check non-price exit conditions.
        if exit_reason is None:
            if trade.end_date and trade.end_date <= now:
                exit_reason = "end_date_passed"
                fill_price = latest_price
            elif now - trade.opened_at >= timedelta(days=STALE_DAYS):
                exit_reason = "stale"
                fill_price = latest_price
            else:
                # Gamma round-trip to detect resolution. Narrow trigger
                # to 0.995/0.005 — resolved markets converge to exactly
                # 0 or 1 (often within a few thousandths). Anything
                # else is just deep ITM/OTM and not resolved yet.
                if latest_price >= 0.995 or latest_price <= 0.005:
                    if await _is_market_closed(client, trade.condition_id):
                        exit_reason = "market_resolved"
                        fill_price = latest_price
            # Source-signal dropout check (lightest, last)
            if exit_reason is None:
                sig = await session.get(PolymarketSignalRow, trade.asset_id)
                if sig is not None and not sig.is_live:
                    exit_reason = "signal_dropped"
                    fill_price = latest_price

        # Apply the result.
        if exit_reason and fill_price is not None:
            cur_value = trade.shares * fill_price
            unreal = cur_value - trade.stake_usd
            trade.status = _status_for_exit(exit_reason, unreal)
            trade.cur_price = fill_price
            trade.cur_value_usd = round(cur_value, 4)
            trade.unrealized_pnl_usd = round(unreal, 4)
            trade.closed_at = now
            trade.exit_price = fill_price
            trade.exit_reason = exit_reason
            trade.realized_pnl_usd = round(unreal, 4)
            trade.last_refreshed_at = now
            realized_total += unreal
            closed_count += 1
            refreshed_count += 1
            await session.execute(
                update(PaperBankrollRow)
                .where(PaperBankrollRow.scope == SCOPE)
                .values(
                    current_balance_usd=PaperBankrollRow.current_balance_usd + cur_value,
                    total_realized_pnl_usd=PaperBankrollRow.total_realized_pnl_usd + unreal,
                    win_count=PaperBankrollRow.win_count + (1 if unreal > 0 else 0),
                    loss_count=PaperBankrollRow.loss_count + (1 if unreal < 0 else 0),
                )
            )
        else:
            # Just refresh the mark-to-market on the open position.
            cur_value = trade.shares * latest_price
            trade.cur_price = latest_price
            trade.cur_value_usd = round(cur_value, 4)
            trade.unrealized_pnl_usd = round(cur_value - trade.stake_usd, 4)
            trade.last_refreshed_at = now
            refreshed_count += 1

    await session.commit()
    return closed_count, refreshed_count, realized_total


# ───────────────────────── entry pass ─────────────────────────


async def _open_fresh_entries(
    session: AsyncSession,
    client: httpx.AsyncClient,
    bankroll: PaperBankrollRow,
    now: datetime,
) -> int:
    """Open new paper_trades for any qualifying signal not currently
    held. Returns the count opened this cycle (capped at NEW_PER_RUN).
    Fetches the LATEST per-asset price at entry time so we don't buy
    at the signal's stale snapshot price.
    """
    sig_q = await session.execute(
        select(PolymarketSignalRow)
        .where(PolymarketSignalRow.is_live.is_(True))
        .where(PolymarketSignalRow.edge_score >= ENTRY_EDGE_THRESHOLD)
        .order_by(PolymarketSignalRow.edge_score.desc())
    )
    candidates = list(sig_q.scalars().all())
    if not candidates:
        return 0

    open_assets_q = await session.execute(
        select(PaperTradeRow.asset_id).where(PaperTradeRow.status == "open")
    )
    held = {row[0] for row in open_assets_q.all()}

    opened = 0
    for sig in candidates:
        if opened >= NEW_PER_RUN:
            break
        if sig.asset_id in held:
            continue

        # Get the fresh entry price. If the API call fails, skip this
        # candidate — better to wait than enter at a stale value.
        live_price = await _fetch_latest_price(client, sig.asset_id)
        if live_price is None:
            continue
        # Refuse to enter if the live price has run away from the
        # cohort's avg entry — at that point we'd be paying the spike.
        if sig.avg_entry_price > 0 and live_price > sig.avg_entry_price * 1.6:
            continue
        # And require the target still has room (the cohort's target
        # was set based on the avg_entry, but the live price may have
        # closed the gap).
        if live_price >= sig.target_exit_price:
            continue

        stake = _suggested_bet_usd(
            bankroll=bankroll.current_balance_usd,
            edge_score=sig.edge_score,
            cur_price=live_price,
            target_exit_price=sig.target_exit_price,
        )
        if stake < 1.0 or stake > bankroll.current_balance_usd:
            continue

        # Belt + suspenders: re-check is_live just before the INSERT
        # in case the polymarket_scan job marked the signal stale
        # between our SELECT and now. The DB still gets a consistent
        # view via MVCC, but the signal's *meaning* could have flipped.
        fresh_sig = await session.get(PolymarketSignalRow, sig.asset_id)
        if fresh_sig is None or not fresh_sig.is_live:
            continue

        shares = stake / live_price
        cur_value = shares * live_price
        trade = PaperTradeRow(
            id=uuid.uuid4(),
            scope=SCOPE,
            asset_id=sig.asset_id,
            condition_id=sig.condition_id,
            title=sig.title,
            outcome=sig.outcome,
            outcome_index=sig.outcome_index,
            slug=sig.slug,
            event_slug=sig.event_slug,
            end_date=sig.end_date,
            entry_price=live_price,
            target_exit_price=sig.target_exit_price,
            edge_score_at_entry=sig.edge_score,
            stake_usd=stake,
            shares=shares,
            cur_price=live_price,
            cur_value_usd=cur_value,
            unrealized_pnl_usd=0.0,
            status="open",
            opened_at=now,
            last_refreshed_at=now,
        )
        session.add(trade)
        await session.execute(
            update(PaperBankrollRow)
            .where(PaperBankrollRow.scope == SCOPE)
            .values(
                current_balance_usd=PaperBankrollRow.current_balance_usd - stake,
                trade_count=PaperBankrollRow.trade_count + 1,
            )
        )
        held.add(sig.asset_id)
        opened += 1

    await session.commit()
    return opened


def _status_for_exit(reason: str, unrealized: float) -> str:
    if reason == "hit_target":
        return "closed_win"
    if reason == "stop_loss":
        return "closed_loss"
    if reason in ("market_resolved", "end_date_passed"):
        return "closed_win" if unrealized > 0 else "closed_loss"
    if reason == "signal_dropped":
        return "closed_signal_dropped"
    if reason == "stale":
        return "closed_stale"
    return "closed_other"


async def _refresh_bankroll_totals(
    session: AsyncSession, now: datetime, session_expired: bool
) -> None:
    """Recompute summary fields on the bankroll row + auto-stop on expiry."""
    updates: dict[str, Any] = {}
    if session_expired:
        updates["status"] = "completed"
    if updates:
        await session.execute(
            update(PaperBankrollRow)
            .where(PaperBankrollRow.scope == SCOPE)
            .values(**updates)
        )
        await session.commit()
