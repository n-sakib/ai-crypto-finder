"""
SQLAlchemy ORM models for Telegram Token Discovery.

Tables:
    - telegram_sources: Configured Telegram groups/channels to monitor
    - telegram_messages: Minimal message metadata (no raw text by default)
    - candidate_tokens: Canonical tokens discovered from Telegram
    - telegram_token_mentions: Individual mention events
    - telegram_discovery_rankings: Aggregated rankings per time window
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Enum as SAEnum,
    ForeignKey, Text, Index, UniqueConstraint, BigInteger,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


# ── Enums ──────────────────────────────────────────────────────────────

class DiscoveryMethod(str, enum.Enum):
    CONTRACT_ADDRESS = "CONTRACT_ADDRESS"
    DEX_LINK = "DEX_LINK"
    CASHTAG = "CASHTAG"
    TOKEN_NAME = "TOKEN_NAME"


class DiscoveryConfidence(str, enum.Enum):
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceType(str, enum.Enum):
    ALPHA_GROUP = "alpha_group"
    TREND_GROUP = "trend_group"
    MEME_GROUP = "meme_group"
    TRADING_GROUP = "trading_group"
    CHAIN_GROUP = "chain_group"


# ── Telegram Sources ───────────────────────────────────────────────────

class TelegramSource(Base):
    """A configured Telegram group/channel to monitor for token mentions."""

    __tablename__ = "telegram_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    telegram_identifier = Column(String(256), nullable=False)
    source_type = Column(SAEnum(SourceType), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    last_message_id = Column(BigInteger, nullable=True)  # checkpoint
    last_collected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    messages = relationship("TelegramMessage", back_populates="source")
    mentions = relationship("TelegramTokenMention", back_populates="source")

    __table_args__ = (
        Index("ix_telegram_sources_enabled", "enabled"),
    )


# ── Telegram Messages ──────────────────────────────────────────────────

class TelegramMessage(Base):
    """
    Minimal message metadata.

    raw_text is nullable and configurable — off by default for privacy.
    Prefer storing hashes over raw text.
    """

    __tablename__ = "telegram_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("telegram_sources.id"), nullable=False, index=True)
    telegram_message_id = Column(BigInteger, nullable=False)
    message_timestamp = Column(DateTime(timezone=True), nullable=False)
    sender_id_hash = Column(String(128), nullable=False)
    text_hash = Column(String(128), nullable=False)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    source = relationship("TelegramSource", back_populates="messages")
    mentions = relationship("TelegramTokenMention", back_populates="message")

    __table_args__ = (
        UniqueConstraint("source_id", "telegram_message_id", name="uq_telegram_msg_source_msgid"),
        Index("ix_telegram_messages_text_hash", "text_hash"),
        Index("ix_telegram_messages_timestamp", "message_timestamp"),
    )


# ── Candidate Tokens ───────────────────────────────────────────────────

class CandidateToken(Base):
    """
    Canonical token discovered from Telegram.

    One row per unique chain + token_address.
    Multiple mentions of the same token are tracked in telegram_token_mentions.
    """

    __tablename__ = "candidate_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(String(32), nullable=False, index=True)
    token_address = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    name = Column(String(256), nullable=True)
    first_discovered_at = Column(DateTime(timezone=True), nullable=False)
    first_discovered_source_id = Column(UUID(as_uuid=True), ForeignKey("telegram_sources.id"), nullable=True)
    first_discovery_method = Column(SAEnum(DiscoveryMethod), nullable=False)
    pair_address = Column(String(128), nullable=True)
    dex_url = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    mentions = relationship("TelegramTokenMention", back_populates="candidate_token")
    rankings = relationship("TelegramDiscoveryRanking", back_populates="candidate_token")

    __table_args__ = (
        UniqueConstraint("chain", "token_address", name="uq_candidate_token_chain_address"),
        Index("ix_candidate_tokens_chain", "chain"),
    )


# ── Telegram Token Mentions ────────────────────────────────────────────

class TelegramTokenMention(Base):
    """
    A single mention of a token in a Telegram message.

    Idempotent: same message processed twice will not create duplicate mentions
    (guarded by unique constraint on candidate_token_id + telegram_message_id + discovery_method).
    """

    __tablename__ = "telegram_token_mentions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_token_id = Column(UUID(as_uuid=True), ForeignKey("candidate_tokens.id"), nullable=False, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("telegram_sources.id"), nullable=False, index=True)
    telegram_message_id = Column(UUID(as_uuid=True), ForeignKey("telegram_messages.id"), nullable=False, index=True)
    message_timestamp = Column(DateTime(timezone=True), nullable=False)
    sender_id_hash = Column(String(128), nullable=False)
    discovery_method = Column(SAEnum(DiscoveryMethod), nullable=False)
    confidence = Column(SAEnum(DiscoveryConfidence), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    candidate_token = relationship("CandidateToken", back_populates="mentions")
    source = relationship("TelegramSource", back_populates="mentions")
    message = relationship("TelegramMessage", back_populates="mentions")

    __table_args__ = (
        UniqueConstraint(
            "candidate_token_id", "telegram_message_id", "discovery_method",
            name="uq_mention_token_msg_method",
        ),
        Index("ix_mentions_timestamp", "message_timestamp"),
        Index("ix_mentions_token_window", "candidate_token_id", "message_timestamp"),
    )


# ── Telegram Discovery Rankings ────────────────────────────────────────

class TelegramDiscoveryRanking(Base):
    """
    Aggregated ranking of tokens for a specific time window.

    Ranked by: mention_count DESC, unique_user_count DESC, group_count DESC,
    most recent mention DESC.
    """

    __tablename__ = "telegram_discovery_rankings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_token_id = Column(UUID(as_uuid=True), ForeignKey("candidate_tokens.id"), nullable=False, index=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    mention_count = Column(Integer, nullable=False, default=0)
    unique_user_count = Column(Integer, nullable=False, default=0)
    group_count = Column(Integer, nullable=False, default=0)
    first_seen_in_window = Column(DateTime(timezone=True), nullable=False)
    last_seen_in_window = Column(DateTime(timezone=True), nullable=False)
    rank = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    candidate_token = relationship("CandidateToken", back_populates="rankings")

    __table_args__ = (
        UniqueConstraint(
            "candidate_token_id", "window_start", "window_end",
            name="uq_ranking_token_window",
        ),
        Index("ix_rankings_window", "window_start", "window_end"),
        Index("ix_rankings_rank", "rank"),
    )
