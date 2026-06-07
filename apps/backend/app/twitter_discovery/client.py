"""
TwitterClientService — Collects tweets via Playwright scraping of public X profiles
and persists token mentions.

The actual Playwright scraping runs via collect_twitter_playwright.py (host machine),
which feeds results through the /twitter/ingest API endpoint.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Awaitable

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.twitter_discovery.models import (
    TwitterSource, TwitterTweet, TwitterCandidateToken,
    TwitterTokenMention, TwitterDiscoveryMethod, TwitterMentionDiscoveryMethod,
    TwitterDiscoveryConfidence,
    TwitterSourceType,
)
from app.twitter_discovery.config import seed_twitter_sources
from app.layers.discovery.twitter_discovery import TwitterDiscovery

logger = logging.getLogger(__name__)


class TwitterClientService:
    """Orchestrates Twitter collection: process ingested candidates → store."""

    def __init__(self):
        self._discovery = TwitterDiscovery()

    async def collect(
        self,
        session: AsyncSession,
        progress_callback: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> dict:
        """
        Run a full collection cycle:
        1. Seed default sources if needed
        2. Process any pending Playwright-scraped candidates from Redis
        3. Extract tokens and store mentions
        """
        stats = {
            "tweets_stored": 0,
            "tweets_skipped_duplicate": 0,
            "mentions_stored": 0,
            "tokens_discovered": 0,
            "errors": [],
        }

        # Seed default sources
        await seed_twitter_sources(session)

        # Discover candidates (from Redis pending queue populated by Playwright)
        if progress_callback:
            await progress_callback({"status": "searching", "query": "public profiles"})

        candidates = await self._discovery.discover()

        if progress_callback:
            await progress_callback({
                "status": "extracting",
                "candidates_found": len(candidates),
            })

        # Store results
        for candidate in candidates:
            try:
                await self._store_candidate(session, candidate, stats)
            except Exception as e:
                stats["errors"].append(f"Store error for {candidate.get('symbol')}: {str(e)}")

        await session.commit()

        if progress_callback:
            await progress_callback({
                "status": "done",
                "tweets_stored": stats["tweets_stored"],
                "mentions_stored": stats["mentions_stored"],
                "tokens_discovered": stats["tokens_discovered"],
            })

        return stats

    async def ingest_playwright_candidates(
        self,
        session: AsyncSession,
        candidates: list[dict],
    ) -> dict:
        """Ingest candidates scraped by the Playwright collector script.

        Called from the /twitter/ingest API endpoint.
        Stores tweets and mentions directly.
        """
        stats = {
            "tweets_stored": 0,
            "mentions_stored": 0,
            "tokens_discovered": 0,
            "errors": [],
        }

        await seed_twitter_sources(session)

        for candidate in candidates:
            try:
                await self._store_candidate(session, candidate, stats)
            except Exception as e:
                stats["errors"].append(f"Store error: {str(e)[:200]}")

        await session.commit()
        return stats

    async def _store_candidate(
        self,
        session: AsyncSession,
        candidate: dict,
        stats: dict,
    ):
        """Store a candidate token and its mention."""
        symbol = candidate.get("symbol", "UNKNOWN")
        contract_address = candidate.get("contract_address", "")
        chain = candidate.get("chain", "") or "unknown"
        source_name = candidate.get("source", "playwright")
        mention_count = candidate.get("mention_count", 1)
        unique_accounts = candidate.get("unique_accounts", 1)
        engagement = candidate.get("total_engagement", 0)
        authority_mentions = candidate.get("authority_mentions", 0)
        sample_tweets = candidate.get("sample_tweets", [])

        if not symbol or symbol == "UNKNOWN":
            return

        # Determine discovery method
        if contract_address:
            method = TwitterDiscoveryMethod.CONTRACT_ADDRESS
            mention_method = TwitterMentionDiscoveryMethod.CONTRACT_ADDRESS
        else:
            method = TwitterDiscoveryMethod.CASHTAG
            mention_method = TwitterMentionDiscoveryMethod.CASHTAG

        # Find or create matching source
        source_result = await session.execute(
            sa_select(TwitterSource).where(
                TwitterSource.query.ilike(f"%{symbol}%"),
                TwitterSource.enabled == True,
            ).limit(1)
        )
        source = source_result.scalar_one_or_none()
        if not source:
            # Use first enabled source as fallback
            source_result = await session.execute(
                sa_select(TwitterSource).where(TwitterSource.enabled == True).limit(1)
            )
            source = source_result.scalar_one_or_none()
        if not source:
            return

        # Find or create candidate token
        token_key = (chain.lower(), contract_address.lower() if contract_address else symbol.lower())
        token_result = await session.execute(
            sa_select(TwitterCandidateToken).where(
                TwitterCandidateToken.chain == chain,
                TwitterCandidateToken.token_address == (contract_address or symbol),
            )
        )
        token = token_result.scalar_one_or_none()

        if not token:
            token = TwitterCandidateToken(
                chain=chain,
                token_address=contract_address or symbol,
                symbol=symbol,
                first_discovered_at=datetime.now(timezone.utc),
                first_discovered_source_id=source.id,
                first_discovery_method=method,
            )
            session.add(token)
            await session.flush()
            stats["tokens_discovered"] += 1

        # Store a synthetic tweet for the mention
        combined_text = " ".join(sample_tweets[:3]) if sample_tweets else symbol
        text_hash = hashlib.sha256(combined_text.encode()).hexdigest()

        tweet = TwitterTweet(
            source_id=source.id,
            tweet_id=hashlib.sha256(f"{symbol}_{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:32],
            tweet_timestamp=datetime.now(timezone.utc),
            author_name=f"playwright_{source_name}",
            text_hash=text_hash,
            tweet_text=combined_text[:500],
            retweet_count=max(0, int(engagement * 0.3)),
            like_count=max(0, int(engagement * 0.5)),
            reply_count=max(0, int(engagement * 0.2)),
        )
        session.add(tweet)
        await session.flush()
        stats["tweets_stored"] += 1

        # Determine confidence
        if authority_mentions >= 2:
            confidence = TwitterDiscoveryConfidence.VERY_HIGH
        elif authority_mentions >= 1:
            confidence = TwitterDiscoveryConfidence.HIGH
        elif mention_count >= 3:
            confidence = TwitterDiscoveryConfidence.MEDIUM
        else:
            confidence = TwitterDiscoveryConfidence.LOW

        # Store mention
        mention = TwitterTokenMention(
            candidate_token_id=token.id,
            source_id=source.id,
            tweet_id=tweet.id,
            tweet_timestamp=tweet.tweet_timestamp,
            author_name=tweet.author_name,
            discovery_method=mention_method,
            confidence=confidence.value,
            is_reputable=authority_mentions > 0,
            engagement_score=float(engagement),
        )
        session.add(mention)
        stats["mentions_stored"] += 1
