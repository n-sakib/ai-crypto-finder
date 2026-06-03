"""
TwitterDiscoveryAggregator — Aggregates Twitter mentions into discovery rankings.

For a configurable time window, ranks tokens by:
    1. mention_count DESC
    2. unique_user_count DESC
    3. total_engagement DESC
    4. authority_mentions DESC
    5. most recent mention DESC

Tracks KPIs: mentions, unique_users, engagement, authority_mentions
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, desc, and_, Integer, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.twitter_discovery.models import (
    TwitterCandidateToken, TwitterTokenMention, TwitterDiscoveryRanking,
    TwitterTweet, TwitterSource, TwitterDiscoveryMethod,
)
from app.twitter_discovery.schemas import TwitterDiscoveryRankingItem, TwitterDiscoveryRankingResponse
from app.config import settings

logger = logging.getLogger(__name__)


def parse_window(window_str: str) -> timedelta:
    """Parse a window string like '1h', '6h', '24h' into a timedelta."""
    match = re.match(r"^(\d+)([mhd])$", window_str.strip().lower())
    if not match:
        return timedelta(hours=24)
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    return timedelta(hours=24)


class TwitterDiscoveryAggregator:
    """Aggregates Twitter token mentions into ranked discovery lists."""

    def __init__(
        self,
        min_mention_count: int | None = None,
        min_unique_users: int | None = None,
    ):
        self.min_mention_count = min_mention_count if min_mention_count is not None else 1
        self.min_unique_users = min_unique_users if min_unique_users is not None else 1

    async def rank(
        self,
        session: AsyncSession,
        window: str = "24h",
        limit: int | None = None,
    ) -> TwitterDiscoveryRankingResponse:
        """Compute rankings for the given time window."""
        if limit is None:
            limit = settings.TOP_DISCOVERY_LIMIT
        window_delta = parse_window(window)
        now = datetime.now(timezone.utc)
        window_start = now - window_delta
        window_end = now

        rankings = await self._aggregate_mentions(session, window_start, window_end, limit)
        total_tweets = await self._count_tweets_in_window(session, window_start, window_end)
        await self._persist_rankings(session, rankings, window_start, window_end)

        return TwitterDiscoveryRankingResponse(
            window=window,
            window_start=window_start,
            window_end=window_end,
            total_tokens=len(rankings),
            total_tweets=total_tweets,
            generated_at=now,
            tokens=rankings,
        )

    async def _aggregate_mentions(
        self,
        session: AsyncSession,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> list[TwitterDiscoveryRankingItem]:
        """Query mentions in the time window and aggregate by token."""
        mention_agg = (
            select(
                TwitterTokenMention.candidate_token_id,
                func.count(TwitterTokenMention.id).label("mention_count"),
                func.count(func.distinct(TwitterTokenMention.author_name)).label("unique_user_count"),
                func.coalesce(func.sum(TwitterTokenMention.engagement_score), 0).label("total_engagement"),
                func.coalesce(func.sum(case((TwitterTokenMention.is_reputable == True, 1), else_=0)), 0).label("authority_mentions"),
                func.min(TwitterTokenMention.tweet_timestamp).label("first_seen"),
                func.max(TwitterTokenMention.tweet_timestamp).label("last_seen"),
            )
            .where(
                and_(
                    TwitterTokenMention.tweet_timestamp >= window_start,
                    TwitterTokenMention.tweet_timestamp < window_end,
                )
            )
            .group_by(TwitterTokenMention.candidate_token_id)
            .having(
                and_(
                    func.count(TwitterTokenMention.id) >= self.min_mention_count,
                    func.count(func.distinct(TwitterTokenMention.author_name)) >= self.min_unique_users,
                )
            )
            .order_by(
                desc("mention_count"),
                desc("unique_user_count"),
                desc("total_engagement"),
                desc("authority_mentions"),
                desc("last_seen"),
            )
            .limit(limit)
        ).subquery()

        query = (
            select(
                TwitterCandidateToken,
                mention_agg.c.mention_count,
                mention_agg.c.unique_user_count,
                mention_agg.c.total_engagement,
                mention_agg.c.authority_mentions,
                mention_agg.c.first_seen,
                mention_agg.c.last_seen,
            )
            .join(mention_agg, TwitterCandidateToken.id == mention_agg.c.candidate_token_id)
            .order_by(
                desc(mention_agg.c.mention_count),
                desc(mention_agg.c.unique_user_count),
                desc(mention_agg.c.total_engagement),
                desc(mention_agg.c.authority_mentions),
                desc(mention_agg.c.last_seen),
            )
        )

        result = await session.execute(query)
        rows = result.all()

        rankings: list[TwitterDiscoveryRankingItem] = []
        for rank_idx, row in enumerate(rows, start=1):
            token = row[0]

            # Get discovery methods and source names
            methods_result = await session.execute(
                select(func.distinct(TwitterTokenMention.discovery_method))
                .where(
                    and_(
                        TwitterTokenMention.candidate_token_id == token.id,
                        TwitterTokenMention.tweet_timestamp >= window_start,
                        TwitterTokenMention.tweet_timestamp < window_end,
                    )
                )
            )
            methods = [r[0] for r in methods_result.all()]

            sources_result = await session.execute(
                select(TwitterSource.name)
                .join(TwitterTokenMention, TwitterTokenMention.source_id == TwitterSource.id)
                .where(
                    and_(
                        TwitterTokenMention.candidate_token_id == token.id,
                        TwitterTokenMention.tweet_timestamp >= window_start,
                        TwitterTokenMention.tweet_timestamp < window_end,
                    )
                )
                .distinct()
            )
            source_names = [r[0] for r in sources_result.all()]

            total_score = (
                row.mention_count * 10
                + row.unique_user_count * 5
                + (row.total_engagement or 0) * 0.1
                + (row.authority_mentions or 0) * 50
            )

            rankings.append(TwitterDiscoveryRankingItem(
                rank=rank_idx,
                chain=token.chain,
                token_address=token.token_address,
                symbol=token.symbol,
                name=token.name,
                mention_count=row.mention_count,
                unique_user_count=row.unique_user_count,
                total_engagement=int(row.total_engagement or 0),
                authority_mentions=row.authority_mentions or 0,
                total_score=round(total_score, 1),
                first_seen_in_window=row.first_seen,
                last_seen_in_window=row.last_seen,
                discovery_methods=methods,
                source_names=source_names,
                dex_url=token.dex_url,
                pair_address=token.pair_address,
            ))

        return rankings

    async def _count_tweets_in_window(
        self,
        session: AsyncSession,
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        result = await session.execute(
            select(func.count(TwitterTweet.id)).where(
                and_(
                    TwitterTweet.tweet_timestamp >= window_start,
                    TwitterTweet.tweet_timestamp < window_end,
                )
            )
        )
        return result.scalar() or 0

    async def _persist_rankings(
        self,
        session: AsyncSession,
        rankings: list[TwitterDiscoveryRankingItem],
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        """Persist rankings to the database."""
        from sqlalchemy import delete
        await session.execute(
            delete(TwitterDiscoveryRanking).where(
                and_(
                    TwitterDiscoveryRanking.window_start == window_start,
                    TwitterDiscoveryRanking.window_end == window_end,
                )
            )
        )

        for item in rankings:
            token_result = await session.execute(
                select(TwitterCandidateToken.id).where(
                    and_(
                        TwitterCandidateToken.chain == item.chain,
                        TwitterCandidateToken.token_address == item.token_address,
                    )
                )
            )
            token_id = token_result.scalar_one_or_none()
            if not token_id:
                continue

            ranking = TwitterDiscoveryRanking(
                candidate_token_id=token_id,
                window_start=window_start,
                window_end=window_end,
                mention_count=item.mention_count,
                unique_user_count=item.unique_user_count,
                total_engagement=item.total_engagement,
                authority_mentions=item.authority_mentions,
                total_score=int(item.total_score),
                rank=item.rank,
            )
            session.add(ranking)

        await session.commit()

    async def get_token_detail(
        self,
        session: AsyncSession,
        chain: str,
        token_address: str,
    ) -> dict | None:
        """Get detailed discovery data for a specific token."""
        token_result = await session.execute(
            select(TwitterCandidateToken).where(
                and_(
                    TwitterCandidateToken.chain == chain,
                    TwitterCandidateToken.token_address == token_address,
                )
            )
        )
        token = token_result.scalar_one_or_none()
        if not token:
            return None

        mention_count_result = await session.execute(
            select(func.count(TwitterTokenMention.id))
            .where(TwitterTokenMention.candidate_token_id == token.id)
        )
        total_mentions = mention_count_result.scalar() or 0

        users_result = await session.execute(
            select(func.count(func.distinct(TwitterTokenMention.author_name)))
            .where(TwitterTokenMention.candidate_token_id == token.id)
        )
        unique_users = users_result.scalar() or 0

        eng_result = await session.execute(
            select(func.coalesce(func.sum(TwitterTokenMention.engagement_score), 0))
            .where(TwitterTokenMention.candidate_token_id == token.id)
        )
        total_engagement = int(eng_result.scalar() or 0)

        auth_result = await session.execute(
            select(func.coalesce(func.sum(case((TwitterTokenMention.is_reputable == True, 1), else_=0)), 0))
            .where(TwitterTokenMention.candidate_token_id == token.id)
        )
        authority_mentions = auth_result.scalar() or 0

        total_score = total_mentions * 10 + unique_users * 5 + total_engagement * 0.1 + (authority_mentions or 0) * 50

        # Recent mentions
        recent_result = await session.execute(
            select(
                TwitterTokenMention,
                TwitterTweet.tweet_text,
                TwitterSource.name,
            )
            .join(TwitterTweet, TwitterTokenMention.tweet_id == TwitterTweet.id)
            .join(TwitterSource, TwitterTokenMention.source_id == TwitterSource.id)
            .where(TwitterTokenMention.candidate_token_id == token.id)
            .order_by(desc(TwitterTokenMention.tweet_timestamp))
            .limit(20)
        )
        recent = [
            {
                "author": r[0].author_name,
                "discovery_method": r[0].discovery_method.value if hasattr(r[0].discovery_method, 'value') else str(r[0].discovery_method),
                "tweet_text": (r[1] or "")[:200],
                "source_name": r[2],
                "is_reputable": r[0].is_reputable,
                "timestamp": r[0].tweet_timestamp.isoformat(),
            }
            for r in recent_result.all()
        ]

        return {
            "chain": token.chain,
            "token_address": token.token_address,
            "symbol": token.symbol,
            "name": token.name,
            "pair_address": token.pair_address,
            "dex_url": token.dex_url,
            "first_discovered_at": token.first_discovered_at,
            "first_discovery_method": token.first_discovery_method,
            "total_mentions": total_mentions,
            "unique_users": unique_users,
            "total_engagement": total_engagement,
            "authority_mentions": authority_mentions,
            "total_score": round(total_score, 1),
            "recent_mentions": recent,
            "rankings": [],
        }
