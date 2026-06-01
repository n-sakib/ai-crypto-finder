"""
Pydantic schemas for Reddit Discovery API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.reddit_discovery.models import RedditDiscoveryMethod, RedditDiscoveryConfidence, RedditSourceType


# ── Source Schemas ─────────────────────────────────────────────────────

class RedditSourceResponse(BaseModel):
    id: UUID
    source_id: str
    name: str
    subreddit_name: str
    source_type: RedditSourceType
    enabled: bool
    last_post_id: Optional[str] = None
    last_collected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Ranking Schemas ────────────────────────────────────────────────────

class RedditDiscoveryRankingItem(BaseModel):
    """A single ranked token in a discovery window."""
    rank: int
    chain: str
    token_address: str
    symbol: str
    name: Optional[str] = None
    mention_count: int
    unique_user_count: int
    subreddit_count: int
    post_count: int = 0
    comment_count: int = 0
    upvotes: int = 0
    total_score: int
    first_seen_in_window: datetime
    last_seen_in_window: datetime
    discovery_methods: list[RedditDiscoveryMethod]
    source_names: list[str]
    dex_url: Optional[str] = None
    pair_address: Optional[str] = None

    model_config = {"from_attributes": True}


class RedditDiscoveryRankingResponse(BaseModel):
    """Response for the discovery ranking endpoint."""
    window: str = "24h"
    window_start: datetime
    window_end: datetime
    total_tokens: int
    total_posts: int = 0
    total_comments: int = 0
    total_upvotes: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    tokens: list[RedditDiscoveryRankingItem]


class RedditTokenMentionDetail(BaseModel):
    """Detailed view of a single token's Reddit discovery data."""
    chain: str
    token_address: str
    symbol: str
    name: Optional[str] = None
    pair_address: Optional[str] = None
    dex_url: Optional[str] = None
    first_discovered_at: datetime
    first_discovery_method: RedditDiscoveryMethod
    total_mentions: int
    unique_users: int
    subreddit_count: int
    post_count: int = 0
    comment_count: int = 0
    upvotes: int = 0
    total_score: int
    recent_mentions: list[dict] = []
    rankings: list[dict] = []

    model_config = {"from_attributes": True}


# ── Stats ──────────────────────────────────────────────────────────────

class RedditStatsResponse(BaseModel):
    candidate_tokens: int
    total_mentions: int
    posts_stored: int
    total_comments: int = 0
    total_upvotes: int = 0
    enabled_sources: int
    latest_mention_at: Optional[datetime] = None
    generated_at: datetime
