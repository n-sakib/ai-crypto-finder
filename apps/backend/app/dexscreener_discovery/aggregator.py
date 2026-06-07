"""DexScreener Discovery Aggregator."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dexscreener_discovery.models import DexScreenerToken
from app.dexscreener_discovery.schemas import DexScreenerDiscoveryItem, DexScreenerDiscoveryResponse

logger = logging.getLogger(__name__)


def parse_window(window_str: str) -> timedelta:
    unit = window_str[-1]
    value = int(window_str[:-1])
    if unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    return timedelta(hours=1)


class DexScreenerDiscoveryAggregator:
    def __init__(self, min_volume: float = 0):
        self.min_volume = min_volume

    async def rank(
        self,
        session: AsyncSession,
        window: str = "1h",
        limit: int = 50,
    ) -> DexScreenerDiscoveryResponse:
        window_delta = parse_window(window)
        now = datetime.now(timezone.utc)
        window_start = now - window_delta
        window_end = now

        # Boosted tokens first, then by volume
        query = (
            select(DexScreenerToken)
            .where(
                DexScreenerToken.last_seen_at >= window_start,
                DexScreenerToken.last_seen_at < window_end,
            )
            .where(DexScreenerToken.volume_24h >= self.min_volume)
            .order_by(
                desc(DexScreenerToken.is_boosted),
                desc(func.coalesce(DexScreenerToken.volume_5m, 0)),
                desc(func.coalesce(DexScreenerToken.volume_24h, 0)),
            )
            .limit(limit)
        )
        result = await session.execute(query)
        tokens = result.scalars().all()

        items = []
        for rank_idx, token in enumerate(tokens, start=1):
            score = (
                (token.volume_24h or 0) * 0.4 +
                (token.txns_5m_buys or 0) * 0.3 +
                (token.liquidity_usd or 0) * 0.2 +
                (10 if token.is_boosted else 0)
            )
            items.append(DexScreenerDiscoveryItem(
                rank=rank_idx,
                chain=token.chain,
                token_address=token.token_address,
                symbol=token.symbol,
                name=token.name,
                score=round(score, 2),
                pair_address=token.pair_address,
                dex_url=token.dex_url,
                dex_id=token.dex_id,
                price_usd=token.price_usd,
                price_change_5m=token.price_change_5m,
                price_change_1h=token.price_change_1h,
                price_change_6h=token.price_change_6h,
                price_change_24h=token.price_change_24h,
                volume_5m=token.volume_5m,
                volume_1h=token.volume_1h,
                volume_6h=token.volume_6h,
                volume_24h=token.volume_24h,
                txns_5m_buys=token.txns_5m_buys,
                txns_5m_sells=token.txns_5m_sells,
                txns_1h_buys=token.txns_1h_buys,
                txns_1h_sells=token.txns_1h_sells,
                liquidity_usd=token.liquidity_usd,
                market_cap=token.market_cap,
                fdv=token.fdv,
                total_boosts=token.total_boosts,
                boost_amount=token.boost_amount,
                is_boosted=token.is_boosted or False,
                pair_created_at=token.pair_created_at,
                first_seen_at=token.first_seen_at,
                last_seen_at=token.last_seen_at,
            ))

        return DexScreenerDiscoveryResponse(
            window=window,
            window_start=window_start,
            window_end=window_end,
            total_tokens=len(items),
            generated_at=now,
            tokens=items,
        )
