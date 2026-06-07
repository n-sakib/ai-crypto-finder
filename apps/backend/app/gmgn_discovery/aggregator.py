"""
GMGN Discovery Aggregator — ranks and returns GMGN tokens.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.gmgn_discovery.models import GMGNToken, GMGNDiscoveryRanking
from app.gmgn_discovery.schemas import GMGNDiscoveryItem, GMGNDiscoveryResponse

logger = logging.getLogger(__name__)


def parse_window(window_str: str) -> timedelta:
    """Parse window string like '15m', '1h', '6h', '24h' to timedelta."""
    unit = window_str[-1]
    value = int(window_str[:-1])
    if unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    return timedelta(hours=1)


class GMGNDiscoveryAggregator:
    """Ranks GMGN tokens by composite score."""

    def __init__(self, min_volume: float = 0):
        self.min_volume = min_volume

    async def rank(
        self,
        session: AsyncSession,
        window: str = "1h",
        limit: int = 50,
    ) -> GMGNDiscoveryResponse:
        window_delta = parse_window(window)
        now = datetime.now(timezone.utc)
        window_start = now - window_delta
        window_end = now

        # Rank: score = volume_24h * 0.4 + swaps * 0.3 + net_volume * 0.2 + price_change_5m * 0.1
        query = (
            select(GMGNToken)
            .where(
                GMGNToken.last_seen_at >= window_start,
                GMGNToken.last_seen_at < window_end,
            )
            .where(GMGNToken.volume_24h >= self.min_volume)
            .order_by(
                desc(
                    func.coalesce(GMGNToken.volume_24h, 0) * 0.4 +
                    func.coalesce(GMGNToken.swaps_24h, 0) * 0.3 +
                    func.coalesce(GMGNToken.net_volume_24h, 0) * 0.2 +
                    func.coalesce(GMGNToken.price_change_5m, 0) * 0.1
                )
            )
            .limit(limit)
        )
        result = await session.execute(query)
        tokens = result.scalars().all()

        items: list[GMGNDiscoveryItem] = []
        for rank_idx, token in enumerate(tokens, start=1):
            score = (
                (token.volume_24h or 0) * 0.4 +
                (token.swaps_24h or 0) * 0.3 +
                (token.net_volume_24h or 0) * 0.2 +
                (token.price_change_5m or 0) * 0.1
            )
            items.append(GMGNDiscoveryItem(
                rank=rank_idx,
                chain=token.chain,
                token_address=token.token_address,
                symbol=token.symbol,
                name=token.name,
                score=round(score, 2),
                volume_24h=token.volume_24h,
                price_change_24h=token.price_change_24h,
                price_change_5m=token.price_change_5m,
                market_cap=token.market_cap,
                liquidity=token.liquidity,
                holders=token.holders,
                swaps_24h=token.swaps_24h,
                buys_24h=token.buys_24h,
                sells_24h=token.sells_24h,
                net_volume_24h=token.net_volume_24h,
                gmgn_score=token.gmgn_score,
                hot_level=token.hot_level,
                dex_url=token.dex_url,
                pair_address=token.pair_address,
                price_usd=token.price_usd,
                fdv=token.fdv,
                first_seen_at=token.first_seen_at,
                last_seen_at=token.last_seen_at,
            ))

        return GMGNDiscoveryResponse(
            window=window,
            window_start=window_start,
            window_end=window_end,
            total_tokens=len(items),
            generated_at=now,
            tokens=items,
        )
