"""
SQLAlchemy ORM models for Reddit Token Discovery.

Tables:
    - reddit_sources: Configured subreddits to monitor
    - reddit_posts: Minimal post metadata (no raw text by default)
    - reddit_candidate_tokens: Canonical tokens discovered from Reddit
    - reddit_token_mentions: Individual mention events
    - reddit_discovery_rankings: Aggregated rankings per time window
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Enum as SAEnum,
    ForeignKey, Text, Index, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


# ── Enums ──────────────────────────────────────────────────────────────

class RedditDiscoveryMethod(str, enum.Enum):
    CONTRACT_ADDRESS = "CONTRACT_ADDRESS"
    DEX_LINK = "DEX_LINK"
    CASHTAG = "CASHTAG"
    TOKEN_NAME = "TOKEN_NAME"


class RedditDiscoveryConfidence(str, enum.Enum):
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RedditSourceType(str, enum.Enum):
    GENERAL_CRYPTO = "general_crypto"
    MEME_COINS = "meme_coins"
    TRADING = "trading"
    DEFI = "defi"
    CHAIN_SPECIFIC = "chain_specific"


# ── Reddit Sources ─────────────────────────────────────────────────────

class RedditSource(Base):
    """A configured subreddit to monitor for token mentions."""

    __tablename__ = "reddit_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    subreddit_name = Column(String(256), nullable=False)  # e.g., "CryptoCurrency"
    source_type = Column(SAEnum(RedditSourceType), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    last_post_id = Column(String(64), nullable=True)  # Reddit post fullname (t3_xxx)
    last_collected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    posts = relationship("RedditPost", back_populates="source")
    mentions = relationship("RedditTokenMention", back_populates="source")

    __table_args__ = (
        Index("ix_reddit_sources_enabled", "enabled"),
    )


# ── Reddit Posts ────────────────────────────────────────────────────────

class RedditPost(Base):
    """
    Minimal Reddit post metadata.

    selftext is nullable and configurable — off by default for privacy.
    """

    __tablename__ = "reddit_posts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("reddit_sources.id"), nullable=False, index=True)
    reddit_post_id = Column(String(64), nullable=False)  # Reddit fullname (t3_xxx)
    post_timestamp = Column(DateTime(timezone=True), nullable=False)
    author = Column(String(128), nullable=False)
    title = Column(Text, nullable=False)
    text_hash = Column(String(128), nullable=False)
    selftext = Column(Text, nullable=True)
    post_url = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    source = relationship("RedditSource", back_populates="posts")
    mentions = relationship("RedditTokenMention", back_populates="post")

    __table_args__ = (
        UniqueConstraint("source_id", "reddit_post_id", name="uq_reddit_post_source_postid"),
        Index("ix_reddit_posts_text_hash", "text_hash"),
        Index("ix_reddit_posts_timestamp", "post_timestamp"),
    )


# ── Reddit Candidate Tokens ─────────────────────────────────────────────

class RedditCandidateToken(Base):
    """
    Canonical token discovered from Reddit.

    One row per unique chain + token_address.
    """

    __tablename__ = "reddit_candidate_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(String(32), nullable=False, index=True)
    token_address = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    name = Column(String(256), nullable=True)
    first_discovered_at = Column(DateTime(timezone=True), nullable=False)
    first_discovered_source_id = Column(UUID(as_uuid=True), ForeignKey("reddit_sources.id"), nullable=True)
    first_discovery_method = Column(SAEnum(RedditDiscoveryMethod), nullable=False)
    pair_address = Column(String(128), nullable=True)
    dex_url = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    mentions = relationship("RedditTokenMention", back_populates="candidate_token")
    rankings = relationship("RedditDiscoveryRanking", back_populates="candidate_token")

    __table_args__ = (
        UniqueConstraint("chain", "token_address", name="uq_reddit_candidate_token_chain_address"),
        Index("ix_reddit_candidate_tokens_chain", "chain"),
    )


# ── Reddit Token Mentions ──────────────────────────────────────────────

class RedditTokenMention(Base):
    """
    A single mention of a token in a Reddit post.

    Idempotent: same post processed twice will not create duplicate mentions.
    """

    __tablename__ = "reddit_token_mentions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_token_id = Column(UUID(as_uuid=True), ForeignKey("reddit_candidate_tokens.id"), nullable=False, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("reddit_sources.id"), nullable=False, index=True)
    reddit_post_id = Column(UUID(as_uuid=True), ForeignKey("reddit_posts.id"), nullable=False, index=True)
    post_timestamp = Column(DateTime(timezone=True), nullable=False)
    author = Column(String(128), nullable=False)
    discovery_method = Column(SAEnum(RedditDiscoveryMethod), nullable=False)
    confidence = Column(SAEnum(RedditDiscoveryConfidence), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    candidate_token = relationship("RedditCandidateToken", back_populates="mentions")
    source = relationship("RedditSource", back_populates="mentions")
    post = relationship("RedditPost", back_populates="mentions")

    __table_args__ = (
        UniqueConstraint(
            "candidate_token_id", "reddit_post_id", "discovery_method",
            name="uq_reddit_mention_token_post_method",
        ),
        Index("ix_reddit_mentions_timestamp", "post_timestamp"),
        Index("ix_reddit_mentions_token_window", "candidate_token_id", "post_timestamp"),
    )


# ── Reddit Discovery Rankings ──────────────────────────────────────────

class RedditDiscoveryRanking(Base):
    """
    Aggregated ranking of tokens for a specific time window.

    Ranked by: mention_count DESC, unique_user_count DESC, subreddit_count DESC,
    total_score DESC, most recent mention DESC.
    """

    __tablename__ = "reddit_discovery_rankings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_token_id = Column(UUID(as_uuid=True), ForeignKey("reddit_candidate_tokens.id"), nullable=False, index=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    mention_count = Column(Integer, nullable=False, default=0)
    unique_user_count = Column(Integer, nullable=False, default=0)
    subreddit_count = Column(Integer, nullable=False, default=0)
    post_count = Column(Integer, nullable=False, default=0)
    total_score = Column(Integer, nullable=False, default=0)
    rank = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    candidate_token = relationship("RedditCandidateToken", back_populates="rankings")

    __table_args__ = (
        Index("ix_reddit_rankings_window", "window_start", "window_end"),
        Index("ix_reddit_rankings_token_window", "candidate_token_id", "window_start"),
    )
