"""
RedditDiscoveryAggregator — Aggregates Reddit mentions and produces discovery rankings.

For a configurable time window, ranks tokens by:
    1. mention_count DESC
    2. unique_user_count DESC
    3. subreddit_count DESC
    4. post_count DESC
    5. total_score (upvotes) DESC
    6. most recent mention DESC

Tracks KPIs: mentions, unique_authors, subreddit_count, post_count, comment_count, upvotes

Minimum filters:
    - mention_count >= 2
    - unique_user_count >= 2
    - token must resolve to chain + token_address
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.reddit_discovery.models import (
    RedditCandidateToken, RedditTokenMention, RedditDiscoveryRanking,
    RedditPost, RedditSource, RedditDiscoveryMethod,
)
from app.reddit_discovery.schemas import RedditDiscoveryRankingItem, RedditDiscoveryRankingResponse
from app.config import settings

logger = logging.getLogger(__name__)


def parse_window(window_str: str) -> timedelta:
    """Parse a window string like '1h', '30m', '6h', '24h' into a timedelta."""
    match = re.match(r"^(\d+)([mhd])$", window_str.strip().lower())
    if not match:
        return timedelta(hours=24)  # Default: 24h for Reddit (slower signal)
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    return timedelta(hours=24)


class RedditDiscoveryAggregator:
    """
    Aggregates Reddit token mentions into ranked discovery lists.
    """

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
    ) -> RedditDiscoveryRankingResponse:
        """Compute rankings for the given time window."""
        if limit is None:
            limit = settings.TOP_DISCOVERY_LIMIT
        window_delta = parse_window(window)
        now = datetime.now(timezone.utc)
        window_start = now - window_delta
        window_end = now

        rankings = await self._aggregate_mentions(session, window_start, window_end, limit)
        total_posts = await self._count_posts_in_window(session, window_start, window_end)
        total_comments = sum(t.comment_count for t in rankings)
        total_upvotes = sum(t.upvotes for t in rankings)
        await self._persist_rankings(session, rankings, window_start, window_end)

        return RedditDiscoveryRankingResponse(
            window=window,
            window_start=window_start,
            window_end=window_end,
            total_tokens=len(rankings),
            total_posts=total_posts,
            total_comments=total_comments,
            total_upvotes=total_upvotes,
            generated_at=now,
            tokens=rankings,
        )

    async def _aggregate_mentions(
        self,
        session: AsyncSession,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> list[RedditDiscoveryRankingItem]:
        """Query mentions in the time window and aggregate by token."""
        mention_agg = (
            select(
                RedditTokenMention.candidate_token_id,
                func.count(RedditTokenMention.id).label("mention_count"),
                func.count(func.distinct(RedditTokenMention.author)).label("unique_user_count"),
                func.count(func.distinct(RedditTokenMention.source_id)).label("subreddit_count"),
                func.count(func.distinct(RedditTokenMention.reddit_post_id)).label("post_count"),
                func.min(RedditTokenMention.post_timestamp).label("first_seen"),
                func.max(RedditTokenMention.post_timestamp).label("last_seen"),
            )
            .where(
                and_(
                    RedditTokenMention.post_timestamp >= window_start,
                    RedditTokenMention.post_timestamp < window_end,
                )
            )
            .group_by(RedditTokenMention.candidate_token_id)
            .having(
                and_(
                    func.count(RedditTokenMention.id) >= self.min_mention_count,
                    func.count(func.distinct(RedditTokenMention.author)) >= self.min_unique_users,
                )
            )
            .order_by(
                desc("mention_count"),
                desc("unique_user_count"),
                desc("subreddit_count"),
                desc("post_count"),
                desc("last_seen"),
            )
            .limit(limit)
        ).subquery()

        query = (
            select(
                RedditCandidateToken,
                mention_agg.c.mention_count,
                mention_agg.c.unique_user_count,
                mention_agg.c.subreddit_count,
                mention_agg.c.post_count,
                mention_agg.c.first_seen,
                mention_agg.c.last_seen,
            )
            .join(mention_agg, RedditCandidateToken.id == mention_agg.c.candidate_token_id)
            .order_by(
                desc(mention_agg.c.mention_count),
                desc(mention_agg.c.unique_user_count),
                desc(mention_agg.c.subreddit_count),
                desc(mention_agg.c.post_count),
                desc(mention_agg.c.last_seen),
            )
        )

        result = await session.execute(query)
        rows = result.all()

        rankings: list[RedditDiscoveryRankingItem] = []
        for rank_idx, row in enumerate(rows, start=1):
            token = row[0]
            # Get total score, comment count, and upvotes from posts
            score_result = await session.execute(
                select(
                    func.coalesce(func.sum(RedditPost.score), 0),
                    func.coalesce(func.sum(RedditPost.num_comments), 0),
                )
                .join(RedditTokenMention, RedditTokenMention.reddit_post_id == RedditPost.id)
                .where(
                    and_(
                        RedditTokenMention.candidate_token_id == token.id,
                        RedditTokenMention.post_timestamp >= window_start,
                        RedditTokenMention.post_timestamp < window_end,
                    )
                )
            )
            score_row = score_result.one()
            total_score = score_row[0] or 0
            comment_count = score_row[1] or 0

            # Get discovery methods and source names
            methods_result = await session.execute(
                select(func.distinct(RedditTokenMention.discovery_method))
                .where(
                    and_(
                        RedditTokenMention.candidate_token_id == token.id,
                        RedditTokenMention.post_timestamp >= window_start,
                        RedditTokenMention.post_timestamp < window_end,
                    )
                )
            )
            methods = [r[0] for r in methods_result.all()]

            sources_result = await session.execute(
                select(RedditSource.name)
                .join(RedditTokenMention, RedditTokenMention.source_id == RedditSource.id)
                .where(
                    and_(
                        RedditTokenMention.candidate_token_id == token.id,
                        RedditTokenMention.post_timestamp >= window_start,
                        RedditTokenMention.post_timestamp < window_end,
                    )
                )
                .distinct()
            )
            source_names = [r[0] for r in sources_result.all()]

            rankings.append(RedditDiscoveryRankingItem(
                rank=rank_idx,
                chain=token.chain,
                token_address=token.token_address,
                symbol=token.symbol,
                name=token.name,
                mention_count=row.mention_count,
                unique_user_count=row.unique_user_count,
                subreddit_count=row.subreddit_count,
                post_count=row.post_count,
                comment_count=comment_count,
                upvotes=total_score,
                total_score=total_score,
                first_seen_in_window=row.first_seen,
                last_seen_in_window=row.last_seen,
                discovery_methods=methods,
                source_names=source_names,
                dex_url=token.dex_url,
                pair_address=token.pair_address,
            ))

        return rankings

    async def _count_posts_in_window(
        self,
        session: AsyncSession,
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        result = await session.execute(
            select(func.count(RedditPost.id)).where(
                and_(
                    RedditPost.post_timestamp >= window_start,
                    RedditPost.post_timestamp < window_end,
                )
            )
        )
        return result.scalar() or 0

    async def _persist_rankings(
        self,
        session: AsyncSession,
        rankings: list[RedditDiscoveryRankingItem],
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        """Persist rankings to the database."""
        # Clean old rankings for this window
        from sqlalchemy import delete
        await session.execute(
            delete(RedditDiscoveryRanking).where(
                and_(
                    RedditDiscoveryRanking.window_start == window_start,
                    RedditDiscoveryRanking.window_end == window_end,
                )
            )
        )

        for item in rankings:
            # Find the candidate token ID
            token_result = await session.execute(
                select(RedditCandidateToken.id).where(
                    and_(
                        RedditCandidateToken.chain == item.chain,
                        RedditCandidateToken.token_address == item.token_address,
                    )
                )
            )
            token_id = token_result.scalar_one_or_none()
            if not token_id:
                continue

            ranking = RedditDiscoveryRanking(
                candidate_token_id=token_id,
                window_start=window_start,
                window_end=window_end,
                mention_count=item.mention_count,
                unique_user_count=item.unique_user_count,
                subreddit_count=item.subreddit_count,
                post_count=item.post_count,
                comment_count=item.comment_count,
                total_score=item.total_score,
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
            select(RedditCandidateToken).where(
                and_(
                    RedditCandidateToken.chain == chain,
                    RedditCandidateToken.token_address == token_address,
                )
            )
        )
        token = token_result.scalar_one_or_none()
        if not token:
            return None

        mention_count_result = await session.execute(
            select(func.count(RedditTokenMention.id))
            .where(RedditTokenMention.candidate_token_id == token.id)
        )
        total_mentions = mention_count_result.scalar() or 0

        users_result = await session.execute(
            select(func.count(func.distinct(RedditTokenMention.author)))
            .where(RedditTokenMention.candidate_token_id == token.id)
        )
        unique_users = users_result.scalar() or 0

        sr_result = await session.execute(
            select(func.count(func.distinct(RedditTokenMention.source_id)))
            .where(RedditTokenMention.candidate_token_id == token.id)
        )
        subreddit_count = sr_result.scalar() or 0

        post_count_result = await session.execute(
            select(func.count(func.distinct(RedditTokenMention.reddit_post_id)))
            .where(RedditTokenMention.candidate_token_id == token.id)
        )
        post_count = post_count_result.scalar() or 0

        post_agg_result = await session.execute(
            select(
                func.coalesce(func.sum(RedditPost.score), 0),
                func.coalesce(func.sum(RedditPost.num_comments), 0),
            )
            .join(RedditTokenMention, RedditTokenMention.reddit_post_id == RedditPost.id)
            .where(RedditTokenMention.candidate_token_id == token.id)
        )
        post_agg_row = post_agg_result.one()
        total_score = post_agg_row[0] or 0
        total_comments = post_agg_row[1] or 0

        # Recent mentions
        recent_result = await session.execute(
            select(
                RedditTokenMention,
                RedditPost.title,
                RedditPost.score,
                RedditSource.name,
            )
            .join(RedditPost, RedditTokenMention.reddit_post_id == RedditPost.id)
            .join(RedditSource, RedditTokenMention.source_id == RedditSource.id)
            .where(RedditTokenMention.candidate_token_id == token.id)
            .order_by(desc(RedditTokenMention.post_timestamp))
            .limit(20)
        )
        recent = [
            {
                "author": r[0].author,
                "discovery_method": r[0].discovery_method.value if hasattr(r[0].discovery_method, 'value') else str(r[0].discovery_method),
                "post_title": r[1],
                "post_score": r[2],
                "source_name": r[3],
                "timestamp": r[0].post_timestamp.isoformat(),
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
            "subreddit_count": subreddit_count,
            "post_count": post_count,
            "comment_count": total_comments,
            "upvotes": total_score,
            "total_score": total_score,
            "recent_mentions": recent,
            "rankings": [],
        }
