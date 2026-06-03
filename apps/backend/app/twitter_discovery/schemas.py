"""
Pydantic schemas for Twitter Discovery API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.twitter_discovery.models import TwitterDiscoveryMethod, TwitterDiscoveryConfidence, TwitterSourceType


# ── Source Schemas ─────────────────────────────────────────────────────

class TwitterSourceResponse(BaseModel):
    id: UUID
    source_id: str
    name: str
    query: str
    source_type: TwitterSourceType
    enabled: bool
    last_tweet_id: Optional[str] = None
    last_collected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Ranking Schemas ────────────────────────────────────────────────────

class TwitterDiscoveryRankingItem(BaseModel):
    """A single ranked token in a discovery window."""
    rank: int
    chain: str
    token_address: str
    symbol: str
    name: Optional[str] = None
    mention_count: int
    unique_user_count: int
    total_engagement: int
    authority_mentions: int
    total_score: float
    first_seen_in_window: datetime
    last_seen_in_window: datetime
    discovery_methods: list[TwitterDiscoveryMethod]
    source_names: list[str]
    dex_url: Optional[str] = None
    pair_address: Optional[str] = None

    model_config = {"from_attributes": True}


class TwitterDiscoveryRankingResponse(BaseModel):
    """Response for the discovery ranking endpoint."""
    window: str = "24h"
    window_start: datetime
    window_end: datetime
    total_tokens: int
    total_tweets: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    tokens: list[TwitterDiscoveryRankingItem]


class TwitterTokenMentionDetail(BaseModel):
    """Detailed view of a single token's Twitter discovery data."""
    chain: str
    token_address: str
    symbol: str
    name: Optional[str] = None
    pair_address: Optional[str] = None
    dex_url: Optional[str] = None
    first_discovered_at: datetime
    first_discovery_method: TwitterDiscoveryMethod
    total_mentions: int
    unique_users: int
    total_engagement: int
    authority_mentions: int
    total_score: float
    recent_mentions: list[dict] = []
    rankings: list[dict] = []

    model_config = {"from_attributes": True}


# ── Stats ──────────────────────────────────────────────────────────────

class TwitterStatsResponse(BaseModel):
    candidate_tokens: int
    total_mentions: int
    tweets_stored: int
    enabled_sources: int
    latest_mention_at: Optional[datetime] = None
    generated_at: datetime
