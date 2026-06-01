"""
Reddit Token Resolver — Resolves extracted token references to canonical tokens.

Resolves symbols to contract addresses via DexScreener API.
Enriches with DexScreener metadata (name, pair_address, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select as sa_select, and_

from app.config import settings
from app.reddit_discovery.models import (
    RedditCandidateToken, RedditTokenMention, RedditPost,
    RedditDiscoveryMethod, RedditDiscoveryConfidence,
)

logger = logging.getLogger(__name__)

DEXSCREENER_SEARCH_URL = f"{settings.DEXSCREENER_API_URL}/latest/dex/search"


class RedditTokenResolver:
    """Resolves extracted token references to canonical on-chain tokens."""

    def __init__(self):
        self._dex_cache: dict[str, dict] = {}

    async def resolve(
        self,
        session: AsyncSession,
        extractions: list[dict],
        reddit_post: RedditPost,
    ) -> int:
        """
        Resolve extracted references and create mentions.

        Returns number of mentions created.
        """
        mentions_created = 0

        for ext in extractions:
            # Skip if we already have a complete reference
            if ext.get("chain") and ext.get("token_address"):
                token = await self._get_or_create_token(session, ext)
                if token:
                    await self._create_mention(session, token, reddit_post, ext)
                    mentions_created += 1
                continue

            # Try to resolve symbol to address via DexScreener
            if ext.get("symbol") and not ext.get("token_address"):
                resolved = await self._resolve_symbol(ext["symbol"])
                if resolved:
                    ext["chain"] = resolved.get("chain", "solana")
                    ext["token_address"] = resolved.get("token_address")
                    ext["name"] = ext.get("name") or resolved.get("name")
                    ext["dex_url"] = ext.get("dex_url") or resolved.get("dex_url")
                    ext["pair_address"] = resolved.get("pair_address")
                    token = await self._get_or_create_token(session, ext)
                    if token:
                        await self._create_mention(session, token, reddit_post, ext)
                        mentions_created += 1

        await session.commit()
        return mentions_created

    async def _get_or_create_token(
        self,
        session: AsyncSession,
        ext: dict,
    ) -> Optional[RedditCandidateToken]:
        """Get existing candidate token or create a new one."""
        chain = ext.get("chain", "ethereum")
        token_address = ext.get("token_address")
        if not token_address:
            return None

        result = await session.execute(
            sa_select(RedditCandidateToken).where(
                and_(
                    RedditCandidateToken.chain == chain,
                    RedditCandidateToken.token_address == token_address,
                )
            )
        )
        token = result.scalar_one_or_none()

        if not token:
            # Convert enum values to strings for SAEnum compatibility
            first_method = ext.get("discovery_method", RedditDiscoveryMethod.CONTRACT_ADDRESS)
            if hasattr(first_method, 'value'):
                first_method = first_method.value

            token = RedditCandidateToken(
                chain=chain,
                token_address=token_address,
                symbol=ext.get("symbol") or "UNKNOWN",
                name=ext.get("name"),
                first_discovered_at=datetime.now(timezone.utc),
                first_discovery_method=first_method,
                pair_address=ext.get("pair_address"),
                dex_url=ext.get("dex_url"),
            )
            session.add(token)
            await session.flush()

        return token

    async def _create_mention(
        self,
        session: AsyncSession,
        token: RedditCandidateToken,
        post: RedditPost,
        ext: dict,
    ) -> None:
        """Create a mention record (idempotent)."""
        # Convert enum values to strings for SAEnum compatibility
        discovery_method = ext.get("discovery_method", RedditDiscoveryMethod.CONTRACT_ADDRESS)
        confidence = ext.get("confidence", RedditDiscoveryConfidence.MEDIUM)
        if hasattr(discovery_method, 'value'):
            discovery_method = discovery_method.value
        if hasattr(confidence, 'value'):
            confidence = confidence.value

        # Check for existing mention
        existing = await session.execute(
            sa_select(RedditTokenMention).where(
                and_(
                    RedditTokenMention.candidate_token_id == token.id,
                    RedditTokenMention.reddit_post_id == post.id,
                    RedditTokenMention.discovery_method == discovery_method,
                )
            )
        )
        if existing.scalar_one_or_none():
            return

        mention = RedditTokenMention(
            candidate_token_id=token.id,
            source_id=post.source_id,
            reddit_post_id=post.id,
            post_timestamp=post.post_timestamp,
            author=post.author,
            discovery_method=discovery_method,
            confidence=confidence,
        )
        session.add(mention)

    async def _resolve_symbol(self, symbol: str) -> Optional[dict]:
        """Resolve a symbol to a token via DexScreener search."""
        symbol_upper = symbol.upper()
        if symbol_upper in self._dex_cache:
            return self._dex_cache[symbol_upper]

        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    DEXSCREENER_SEARCH_URL,
                    params={"q": symbol},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if not pairs:
                        return None

                    # Prefer pairs on focus chains, then by highest liquidity
                    focus_pairs = [p for p in pairs if p.get("chainId", "").lower() in ("solana", "base", "ethereum", "bsc")]
                    candidate = focus_pairs[0] if focus_pairs else pairs[0]

                    result = {
                        "chain": candidate.get("chainId", "ethereum"),
                        "token_address": candidate.get("baseToken", {}).get("address"),
                        "name": candidate.get("baseToken", {}).get("name"),
                        "pair_address": candidate.get("pairAddress"),
                        "dex_url": candidate.get("url"),
                    }
                    self._dex_cache[symbol_upper] = result
                    return result
        except Exception as e:
            logger.warning(f"DexScreener symbol resolution failed for '{symbol}': {e}")
            return None
