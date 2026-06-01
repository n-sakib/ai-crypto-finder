"""
Pydantic schemas for Telegram Discovery API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.telegram_discovery.models import DiscoveryMethod, DiscoveryConfidence, SourceType


# ── Source Schemas ─────────────────────────────────────────────────────

class TelegramSourceResponse(BaseModel):
    id: UUID
    source_id: str
    name: str
    telegram_identifier: str
    source_type: SourceType
    enabled: bool
    last_message_id: Optional[int] = None
    last_collected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Extracted Token Reference (internal) ───────────────────────────────

class ExtractedTokenReference(BaseModel):
    """A token identifier extracted from a Telegram message."""
    discovery_method: DiscoveryMethod
    confidence: DiscoveryConfidence
    chain: Optional[str] = None
    token_address: Optional[str] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    pair_address: Optional[str] = None
    dex_url: Optional[str] = None
    raw_value: str  # The raw extracted string


# ── Ranking Schemas ────────────────────────────────────────────────────

class DiscoveryRankingItem(BaseModel):
    """A single ranked token in a discovery window."""
    rank: int
    chain: str
    token_address: str
    symbol: str
    name: Optional[str] = None
    mention_count: int
    unique_user_count: int
    group_count: int
    first_seen_in_window: datetime
    last_seen_in_window: datetime
    discovery_methods: list[DiscoveryMethod]
    source_names: list[str]
    dex_url: Optional[str] = None
    pair_address: Optional[str] = None

    model_config = {"from_attributes": True}


class DiscoveryRankingResponse(BaseModel):
    """Response for the discovery ranking endpoint."""
    window: str = "1h"
    window_start: datetime
    window_end: datetime
    total_tokens: int
    total_messages: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    tokens: list[DiscoveryRankingItem]


class TokenMentionDetail(BaseModel):
    """Detailed view of a single token's discovery data."""
    chain: str
    token_address: str
    symbol: str
    name: Optional[str] = None
    pair_address: Optional[str] = None
    dex_url: Optional[str] = None
    first_discovered_at: datetime
    first_discovery_method: DiscoveryMethod
    total_mentions: int
    unique_users: int
    group_count: int
    recent_mentions: list[dict] = []
    rankings: list[dict] = []

    model_config = {"from_attributes": True}


# ── Collection Result ──────────────────────────────────────────────────

class CollectionResult(BaseModel):
    """Result of a single collection run."""
    sources_scanned: int
    messages_processed: int
    messages_skipped_duplicate: int
    messages_skipped_no_tokens: int
    tokens_extracted: int
    tokens_resolved: int
    mentions_created: int
    errors: list[str] = []
    duration_seconds: float = 0.0


class RankingResult(BaseModel):
    """Result of a ranking run."""
    window: str
    window_start: datetime
    window_end: datetime
    total_candidates: int
    ranked: int
    filtered_out: int
    duration_seconds: float = 0.0
