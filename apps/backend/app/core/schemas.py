"""
Pydantic schemas for API request/response validation.

These are separate from SQLAlchemy models to keep the API contract clean.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.core.models import (
    AgeBucket, RiskLevel, RankingTier, NarrativeType, NarrativeStrength,
    DiscoverySource, PipelineStatus,
)


# ── Token Schemas ──────────────────────────────────────────────────────

class TokenSummary(BaseModel):
    """Compact token view for list responses."""
    id: UUID
    chain: str
    symbol: str
    name: Optional[str] = None
    contract_address: str
    pair_address: str
    age_bucket: Optional[AgeBucket] = None
    liquidity_usd: float = 0.0
    volume_24h: float = 0.0
    price_change_24h: float = 0.0
    market_cap: float = 0.0
    early_momentum_score: float = 0.0
    risk_level: Optional[RiskLevel] = None
    tier: Optional[RankingTier] = None
    rank_position: Optional[int] = None

    model_config = {"from_attributes": True}


class TokenDetail(TokenSummary):
    """Full token detail for drill-down."""
    dex_id: Optional[str] = None
    launched_at: Optional[datetime] = None
    first_seen_at: Optional[datetime] = None
    pipeline_status: PipelineStatus

    # Safety
    is_honeypot: bool = False
    has_mint_risk: bool = False
    has_sell_block: bool = False
    is_liquidity_locked: bool = False
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    liquidity_trend: Optional[str] = None

    # Volume / trades
    volume_1h: float = 0.0
    trade_count_24h: int = 0
    unique_buyers_24h: int = 0
    unique_sellers_24h: int = 0

    # Holders
    holder_count: int = 0
    meaningful_holders: int = 0
    top_holder_pct: float = 0.0

    # Price
    price_usd: float = 0.0
    price_change_1h: float = 0.0
    price_change_6h: float = 0.0
    price_change_7d: float = 0.0
    distance_from_24h_high: float = 0.0
    distance_from_7d_high: float = 0.0
    distance_from_30d_high: float = 0.0
    fully_diluted_valuation: float = 0.0

    # Scores
    attention_score: float = 0.0
    market_flow_score: float = 0.0
    adoption_score: float = 0.0
    liquidity_quality_score: float = 0.0
    smart_money_score: float = 0.0
    narrative_score: float = 0.0
    price_compression_score: float = 0.0
    risk_score: float = 0.0

    # Review
    is_approved: bool = False
    coingecko_trending: bool = False
    cmc_trending: bool = False
    news_mentions: int = 0

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Ranking Response ──────────────────────────────────────────────────

class RankingResponse(BaseModel):
    tier_a: list[TokenSummary] = []
    tier_b: list[TokenSummary] = []
    tier_c: list[TokenSummary] = []
    excluded: list[TokenSummary] = []
    total_candidates: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Pipeline Status ───────────────────────────────────────────────────

class PipelineStatusResponse(BaseModel):
    latest_runs: list[dict] = []
    tokens_in_pipeline: int = 0
    tokens_by_status: dict[str, int] = {}
    last_full_run: Optional[datetime] = None
    progress: dict = {}


# ── Discovery Event ───────────────────────────────────────────────────

class DiscoveryEventResponse(BaseModel):
    id: UUID
    token_id: UUID
    source: DiscoverySource
    signal_strength: float
    discovered_at: datetime

    model_config = {"from_attributes": True}


# ── Webhook / Incoming ────────────────────────────────────────────────

class TokenDiscoveredRequest(BaseModel):
    chain: str
    contract_address: str
    pair_address: str
    symbol: str
    name: Optional[str] = None
    dex_id: Optional[str] = None
    source: DiscoverySource
    raw_data: dict = Field(default_factory=dict)
