"""
DexScreener Discovery Models.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, DateTime, Float, Integer, Boolean, Text,
    UniqueConstraint, Index, ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class DexScreenerToken(Base):
    """Token discovered from DexScreener token boosts/new pairs API."""

    __tablename__ = "dexscreener_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(String(32), nullable=False, index=True)
    token_address = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=True)
    name = Column(String(128), nullable=True)

    # Pair info
    pair_address = Column(String(128), nullable=True, index=True)
    dex_url = Column(String(512), nullable=True)
    dex_id = Column(String(32), nullable=True)

    # Price & volume
    price_usd = Column(Float, nullable=True)
    price_change_5m = Column(Float, nullable=True)
    price_change_1h = Column(Float, nullable=True)
    price_change_6h = Column(Float, nullable=True)
    price_change_24h = Column(Float, nullable=True)
    volume_5m = Column(Float, nullable=True)
    volume_1h = Column(Float, nullable=True)
    volume_6h = Column(Float, nullable=True)
    volume_24h = Column(Float, nullable=True)
    txns_5m_buys = Column(Integer, nullable=True)
    txns_5m_sells = Column(Integer, nullable=True)
    txns_1h_buys = Column(Integer, nullable=True)
    txns_1h_sells = Column(Integer, nullable=True)

    # Liquidity & market cap
    liquidity_usd = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)
    fdv = Column(Float, nullable=True)

    # Boost info
    total_boosts = Column(Integer, nullable=True)
    boost_amount = Column(Float, nullable=True)
    is_boosted = Column(Boolean, default=False)

    # Metadata
    pair_created_at = Column(DateTime(timezone=True), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("chain", "token_address", name="uq_ds_token_chain_addr"),
        Index("ix_ds_tokens_first_seen", "first_seen_at"),
        Index("ix_ds_tokens_volume", "volume_24h"),
        Index("ix_ds_tokens_boosted", "is_boosted"),
    )
