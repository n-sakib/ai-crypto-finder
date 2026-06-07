"""
GMGN Discovery Models — tracks tokens discovered via GMGN API.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, DateTime, Float, Integer, Boolean, Text,
    ForeignKey, UniqueConstraint, Index, Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class GMGNToken(Base):
    """Token discovered from GMGN trending/new pairs API."""

    __tablename__ = "gmgn_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(String(32), nullable=False, index=True)
    token_address = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=True)
    name = Column(String(128), nullable=True)

    # GMGN-specific metrics
    market_cap = Column(Float, nullable=True)
    liquidity = Column(Float, nullable=True)
    volume_24h = Column(Float, nullable=True)
    price_change_24h = Column(Float, nullable=True)
    price_change_5m = Column(Float, nullable=True)
    price_change_1h = Column(Float, nullable=True)
    holders = Column(Integer, nullable=True)
    swaps_24h = Column(Integer, nullable=True)
    buys_24h = Column(Integer, nullable=True)
    sells_24h = Column(Integer, nullable=True)
    buy_volume_24h = Column(Float, nullable=True)
    sell_volume_24h = Column(Float, nullable=True)
    net_volume_24h = Column(Float, nullable=True)

    # GMGN scores
    gmgn_score = Column(Float, nullable=True)
    hot_level = Column(Integer, nullable=True)

    # DexScreener enrichment
    dex_url = Column(String(512), nullable=True)
    pair_address = Column(String(128), nullable=True)
    price_usd = Column(Float, nullable=True)
    fdv = Column(Float, nullable=True)

    # Metadata
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("chain", "token_address", name="uq_gmgn_token_chain_addr"),
        Index("ix_gmgn_tokens_first_seen", "first_seen_at"),
        Index("ix_gmgn_tokens_volume", "volume_24h"),
    )


class GMGNDiscoveryRanking(Base):
    """Persisted rankings for GMGN discovery windows."""

    __tablename__ = "gmgn_discovery_rankings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gmgn_token_id = Column(UUID(as_uuid=True), ForeignKey("gmgn_tokens.id"), nullable=False)
    rank = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    token = relationship("GMGNToken")

    __table_args__ = (
        Index("ix_gmgn_rankings_window", "window_start", "window_end"),
    )
