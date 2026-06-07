"""GMGN Discovery Pydantic Schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GMGNTokenResponse(BaseModel):
    """API response for a single GMGN token."""
    id: str
    chain: str
    token_address: str
    symbol: Optional[str] = None
    name: Optional[str] = None
    market_cap: Optional[float] = None
    liquidity: Optional[float] = None
    volume_24h: Optional[float] = None
    price_change_24h: Optional[float] = None
    price_change_5m: Optional[float] = None
    price_change_1h: Optional[float] = None
    holders: Optional[int] = None
    swaps_24h: Optional[int] = None
    buys_24h: Optional[int] = None
    sells_24h: Optional[int] = None
    buy_volume_24h: Optional[float] = None
    sell_volume_24h: Optional[float] = None
    net_volume_24h: Optional[float] = None
    gmgn_score: Optional[float] = None
    hot_level: Optional[int] = None
    dex_url: Optional[str] = None
    pair_address: Optional[str] = None
    price_usd: Optional[float] = None
    fdv: Optional[float] = None
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class GMGNDiscoveryItem(BaseModel):
    """Ranked token in discovery results."""
    rank: int
    chain: str
    token_address: str
    symbol: Optional[str] = None
    name: Optional[str] = None
    score: float
    volume_24h: Optional[float] = None
    price_change_24h: Optional[float] = None
    price_change_5m: Optional[float] = None
    market_cap: Optional[float] = None
    liquidity: Optional[float] = None
    holders: Optional[int] = None
    swaps_24h: Optional[int] = None
    buys_24h: Optional[int] = None
    sells_24h: Optional[int] = None
    net_volume_24h: Optional[float] = None
    gmgn_score: Optional[float] = None
    hot_level: Optional[int] = None
    dex_url: Optional[str] = None
    pair_address: Optional[str] = None
    price_usd: Optional[float] = None
    fdv: Optional[float] = None
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class GMGNDiscoveryResponse(BaseModel):
    """Discovery response with ranked tokens."""
    window: str
    window_start: datetime
    window_end: datetime
    total_tokens: int
    generated_at: datetime
    tokens: list[GMGNDiscoveryItem]


class GMGNStats(BaseModel):
    """Stats for GMGN discovery."""
    total_tokens: int
    latest_token_at: Optional[datetime] = None
    generated_at: datetime
