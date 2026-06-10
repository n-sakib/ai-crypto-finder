"""
GMGN Discovery API Routes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.gmgn_discovery.aggregator import GMGNDiscoveryAggregator
from app.gmgn_discovery.client import GMGNClient
from app.gmgn_discovery.models import GMGNToken
from app.gmgn_discovery.schemas import GMGNDiscoveryResponse, GMGNKOLClustersResponse, GMGNStats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gmgn", tags=["gmgn"])

_COLLECT_LOCK = asyncio.Lock()
_KOL_WINDOWS = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
}
_NATIVE_TOKEN_ADDRESSES = {
    "sol": {"So11111111111111111111111111111111111111112"},
}


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _trade_time(raw: dict) -> datetime | None:
    timestamp = raw.get("timestamp")
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _token_name(token: dict) -> str | None:
    return token.get("name") or token.get("symbol")


def _build_kol_clusters(
    trades: list[dict],
    *,
    chain: str,
    window: str,
    min_buyers: int,
) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - _KOL_WINDOWS[window]
    native_addresses = _NATIVE_TOKEN_ADDRESSES.get(chain, set())
    clusters: dict[str, dict] = {}
    buy_trades = 0

    for raw in trades:
        if str(raw.get("side", "")).lower() != "buy":
            continue
        bought_at = _trade_time(raw)
        if not bought_at or bought_at < cutoff:
            continue

        token_address = raw.get("base_address")
        if not token_address or token_address in native_addresses:
            continue

        maker = raw.get("maker")
        if not maker:
            continue

        buy_trades += 1
        token = raw.get("base_token") or {}
        maker_info = raw.get("maker_info") or {}
        amount_usd = _as_float(raw.get("amount_usd"))
        bucket = clusters.setdefault(
            token_address,
            {
                "token_address": token_address,
                "symbol": token.get("symbol"),
                "name": _token_name(token),
                "logo": token.get("logo"),
                "launchpad": token.get("launchpad"),
                "kol_wallets": {},
                "trades": [],
                "buy_count": 0,
                "total_amount_usd": 0.0,
                "last_buy_at": bought_at,
            },
        )
        bucket["buy_count"] += 1
        bucket["total_amount_usd"] += amount_usd
        bucket["last_buy_at"] = max(bucket["last_buy_at"], bought_at)

        wallet = bucket["kol_wallets"].setdefault(
            maker,
            {
                "maker": maker,
                "twitter_username": maker_info.get("twitter_username"),
                "twitter_name": maker_info.get("twitter_name"),
                "tags": maker_info.get("tags") or [],
                "amount_usd": 0.0,
                "buy_count": 0,
                "last_buy_at": bought_at,
            },
        )
        wallet["amount_usd"] += amount_usd
        wallet["buy_count"] += 1
        wallet["last_buy_at"] = max(wallet["last_buy_at"], bought_at)

        bucket["trades"].append(
            {
                "transaction_hash": raw.get("transaction_hash"),
                "maker": maker,
                "twitter_username": maker_info.get("twitter_username"),
                "twitter_name": maker_info.get("twitter_name"),
                "amount_usd": amount_usd,
                "price_usd": _as_float(raw.get("price_usd")) if raw.get("price_usd") is not None else None,
                "bought_at": bought_at,
            }
        )

    results = []
    for bucket in clusters.values():
        wallets = sorted(
            bucket["kol_wallets"].values(),
            key=lambda wallet: (wallet["amount_usd"], wallet["last_buy_at"]),
            reverse=True,
        )
        if len(wallets) < min_buyers:
            continue
        trades_recent = sorted(bucket["trades"], key=lambda trade: trade["bought_at"], reverse=True)[:10]
        results.append(
            {
                "token_address": bucket["token_address"],
                "symbol": bucket["symbol"],
                "name": bucket["name"],
                "logo": bucket["logo"],
                "launchpad": bucket["launchpad"],
                "kol_count": len(wallets),
                "buy_count": bucket["buy_count"],
                "total_amount_usd": round(bucket["total_amount_usd"], 2),
                "last_buy_at": bucket["last_buy_at"],
                "kol_wallets": wallets,
                "trades": trades_recent,
            }
        )

    results.sort(key=lambda item: (item["kol_count"], item["total_amount_usd"], item["last_buy_at"]), reverse=True)
    return {
        "chain": chain,
        "window": window,
        "generated_at": now,
        "total_trades": len(trades),
        "total_buy_trades": buy_trades,
        "clusters": results,
    }


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


@router.get("/kol-clusters", response_model=GMGNKOLClustersResponse)
async def get_gmgn_kol_clusters(
    chain: str = Query("sol", pattern="^(sol|eth|bsc|base)$"),
    window: str = Query("30m", description="Time window: 5m, 15m, 30m, 1h, 6h, 24h"),
    limit: int = Query(200, ge=1, le=200),
    min_buyers: int = Query(2, ge=1, le=20),
):
    """Group GMGN renowned/KOL buys by token to show coins KOLs bought together."""
    if window not in _KOL_WINDOWS:
        raise HTTPException(status_code=400, detail=f"Unsupported window: {window}")

    client = GMGNClient()
    try:
        trades = await client.fetch_kol_trades(chain=chain, limit=limit)
        return _build_kol_clusters(trades, chain=chain, window=window, min_buyers=min_buyers)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            reset = exc.response.headers.get("X-RateLimit-Reset")
            detail = "GMGN rate limit exceeded"
            if reset:
                detail = f"{detail}; retry after {reset}"
            raise HTTPException(status_code=429, detail=detail) from exc
        logger.error("GMGN KOL fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="GMGN KOL feed is unavailable") from exc


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
