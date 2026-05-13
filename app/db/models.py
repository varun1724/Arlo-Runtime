import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowRow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    context: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    step_definitions: Mapped[str] = mapped_column(Text, nullable=False)
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # Progress
    current_step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    iteration_count: Mapped[int] = mapped_column(Integer, default=0)

    # Result
    result_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Workspace
    workspace_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    workspace_pinned: Mapped[bool] = mapped_column(default=False)

    # Worker tracking
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Workflow (NULL for standalone jobs)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=True, index=True
    )
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Round 3: token usage and estimated cost. Populated by job handlers
    # after each Claude CLI call. Nullable because (a) older rows predate
    # these columns and (b) some Claude CLI versions don't return usage data.
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobEventRow(Base):
    __tablename__ = "job_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApartmentListingGroupRow(Base):
    """Atomic newness tracker for the apartment_search dedup pipeline.

    The persist job inserts into this table with ``ON CONFLICT DO NOTHING
    RETURNING (xmax = 0)``. If the INSERT branch fired, this scan is
    the first to see the group — emit a notification. If the conflict
    branch fired, another scan already claimed it — skip.

    Without this table, two overlapping scans both snapshot
    pre_existing_group_ids before either commits and each independently
    concludes the group is new. The codex Round 2 review flagged this
    as a real double-notify race.
    """

    __tablename__ = "apartment_listing_groups"

    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApartmentListingRow(Base):
    __tablename__ = "apartment_listings"

    listing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    neighborhood: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    rent_usd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baths: Mapped[float | None] = mapped_column(Float, nullable=True)
    sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bike_time_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_breakdown: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    amenities: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    photos: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=True
    )
    raw: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    # Dedup columns (migration 0006). listing_group_id is a deterministic
    # hash computed by the apartments_persist job's tiered match rule;
    # rows with the same group id represent the same physical apartment
    # surfaced on different rental sites.
    listing_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    canonical_address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    building_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    photo_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SavedApartmentRow(Base):
    __tablename__ = "saved_apartments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    listing_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("apartment_listings.listing_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_email: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("listing_id", "user_email", name="uq_saved_apartments_listing_user"),
    )


class PolymarketSignalRow(Base):
    """One row per (market outcome) that the copytrade scan currently
    surfaces as a high-edge signal. See migration 0007 for design notes.

    Lifecycle: each scan upserts the rows it finds and sets is_live=True;
    a sweep at end-of-scan marks rows not seen in this scan as is_live=False
    rather than deleting them, so the iOS app can render "stale" state
    and the next scan can flip them back to live if they re-qualify.
    """

    __tablename__ = "polymarket_signals"

    asset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    condition_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_index: Mapped[int] = mapped_column(Integer, nullable=False)
    slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    event_slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    n_holders: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    cur_price: Mapped[float] = mapped_column(Float, nullable=False)
    target_exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    upside_pct: Mapped[float] = mapped_column(Float, nullable=False)
    avg_pnl_pct: Mapped[float] = mapped_column(Float, nullable=False)
    total_size_usd: Mapped[float] = mapped_column(Float, nullable=False)
    days_to_resolution: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge_score: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    holders: Mapped[Any] = mapped_column(JSONB, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_scan_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_live: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaperBankrollRow(Base):
    """Paper-trading bankroll. Separate from UserBankrollRow on purpose
    so the sim loop can't touch the user's real-money state.

    The paper engine job (app/jobs/paper_trading.py) initializes this
    via the POST /paper-trading/start endpoint, then debits/credits
    current_balance_usd on each entry/exit. ``ends_at`` is the
    auto-stop deadline (set to start_time + 7 days by default).
    ``status`` is 'active' / 'stopped' / 'completed'.
    """

    __tablename__ = "paper_bankroll"

    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    initial_balance_usd: Mapped[float] = mapped_column(Float, nullable=False)
    current_balance_usd: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_realized_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class PaperTradeRow(Base):
    """One simulated Polymarket position. Status starts as 'open' on
    entry; the engine refreshes cur_price + unrealized_pnl_usd each
    cycle and flips status on exit:
      - closed_win: cur_price reached target_exit_price
      - closed_loss: cur_price dropped below entry_price * 0.5 (stop)
      - closed_resolved: market resolved (end_date past)
      - closed_signal_dropped: source signal went is_live=False
      - closed_stale: open for >30 days with no movement
    """

    __tablename__ = "paper_trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    asset_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    condition_id: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_index: Mapped[int] = mapped_column(Integer, nullable=False)
    slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    event_slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    target_exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    edge_score_at_entry: Mapped[float] = mapped_column(Float, nullable=False)
    stake_usd: Mapped[float] = mapped_column(Float, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)

    cur_price: Mapped[float] = mapped_column(Float, nullable=False)
    cur_value_usd: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # VARCHAR(32) — widened from 16 in migration 0010 because
    # 'closed_signal_dropped' (21 chars) was overflowing and poisoning
    # the engine session every cycle.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    realized_pnl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserBankrollRow(Base):
    """The user's current Polymarket bankroll for bet-size suggestions.

    Single row per user_email (single-user app today). The signals API
    reads this on each /signals call and adds a ``suggested_bet_usd``
    field to every row based on quarter Kelly with a 70% confidence
    discount, capped at 15% of bankroll. User updates manually after
    each trade resolves — see migration 0008 for design notes.
    """

    __tablename__ = "user_bankroll"

    user_email: Mapped[str] = mapped_column(String(256), primary_key=True)
    balance_usd: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
