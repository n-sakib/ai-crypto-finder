"""
SQLAlchemy ORM models for Twitter Token Discovery.

Tables:
    - twitter_sources: Search queries / accounts to monitor
    - twitter_tweets: Minimal tweet metadata
    - twitter_candidate_tokens: Canonical tokens discovered from Twitter
    - twitter_token_mentions: Individual mention events
    - twitter_discovery_rankings: Aggregated rankings per time window
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Enum as SAEnum,
    ForeignKey, Text, Index, UniqueConstraint, Float,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


# ── Enums ──────────────────────────────────────────────────────────────

class TwitterDiscoveryMethod(str, enum.Enum):
    CASHTAG = "CASHTAG"
    CONTRACT_ADDRESS = "CONTRACT_ADDRESS"
    TOKEN_NAME = "TOKEN_NAME"


class TwitterDiscoveryConfidence(str, enum.Enum):
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TwitterSourceType(str, enum.Enum):
    CASHTAG_SEARCH = "cashtag_search"
    KEYWORD_SEARCH = "keyword_search"
    ADDRESS_SEARCH = "address_search"
    ACCOUNT_MONITOR = "account_monitor"


# ── Twitter Sources ────────────────────────────────────────────────────

class TwitterSource(Base):
    """A configured Twitter search query or account to monitor."""

    __tablename__ = "twitter_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    query = Column(String(512), nullable=False)  # Search query or account handle
    source_type = Column(SAEnum(TwitterSourceType), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    last_tweet_id = Column(String(64), nullable=True)
    last_collected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    tweets = relationship("TwitterTweet", back_populates="source")
    mentions = relationship("TwitterTokenMention", back_populates="source")

    __table_args__ = (
        Index("ix_twitter_sources_enabled", "enabled"),
    )


# ── Twitter Tweets ─────────────────────────────────────────────────────

class TwitterTweet(Base):
    """Minimal tweet metadata. No raw text stored by default."""

    __tablename__ = "twitter_tweets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("twitter_sources.id"), nullable=False, index=True)
    tweet_id = Column(String(64), nullable=False)
    tweet_timestamp = Column(DateTime(timezone=True), nullable=False)
    author_name = Column(String(128), nullable=False)
    text_hash = Column(String(128), nullable=False)
    tweet_text = Column(Text, nullable=True)
    retweet_count = Column(Integer, nullable=False, default=0)
    like_count = Column(Integer, nullable=False, default=0)
    reply_count = Column(Integer, nullable=False, default=0)
    tweet_url = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    source = relationship("TwitterSource", back_populates="tweets")
    mentions = relationship("TwitterTokenMention", back_populates="tweet")

    __table_args__ = (
        UniqueConstraint("source_id", "tweet_id", name="uq_twitter_tweet_source_tweetid"),
        Index("ix_twitter_tweets_text_hash", "text_hash"),
        Index("ix_twitter_tweets_timestamp", "tweet_timestamp"),
    )


# ── Twitter Candidate Tokens ───────────────────────────────────────────

class TwitterCandidateToken(Base):
    """Canonical token discovered from Twitter."""

    __tablename__ = "twitter_candidate_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(String(32), nullable=False, index=True)
    token_address = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    name = Column(String(256), nullable=True)
    first_discovered_at = Column(DateTime(timezone=True), nullable=False)
    first_discovered_source_id = Column(UUID(as_uuid=True), ForeignKey("twitter_sources.id"), nullable=True)
    first_discovery_method = Column(SAEnum(TwitterDiscoveryMethod), nullable=False)
    pair_address = Column(String(128), nullable=True)
    dex_url = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    mentions = relationship("TwitterTokenMention", back_populates="candidate_token")
    rankings = relationship("TwitterDiscoveryRanking", back_populates="candidate_token")

    __table_args__ = (
        UniqueConstraint("chain", "token_address", name="uq_twitter_candidate_token_chain_address"),
        Index("ix_twitter_candidate_tokens_chain", "chain"),
    )


# ── Twitter Token Mentions ─────────────────────────────────────────────

class TwitterTokenMention(Base):
    """A single mention of a token in a tweet."""

    __tablename__ = "twitter_token_mentions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_token_id = Column(UUID(as_uuid=True), ForeignKey("twitter_candidate_tokens.id"), nullable=False, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("twitter_sources.id"), nullable=False, index=True)
    tweet_id = Column(UUID(as_uuid=True), ForeignKey("twitter_tweets.id"), nullable=False, index=True)
    tweet_timestamp = Column(DateTime(timezone=True), nullable=False)
    author_name = Column(String(128), nullable=False)
    discovery_method = Column(SAEnum(TwitterDiscoveryMethod), nullable=False)
    confidence = Column(SAEnum(TwitterDiscoveryConfidence), nullable=False)
    is_reputable = Column(Boolean, default=False)
    engagement_score = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    candidate_token = relationship("TwitterCandidateToken", back_populates="mentions")
    source = relationship("TwitterSource", back_populates="mentions")
    tweet = relationship("TwitterTweet", back_populates="mentions")

    __table_args__ = (
        UniqueConstraint(
            "candidate_token_id", "tweet_id", "discovery_method",
            name="uq_twitter_mention_token_tweet_method",
        ),
        Index("ix_twitter_mentions_timestamp", "tweet_timestamp"),
        Index("ix_twitter_mentions_token_window", "candidate_token_id", "tweet_timestamp"),
    )


# ── Twitter Discovery Rankings ─────────────────────────────────────────

class TwitterDiscoveryRanking(Base):
    """Aggregated ranking of tokens for a specific time window."""

    __tablename__ = "twitter_discovery_rankings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_token_id = Column(UUID(as_uuid=True), ForeignKey("twitter_candidate_tokens.id"), nullable=False, index=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    mention_count = Column(Integer, nullable=False, default=0)
    unique_user_count = Column(Integer, nullable=False, default=0)
    total_engagement = Column(Integer, nullable=False, default=0)
    authority_mentions = Column(Integer, nullable=False, default=0)
    total_score = Column(Integer, nullable=False, default=0)
    rank = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    candidate_token = relationship("TwitterCandidateToken", back_populates="rankings")

    __table_args__ = (
        Index("ix_twitter_rankings_window", "window_start", "window_end"),
        Index("ix_twitter_rankings_token_window", "candidate_token_id", "window_start"),
    )
