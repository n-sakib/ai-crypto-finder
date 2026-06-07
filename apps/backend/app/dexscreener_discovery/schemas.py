"""DexScreener Discovery Schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DexScreenerDiscoveryItem(BaseModel):
    rank: int
    chain: str
    token_address: str
    symbol: Optional[str] = None
    name: Optional[str] = None
    score: float
    pair_address: Optional[str] = None
    dex_url: Optional[str] = None
    dex_id: Optional[str] = None
    price_usd: Optional[float] = None
    price_change_5m: Optional[float] = None
    price_change_1h: Optional[float] = None
    price_change_6h: Optional[float] = None
    price_change_24h: Optional[float] = None
    volume_5m: Optional[float] = None
    volume_1h: Optional[float] = None
    volume_6h: Optional[float] = None
    volume_24h: Optional[float] = None
    txns_5m_buys: Optional[int] = None
    txns_5m_sells: Optional[int] = None
    txns_1h_buys: Optional[int] = None
    txns_1h_sells: Optional[int] = None
    liquidity_usd: Optional[float] = None
    market_cap: Optional[float] = None
    fdv: Optional[float] = None
    total_boosts: Optional[int] = None
    boost_amount: Optional[float] = None
    is_boosted: bool = False
    pair_created_at: Optional[datetime] = None
    first_seen_at: datetime
    last_seen_at: datetime
    model_config = {"from_attributes": True}


class DexScreenerDiscoveryResponse(BaseModel):
    window: str
    window_start: datetime
    window_end: datetime
    total_tokens: int
    generated_at: datetime
    tokens: list[DexScreenerDiscoveryItem]


class DexScreenerStats(BaseModel):
    total_tokens: int
    boosted_tokens: int
    latest_token_at: Optional[datetime] = None
    generated_at: datetime
