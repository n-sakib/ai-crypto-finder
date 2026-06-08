"""
TelegramDiscoveryAggregator — Aggregates mentions and produces discovery rankings.

For a configurable time window, ranks tokens by:
    1. mention_count DESC
    2. unique_user_count DESC
    3. group_count DESC
    4. most recent mention DESC

Minimum filters:
    - mention_count >= 5
    - unique_user_count >= 3
    - token must resolve to chain + token_address (enforced by schema)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, desc, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.telegram_discovery.models import (
    CandidateToken, TelegramTokenMention, TelegramDiscoveryRanking,
    TelegramMessage, TelegramSource, DiscoveryMethod,
)
from app.telegram_discovery.schemas import DiscoveryRankingItem, DiscoveryRankingResponse
from app.config import settings

logger = logging.getLogger(__name__)


def parse_window(window_str: str) -> timedelta:
    """
    Parse a window string like '1h', '30m', '6h', '24h' into a timedelta.

    Supported units: m (minutes), h (hours), d (days).
    Defaults to 1 hour for unparseable input.
    """
    import re
    window_str = window_str.strip().lower()

    # Match number + unit pattern
    match = re.match(r"^(\d+)([mhd])$", window_str)
    if not match:
        return timedelta(hours=1)  # Default

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    else:
        return timedelta(hours=1)


class TelegramDiscoveryAggregator:
    """
    Aggregates Telegram token mentions into ranked discovery lists.

    Thresholds default to env vars: MIN_MENTIONS, MIN_UNIQUE_USERS, TOP_DISCOVERY_LIMIT.

    Usage:
        agg = TelegramDiscoveryAggregator()
        rankings = await agg.rank(session, window="1h", limit=100)
    """

    def __init__(
        self,
        min_mention_count: int | None = None,
        min_group_count: int = 1,
        min_unique_user_count: int = 1,
    ):
        self.min_mention_count = min_mention_count if min_mention_count is not None else settings.MIN_MENTIONS
        self.min_group_count = min_group_count
        self.min_unique_user_count = min_unique_user_count

    async def rank(
        self,
        session: AsyncSession,
        window: str = "1h",
        limit: int | None = None,
    ) -> DiscoveryRankingResponse:
        """
        Compute rankings for the given time window.

        Args:
            session: Async database session.
            window: Time window string (e.g., '1h', '6h', '24h').
            limit: Maximum number of ranked tokens to return.
                   Defaults to TOP_DISCOVERY_LIMIT env var.

        Returns:
            DiscoveryRankingResponse with ranked tokens.
        """
        if limit is None:
            limit = settings.TOP_DISCOVERY_LIMIT
        window_delta = parse_window(window)
        now = datetime.now(timezone.utc)
        window_start = now - window_delta
        window_end = now

        # ── Aggregate mentions within the window ──────────────────────
        rankings = await self._aggregate_mentions(
            session, window_start, window_end, limit,
        )

        # ── Count unique messages in window ──────────────────────────
        total_messages = await self._count_messages_in_window(
            session, window_start, window_end,
        )

        # ── Persist rankings ─────────────────────────────────────────
        await self._persist_rankings(
            session, rankings, window_start, window_end,
        )

        return DiscoveryRankingResponse(
            window=window,
            window_start=window_start,
            window_end=window_end,
            total_tokens=len(rankings),
            total_messages=total_messages,
            generated_at=now,
            tokens=rankings,
        )

    async def _aggregate_mentions(
        self,
        session: AsyncSession,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> list[DiscoveryRankingItem]:
        """
        Query mentions in the time window and aggregate by token.

        mention_count = total raw mentions (COUNT *)
        unique_user_count = distinct users (COUNT DISTINCT sender)
        group_count = distinct groups (COUNT DISTINCT source)
        """
        mention_agg = (
            select(
                TelegramTokenMention.candidate_token_id,
                func.count(TelegramTokenMention.id).label("mention_count"),
                func.count(func.distinct(TelegramTokenMention.sender_id_hash)).label("unique_user_count"),
                func.count(func.distinct(TelegramTokenMention.source_id)).label("group_count"),
                func.min(TelegramTokenMention.message_timestamp).label("first_seen"),
                func.max(TelegramTokenMention.message_timestamp).label("last_seen"),
            )
            .where(
                and_(
                    TelegramTokenMention.message_timestamp >= window_start,
                    TelegramTokenMention.message_timestamp < window_end,
                )
            )
            .group_by(TelegramTokenMention.candidate_token_id)
            .having(
                and_(
                    func.count(TelegramTokenMention.id) >= self.min_mention_count,
                    func.count(func.distinct(TelegramTokenMention.source_id)) >= self.min_group_count,
                    func.count(func.distinct(TelegramTokenMention.sender_id_hash)) >= self.min_unique_user_count,
                )
            )
            .order_by(
                desc("group_count"),
                desc("mention_count"),
                desc("unique_user_count"),
                desc("last_seen"),
            )
            .limit(limit)
        ).subquery()

        # Join with candidate tokens to get token details (only enriched ones)
        query = (
            select(
                CandidateToken,
                mention_agg.c.mention_count,
                mention_agg.c.unique_user_count,
                mention_agg.c.group_count,
                mention_agg.c.first_seen,
                mention_agg.c.last_seen,
            )
            .join(mention_agg, CandidateToken.id == mention_agg.c.candidate_token_id)
            .where(CandidateToken.pair_address.isnot(None))
            .order_by(
                desc(mention_agg.c.group_count),
                desc(mention_agg.c.mention_count),
                desc(mention_agg.c.unique_user_count),
                desc(mention_agg.c.last_seen),
            )
        )

        result = await session.execute(query)
        rows = result.all()

        rankings: list[DiscoveryRankingItem] = []
        for rank_idx, row in enumerate(rows, start=1):
            token = row[0]

            # Skip unresolved cashtags — they have no real contract address
            if token.token_address.startswith("cashtag:"):
                continue

            # Get discovery methods used for this token
            methods = await self._get_discovery_methods(session, token.id, window_start, window_end)
            source_names = await self._get_source_names(session, token.id, window_start, window_end)
            source_mentions = await self._get_source_mentions(session, token.id, window_start, window_end)
            social_stats = await self._get_social_stats(session, token.id, window_start, window_end)

            # AI evaluation data
            ai_eval = token.ai_evaluation or {}
            ai_decision = token.ai_decision
            ai_confidence = ai_eval.get("confidence") if token.ai_evaluation else None
            ai_reasoning = ai_eval.get("reasoning")
            ai_red_flags = ai_eval.get("red_flags", [])
            ai_positive_signals = ai_eval.get("positive_signals", [])

            rankings.append(DiscoveryRankingItem(
                rank=rank_idx,
                chain=token.chain,
                token_address=token.token_address,
                symbol=token.symbol,
                name=token.name,
                mention_count=row.mention_count,
                unique_user_count=row.unique_user_count,
                group_count=row.group_count,
                total_reactions=social_stats.get("total_reactions", 0),
                total_replies=social_stats.get("total_replies", 0),
                total_views=social_stats.get("total_views", 0),
                total_forwards=social_stats.get("total_forwards", 0),
                first_seen_in_window=row.first_seen,
                last_seen_in_window=row.last_seen,
                discovery_methods=methods,
                source_names=source_names,
                source_mentions=source_mentions,
                dex_url=token.dex_url,
                pair_address=token.pair_address,
                ai_decision=ai_decision,
                ai_confidence=ai_confidence,
                ai_reasoning=ai_reasoning,
                ai_red_flags=ai_red_flags or [],
                ai_positive_signals=ai_positive_signals or [],
            ))

        return rankings

    async def _count_messages_in_window(
        self,
        session: AsyncSession,
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        """Count distinct messages that have mentions in the time window."""
        result = await session.execute(
            select(func.count(func.distinct(TelegramTokenMention.telegram_message_id)))
            .where(
                and_(
                    TelegramTokenMention.message_timestamp >= window_start,
                    TelegramTokenMention.message_timestamp < window_end,
                )
            )
        )
        return result.scalar() or 0

    async def _get_discovery_methods(
        self,
        session: AsyncSession,
        candidate_token_id,
        window_start: datetime,
        window_end: datetime,
    ) -> list[DiscoveryMethod]:
        """Get distinct discovery methods used for a token in the window."""
        result = await session.execute(
            select(func.distinct(TelegramTokenMention.discovery_method))
            .where(
                and_(
                    TelegramTokenMention.candidate_token_id == candidate_token_id,
                    TelegramTokenMention.message_timestamp >= window_start,
                    TelegramTokenMention.message_timestamp < window_end,
                )
            )
        )
        return [row[0] for row in result.all()]

    async def _get_source_names(
        self,
        session: AsyncSession,
        candidate_token_id,
        window_start: datetime,
        window_end: datetime,
    ) -> list[str]:
        """Get distinct source names for a token's mentions in the window."""
        result = await session.execute(
            select(func.distinct(TelegramSource.name))
            .join(TelegramTokenMention, TelegramTokenMention.source_id == TelegramSource.id)
            .where(
                and_(
                    TelegramTokenMention.candidate_token_id == candidate_token_id,
                    TelegramTokenMention.message_timestamp >= window_start,
                    TelegramTokenMention.message_timestamp < window_end,
                )
            )
        )
        return [row[0] for row in result.all()]

    async def _get_source_mentions(
        self,
        session: AsyncSession,
        candidate_token_id,
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, int]:
        """Get per-group mention counts for a token in the window.

        Returns dict of {group_name: mention_count}.
        Per-group dedup: multiple mentions in same group = 1 mention.
        """
        result = await session.execute(
            select(
                TelegramSource.name,
                func.count(func.distinct(TelegramTokenMention.telegram_message_id)).label("cnt"),
            )
            .join(TelegramTokenMention, TelegramTokenMention.source_id == TelegramSource.id)
            .where(
                and_(
                    TelegramTokenMention.candidate_token_id == candidate_token_id,
                    TelegramTokenMention.message_timestamp >= window_start,
                    TelegramTokenMention.message_timestamp < window_end,
                )
            )
            .group_by(TelegramSource.name)
            .order_by(desc("cnt"))
        )
        return {row[0]: row[1] for row in result.all()}

    async def _get_social_stats(
        self,
        session: AsyncSession,
        candidate_token_id,
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, int]:
        """Get aggregated social stats (reactions, replies) for a token's messages.

        Views and forwards are channel-only — not available for group chats.
        Reactions work for all chat types. Replies work for all chat types.
        """
        result = await session.execute(
            select(
                func.coalesce(func.sum(TelegramMessage.reactions_count), 0),
                func.coalesce(func.sum(TelegramMessage.reply_count), 0),
            )
            .join(TelegramTokenMention, TelegramTokenMention.telegram_message_id == TelegramMessage.id)
            .where(
                and_(
                    TelegramTokenMention.candidate_token_id == candidate_token_id,
                    TelegramTokenMention.message_timestamp >= window_start,
                    TelegramTokenMention.message_timestamp < window_end,
                )
            )
        )
        row = result.one_or_none()
        if row:
            return {"total_reactions": int(row[0]), "total_replies": int(row[1]), "total_forwards": 0}
        return {"total_reactions": 0, "total_replies": 0, "total_forwards": 0}

    async def _persist_rankings(
        self,
        session: AsyncSession,
        rankings: list[DiscoveryRankingItem],
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        """Persist computed rankings to the database."""
        for item in rankings:
            # Resolve candidate_token_id from chain + token_address
            result = await session.execute(
                select(CandidateToken.id).where(
                    CandidateToken.chain == item.chain,
                    CandidateToken.token_address == item.token_address,
                )
            )
            token_id = result.scalar_one_or_none()
            if not token_id:
                continue

            # Upsert ranking
            existing = await session.execute(
                select(TelegramDiscoveryRanking).where(
                    TelegramDiscoveryRanking.candidate_token_id == token_id,
                    TelegramDiscoveryRanking.window_start == window_start,
                    TelegramDiscoveryRanking.window_end == window_end,
                )
            )
            rank_record = existing.scalar_one_or_none()

            if rank_record:
                rank_record.mention_count = item.mention_count
                rank_record.unique_user_count = item.unique_user_count
                rank_record.group_count = item.group_count
                rank_record.first_seen_in_window = item.first_seen_in_window
                rank_record.last_seen_in_window = item.last_seen_in_window
                rank_record.rank = item.rank
            else:
                rank_record = TelegramDiscoveryRanking(
                    candidate_token_id=token_id,
                    window_start=window_start,
                    window_end=window_end,
                    mention_count=item.mention_count,
                    unique_user_count=item.unique_user_count,
                    group_count=item.group_count,
                    first_seen_in_window=item.first_seen_in_window,
                    last_seen_in_window=item.last_seen_in_window,
                    rank=item.rank,
                )
                session.add(rank_record)

        await session.flush()

    async def get_token_detail(
        self,
        session: AsyncSession,
        chain: str,
        token_address: str,
    ) -> Optional[dict]:
        """Get detailed discovery data for a specific token."""
        result = await session.execute(
            select(CandidateToken).where(
                CandidateToken.chain == chain.lower(),
                CandidateToken.token_address == token_address.lower(),
            )
        )
        token = result.scalar_one_or_none()
        if not token:
            return None

        # Get mention stats
        mention_stats = await session.execute(
            select(
                func.count(TelegramTokenMention.id).label("total"),
                func.count(func.distinct(TelegramTokenMention.sender_id_hash)).label("users"),
                func.count(func.distinct(TelegramTokenMention.source_id)).label("groups"),
            )
            .where(TelegramTokenMention.candidate_token_id == token.id)
        )
        stats = mention_stats.one()

        # Get recent mentions (last 10)
        recent = await session.execute(
            select(
                TelegramTokenMention.message_timestamp,
                TelegramTokenMention.discovery_method,
                TelegramTokenMention.confidence,
                TelegramSource.name,
            )
            .join(TelegramSource, TelegramTokenMention.source_id == TelegramSource.id)
            .where(TelegramTokenMention.candidate_token_id == token.id)
            .order_by(desc(TelegramTokenMention.message_timestamp))
            .limit(10)
        )
        recent_mentions = [
            {
                "timestamp": r.message_timestamp.isoformat(),
                "method": r.discovery_method.value if r.discovery_method else None,
                "confidence": r.confidence.value if r.confidence else None,
                "source": r.name,
            }
            for r in recent.all()
        ]

        # Get ranking history
        rank_history = await session.execute(
            select(
                TelegramDiscoveryRanking.window_start,
                TelegramDiscoveryRanking.window_end,
                TelegramDiscoveryRanking.mention_count,
                TelegramDiscoveryRanking.rank,
            )
            .where(TelegramDiscoveryRanking.candidate_token_id == token.id)
            .order_by(desc(TelegramDiscoveryRanking.window_end))
            .limit(5)
        )
        rankings_list = [
            {
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                "mention_count": r.mention_count,
                "rank": r.rank,
            }
            for r in rank_history.all()
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
            "total_mentions": stats.total,
            "unique_users": stats.users,
            "group_count": stats.groups,
            "recent_mentions": recent_mentions,
            "rankings": rankings_list,
        }
