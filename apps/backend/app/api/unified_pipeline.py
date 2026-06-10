"""Unified Pipeline API Routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession
import json

from app.core.database import get_session
from app.core.models import UnifiedToken
from app.services.unified_pipeline import pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_PIPELINE_LOCK = asyncio.Lock()
_pipeline_status: dict = {"status": "idle", "step": "", "detail": "", "tokens": 0}
_stop_requested = False


@router.get("/status")
async def get_pipeline_status():
    """Get current pipeline run status."""
    return _pipeline_status


@router.post("/stop")
async def stop_pipeline():
    """Request the running pipeline to stop."""
    global _stop_requested
    if _PIPELINE_LOCK.locked():
        _stop_requested = True
        _pipeline_status["status"] = "stopping"
        _pipeline_status["detail"] = "Stop requested..."
        return {"status": "stopping"}
    return {"status": "not_running"}


@router.post("/run")
async def run_pipeline(window: str = Query("24h", description="Time window: 5m, 1h, 6h, 24h")):
    """Run the unified pipeline for a specific time window."""
    if window not in ("5m", "1h", "6h", "24h"):
        return {"status": "error", "detail": f"Invalid window: {window}. Use 5m, 1h, 6h, or 24h."}
    if _PIPELINE_LOCK.locked():
        return {"status": "already_running"}

    async def do_run():
        global _pipeline_status, _stop_requested
        _stop_requested = False
        async with _PIPELINE_LOCK:
            from app.core.database import async_session_factory

            def update_step(step: str, detail: str = "", tokens: int | None = None, total: int | None = None):
                previous_step = _pipeline_status.get("step")
                _pipeline_status["step"] = step
                _pipeline_status["detail"] = detail
                if tokens is not None:
                    _pipeline_status["tokens"] = tokens
                elif previous_step != step:
                    _pipeline_status["tokens"] = 0
                if total is not None:
                    _pipeline_status["total"] = total
                elif previous_step != step:
                    _pipeline_status.pop("total", None)

            async with async_session_factory() as session:
                try:
                    _pipeline_status = {"status": "running", "step": "init", "detail": f"Running pipeline for {window} window...", "tokens": 0}
                    result = await pipeline.run(session, window=window, status_callback=update_step,
                                                should_stop=lambda: _stop_requested)
                    if _stop_requested:
                        _pipeline_status = {"status": "idle", "step": "", "detail": "Pipeline stopped.", "tokens": 0}
                    elif not result:
                        _pipeline_status = {"status": "idle", "step": "", "detail": "No tokens found.", "tokens": 0}
                    else:
                        _pipeline_status = {
                            "status": "done",
                            "step": "complete",
                            "detail": f"Pipeline complete ({window}): {len(result)} tokens",
                            "tokens": len(result),
                    }
                except Exception as e:
                    logger.error("Pipeline failed: %s", e, exc_info=True)
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                    _pipeline_status = {"status": "error", "step": "", "detail": str(e), "tokens": 0}

    asyncio.create_task(do_run())
    return {"status": "started"}


@router.get("/results")
async def get_pipeline_results(
    sort_by: str = Query("rank", description="rank, volume, mentions, score"),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """Get pipeline results — ranked tokens with full windowed data."""
    order_map = {
        "rank": UnifiedToken.rank.asc(),
        "score": desc(UnifiedToken.composite_score),
        "volume": desc(func.coalesce(UnifiedToken.volume_24h, 0)),
        "mentions": desc(func.coalesce(UnifiedToken.tg_mentions_24h, 0)),
    }
    order = order_map.get(sort_by, UnifiedToken.rank.asc())

    result = await session.execute(
        select(UnifiedToken).order_by(order).limit(limit)
    )
    tokens = result.scalars().all()

    # Get actual total count (not limited)
    total_result = await session.execute(
        select(func.count()).select_from(UnifiedToken)
    )
    actual_total = total_result.scalar() or 0

    return {
        "total": actual_total,
        "pipeline_status": _pipeline_status,
        "tokens": [
            {
                "rank": t.rank, "chain": t.chain, "token_address": t.token_address,
                "symbol": t.symbol, "name": t.name,
                "dex_url": t.dex_url, "pair_address": t.pair_address,
                "gmgn_score": t.gmgn_score, "gmgn_hot_level": t.gmgn_hot_level,
                "is_dexscreener_trending": t.is_dexscreener_trending or False,
                "is_dexscreener_boosted": t.is_dexscreener_boosted or False,
                "is_gmgn_trending": t.is_gmgn_trending or False,
                "dexscreener_trending_rank": t.dexscreener_trending_rank,
                "dexscreener_boost_amount": t.dexscreener_boost_amount,
                "dexscreener_boost_total": t.dexscreener_boost_total,
                "gmgn_trending_rank": t.gmgn_trending_rank,
                "gmgn_kol_count": t.gmgn_kol_count or 0,
                "gmgn_kol_buy_count": t.gmgn_kol_buy_count or 0,
                "gmgn_kol_total_amount_usd": t.gmgn_kol_total_amount_usd or 0,
                "gmgn_kol_last_buy_at": t.gmgn_kol_last_buy_at.isoformat() if t.gmgn_kol_last_buy_at else None,
                "gmgn_kol_wallets": t.gmgn_kol_wallets or [],
                "composite_score": t.composite_score,
                "source_groups": t.source_groups or [],
                "group_count": t.group_count or 0,
                "discovery_methods": t.discovery_methods or [],
                "windows": {
                    "5m": {
                        "price": t.price_5m, "price_change": t.price_change_5m,
                        "volume": t.volume_5m, "buys": t.buys_5m, "sells": t.sells_5m,
                        "trades": t.trades_5m, "liquidity": t.liquidity_5m,
                        "market_cap": t.market_cap_5m,
                        "telegram": {
                            "mentions": t.tg_mentions_5m, "users": t.tg_users_5m,
                            "groups": t.tg_groups_5m, "reactions": t.tg_reactions_5m,
                            "replies": t.tg_replies_5m,
                        },
                    },
                    "1h": {
                        "price": t.price_1h, "price_change": t.price_change_1h,
                        "volume": t.volume_1h, "buys": t.buys_1h, "sells": t.sells_1h,
                        "trades": t.trades_1h, "liquidity": t.liquidity_1h,
                        "market_cap": t.market_cap_1h,
                        "telegram": {
                            "mentions": t.tg_mentions_1h, "users": t.tg_users_1h,
                            "groups": t.tg_groups_1h, "reactions": t.tg_reactions_1h,
                            "replies": t.tg_replies_1h,
                        },
                    },
                    "6h": {
                        "price": t.price_6h, "price_change": t.price_change_6h,
                        "volume": t.volume_6h, "buys": t.buys_6h, "sells": t.sells_6h,
                        "trades": t.trades_6h, "liquidity": t.liquidity_6h,
                        "market_cap": t.market_cap_6h,
                        "telegram": {
                            "mentions": t.tg_mentions_6h, "users": t.tg_users_6h,
                            "groups": t.tg_groups_6h, "reactions": t.tg_reactions_6h,
                            "replies": t.tg_replies_6h,
                        },
                    },
                    "24h": {
                        "price": t.price_24h, "price_change": t.price_change_24h,
                        "volume": t.volume_24h, "buys": t.buys_24h, "sells": t.sells_24h,
                        "trades": t.trades_24h, "liquidity": t.liquidity_24h,
                        "market_cap": t.market_cap_24h,
                        "telegram": {
                            "mentions": t.tg_mentions_24h, "users": t.tg_users_24h,
                            "groups": t.tg_groups_24h, "reactions": t.tg_reactions_24h,
                            "replies": t.tg_replies_24h,
                        },
                    },
                },
                "first_seen_at": t.first_seen_at.isoformat() if t.first_seen_at else None,
                "last_seen_at": t.last_seen_at.isoformat() if t.last_seen_at else None,
                "pipeline_run_at": t.pipeline_run_at.isoformat() if t.pipeline_run_at else None,
            }
            for t in tokens
        ],
    }


@router.delete("/results")
async def clear_pipeline_results(session: AsyncSession = Depends(get_session)):
    """Clear all pipeline results from the database."""
    result = await session.execute(delete(UnifiedToken))
    await session.commit()
    count = result.rowcount
    logger.info("Cleared %d pipeline tokens from database", count)
    return {"status": "cleared", "deleted": count}
