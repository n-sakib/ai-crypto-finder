"""
GMGN API Client — fetches trending and new tokens from gmgn.ai.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from app.config import settings

logger = logging.getLogger(__name__)

GMGN_BASE_URL = "https://gmgn.ai"
GMGN_TRENDING_URL = f"{GMGN_BASE_URL}/defi/router/v1/sol/txns/trending"
GMGN_NEW_PAIRS_URL = f"{GMGN_BASE_URL}/defi/router/v1/sol/new_pairs"
GMGN_TOKEN_INFO_URL = f"{GMGN_BASE_URL}/defi/router/v1/sol/token_info"


class GMGNClient:
    """Client for fetching trending/new tokens from GMGN API."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Origin": "https://gmgn.ai",
                    "Referer": "https://gmgn.ai/",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_trending(self, limit: int = 50) -> list[dict]:
        """
        Fetch trending tokens from GMGN.

        Returns list of token dicts with:
          - address, symbol, name, chain
          - market_cap, liquidity, volume_24h
          - price_change (5m, 1h, 24h)
          - swaps, buys, sells
          - hot_level, score
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                GMGN_TRENDING_URL,
                params={"limit": limit, "orderby": "swaps", "direction": "desc"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("rank", [])
            logger.warning("GMGN trending API returned code=%s msg=%s", data.get("code"), data.get("msg"))
            return []
        except Exception as e:
            logger.error("Failed to fetch GMGN trending: %s", e)
            return []

    async def fetch_new_pairs(self, limit: int = 50) -> list[dict]:
        """Fetch recently created token pairs from GMGN."""
        client = await self._get_client()
        try:
            resp = await client.get(
                GMGN_NEW_PAIRS_URL,
                params={"limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("pairs", [])
            return []
        except Exception as e:
            logger.error("Failed to fetch GMGN new pairs: %s", e)
            return []

    @staticmethod
    def normalize_token(raw: dict) -> dict:
        """Normalize GMGN token data to our internal format."""
        return {
            "chain": raw.get("chain", "solana"),
            "token_address": raw.get("address", ""),
            "symbol": raw.get("symbol"),
            "name": raw.get("name"),
            "market_cap": raw.get("market_cap"),
            "liquidity": raw.get("liquidity"),
            "volume_24h": raw.get("volume_24h") or raw.get("volume"),
            "price_change_24h": raw.get("price_change_24h") or raw.get("price_change", {}).get("h24"),
            "price_change_5m": raw.get("price_change_5m") or raw.get("price_change", {}).get("m5"),
            "price_change_1h": raw.get("price_change_1h") or raw.get("price_change", {}).get("h1"),
            "holders": raw.get("holders") or raw.get("holder_count"),
            "swaps_24h": raw.get("swaps_24h") or raw.get("swaps"),
            "buys_24h": raw.get("buys_24h") or raw.get("buys"),
            "sells_24h": raw.get("sells_24h") or raw.get("sells"),
            "buy_volume_24h": raw.get("buy_volume_24h") or raw.get("buy_volume"),
            "sell_volume_24h": raw.get("sell_volume_24h") or raw.get("sell_volume"),
            "net_volume_24h": raw.get("net_volume_24h") or raw.get("net_volume"),
            "gmgn_score": raw.get("score") or raw.get("hot_score"),
            "hot_level": raw.get("hot_level"),
            "price_usd": raw.get("price_usd") or raw.get("price"),
            "fdv": raw.get("fdv"),
        }
