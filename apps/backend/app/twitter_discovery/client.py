"""
TwitterClientService — Collects tweets via twikit and stores token mentions.

Uses the existing TwitterDiscovery layer for actual searching,
then persists results into the twitter_discovery tables.
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
    TwitterTokenMention, TwitterDiscoveryMethod, TwitterDiscoveryConfidence,
    TwitterSourceType,
)
from app.twitter_discovery.config import seed_twitter_sources
from app.layers.discovery.twitter_discovery import TwitterDiscovery

logger = logging.getLogger(__name__)


class TwitterClientService:
    """Orchestrates Twitter collection: search → extract → store."""

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
        2. Run TwitterDiscovery searches via twikit (keyword/cashtag/address queries)
        3. Fetch tweets from monitored accounts (@handles)
        4. Extract tokens and store mentions
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

        # Get all enabled sources
        sources_result = await session.execute(
            sa_select(TwitterSource).where(TwitterSource.enabled == True)
        )
        sources = sources_result.scalars().all()

        if not sources:
            stats["errors"].append("No enabled Twitter sources")
            return stats

        # Split sources: account monitors vs search queries
        account_sources = [s for s in sources if s.source_type == TwitterSourceType.ACCOUNT_MONITOR]
        search_sources = [s for s in sources if s.source_type != TwitterSourceType.ACCOUNT_MONITOR]

        discovery = self._discovery
        candidates: list[dict] = []

        # Phase 1: Account monitoring — fetch tweets from followed accounts
        if account_sources:
            total_accounts = len(account_sources)
            for idx, src in enumerate(account_sources):
                if progress_callback:
                    await progress_callback({
                        "status": "searching",
                        "sources_total": total_accounts + 30,
                        "sources_done": idx,
                        "query": f"@{src.query.replace('@', '')}",
                    })
                try:
                    account_candidates = await self._fetch_account_tweets(session, src, stats)
                    candidates.extend(account_candidates)
                except Exception as e:
                    logger.error("Account fetch failed for %s: %s", src.query, e)
                    stats["errors"].append(f"@{src.query}: {str(e)}")
                await asyncio.sleep(2.0)

        # Phase 2: Search-based discovery
        if search_sources:
            discovery = self._discovery
            client = await discovery._get_client()

            if client is not None:
                await self._run_searches(candidates, discovery, len(account_sources), progress_callback)
            else:
                logger.warning("Twikit auth failed — skipping searches")
                stats["errors"].append("Twitter login failed — check TWITTER_USERNAME/TWITTER_PASSWORD in .env")

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

    async def _run_searches(
        self, candidates: list, discovery, account_offset: int,
        progress_callback,
    ):
        """Run keyword + address searches using twikit."""
        keyword_count = len(discovery.SEARCH_TERMS)
        total_terms = account_offset + keyword_count + 3

        async def keyword_progress(data: dict):
            if progress_callback:
                d = data.copy()
                d["sources_done"] = account_offset + d.get("sources_done", 0)
                d["sources_total"] = total_terms
                await progress_callback(d)

        async def address_progress(data: dict):
            if progress_callback:
                d = data.copy()
                d["sources_done"] = account_offset + keyword_count + d.get("sources_done", 0)
                d["sources_total"] = total_terms
                await progress_callback(d)

        try:
            kw = await discovery._search_keywords(progress_callback=keyword_progress)
        except Exception as e:
            logger.error("Twikit keyword search failed: %s", e)
            kw = []
        try:
            addr = await discovery._search_addresses(progress_callback=address_progress)
        except Exception as e:
            logger.error("Twikit address search failed: %s", e)
            addr = []
        if isinstance(kw, list): candidates.extend(kw)
        if isinstance(addr, list): candidates.extend(addr)

    async def _fetch_account_tweets(
        self,
        session: AsyncSession,
        source: TwitterSource,
        stats: dict,
        max_tweets: int = 50,
    ) -> list[dict]:
        """Fetch recent tweets from a monitored Twitter account via twikit."""
        client = await self._discovery._get_client()
        if client is None:
            return []

        handle = source.query.lstrip("@")
        candidates: list[dict] = []
        tweet_count = 0

        try:
            user = await client.get_user_by_screen_name(handle)
            if not user:
                logger.warning("User not found: @%s", handle)
                return []

            user_id = str(getattr(user, "id", ""))
            logger.info("Fetching tweets for @%s (id=%s)...", handle, user_id)

            tweets = await client.get_user_tweets(user_id, "Tweets")
            count = 0
            async for tweet in tweets:
                if count >= max_tweets:
                    break
                count += 1

                text = getattr(tweet, "text", "") or ""
                if not text.strip():
                    continue

                created_at = getattr(tweet, "created_at", None)
                if created_at:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                    if created_at < cutoff:
                        continue

                tweet_count += 1
                engagement = (
                    (getattr(tweet, "retweet_count", 0) or 0)
                    + (getattr(tweet, "like_count", 0) or 0)
                    + (getattr(tweet, "reply_count", 0) or 0)
                )
                text_hash = hashlib.sha256(text.encode()).hexdigest()
                tweet_id_str = str(getattr(tweet, "id", ""))
                tweet_user = getattr(tweet, "user", None)
                author_name = getattr(tweet_user, "name", "") if tweet_user else handle

                existing = await session.execute(
                    sa_select(TwitterTweet).where(
                        TwitterTweet.source_id == source.id,
                        TwitterTweet.tweet_id == tweet_id_str,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                tw_tweet = TwitterTweet(
                    source_id=source.id, tweet_id=tweet_id_str,
                    tweet_timestamp=created_at or datetime.now(timezone.utc),
                    author_name=author_name, text_hash=text_hash,
                    tweet_text=text[:500],
                    retweet_count=getattr(tweet, "retweet_count", 0) or 0,
                    like_count=getattr(tweet, "like_count", 0) or 0,
                    reply_count=getattr(tweet, "reply_count", 0) or 0,
                    tweet_url=f"https://twitter.com/{handle}/status/{tweet_id_str}",
                )
                session.add(tw_tweet)
                await session.flush()
                stats["tweets_stored"] += 1

                cashtags = TwitterDiscovery.CASHTAG_RE.findall(text)
                for sym in cashtags:
                    sym_u = sym.upper()
                    if sym_u in TwitterDiscovery.SPAM_CASHTAGS or len(sym_u) < 2:
                        continue
                    candidates.append({
                        "symbol": sym_u, "contract_address": "", "chain": "",
                        "mention_count": 1.0, "unique_accounts": 1,
                        "total_engagement": engagement, "authority_mentions": 1,
                        "source": f"@{handle}", "sample_tweets": [text[:200]],
                    })
                for addr in TwitterDiscovery.CONTRACT_ADDRESS_EVM_RE.findall(text):
                    candidates.append({
                        "symbol": "UNKNOWN", "contract_address": addr,
                        "chain": "ethereum", "mention_count": 1.0,
                        "unique_accounts": 1, "total_engagement": engagement,
                        "authority_mentions": 1,
                        "source": f"@{handle}", "sample_tweets": [text[:200]],
                    })

        except Exception as e:
            logger.error("Error fetching tweets for @%s: %s", handle, e)
            raise

        source.last_collected_at = datetime.now(timezone.utc)
        logger.info("@%s: %d tweets fetched, %d tokens found", handle, tweet_count, len(candidates))
        return candidates

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
        source_name = candidate.get("source", "twikit")
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
        else:
            method = TwitterDiscoveryMethod.CASHTAG

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
            author_name=f"twikit_{source_name}",
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
            discovery_method=method,
            confidence=confidence,
            is_reputable=authority_mentions > 0,
            engagement_score=float(engagement),
        )
        session.add(mention)
        stats["mentions_stored"] += 1
