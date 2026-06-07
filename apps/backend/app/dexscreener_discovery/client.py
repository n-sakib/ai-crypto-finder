"""
DexScreener API Client — fetches boosted/latest tokens and pair data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _parse_timestamp(ts) -> Optional[datetime]:
    """Parse DexScreener timestamp (Unix ms integer) to datetime."""
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return None
    except (ValueError, OSError):
        return None

DEXSCREENER_API = "https://api.dexscreener.com"
BOOSTS_URL = f"{DEXSCREENER_API}/token-boosts/latest/v1"
TOKEN_PAIRS_URL = f"{DEXSCREENER_API}/tokens/v1"


class DexScreenerClient:
    """Client for DexScreener token boosts and pair data."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_boosted_tokens(self) -> list[dict]:
        """Fetch currently boosted tokens from DexScreener. Returns list with tokenAddress, chainId, url, amount."""
        client = await self._get_client()
        try:
            resp = await client.get(BOOSTS_URL)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error("DexScreener boosts fetch failed: %s", e)
            return []

    async def fetch_token_pairs(self, chain: str, token_address: str) -> list[dict]:
        """Fetch pair data for a specific token from DexScreener."""
        client = await self._get_client()
        try:
            url = f"{TOKEN_PAIRS_URL}/{chain}/{token_address}"
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json() if isinstance(resp.json(), list) else []
        except Exception as e:
            logger.debug("DexScreener pair fetch for %s failed: %s", token_address[:12], e)
            return []

    @staticmethod
    def normalize_boost(raw: dict) -> dict:
        """Normalize boosted token data (basic profile only)."""
        return {
            "chain": raw.get("chainId", "unknown"),
            "token_address": raw.get("tokenAddress", ""),
            "symbol": None,
            "name": None,
            "dex_url": raw.get("url"),
            "is_boosted": True,
            "total_boosts": raw.get("totalAmount", 0),
            "boost_amount": raw.get("amount", 0),
        }

    @staticmethod
    def normalize_pair(raw: dict) -> dict:
        """Normalize DexScreener pair data with full metrics."""
        base = raw.get("baseToken", {})
        return {
            "chain": raw.get("chainId", "unknown"),
            "token_address": base.get("address", ""),
            "symbol": base.get("symbol"),
            "name": base.get("name"),
            "pair_address": raw.get("pairAddress"),
            "dex_url": raw.get("url"),
            "dex_id": raw.get("dexId"),
            "price_usd": float(raw.get("priceUsd", 0) or 0),
            "price_change_5m": raw.get("priceChange", {}).get("m5"),
            "price_change_1h": raw.get("priceChange", {}).get("h1"),
            "price_change_6h": raw.get("priceChange", {}).get("h6"),
            "price_change_24h": raw.get("priceChange", {}).get("h24"),
            "volume_5m": raw.get("volume", {}).get("m5"),
            "volume_1h": raw.get("volume", {}).get("h1"),
            "volume_6h": raw.get("volume", {}).get("h6"),
            "volume_24h": raw.get("volume", {}).get("h24"),
            "txns_5m_buys": raw.get("txns", {}).get("m5", {}).get("buys"),
            "txns_5m_sells": raw.get("txns", {}).get("m5", {}).get("sells"),
            "txns_1h_buys": raw.get("txns", {}).get("h1", {}).get("buys"),
            "txns_1h_sells": raw.get("txns", {}).get("h1", {}).get("sells"),
            "liquidity_usd": raw.get("liquidity", {}).get("usd"),
            "market_cap": raw.get("marketCap"),
            "fdv": raw.get("fdv"),
            "pair_created_at": _parse_timestamp(raw.get("pairCreatedAt")),
            "is_boosted": False,
            "total_boosts": 0,
            "boost_amount": 0,
        }

    def merge_boost_with_pair(self, boost: dict, pair: dict | None) -> dict:
        """Merge boost data into pair data. If no pair, use boost profile only."""
        norm = self.normalize_boost(boost)
        if pair:
            pnorm = self.normalize_pair(pair)
            # Merge: boost flags take priority
            pnorm["is_boosted"] = True
            pnorm["total_boosts"] = norm["total_boosts"]
            pnorm["boost_amount"] = norm["boost_amount"]
            # Fill in name/symbol from pair if available
            norm = pnorm
        return norm
