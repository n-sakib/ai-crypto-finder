"""
Twitter Discovery Configuration — Default search queries and source management.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.twitter_discovery.models import TwitterSource, TwitterSourceType

logger = logging.getLogger(__name__)

# Default search queries for Twitter discovery
DEFAULT_TWITTER_SOURCES: list[dict] = [
    # Keyword searches
    {"source_id": "twitter_kw_new_launch", "name": "New Launch Crypto", "query": "new launch crypto", "source_type": TwitterSourceType.KEYWORD_SEARCH},
    {"source_id": "twitter_kw_fair_launch", "name": "Fair Launch", "query": "fair launch token", "source_type": TwitterSourceType.KEYWORD_SEARCH},
    {"source_id": "twitter_kw_ai_crypto", "name": "AI Agent Crypto", "query": "AI agent crypto token", "source_type": TwitterSourceType.KEYWORD_SEARCH},
    {"source_id": "twitter_kw_depin", "name": "DePIN", "query": "DePIN crypto", "source_type": TwitterSourceType.KEYWORD_SEARCH},
    {"source_id": "twitter_kw_memecoin", "name": "Memecoin", "query": "memecoin 100x", "source_type": TwitterSourceType.KEYWORD_SEARCH},

    # ── Alpha Accounts — monitored for early token mentions ──────────
    # Tier 1 — On-chain / wallet tracking
    {"source_id": "twitter_acct_theunipcs", "name": "@theunipcs", "query": "@theunipcs", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_lookonchain", "name": "@lookonchain", "query": "@lookonchain", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_onchainlens", "name": "@OnchainLens", "query": "@OnchainLens", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_ai9684xtpa", "name": "@ai_9684xtpa", "query": "@ai_9684xtpa", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_whale_alert", "name": "@Whale_Alert", "query": "@Whale_Alert", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_spotonchain", "name": "@spotonchain", "query": "@spotonchain", "source_type": TwitterSourceType.ACCOUNT_MONITOR},

    # Tier 2 — Early narrative & ecosystem
    {"source_id": "twitter_acct_0xdete", "name": "@0xDete", "query": "@0xDete", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_s4mmyeth", "name": "@s4mmyeth", "query": "@s4mmyeth", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_mandoct", "name": "@MandoCT", "query": "@MandoCT", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_zeneca", "name": "@Zeneca", "query": "@Zeneca", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_cryptohayes", "name": "@CryptoHayes", "query": "@CryptoHayes", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_pentosh1", "name": "@Pentosh1", "query": "@Pentosh1", "source_type": TwitterSourceType.ACCOUNT_MONITOR},

    # Tier 3 — Small-cap & research
    {"source_id": "twitter_acct_murocrypto", "name": "@MuroCrypto", "query": "@MuroCrypto", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_defiignas", "name": "@DefiIgnas", "query": "@DefiIgnas", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_route2fi", "name": "@route2fi", "query": "@route2fi", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_hsakatrades", "name": "@hsakaTrades", "query": "@hsakaTrades", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_pauly0x", "name": "@Pauly0x", "query": "@Pauly0x", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_ansem", "name": "@Ansem", "query": "@Ansem", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_wale", "name": "@Wale", "query": "@Wale", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_banditxbt", "name": "@BanditXBT", "query": "@BanditXBT", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    {"source_id": "twitter_acct_cryptokoryo", "name": "@CryptoKoryo", "query": "@CryptoKoryo", "source_type": TwitterSourceType.ACCOUNT_MONITOR},

    # Address searches
    {"source_id": "twitter_addr_0x", "name": "Contract Address 0x", "query": "contract address 0x", "source_type": TwitterSourceType.ADDRESS_SEARCH},
    {"source_id": "twitter_addr_ca", "name": "CA: 0x", "query": "ca: 0x token", "source_type": TwitterSourceType.ADDRESS_SEARCH},
]


async def seed_twitter_sources(session: AsyncSession) -> int:
    """Insert default Twitter sources if they don't exist. Returns count seeded."""
    count = 0
    for cfg in DEFAULT_TWITTER_SOURCES:
        existing = (await session.execute(
            select(TwitterSource).where(TwitterSource.source_id == cfg["source_id"])
        )).scalar_one_or_none()
        if not existing:
            src = TwitterSource(
                source_id=cfg["source_id"],
                name=cfg["name"],
                query=cfg["query"],
                source_type=cfg["source_type"],
                enabled=True,
            )
            session.add(src)
            count += 1
    if count:
        await session.commit()
        logger.info("Seeded %d Twitter discovery sources", count)
    return count
