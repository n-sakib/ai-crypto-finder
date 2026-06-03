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
    # Account monitors — fetch tweets from reputable crypto voices (disabled by default)
    # {"source_id": "twitter_acct_aeyakovenko", "name": "@aeyakovenko", "query": "@aeyakovenko", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
    # {"source_id": "twitter_acct_cz_binance", "name": "@cz_binance", "query": "@cz_binance", "source_type": TwitterSourceType.ACCOUNT_MONITOR},
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
