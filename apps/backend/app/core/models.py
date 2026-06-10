"""
Core SQLAlchemy ORM models for the entire pipeline.

Each layer in the pipeline has corresponding tables to track state,
scores, and metadata for every candidate token.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Enum,
    ForeignKey, Text, JSON, Index, UniqueConstraint, BigInteger,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


# ── Enums ──────────────────────────────────────────────────────────────

class AgeBucket(str, enum.Enum):
    NEW_LAUNCH = "new_launch"        # 0–24h
    YOUNG = "young"                   # 1–7 days
    GROWING = "growing"               # 7–30 days
    MATURE = "mature"                 # 30+ days


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RankingTier(str, enum.Enum):
    TIER_A = "tier_a"                # High momentum, low/medium risk
    TIER_B = "tier_b"                # Strong momentum, acceptable risk
    TIER_C = "tier_c"                # Early signs, needs confirmation
    EXCLUDED = "excluded"            # High momentum + critical risk


class NarrativeType(str, enum.Enum):
    AI = "ai"
    RWA = "rwa"
    DEPIN = "depin"
    GAMING = "gaming"
    PRIVACY = "privacy"
    MEMES = "memes"
    PREDICTION_MARKETS = "prediction_markets"
    L1_L2 = "l1_l2"


class NarrativeStrength(str, enum.Enum):
    COLD = "cold"        # 0% boost
    WARM = "warm"        # 10% boost
    HOT = "hot"          # 20% boost
    DOMINANT = "dominant"  # 30% boost


class DiscoverySource(str, enum.Enum):
    DEXSCREENER_VOLUME = "dexscreener_volume"
    DEXSCREENER_TRENDING = "dexscreener_trending"
    TWITTER = "twitter"
    TELEGRAM = "telegram"
    REDDIT = "reddit"
    SMART_WALLET = "smart_wallet"
    DORMANT_AWAKENING = "dormant_awakening"
    NARRATIVE = "narrative"


class PipelineStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    IDENTITY_RESOLVED = "identity_resolved"
    AGE_CLASSIFIED = "age_classified"
    SAFETY_PASSED = "safety_passed"
    MANIPULATION_CHECKED = "manipulation_checked"
    ATTENTION_SCORED = "attention_scored"
    MARKET_FLOW_SCORED = "market_flow_scored"
    ADOPTION_SCORED = "adoption_scored"
    LIQUIDITY_SCORED = "liquidity_scored"
    SMART_MONEY_SCORED = "smart_money_scored"
    NARRATIVE_SCORED = "narrative_scored"
    PRICE_COMPRESSION_SCORED = "price_compression_scored"
    RISK_SCORED = "risk_scored"
    MOMENTUM_SCORED = "momentum_scored"
    RANKED = "ranked"
    HUMAN_REVIEWED = "human_reviewed"
    VALIDATED = "validated"
    REJECTED = "rejected"


# ── Core Token Model ───────────────────────────────────────────────────

class Token(Base):
    __tablename__ = "tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(String(32), nullable=False, index=True)
    contract_address = Column(String(128), nullable=False, index=True)
    pair_address = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    name = Column(String(256))
    dex_id = Column(String(64))

    # Age classification
    age_bucket = Column(Enum(AgeBucket), nullable=True)
    launched_at = Column(DateTime(timezone=True), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Pipeline status
    pipeline_status = Column(Enum(PipelineStatus), default=PipelineStatus.DISCOVERED)
    status_changed_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Safety flags
    is_honeypot = Column(Boolean, default=False)
    has_mint_risk = Column(Boolean, default=False)
    has_sell_block = Column(Boolean, default=False)
    is_liquidity_locked = Column(Boolean, default=False)
    buy_tax_pct = Column(Float, default=0.0)
    sell_tax_pct = Column(Float, default=0.0)

    # Liquidity
    liquidity_usd = Column(Float, default=0.0)
    liquidity_trend = Column(String(16))  # stable, increasing, falling

    # Volume
    volume_24h = Column(Float, default=0.0)
    volume_1h = Column(Float, default=0.0)
    trade_count_24h = Column(Integer, default=0)
    unique_buyers_24h = Column(Integer, default=0)
    unique_sellers_24h = Column(Integer, default=0)

    # Holders
    holder_count = Column(Integer, default=0)
    meaningful_holders = Column(Integer, default=0)
    top_holder_pct = Column(Float, default=0.0)

    # Price
    price_usd = Column(Float, default=0.0)
    price_change_1h = Column(Float, default=0.0)
    price_change_6h = Column(Float, default=0.0)
    price_change_24h = Column(Float, default=0.0)
    price_change_7d = Column(Float, default=0.0)
    distance_from_24h_high = Column(Float, default=0.0)
    distance_from_7d_high = Column(Float, default=0.0)
    distance_from_30d_high = Column(Float, default=0.0)

    # Market cap
    market_cap = Column(Float, default=0.0)
    fully_diluted_valuation = Column(Float, default=0.0)

    # Scores (0-100)
    attention_score = Column(Float, default=0.0)
    market_flow_score = Column(Float, default=0.0)
    adoption_score = Column(Float, default=0.0)
    liquidity_quality_score = Column(Float, default=0.0)
    smart_money_score = Column(Float, default=0.0)
    narrative_score = Column(Float, default=0.0)
    price_compression_score = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)
    risk_level = Column(Enum(RiskLevel), nullable=True)
    early_momentum_score = Column(Float, default=0.0)

    # Ranking
    tier = Column(Enum(RankingTier), nullable=True)
    rank_position = Column(Integer, nullable=True)

    # Human review
    website = Column(String(512))
    docs_url = Column(String(512))
    team_info = Column(JSON, default=dict)
    roadmap_summary = Column(Text)
    tokenomics_summary = Column(Text)
    human_review_notes = Column(Text)
    is_approved = Column(Boolean, default=False)

    # Validation
    coingecko_trending = Column(Boolean, default=False)
    cmc_trending = Column(Boolean, default=False)
    news_mentions = Column(Integer, default=0)
    exchange_listings = Column(JSON, default=list)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    baselines = relationship("TokenBaseline", back_populates="token", uselist=False)
    social_mentions = relationship("SocialMention", back_populates="token")
    smart_wallet_trades = relationship("SmartWalletTrade", back_populates="token")
    narratives = relationship("TokenNarrative", back_populates="token")
    holder_snapshots = relationship("HolderSnapshot", back_populates="token")
    discovery_events = relationship("DiscoveryEvent", back_populates="token")

    __table_args__ = (
        UniqueConstraint("chain", "contract_address", name="uq_token_chain_contract"),
        Index("ix_token_pair", "chain", "pair_address"),
        Index("ix_token_tier", "tier"),
        Index("ix_token_momentum", "early_momentum_score"),
    )


# ── Baselines (per-token, age-adjusted) ────────────────────────────────

class TokenBaseline(Base):
    __tablename__ = "token_baselines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id = Column(UUID(as_uuid=True), ForeignKey("tokens.id"), unique=True, nullable=False)

    # Volume baselines
    avg_volume_15m = Column(Float, default=0.0)
    avg_volume_1h = Column(Float, default=0.0)
    avg_volume_6h = Column(Float, default=0.0)
    avg_volume_24h = Column(Float, default=0.0)
    avg_volume_7d = Column(Float, default=0.0)
    avg_volume_30d = Column(Float, default=0.0)
    avg_volume_90d = Column(Float, default=0.0)

    # Trade count baselines
    avg_trades_1h = Column(Float, default=0.0)
    avg_trades_6h = Column(Float, default=0.0)
    avg_trades_24h = Column(Float, default=0.0)

    # Social baselines
    avg_twitter_mentions = Column(Float, default=0.0)
    avg_telegram_messages = Column(Float, default=0.0)
    avg_reddit_mentions = Column(Float, default=0.0)

    # Holder baselines
    avg_new_holders_6h = Column(Float, default=0.0)
    avg_new_holders_24h = Column(Float, default=0.0)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    token = relationship("Token", back_populates="baselines")


# ── Social Mentions ───────────────────────────────────────────────────

class SocialMention(Base):
    __tablename__ = "social_mentions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id = Column(UUID(as_uuid=True), ForeignKey("tokens.id"), nullable=False, index=True)

    source = Column(String(32), nullable=False)   # twitter, telegram, reddit
    mention_count = Column(Integer, default=0)
    unique_accounts = Column(Integer, default=0)
    engagement = Column(Integer, default=0)         # likes, retweets, upvotes
    new_members = Column(Integer, default=0)        # telegram specific
    is_spam_flagged = Column(Boolean, default=False)
    spam_reason = Column(String(256))
    snapshot_at = Column(DateTime(timezone=True), nullable=False)

    token = relationship("Token", back_populates="social_mentions")

    __table_args__ = (
        Index("ix_social_source_time", "token_id", "source", "snapshot_at"),
    )


# ── Smart Wallet Trades ───────────────────────────────────────────────

class SmartWalletTrade(Base):
    __tablename__ = "smart_wallet_trades"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id = Column(UUID(as_uuid=True), ForeignKey("tokens.id"), nullable=False, index=True)

    wallet_address = Column(String(128), nullable=False, index=True)
    buy_amount_usd = Column(Float, default=0.0)
    wallet_avg_buy_size = Column(Float, default=0.0)
    normalized_buy_size = Column(Float, default=0.0)  # buy_amount / avg_buy_size
    wallet_win_rate = Column(Float, default=0.0)
    wallet_avg_roi = Column(Float, default=0.0)
    wallet_completed_trades = Column(Integer, default=0)

    traded_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    token = relationship("Token", back_populates="smart_wallet_trades")


# ── Narratives ───────────────────────────────────────────────────────

class TokenNarrative(Base):
    __tablename__ = "token_narratives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id = Column(UUID(as_uuid=True), ForeignKey("tokens.id"), nullable=False, index=True)

    narrative = Column(Enum(NarrativeType), nullable=False)
    strength = Column(Enum(NarrativeStrength), default=NarrativeStrength.COLD)

    token = relationship("Token", back_populates="narratives")

    __table_args__ = (
        UniqueConstraint("token_id", "narrative", name="uq_token_narrative"),
    )


# ── Holder Snapshots ──────────────────────────────────────────────────

class HolderSnapshot(Base):
    __tablename__ = "holder_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id = Column(UUID(as_uuid=True), ForeignKey("tokens.id"), nullable=False, index=True)

    total_holders = Column(Integer, default=0)
    meaningful_holders = Column(Integer, default=0)  # non-dust, non-bot
    active_wallets = Column(Integer, default=0)
    new_wallets_6h = Column(Integer, default=0)
    suspected_bot_wallets = Column(Integer, default=0)
    top_10_share_pct = Column(Float, default=0.0)

    snapshot_at = Column(DateTime(timezone=True), nullable=False)

    token = relationship("Token", back_populates="holder_snapshots")


# ── Discovery Events ──────────────────────────────────────────────────

class DiscoveryEvent(Base):
    __tablename__ = "discovery_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id = Column(UUID(as_uuid=True), ForeignKey("tokens.id"), nullable=False, index=True)

    source = Column(Enum(DiscoverySource), nullable=False)
    signal_strength = Column(Float, default=0.0)  # 0-1 normalized
    raw_data = Column(JSON, default=dict)
    discovered_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    token = relationship("Token", back_populates="discovery_events")


# ── Pipeline Run Log ──────────────────────────────────────────────────

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    layer_name = Column(String(64), nullable=False)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    tokens_processed = Column(Integer, default=0)
    tokens_passed = Column(Integer, default=0)
    tokens_rejected = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(BigInteger, nullable=True)


# ── Manipulation Flags ────────────────────────────────────────────────

class ManipulationFlag(Base):
    __tablename__ = "manipulation_flags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id = Column(UUID(as_uuid=True), ForeignKey("tokens.id"), nullable=False, index=True)

    flag_type = Column(String(64), nullable=False)  # wash_trading, holder_farming, twitter_spam, etc.
    severity = Column(Float, default=0.5)  # 0–1
    evidence = Column(JSON, default=dict)
    detected_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ── Unified Pipeline Token ─────────────────────────────────────────────

class UnifiedToken(Base):
    """Token enriched through the unified pipeline (Telegram → DexScreener → GMGN → Dedup)."""

    __tablename__ = "unified_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(String(32), nullable=False, index=True)
    token_address = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=True)
    name = Column(String(128), nullable=True)
    logo_url = Column(String(512), nullable=True)

    # DexScreener enrichment
    dex_url = Column(String(512), nullable=True)
    pair_address = Column(String(128), nullable=True)
    dex_id = Column(String(32), nullable=True)

    # GMGN enrichment
    gmgn_url = Column(String(512), nullable=True)
    gmgn_score = Column(Float, nullable=True)
    gmgn_hot_level = Column(Integer, nullable=True)
    gmgn_kol_count = Column(Integer, default=0)
    gmgn_kol_buy_count = Column(Integer, default=0)
    gmgn_kol_total_amount_usd = Column(Float, default=0.0)
    gmgn_kol_last_buy_at = Column(DateTime(timezone=True), nullable=True)
    gmgn_kol_wallets = Column(JSON, default=list)

    # ── 5-minute window ──
    price_5m = Column(Float, nullable=True)
    price_change_5m = Column(Float, nullable=True)
    volume_5m = Column(Float, nullable=True)
    buys_5m = Column(Integer, nullable=True)
    sells_5m = Column(Integer, nullable=True)
    trades_5m = Column(Integer, nullable=True)
    liquidity_5m = Column(Float, nullable=True)
    market_cap_5m = Column(Float, nullable=True)
    tg_mentions_5m = Column(Integer, default=0)
    tg_users_5m = Column(Integer, default=0)
    tg_groups_5m = Column(Integer, default=0)
    tg_reactions_5m = Column(Integer, default=0)
    tg_replies_5m = Column(Integer, default=0)

    # ── 1-hour window ──
    price_1h = Column(Float, nullable=True)
    price_change_1h = Column(Float, nullable=True)
    volume_1h = Column(Float, nullable=True)
    buys_1h = Column(Integer, nullable=True)
    sells_1h = Column(Integer, nullable=True)
    trades_1h = Column(Integer, nullable=True)
    liquidity_1h = Column(Float, nullable=True)
    market_cap_1h = Column(Float, nullable=True)
    tg_mentions_1h = Column(Integer, default=0)
    tg_users_1h = Column(Integer, default=0)
    tg_groups_1h = Column(Integer, default=0)
    tg_reactions_1h = Column(Integer, default=0)
    tg_replies_1h = Column(Integer, default=0)

    # ── 6-hour window ──
    price_6h = Column(Float, nullable=True)
    price_change_6h = Column(Float, nullable=True)
    volume_6h = Column(Float, nullable=True)
    buys_6h = Column(Integer, nullable=True)
    sells_6h = Column(Integer, nullable=True)
    trades_6h = Column(Integer, nullable=True)
    liquidity_6h = Column(Float, nullable=True)
    market_cap_6h = Column(Float, nullable=True)
    tg_mentions_6h = Column(Integer, default=0)
    tg_users_6h = Column(Integer, default=0)
    tg_groups_6h = Column(Integer, default=0)
    tg_reactions_6h = Column(Integer, default=0)
    tg_replies_6h = Column(Integer, default=0)

    # ── 24-hour window ──
    price_24h = Column(Float, nullable=True)
    price_change_24h = Column(Float, nullable=True)
    volume_24h = Column(Float, nullable=True)
    buys_24h = Column(Integer, nullable=True)
    sells_24h = Column(Integer, nullable=True)
    trades_24h = Column(Integer, nullable=True)
    liquidity_24h = Column(Float, nullable=True)
    market_cap_24h = Column(Float, nullable=True)
    tg_mentions_24h = Column(Integer, default=0)
    tg_users_24h = Column(Integer, default=0)
    tg_groups_24h = Column(Integer, default=0)
    tg_reactions_24h = Column(Integer, default=0)
    tg_replies_24h = Column(Integer, default=0)

    # Discovery source flags
    is_dexscreener_trending = Column(Boolean, default=False)
    is_gmgn_trending = Column(Boolean, default=False)
    is_dexscreener_boosted = Column(Boolean, default=False)
    dexscreener_trending_rank = Column(Integer, nullable=True)
    dexscreener_boost_amount = Column(Float, nullable=True)
    dexscreener_boost_total = Column(Float, nullable=True)
    gmgn_trending_rank = Column(Integer, nullable=True)

    # Ranking
    composite_score = Column(Float, nullable=True)
    rank = Column(Integer, nullable=True)

    # Metadata
    group_count = Column(Integer, default=0)
    source_groups = Column(JSON, default=list)
    discovery_methods = Column(JSON, default=list)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    pipeline_run_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("chain", "token_address", name="uq_unified_token_chain_addr"),
        Index("ix_unified_tokens_rank", "composite_score"),
        Index("ix_unified_tokens_first_seen", "first_seen_at"),
    )
