"""
Discovery Layer — Finds candidate tokens from multiple sources.

Sources:
1. DEXScreener Volume Growth
2. DEXScreener Trending / Hot Pairs
3. Twitter/X Discovery
4. Telegram Discovery
5. Reddit Discovery
6. Smart Wallet Discovery
7. Dormant Awakening Discovery
8. Narrative Discovery
"""

import asyncio
from typing import AsyncIterator

from app.core.models import DiscoverySource
from app.layers.discovery.dexscreener import DexScreenerDiscovery
from app.layers.discovery.twitter_discovery import TwitterDiscovery
from app.layers.discovery.telegram_discovery import TelegramDiscovery
from app.layers.discovery.reddit_discovery import RedditDiscovery
from app.layers.discovery.smart_wallet import SmartWalletDiscovery
from app.layers.discovery.dormant_awakening import DormantAwakeningDiscovery
from app.layers.discovery.narrative_discovery import NarrativeDiscovery


class DiscoveryPipeline:
    """Orchestrates all discovery sources and produces raw candidates."""

    def __init__(self) -> None:
        self.sources = {
            DiscoverySource.DEXSCREENER_VOLUME: DexScreenerDiscovery(),
            DiscoverySource.DEXSCREENER_TRENDING: DexScreenerDiscovery(trending_mode=True),
            DiscoverySource.TWITTER: TwitterDiscovery(),
            DiscoverySource.TELEGRAM: TelegramDiscovery(),
            DiscoverySource.REDDIT: RedditDiscovery(),
            DiscoverySource.SMART_WALLET: SmartWalletDiscovery(),
            DiscoverySource.DORMANT_AWAKENING: DormantAwakeningDiscovery(),
            DiscoverySource.NARRATIVE: NarrativeDiscovery(),
        }

    async def run_all(self) -> list[dict]:
        """Run all discovery sources concurrently and return deduplicated candidates."""
        tasks = [
            self._run_source(source, instance)
            for source, instance in self.sources.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: list[dict] = []
        for result in results:
            if isinstance(result, list):
                candidates.extend(result)
            elif isinstance(result, Exception):
                # Log error but don't block other sources
                continue

        return self._deduplicate(candidates)

    async def run_source(self, source: DiscoverySource) -> list[dict]:
        """Run a single discovery source."""
        instance = self.sources.get(source)
        if not instance:
            return []
        return await self._run_source(source, instance)

    async def _run_source(self, source: DiscoverySource, instance) -> list[dict]:
        try:
            candidates = await instance.discover()
            for c in candidates:
                c["discovery_source"] = source.value
            return candidates
        except Exception:
            # Source fails independently — don't block the pipeline
            return []

    def _deduplicate(self, candidates: list[dict]) -> list[dict]:
        """Merge candidates by (chain, contract_address), keeping the earliest discovery source."""
        seen: dict[tuple[str, str], dict] = {}
        for c in candidates:
            key = (c.get("chain", "").lower(), c.get("contract_address", "").lower())
            if not key[0] or not key[1]:
                continue
            if key not in seen:
                seen[key] = c
            else:
                # Merge sources
                existing_sources = seen[key].get("all_sources", [seen[key]["discovery_source"]])
                existing_sources.append(c["discovery_source"])
                seen[key]["all_sources"] = existing_sources
        return list(seen.values())
