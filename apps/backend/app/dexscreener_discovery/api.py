"""DexScreener Discovery API Routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.dexscreener_discovery.aggregator import DexScreenerDiscoveryAggregator
from app.dexscreener_discovery.client import DexScreenerClient
from app.dexscreener_discovery.models import DexScreenerToken
from app.dexscreener_discovery.schemas import DexScreenerDiscoveryResponse, DexScreenerStats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dexscreener", tags=["dexscreener"])

_COLLECT_LOCK = asyncio.Lock()


@router.get("/discovery", response_model=DexScreenerDiscoveryResponse)
async def get_dexscreener_discovery(
    window: str = Query("1h", description="Time window"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    aggregator = DexScreenerDiscoveryAggregator()
    return await aggregator.rank(session, window=window, limit=limit)


@router.get("/discovery/stats", response_model=DexScreenerStats)
async def get_dexscreener_stats(
    session: AsyncSession = Depends(get_session),
):
    total = await session.scalar(select(func.count(DexScreenerToken.id)))
    boosted = await session.scalar(
        select(func.count(DexScreenerToken.id)).where(DexScreenerToken.is_boosted == True)
    )
    latest = await session.scalar(select(func.max(DexScreenerToken.last_seen_at)))
    return DexScreenerStats(
        total_tokens=total or 0,
        boosted_tokens=boosted or 0,
        latest_token_at=latest,
        generated_at=datetime.now(timezone.utc),
    )


@router.post("/collect")
async def trigger_dexscreener_collect(
    session: AsyncSession = Depends(get_session),
):
    if _COLLECT_LOCK.locked():
        return {"status": "already_running"}

    async def do_collect():
        async with _COLLECT_LOCK:
            client = DexScreenerClient()
            try:
                boosted = await client.fetch_boosted_tokens()
                logger.info("DexScreener boosted: fetched %d", len(boosted))

                now = datetime.now(timezone.utc)
                upserted = 0

                for boost in boosted[:30]:  # limit to 30 to avoid rate limits
                    chain = boost.get("chainId", "solana")
                    addr = boost.get("tokenAddress", "")
                    if not addr:
                        continue

                    # Try to get pair data for price/volume metrics
                    pairs = await client.fetch_token_pairs(chain, addr)
                    pair = pairs[0] if pairs else None

                    norm = client.merge_boost_with_pair(boost, pair)
                    if not addr:
                        continue

                    existing = (await session.execute(
                        select(DexScreenerToken).where(
                            DexScreenerToken.chain == norm["chain"],
                            DexScreenerToken.token_address == addr,
                        )
                    )).scalar_one_or_none()

                    if existing:
                        for key in [
                            "symbol", "name", "pair_address", "dex_url", "dex_id",
                            "price_usd", "price_change_5m", "price_change_1h",
                            "price_change_6h", "price_change_24h",
                            "volume_5m", "volume_1h", "volume_6h", "volume_24h",
                            "txns_5m_buys", "txns_5m_sells", "txns_1h_buys",
                            "txns_1h_sells", "liquidity_usd", "market_cap", "fdv",
                            "total_boosts", "boost_amount", "is_boosted",
                        ]:
                            if norm.get(key) is not None:
                                setattr(existing, key, norm[key])
                        existing.last_seen_at = now
                    else:
                        token = DexScreenerToken(
                            chain=norm["chain"],
                            token_address=addr,
                            symbol=norm.get("symbol"),
                            name=norm.get("name"),
                            pair_address=norm.get("pair_address"),
                            dex_url=norm.get("dex_url"),
                            dex_id=norm.get("dex_id"),
                            price_usd=norm.get("price_usd"),
                            price_change_5m=norm.get("price_change_5m"),
                            price_change_1h=norm.get("price_change_1h"),
                            price_change_6h=norm.get("price_change_6h"),
                            price_change_24h=norm.get("price_change_24h"),
                            volume_5m=norm.get("volume_5m"),
                            volume_1h=norm.get("volume_1h"),
                            volume_6h=norm.get("volume_6h"),
                            volume_24h=norm.get("volume_24h"),
                            txns_5m_buys=norm.get("txns_5m_buys"),
                            txns_5m_sells=norm.get("txns_5m_sells"),
                            txns_1h_buys=norm.get("txns_1h_buys"),
                            txns_1h_sells=norm.get("txns_1h_sells"),
                            liquidity_usd=norm.get("liquidity_usd"),
                            market_cap=norm.get("market_cap"),
                            fdv=norm.get("fdv"),
                            total_boosts=norm.get("total_boosts"),
                            boost_amount=norm.get("boost_amount"),
                            is_boosted=norm.get("is_boosted", False),
                            pair_created_at=norm.get("pair_created_at"),
                            first_seen_at=now,
                            last_seen_at=now,
                        )
                        session.add(token)
                    upserted += 1

                await session.commit()
                logger.info("DexScreener collect: upserted %d tokens", upserted)
                return {"status": "done", "tokens_upserted": upserted}
            except Exception as e:
                logger.error("DexScreener collect failed: %s", e, exc_info=True)
                await session.rollback()
                return {"status": "error", "error": str(e)}
            finally:
                await client.close()

    asyncio.create_task(do_collect())
    return {"status": "collecting"}
