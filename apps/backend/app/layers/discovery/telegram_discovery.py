"""
Telegram Discovery — Finds tokens from Telegram channels and groups.

Delegates to the Telegram Discovery Service (app.telegram_discovery).
This file is the pipeline integration layer; the core discovery logic
lives in the telegram_discovery package.

Source: 1.4 Telegram Discovery
Update: hourly
Criteria: token mentions from configured Telegram groups/channels
Finds: contract address mentions, DEX links, cashtags
"""

import logging
from typing import Optional

from app.config import settings
from app.layers.discovery.base import BaseDiscoverySource

logger = logging.getLogger(__name__)


class TelegramDiscovery(BaseDiscoverySource):
    """
    Discovers tokens from Telegram groups and channels.

    Integrates with the Telegram Discovery Service to:
    - Read messages from configured Telegram sources
    - Extract token identifiers (contract addresses, DEX links, cashtags)
    - Resolve identifiers to canonical tokens
    - Aggregate mentions into ranked discoveries

    This is the pipeline layer. For core logic see:
        app.telegram_discovery.client.TelegramClientService
        app.telegram_discovery.extractor.TokenExtractor
        app.telegram_discovery.resolver.TokenResolver
        app.telegram_discovery.aggregator.TelegramDiscoveryAggregator
    """

    def __init__(self):
        pass

    def source_name(self) -> str:
        return "Telegram"

    async def discover(self) -> list[dict]:
        """
        Discover tokens from Telegram.

        Runs the collection + ranking pipeline and returns discovered tokens
        as dicts compatible with the pipeline's expected format.

        Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in settings.
        """
        if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
            logger.debug("Telegram API credentials not configured — skipping")
            return []

        # Delegate to the Telegram discovery pipeline
        try:
            from app.core.database import async_session_factory
            from app.telegram_discovery.client import TelegramClientService
            from app.telegram_discovery.config import load_telegram_sources_async
            from app.telegram_discovery.extractor import TokenExtractor
            from app.telegram_discovery.resolver import TokenResolver
            from app.telegram_discovery.aggregator import TelegramDiscoveryAggregator
            from app.telegram_discovery.models import TelegramMessage, TelegramSource
            from sqlalchemy import select

            configs = await load_telegram_sources_async()
            enabled_configs = [c for c in configs if c.enabled]
            if not enabled_configs:
                logger.debug("No enabled Telegram sources configured")
                return []

            client_service = TelegramClientService(store_raw_text=False)
            extractor = TokenExtractor()
            resolver = TokenResolver()

            candidates: list[dict] = []

            try:
                async with async_session_factory() as session:
                    # Sync and collect
                    enabled_sources = await client_service.sync_sources(session, enabled_configs)
                    if not enabled_sources:
                        return []

                    await client_service.collect_messages(session, enabled_sources)

                    # Extract and resolve from collected messages
                    # (client now returns (msg, source, text) tuples for inline processing)
                    # Re-fetch recent messages with raw_text (if stored)
                    from sqlalchemy import select as sa_select
                    result = await session.execute(
                        sa_select(TelegramMessage)
                        .where(TelegramMessage.raw_text.isnot(None))
                        .order_by(TelegramMessage.message_timestamp.desc())
                        .limit(500)
                    )
                    messages = result.scalars().all()

                    for msg in messages:
                        if not msg.raw_text:
                            continue

                        src_result = await session.execute(
                            select(TelegramSource).where(TelegramSource.id == msg.source_id)
                        )
                        src = src_result.scalar_one_or_none()
                        if not src:
                            continue

                        refs = extractor.extract(msg.raw_text)
                        if not refs:
                            continue

                        await resolver.resolve_and_store_mentions(
                            session, src, msg, refs,
                        )

                    await session.commit()

                    # Get ranked tokens and convert to pipeline format
                    aggregator = TelegramDiscoveryAggregator(
                        min_mention_count=2,  # Lower threshold for pipeline integration
                        min_unique_users=1,
                    )
                    ranking_result = await aggregator.rank(session, window="6h", limit=50)

                    for item in ranking_result.tokens:
                        candidates.append({
                            "chain": item.chain,
                            "contract_address": item.token_address,
                            "pair_address": item.pair_address or item.token_address,
                            "symbol": item.symbol,
                            "name": item.name,
                            "dex_url": item.dex_url,
                            "extra": {
                                "mention_count": item.mention_count,
                                "unique_user_count": item.unique_user_count,
                                "group_count": item.group_count,
                                "discovery_methods": [m.value for m in item.discovery_methods],
                                "source_names": item.source_names,
                            },
                        })

            finally:
                await client_service.disconnect()
                await resolver.close()

            logger.info("Telegram discovery found %d candidates", len(candidates))
            return candidates

        except Exception as e:
            logger.error("Telegram discovery failed: %s", e, exc_info=True)
            return []
        filtered: list[dict] = []
        for c in candidates:
            unique_users = c.get("unique_users", 0)
            new_members = c.get("new_members", 0)
            if unique_users > 0 and new_members > 0:
                filtered.append(c)
        return filtered

    def update_baselines(self, group_metrics: dict[str, dict]):
        """Update per-group baselines."""
        self._baselines.update(group_metrics)
