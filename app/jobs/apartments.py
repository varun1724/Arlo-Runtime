"""Persist apartment-search synthesis results and fire notifications.

Runs as the final step of the ``apartment_search`` pipeline. Reads
the prior step's ``apartment_synthesis`` JSON from the workflow
context, upserts each listing into ``apartment_listings`` keyed by
sha1 of the canonical URL, tracks which listings are new since the
last scan, marks listings not seen in 7 days as inactive, then —
when any new listings are flagged ``notify_worthy=true`` — sends a
match-notification email directly via ``email_sender``.

This pipeline is deliberately NOT registered in the notification
dispatch dicts (``_TEMPLATE_OVERRIDE_KEY`` etc.) because it has no
approval gate and no build-complete email. The persist step owns
the entire notification lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    ApartmentListingGroupRow,
    ApartmentListingRow,
    JobRow,
    WorkflowRow,
)
from app.models.job import JobStatus, JobStopReason
from app.services import email_sender, report_renderer
from app.services.job_service import finalize_job, update_job_progress

logger = logging.getLogger("arlo.jobs.apartments")


# Listings not re-seen in this many days are marked inactive. Most SF
# rental listings churn within a week, so a 7-day window catches the
# common case without flapping on transient scrape misses.
STALE_DAYS = 7


# Street type abbreviations to fold when normalizing addresses.
# Lowercased; longer keys come first so "boulevard" beats "blvd"
# during the replace pass even though they collapse to the same suffix.
_STREET_TYPE_NORMALIZE = {
    "boulevard": "blvd",
    "avenue": "ave",
    "street": "st",
    "drive": "dr",
    "road": "rd",
    "court": "ct",
    "place": "pl",
    "terrace": "ter",
    "highway": "hwy",
    "parkway": "pkwy",
    "lane": "ln",
}


def _canonical_listing_id(url: str) -> str:
    """sha1(canonicalized URL). Lowercased + stripped to deduplicate
    listings that appear on multiple sources with the same canonical
    URL trailing query-string noise."""
    canonical = (url or "").strip().lower().split("?")[0].rstrip("/")
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _normalize_address(addr: str | None) -> tuple[str | None, str | None]:
    """Fold an address to a stable, comparable form. Returns
    ``(normalized_addr, extracted_unit_hint)``.

    Codex Round 2 caught the unit-leak bug: if the unit was embedded
    in the address text and Claude didn't extract it into a separate
    field, my old normalizer simply stripped it and the dedup function
    lost the disambiguator. Now the unit fragment is captured before
    being removed, so the caller can use it when no explicit
    ``listing.unit`` was emitted.

    Steps:
      - lowercase + collapse whitespace
      - drop trailing city/state (everything after first comma)
      - extract any "apt N" / "unit N" / "#N" fragment as the unit hint
      - then strip that fragment out of the returned address
      - punctuation → space; fold street-type and directional words
    """
    if not addr:
        return None, None
    s = addr.strip().lower()
    s = s.split(",", 1)[0]

    # Capture the unit before stripping. Match any of the standard
    # prefixes. Stop at whitespace or end-of-string so we get just the
    # alphanumeric unit token.
    unit_hint: str | None = None
    m = re.search(r"\b(?:apt|apartment|unit|suite|ste|#)\s*([A-Za-z0-9-]+)", s)
    if m:
        candidate = m.group(1).strip()
        if candidate:
            unit_hint = re.sub(r"[^\w]", "", candidate) or None

    # Now strip the unit fragment from the address.
    s = re.sub(r"\b(apt|apartment|unit|suite|ste|#)\s*\S+", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for long_form, short in _STREET_TYPE_NORMALIZE.items():
        s = re.sub(rf"\b{long_form}\b", short, s)
    for long_form, short in (("north", "n"), ("south", "s"), ("east", "e"), ("west", "w")):
        s = re.sub(rf"\b{long_form}\b", short, s)

    addr_out = s if len(s) >= 4 else None
    return addr_out, unit_hint


def _normalize_unit(unit: str | None) -> str | None:
    """Strip prefixes (#, apt, unit) so '#5' and 'Apt 5' both → '5'."""
    if not unit:
        return None
    s = str(unit).strip().lower()
    s = re.sub(r"^(apt|apartment|unit|suite|ste|#)\s*", "", s)
    s = re.sub(r"[^\w]", "", s)
    return s or None


def _rent_bucket(rent: int | float | None, width: int = 50) -> int | None:
    """Round rent to the nearest ``width`` dollars so $3,995 and $4,000
    hash to the same bucket (codex Round 2: tolerance of ~$25-50)."""
    if rent is None:
        return None
    try:
        return int(round(float(rent) / width)) * width
    except (TypeError, ValueError):
        return None


def _sqft_bucket(sqft: int | float | None, width: int = 100) -> int | str:
    """Round sqft to a 100-sqft bucket. When None, returns a sentinel
    so two listings without sqft fall into the same bucket but
    listings WITH different sqft do NOT.

    Codex Round 2: Tier 2/3 of the dedup hash now includes sqft so
    "123 Main #5 (800sqft)" and "123 Main #6 (1050sqft)" — same
    address, same rent, same beds, missing unit on both — don't
    collapse the way the prior implementation did.
    """
    if sqft is None:
        return "unknown"
    try:
        return int(round(float(sqft) / width)) * width
    except (TypeError, ValueError):
        return "unknown"


def _coord_bucket(value: float | None, precision: int = 4) -> str | None:
    """Truncate a lat/lon to N decimal places (4 ≈ 11m in SF latitudes).
    Codex Round 1 flagged 50m as too loose for dense SF; 4dp ≈ 11m sits
    inside the strong-match band."""
    if value is None:
        return None
    try:
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return None


def compute_group_id(listing: dict) -> str:
    """Deterministic dedup key — same physical apartment across sites
    collapses to one group.

    Tiered match (in order of confidence):
      1. ``canonical_address`` + ``unit`` — gold; merges identical units
      2. ``canonical_address`` + ``rent_bucket`` + ``beds`` + ``sqft_bucket``
         — strong when unit is missing. The sqft constraint prevents
         two different units in the same building (e.g. #5 800sqft
         and #6 1050sqft, both 2BR/\$4000) from collapsing.
      3. Coord bucket (4dp lat/lon) + ``rent_bucket`` + ``beds`` +
         ``sqft_bucket`` — fallback for sources that have geo but no
         clean text address
      4. ``url`` hash — terminal fallback so unmergeable listings still
         get a unique id

    Pure function so the dedup logic is unit-testable without DB.
    """
    addr_normalized, addr_unit_hint = _normalize_address(
        listing.get("canonical_address") or listing.get("address")
    )
    # Prefer the explicit unit field; fall back to whatever the address
    # parser pulled out. Resolves codex Round 2 issue 3 — if Claude
    # missed extracting unit but the address string contained it, we
    # still get the disambiguator.
    unit = _normalize_unit(listing.get("unit")) or addr_unit_hint
    rent_b = _rent_bucket(listing.get("rent_usd"))
    beds = listing.get("beds")
    sqft_b = _sqft_bucket(listing.get("sqft"))
    lat_b = _coord_bucket(listing.get("latitude"))
    lon_b = _coord_bucket(listing.get("longitude"))

    if addr_normalized and unit:
        key = f"addr-unit|{addr_normalized}|{unit}"
    elif addr_normalized and rent_b is not None and beds is not None:
        key = f"addr-price-beds-sqft|{addr_normalized}|{rent_b}|{beds}|{sqft_b}"
    elif lat_b and lon_b and rent_b is not None and beds is not None:
        key = f"geo-price-beds-sqft|{lat_b}|{lon_b}|{rent_b}|{beds}|{sqft_b}"
    else:
        # Terminal fallback — keep the row's identity rather than
        # bucketing unmergeable listings into a giant pile.
        url = (listing.get("url") or "").strip().lower().split("?")[0]
        key = f"url|{url}"

    return hashlib.sha1(key.encode("utf-8")).hexdigest()


async def execute_apartments_persist_job(session: AsyncSession, job: JobRow) -> None:
    """Persist apartment-search results + send notification on new matches.

    Reads the prior step's synthesis JSON from the workflow context.
    Returns a small JSON summary as result_data: new vs known counts
    + notification status.
    """
    try:
        await update_job_progress(
            session, job.id,
            current_step="loading_synthesis",
            progress_message="Loading apartment synthesis from workflow context",
            iteration_count=1,
        )

        if job.workflow_id is None:
            await finalize_job(
                session, job.id,
                status=JobStatus.FAILED,
                error_message="apartments_persist job has no workflow_id",
                stop_reason=JobStopReason.ERROR.value,
            )
            return

        workflow = await session.get(WorkflowRow, job.workflow_id)
        if workflow is None:
            await finalize_job(
                session, job.id,
                status=JobStatus.FAILED,
                error_message=f"workflow {job.workflow_id} not found",
                stop_reason=JobStopReason.ERROR.value,
            )
            return

        context = json.loads(workflow.context or "{}")
        synthesis_raw = context.get("apartment_synthesis")
        synthesis = _parse_synthesis(synthesis_raw)
        if synthesis is None:
            await finalize_job(
                session, job.id,
                status=JobStatus.FAILED,
                error_message="could not parse apartment_synthesis JSON from context",
                stop_reason=JobStopReason.ERROR.value,
            )
            return

        top_matches = synthesis.get("top_matches") or []
        if not isinstance(top_matches, list):
            await finalize_job(
                session, job.id,
                status=JobStatus.FAILED,
                error_message="apartment_synthesis.top_matches is not a list",
                stop_reason=JobStopReason.ERROR.value,
            )
            return

        await update_job_progress(
            session, job.id,
            current_step="upserting",
            progress_message=f"Upserting {len(top_matches)} listings",
            iteration_count=2,
        )

        new_notify_listings, upsert_count, refreshed_count = await _upsert_listings(
            session, top_matches, workflow_id=job.workflow_id
        )

        await update_job_progress(
            session, job.id,
            current_step="marking_stale",
            progress_message="Marking stale listings",
            iteration_count=3,
        )
        stale_count = await _mark_stale_inactive(session)

        # Notification: only when new notify_worthy listings landed in
        # this run AND the user opted in by setting the recipient email.
        notification_status = "skipped_no_new_matches"
        if new_notify_listings:
            if settings.approval_recipient_email:
                try:
                    await _send_match_email(session, new_notify_listings)
                    notification_status = f"sent ({len(new_notify_listings)} new)"
                except Exception:
                    logger.exception(
                        "Apartments notification email failed for job %s; continuing",
                        job.id,
                    )
                    notification_status = "email_failed"
            else:
                notification_status = "skipped_no_recipient"

        summary = {
            "upsert_count": upsert_count,
            "refreshed_count": refreshed_count,
            "new_notify_count": len(new_notify_listings),
            "stale_marked_count": stale_count,
            "notification_status": notification_status,
        }
        preview = (
            f"Apartments: {upsert_count} new, {refreshed_count} refreshed, "
            f"{len(new_notify_listings)} new notify-worthy, "
            f"{stale_count} marked stale. Notification: {notification_status}."
        )
        await finalize_job(
            session, job.id,
            status=JobStatus.SUCCEEDED,
            result_preview=preview,
            result_data=json.dumps(summary),
        )
    except Exception as e:
        logger.exception("apartments_persist job %s crashed", job.id)
        await finalize_job(
            session, job.id,
            status=JobStatus.FAILED,
            error_message=f"{type(e).__name__}: {e}",
            stop_reason=JobStopReason.ERROR.value,
        )


def _parse_synthesis(raw) -> dict | None:
    """The synthesis is stored on the workflow context as a JSON string
    (set by advance_workflow from the prior step's result_data). Defend
    against the rare case where it's already been parsed to a dict."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("apartment_synthesis is not valid JSON: %r", raw[:200])
            return None
    return None


async def _upsert_listings(
    session: AsyncSession,
    listings: list[dict],
    *,
    workflow_id,
) -> tuple[list[dict], int, int]:
    """Upsert each listing keyed by sha1(url) AND compute the
    cross-source listing_group_id. Returns:
    - list of dicts that belong to brand-new groups (groups never seen
      before this scan) AND are flagged notify_worthy. One entry per
      new group; multiple URLs landing in the same new group emit
      only one notification.
    - count of brand-new rows inserted this run
    - count of existing rows refreshed (last_seen_at bumped)

    Insert-vs-update is detected atomically using the Postgres
    ``RETURNING (xmax = 0)`` trick (codex Round 1). New-GROUP vs
    new-URL is the codex Round 2 fix: the prior implementation
    notified on every new URL, which would double-fire when the
    same apartment shows up on Craigslist + Zumper in the same scan.
    """
    now = datetime.now(timezone.utc)
    seen_in_this_run_groups: set[str] = set()
    new_notify_by_group: dict[str, dict] = {}

    new_count = 0
    refreshed_count = 0

    for listing in listings:
        if not isinstance(listing, dict):
            continue
        url = listing.get("url")
        if not url:
            continue
        listing_id = _canonical_listing_id(url)
        group_id = compute_group_id(listing)

        values = {
            "listing_id": listing_id,
            "listing_group_id": group_id,
            "source": str(listing.get("source", "other"))[:32],
            "url": url,
            "title": str(listing.get("title", "(untitled)"))[:8000],
            "neighborhood": _trunc(listing.get("neighborhood"), 64),
            "address": listing.get("address"),
            "canonical_address": _trunc(listing.get("canonical_address"), 256),
            "unit": _trunc(listing.get("unit"), 32),
            "building_name": _trunc(listing.get("building_name"), 128),
            "latitude": _safe_float(listing.get("latitude")),
            "longitude": _safe_float(listing.get("longitude")),
            "photo_fingerprint": _trunc(listing.get("photo_fingerprint_hint"), 128),
            "rent_usd": _safe_int(listing.get("rent_usd")),
            "beds": _safe_int(listing.get("beds")),
            "baths": _safe_float(listing.get("baths")),
            "sqft": _safe_int(listing.get("sqft")),
            "bike_time_min": _safe_int(listing.get("bike_time_min")),
            "score": float(listing.get("score") or 0.0),
            "score_breakdown": listing.get("score_breakdown"),
            "amenities": listing.get("amenities") or [],
            "photos": listing.get("photos") or [],
            "summary": listing.get("summary"),
            "workflow_id": workflow_id,
            "raw": listing,
            "last_seen_at": now,
            "is_active": True,
        }

        stmt = pg_insert(ApartmentListingRow).values(
            **values,
            first_seen_at=now,
        )
        # On conflict (URL already seen), refresh the mutable fields but
        # leave first_seen_at alone — it represents discovery time of
        # this URL, which is what makes "new since last scan" meaningful.
        # Note: we leave group_id mutable too. If a future scan extracts
        # a better address signal, the group can be re-classified.
        stmt = stmt.on_conflict_do_update(
            index_elements=["listing_id"],
            set_={k: v for k, v in values.items() if k != "listing_id"},
        ).returning(
            ApartmentListingRow.listing_id,
            literal_column("(xmax = 0)").label("inserted"),
        )
        result = await session.execute(stmt)
        row = result.first()
        is_brand_new_url = bool(row.inserted) if row is not None else False

        if is_brand_new_url:
            new_count += 1
        else:
            refreshed_count += 1

        # Group-level new detection — atomic. INSERT INTO
        # apartment_listing_groups ON CONFLICT DO NOTHING. On the
        # INSERT branch, RETURNING emits one row with inserted=True
        # (=this scan first-claimed the group → new). On the conflict
        # branch, RETURNING emits ZERO rows (Postgres semantics for
        # ON CONFLICT DO NOTHING), so result.first() is None and we
        # treat it as not-new. Two concurrent scans both racing on
        # the same brand-new group: only one gets a row back, only
        # one notifies. Replaces the pre-loaded set codex flagged
        # as racy.
        if group_id in seen_in_this_run_groups:
            continue
        seen_in_this_run_groups.add(group_id)

        group_claim = await session.execute(
            pg_insert(ApartmentListingGroupRow)
            .values(group_id=group_id, first_seen_at=now)
            .on_conflict_do_nothing(index_elements=["group_id"])
            .returning(literal_column("(xmax = 0)").label("inserted"))
        )
        claim_row = group_claim.first()
        is_brand_new_group = bool(claim_row.inserted) if claim_row is not None else False

        if is_brand_new_group and listing.get("notify_worthy") is True:
            new_notify_by_group[group_id] = listing

    await session.commit()
    # Sort new-notify-worthy desc by score so the email shows best first.
    new_notify_listings = sorted(
        new_notify_by_group.values(),
        key=lambda l: float(l.get("score") or 0),
        reverse=True,
    )
    return new_notify_listings, new_count, refreshed_count


async def _mark_stale_inactive(session: AsyncSession) -> int:
    """Set is_active=false on listings not seen in STALE_DAYS days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
    result = await session.execute(
        update(ApartmentListingRow)
        .where(
            ApartmentListingRow.last_seen_at < cutoff,
            ApartmentListingRow.is_active.is_(True),
        )
        .values(is_active=False)
        .returning(ApartmentListingRow.listing_id)
    )
    rows = result.fetchall()
    await session.commit()
    return len(rows)


async def _send_match_email(session: AsyncSession, new_listings: list[dict]) -> None:
    """Render + send the new-matches email."""
    total_known_result = await session.execute(
        select(ApartmentListingRow.listing_id)
    )
    total_known = len(list(total_known_result.scalars().all()))
    run_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html_body, text_fallback = report_renderer.render_apartment_match_email(
        new_listings, total_known=total_known, run_time=run_time,
    )
    n = len(new_listings)
    top = new_listings[0]
    top_summary = (
        f"${_safe_int(top.get('rent_usd')) or '?'}/mo "
        f"{top.get('neighborhood', '?')} (score {float(top.get('score') or 0):.0f})"
    )
    subject = (
        f"[arlo] 1 new apartment — {top_summary}"
        if n == 1
        else f"[arlo] {n} new apartments — top: {top_summary}"
    )[:120]

    await email_sender.send_email(
        to=settings.approval_recipient_email,
        subject=subject,
        html_body=html_body,
        text_fallback=text_fallback,
    )
    logger.info("Sent apartment match email (%d new listings)", n)


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trunc(value, n: int) -> str | None:
    if value is None:
        return None
    return str(value)[:n]
