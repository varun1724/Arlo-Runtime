"""Polymarket copy-trade signal scanner.

Pulls the top ~50 wallets from the public Polymarket leaderboard
(monthly+weekly × profit+volume), fetches each wallet's current open
positions, aggregates by (market outcome) asset, and surfaces assets
held by N+ top wallets where the average position is winning and the
current price still leaves room to enter.

Output: rows in ``polymarket_signals`` with edge_score, recommended
action, holders list, and a notification trigger when a fresh
high-edge signal lands.

Public APIs used (no auth required):
  - https://polymarket.com/leaderboard/overall/{window}/{sort}
    Server-rendered HTML; we regex out ``"proxyWallet":"0x..."``.
  - https://data-api.polymarket.com/positions?user=<wallet>
    Returns the wallet's open positions with avgPrice, curPrice, size,
    currentValue, percentPnl, endDate, etc.

The whole job is deterministic Python — no Claude call, no LLM. Every
input is observable, scoring is reproducible, and a single scan costs
~$0 plus a handful of HTTP calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow, PolymarketSignalRow
from app.models.job import JobStatus, JobStopReason
from app.services import email_sender
from app.services.job_service import finalize_job, update_job_progress

logger = logging.getLogger("arlo.jobs.polymarket")


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
_LEADERBOARD_PAGES = [
    ("monthly", "profit"),
    ("monthly", "volume"),
    ("weekly", "profit"),
    ("weekly", "volume"),
]
_TOP_WALLET_CAP = 50
_PROXY_WALLET_RE = re.compile(r'"proxyWallet":"(0x[a-f0-9]{40})"')

# Signal filters — tuned against scan #1 against the actual leaderboard
# (see /tmp/poly_probe/probe2.py probe output). The deal-breakers are:
#   - too few holders (signal is noise, not consensus)
#   - holders losing in aggregate (no point copying a losing trade)
#   - price already past entry by 60%+ (no upside left)
#   - resolves too soon to enter, or too far to be worth capital lockup
_MIN_HOLDERS = 3
_MIN_TOTAL_SIZE_USD = 2_000.0
_MIN_AVG_PNL_PCT = 0.0
_MIN_DAYS_TO_RESOLUTION = 1.0
_MAX_DAYS_TO_RESOLUTION = 120.0
_MIN_CUR_PRICE = 0.05
_MAX_CUR_PRICE = 0.90
_MAX_ENTRY_DRIFT = 1.60  # cur_price ≤ avg_entry × this

# Score weights — commonality and upside dominate; size and PnL nudge
# the order; time penalty breaks ties toward sooner resolution.
_W_COMMONALITY = 3.0
_W_SIZE = 2.0
_W_UPSIDE = 4.0
_W_PNL = 2.0
_W_TIME_PENALTY = 0.5


async def execute_polymarket_scan_job(session: AsyncSession, job: JobRow) -> None:
    """Run one Polymarket scan: fetch → filter → score → persist → notify."""
    try:
        await update_job_progress(
            session, job.id,
            current_step="fetching_leaderboard",
            progress_message="Fetching top wallets from Polymarket leaderboard",
            iteration_count=1,
        )

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            wallets = await _fetch_leaderboard_wallets(client)
            if not wallets:
                await finalize_job(
                    session, job.id,
                    status=JobStatus.FAILED,
                    error_message="leaderboard returned 0 wallets",
                    stop_reason=JobStopReason.ERROR.value,
                )
                return

            wallets = wallets[:_TOP_WALLET_CAP]
            await update_job_progress(
                session, job.id,
                current_step="fetching_positions",
                progress_message=f"Fetching positions for top {len(wallets)} wallets",
                iteration_count=2,
            )

            positions_by_wallet = await _fetch_all_positions(client, wallets)

        await update_job_progress(
            session, job.id,
            current_step="scoring",
            progress_message="Aggregating + scoring common positions",
            iteration_count=3,
        )

        signals = _compute_signals(positions_by_wallet)

        await update_job_progress(
            session, job.id,
            current_step="persisting",
            progress_message=f"Upserting {len(signals)} signals",
            iteration_count=4,
        )
        fresh_high_edge = await _upsert_signals(session, signals)

        # Mark assets not seen this scan as is_live=False so the iOS app
        # can render them as stale and the next scan can flip them back.
        seen_asset_ids = [s["asset_id"] for s in signals]
        stale_count = await _mark_stale(session, seen_asset_ids)

        notification_status = "skipped_no_fresh_signals"
        if fresh_high_edge:
            if not settings.polymarket_notify_email:
                # User opted out — signals are visible in the iOS app +
                # web. Mark them notified anyway so we don't keep them
                # in the "fresh" queue for if/when emails are re-enabled.
                await _mark_notified(session, [s["asset_id"] for s in fresh_high_edge])
                notification_status = "skipped_email_opted_out"
            elif settings.approval_recipient_email:
                try:
                    await _send_signal_email(fresh_high_edge)
                    notification_status = f"sent ({len(fresh_high_edge)} fresh)"
                    await _mark_notified(session, [s["asset_id"] for s in fresh_high_edge])
                except Exception:
                    logger.exception("Polymarket notification email failed for job %s", job.id)
                    notification_status = "email_failed"
            else:
                notification_status = "skipped_no_recipient"

        summary = {
            "wallets_scanned": len(wallets),
            "signals_qualifying": len(signals),
            "fresh_high_edge_count": len(fresh_high_edge),
            "stale_marked_count": stale_count,
            "notification_status": notification_status,
        }
        preview = (
            f"Polymarket: {len(signals)} signals from {len(wallets)} wallets, "
            f"{len(fresh_high_edge)} fresh high-edge, "
            f"{stale_count} marked stale. Notification: {notification_status}."
        )
        await finalize_job(
            session, job.id,
            status=JobStatus.SUCCEEDED,
            result_preview=preview,
            result_data=json.dumps(summary),
        )
    except Exception as e:
        logger.exception("polymarket_scan job %s crashed", job.id)
        await finalize_job(
            session, job.id,
            status=JobStatus.FAILED,
            error_message=f"{type(e).__name__}: {e}",
            stop_reason=JobStopReason.ERROR.value,
        )


# ───────────────────────── fetchers ─────────────────────────


async def _fetch_leaderboard_wallets(client: httpx.AsyncClient) -> list[str]:
    """Scrape proxy-wallet addresses out of the 4 leaderboard pages.

    Order is preserved: profit-leaders come before volume-leaders, so the
    50-wallet cap biases toward "actually profitable" not "just churns
    volume."
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for window, sort in _LEADERBOARD_PAGES:
        url = f"https://polymarket.com/leaderboard/overall/{window}/{sort}"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Leaderboard fetch failed for %s/%s: %s", window, sort, e)
            continue
        for match in _PROXY_WALLET_RE.findall(resp.text):
            if match not in seen:
                seen.add(match)
                ordered.append(match)
        await asyncio.sleep(0.3)
    return ordered


async def _fetch_all_positions(
    client: httpx.AsyncClient, wallets: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Fetch every wallet's positions, with a small concurrency cap so
    we don't hammer data-api.polymarket.com from a single source IP.
    """
    sem = asyncio.Semaphore(5)

    async def one(wallet: str) -> tuple[str, list[dict[str, Any]]]:
        async with sem:
            url = (
                "https://data-api.polymarket.com/positions"
                f"?user={wallet}&limit=200&sortBy=CURRENT&sortDirection=DESC"
            )
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, json.JSONDecodeError) as e:
                logger.warning("positions fetch failed for %s: %s", wallet[:10], e)
                return wallet, []
            if not isinstance(data, list):
                return wallet, []
            return wallet, data

    results = await asyncio.gather(*(one(w) for w in wallets))
    return dict(results)


# ───────────────────────── scoring ─────────────────────────


def _days_until(end_iso: str | None) -> float | None:
    if not end_iso:
        return None
    try:
        if "T" in end_iso:
            dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(end_iso + "T23:59:59+00:00")
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    return (dt - now).total_seconds() / 86400.0


def _parse_end_date(end_iso: str | None) -> datetime | None:
    if not end_iso:
        return None
    try:
        if "T" in end_iso:
            return datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        return datetime.fromisoformat(end_iso + "T23:59:59+00:00")
    except ValueError:
        return None


def _recommended_action(
    cur_price: float,
    avg_entry: float,
    target_price: float,
    days_to_resolution: float | None,
) -> str:
    """Human-readable hold suggestion. Kept short — fits in an iOS
    detail-view header.
    """
    horizon = ""
    if days_to_resolution is not None:
        if days_to_resolution <= 3:
            horizon = "until resolution (a few days)"
        elif days_to_resolution <= 30:
            horizon = f"~{round(days_to_resolution)} days until resolution"
        elif days_to_resolution <= 90:
            horizon = f"~{round(days_to_resolution / 7)} weeks until resolution"
        else:
            horizon = "or 60 days, whichever is sooner"
    return (
        f"Enter ≤ {cur_price:.2f}, exit at {target_price:.2f} ({horizon}). "
        f"Top traders averaged in at {avg_entry:.2f}."
    )


def _compute_signals(
    positions_by_wallet: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Aggregate per-wallet positions by asset, apply filters, compute
    edge_score, return rows ready to upsert.
    """
    # asset_id -> list of (wallet, position dict)
    by_asset: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    meta: dict[str, dict[str, Any]] = {}

    for wallet, positions in positions_by_wallet.items():
        for p in positions:
            if p.get("redeemable"):
                continue
            if (p.get("size") or 0) < 1:
                continue
            asset = p.get("asset")
            if not asset:
                continue
            by_asset.setdefault(asset, []).append((wallet, p))
            if asset not in meta:
                meta[asset] = {
                    "condition_id": p.get("conditionId", ""),
                    "event_id": p.get("eventId"),
                    "title": p.get("title", "?"),
                    "outcome": p.get("outcome", "?"),
                    "outcome_index": p.get("outcomeIndex", 0),
                    "slug": p.get("slug"),
                    "event_slug": p.get("eventSlug"),
                    "icon": p.get("icon"),
                    "end_date_iso": p.get("endDate"),
                }

    rows: list[dict[str, Any]] = []
    for asset, holders in by_asset.items():
        n = len(holders)
        if n < _MIN_HOLDERS:
            continue
        # Weighted by current_value, not arithmetic mean. A whale entering at
        # 0.10 with $100k and a small holder entering at 0.90 with $1k have
        # a real cohort entry of ~0.11, not 0.50. Reviewer flagged the simple
        # mean as misleading because the entry-drift filter relies on this.
        size_weights = [(h[1].get("currentValue") or 0) for h in holders]
        sum_weights = sum(size_weights)
        if sum_weights > 0:
            avg_entry = sum(
                (h[1].get("avgPrice") or 0) * w
                for h, w in zip(holders, size_weights)
            ) / sum_weights
        else:
            avg_entry = sum((h[1].get("avgPrice") or 0) for h in holders) / n
        cur_price = holders[0][1].get("curPrice") or 0
        avg_pnl_pct = sum((h[1].get("percentPnl") or 0) for h in holders) / n
        total_size_usd = sum_weights
        d_to_res = _days_until(meta[asset]["end_date_iso"])

        if cur_price < _MIN_CUR_PRICE or cur_price > _MAX_CUR_PRICE:
            continue
        if total_size_usd < _MIN_TOTAL_SIZE_USD:
            continue
        if avg_pnl_pct < _MIN_AVG_PNL_PCT:
            continue
        if d_to_res is None or d_to_res < _MIN_DAYS_TO_RESOLUTION or d_to_res > _MAX_DAYS_TO_RESOLUTION:
            continue
        if avg_entry > 0 and cur_price > avg_entry * _MAX_ENTRY_DRIFT:
            continue

        target_price = min(0.92, max(cur_price, avg_entry) * 1.4)
        upside = (target_price - cur_price) / cur_price if cur_price else 0

        edge = (
            _W_COMMONALITY * n
            + _W_SIZE * math.log10(max(total_size_usd, 1))
            + _W_UPSIDE * upside
            + _W_PNL * min(avg_pnl_pct, 100) / 100
            - _W_TIME_PENALTY * (d_to_res / 90)
        )

        rows.append({
            "asset_id": asset,
            "condition_id": meta[asset]["condition_id"],
            "event_id": meta[asset]["event_id"],
            "title": meta[asset]["title"],
            "outcome": meta[asset]["outcome"],
            "outcome_index": meta[asset]["outcome_index"] or 0,
            "slug": meta[asset]["slug"],
            "event_slug": meta[asset]["event_slug"],
            "icon_url": meta[asset]["icon"],
            "end_date": _parse_end_date(meta[asset]["end_date_iso"]),
            "n_holders": n,
            "avg_entry_price": round(avg_entry, 4),
            "cur_price": round(cur_price, 4),
            "target_exit_price": round(target_price, 4),
            "upside_pct": round(upside * 100, 1),
            "avg_pnl_pct": round(avg_pnl_pct, 1),
            "total_size_usd": round(total_size_usd, 0),
            "days_to_resolution": round(d_to_res, 1),
            "edge_score": round(edge, 2),
            "recommended_action": _recommended_action(
                cur_price, avg_entry, target_price, d_to_res
            ),
            "holders": [
                {
                    "wallet": h[0],
                    "pseudonym": h[1].get("name") or h[1].get("pseudonym") or "",
                    "avg_price": round(h[1].get("avgPrice") or 0, 4),
                    "current_value": round(h[1].get("currentValue") or 0, 2),
                    "pnl_pct": round(h[1].get("percentPnl") or 0, 1),
                }
                for h in holders
            ],
        })

    rows.sort(key=lambda r: r["edge_score"], reverse=True)

    # Collapse to one signal per Polymarket market. Each conditionId has
    # TWO outcomes (Yes/No, or team A vs team B). When the top-50 cohort
    # splits — 5 traders backing St. Louis, 4 backing the Athletics —
    # both sides qualify and the API would surface contradictory
    # "take both outcomes" signals. The higher-edge side is the
    # consensus; suppress the other.
    seen_conditions: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        cid = row.get("condition_id") or ""
        if cid and cid in seen_conditions:
            continue
        if cid:
            seen_conditions.add(cid)
        deduped.append(row)
    return deduped


# ───────────────────────── persistence ─────────────────────────


async def _upsert_signals(
    session: AsyncSession, signals: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Upsert each signal row. Returns the subset that is BOTH brand-new
    (no prior row for this asset) AND high-edge (edge_score >= 18), which
    is what the notification step looks at.

    Uses the same atomic-newness trick apartments_persist uses
    (RETURNING (xmax = 0) ``inserted``) to decide insert-vs-update in
    one statement. Without this, two concurrent scans could both read
    notified_at=NULL between their own inserts and double-notify the
    same signal.
    """
    if not signals:
        return []

    now = datetime.now(timezone.utc)
    fresh: list[dict[str, Any]] = []

    for s in signals:
        stmt = (
            pg_insert(PolymarketSignalRow)
            .values(
                asset_id=s["asset_id"],
                condition_id=s["condition_id"],
                event_id=s["event_id"],
                title=s["title"],
                outcome=s["outcome"],
                outcome_index=s["outcome_index"],
                slug=s["slug"],
                event_slug=s["event_slug"],
                icon_url=s["icon_url"],
                end_date=s["end_date"],
                n_holders=s["n_holders"],
                avg_entry_price=s["avg_entry_price"],
                cur_price=s["cur_price"],
                target_exit_price=s["target_exit_price"],
                upside_pct=s["upside_pct"],
                avg_pnl_pct=s["avg_pnl_pct"],
                total_size_usd=s["total_size_usd"],
                days_to_resolution=s["days_to_resolution"],
                edge_score=s["edge_score"],
                recommended_action=s["recommended_action"],
                holders=s["holders"],
                first_seen_at=now,
                last_scan_at=now,
                is_live=True,
            )
            .on_conflict_do_update(
                index_elements=["asset_id"],
                set_={
                    # Refresh the volatile fields; preserve first_seen_at
                    # and notified_at (omitted from set_ so they stick).
                    "n_holders": s["n_holders"],
                    "avg_entry_price": s["avg_entry_price"],
                    "cur_price": s["cur_price"],
                    "target_exit_price": s["target_exit_price"],
                    "upside_pct": s["upside_pct"],
                    "avg_pnl_pct": s["avg_pnl_pct"],
                    "total_size_usd": s["total_size_usd"],
                    "days_to_resolution": s["days_to_resolution"],
                    "edge_score": s["edge_score"],
                    "recommended_action": s["recommended_action"],
                    "holders": s["holders"],
                    "title": s["title"],
                    "outcome": s["outcome"],
                    "end_date": s["end_date"],
                    "last_scan_at": now,
                    "is_live": True,
                },
            )
            .returning(literal_column("(xmax = 0)").label("inserted"))
        )
        result = await session.execute(stmt)
        inserted_row = result.one_or_none()
        was_insert = bool(inserted_row[0]) if inserted_row else False

        # Notify only on FIRST appearance of the signal AND high edge.
        # The xmax-based check is atomic; the second of two concurrent
        # scans will see was_insert=False on the same row.
        if was_insert and s["edge_score"] >= 18.0:
            fresh.append(s)

    await session.commit()
    return fresh


async def _mark_stale(session: AsyncSession, seen_asset_ids: list[str]) -> int:
    """Flip is_live=False for any previously-live row not seen in this scan.

    When the scan finds zero qualifying signals, ``seen_asset_ids`` is
    empty — in that case we mark every live row stale (the simple `where
    asset_id NOT IN ()` would be a SQL parse error in postgres, so we
    branch).
    """
    stmt = (
        update(PolymarketSignalRow)
        .where(PolymarketSignalRow.is_live.is_(True))
        .values(is_live=False)
        .returning(PolymarketSignalRow.asset_id)
    )
    if seen_asset_ids:
        stmt = stmt.where(~PolymarketSignalRow.asset_id.in_(seen_asset_ids))
    result = await session.execute(stmt)
    rows = result.all()
    await session.commit()
    return len(rows)


async def _mark_notified(session: AsyncSession, asset_ids: list[str]) -> None:
    if not asset_ids:
        return
    now = datetime.now(timezone.utc)
    await session.execute(
        update(PolymarketSignalRow)
        .where(PolymarketSignalRow.asset_id.in_(asset_ids))
        .values(notified_at=now)
    )
    await session.commit()


# ───────────────────────── notification ─────────────────────────


async def _send_signal_email(signals: list[dict[str, Any]]) -> None:
    """Plain-HTML digest of fresh high-edge signals.

    The styling is deliberately minimal — it should look the same as the
    apartments-match digest the user is already getting.
    """
    recipient = settings.approval_recipient_email
    if not recipient:
        return

    # Cap the per-email listing at 10 to keep the digest scannable, but
    # be transparent in the subject + header when the cohort is larger.
    SHOWN = 10
    shown_signals = signals[:SHOWN]
    rest = len(signals) - len(shown_signals)

    rows_html = []
    for s in shown_signals:
        slug = s.get("event_slug") or s.get("slug") or ""
        # /us/event/* is Polymarket's Universal Link path — opens the
        # iOS app on tap if installed, otherwise falls back to App Store
        # install. See apple-app-site-association on polymarket.com.
        url = f"https://polymarket.com/us/event/{slug}" if slug else "https://polymarket.com"
        rows_html.append(
            f"<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #eee'>"
            f"<a href='{url}' style='color:#0a66c2;text-decoration:none'>"
            f"<b>{s['title']}</b></a> &mdash; <i>{s['outcome']}</i>"
            f"<br><small>{s['recommended_action']}</small></td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap'>"
            f"<b>edge {s['edge_score']:.1f}</b><br>"
            f"<small>{s['n_holders']} traders, +{s['upside_pct']:.0f}% upside</small></td>"
            f"</tr>"
        )

    header = (
        f"{len(signals)} new Polymarket signals"
        + (f" (showing top {SHOWN}, see the iOS app for the rest)" if rest > 0 else "")
    )
    body = (
        "<div style='font-family:-apple-system,sans-serif;max-width:640px'>"
        f"<h2>{header}</h2>"
        "<p style='color:#666'>Top-50 leaderboard traders converging on these positions.</p>"
        "<table style='width:100%;border-collapse:collapse'>"
        f"{''.join(rows_html)}"
        "</table>"
        "</div>"
    )
    text_lines = [header, ""]
    for s in shown_signals:
        text_lines.append(
            f"- {s['title']} [{s['outcome']}] "
            f"edge={s['edge_score']:.1f} | {s['recommended_action']}"
        )
    await email_sender.send_email(
        to=recipient,
        subject=f"{len(signals)} new Polymarket copy-trade signals",
        html_body=body,
        text_fallback="\n".join(text_lines),
    )
