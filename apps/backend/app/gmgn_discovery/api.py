"""
GMGN Discovery API Routes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.gmgn_discovery.aggregator import GMGNDiscoveryAggregator
from app.gmgn_discovery.client import GMGNClient
from app.gmgn_discovery.models import GMGNToken
from app.gmgn_discovery.schemas import GMGNDiscoveryResponse, GMGNStats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gmgn", tags=["gmgn"])

_COLLECT_LOCK = asyncio.Lock()


@router.get("/discovery", response_model=GMGNDiscoveryResponse)
async def get_gmgn_discovery(
    window: str = Query("1h", description="Time window: 30m, 1h, 6h, 24h"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get top tokens discovered from GMGN."""
    aggregator = GMGNDiscoveryAggregator()
    return await aggregator.rank(session, window=window, limit=limit)


@router.get("/discovery/stats", response_model=GMGNStats)
async def get_gmgn_stats(
    session: AsyncSession = Depends(get_session),
):
    """Get GMGN discovery stats."""
    total = await session.scalar(select(func.count(GMGNToken.id)))
    latest = await session.scalar(select(func.max(GMGNToken.last_seen_at)))
    return GMGNStats(
        total_tokens=total or 0,
        latest_token_at=latest,
        generated_at=datetime.now(timezone.utc),
    )


@router.post("/collect")
async def trigger_gmgn_collect(
    session: AsyncSession = Depends(get_session),
):
    """Trigger GMGN token collection (trending + new pairs)."""
    if _COLLECT_LOCK.locked():
        return {"status": "already_running"}

    async def do_collect():
        async with _COLLECT_LOCK:
            client = GMGNClient()
            try:
                # Fetch trending
                trending = await client.fetch_trending(limit=50)
                logger.info("GMGN trending: fetched %d tokens", len(trending))

                # Fetch new pairs
                new_pairs = await client.fetch_new_pairs(limit=50)
                logger.info("GMGN new pairs: fetched %d tokens", len(new_pairs))

                all_raw = trending + new_pairs
                now = datetime.now(timezone.utc)
                upserted = 0

                for raw in all_raw:
                    norm = GMGNClient.normalize_token(raw)
                    addr = norm.get("token_address")
                    if not addr:
                        continue

                    # Upsert token
                    existing = (await session.execute(
                        select(GMGNToken).where(
                            GMGNToken.chain == norm["chain"],
                            GMGNToken.token_address == addr,
                        )
                    )).scalar_one_or_none()

                    if existing:
                        # Update metrics
                        for key in [
                            "volume_24h", "price_change_24h", "price_change_5m",
                            "price_change_1h", "market_cap", "liquidity",
                            "holders", "swaps_24h", "buys_24h", "sells_24h",
                            "buy_volume_24h", "sell_volume_24h", "net_volume_24h",
                            "gmgn_score", "hot_level", "price_usd", "fdv",
                            "symbol", "name",
                        ]:
                            if norm.get(key) is not None:
                                setattr(existing, key, norm[key])
                        existing.last_seen_at = now
                    else:
                        token = GMGNToken(
                            chain=norm["chain"],
                            token_address=addr,
                            symbol=norm.get("symbol"),
                            name=norm.get("name"),
                            volume_24h=norm.get("volume_24h"),
                            price_change_24h=norm.get("price_change_24h"),
                            price_change_5m=norm.get("price_change_5m"),
                            price_change_1h=norm.get("price_change_1h"),
                            market_cap=norm.get("market_cap"),
                            liquidity=norm.get("liquidity"),
                            holders=norm.get("holders"),
                            swaps_24h=norm.get("swaps_24h"),
                            buys_24h=norm.get("buys_24h"),
                            sells_24h=norm.get("sells_24h"),
                            buy_volume_24h=norm.get("buy_volume_24h"),
                            sell_volume_24h=norm.get("sell_volume_24h"),
                            net_volume_24h=norm.get("net_volume_24h"),
                            gmgn_score=norm.get("gmgn_score"),
                            hot_level=norm.get("hot_level"),
                            price_usd=norm.get("price_usd"),
                            fdv=norm.get("fdv"),
                            first_seen_at=now,
                            last_seen_at=now,
                        )
                        session.add(token)
                    upserted += 1

                await session.commit()
                logger.info("GMGN collect: upserted %d tokens", upserted)
                return {"status": "done", "tokens_upserted": upserted}
            except Exception as e:
                logger.error("GMGN collect failed: %s", e, exc_info=True)
                await session.rollback()
                return {"status": "error", "error": str(e)}
            finally:
                await client.close()

    asyncio.create_task(do_collect())
    return {"status": "collecting"}
