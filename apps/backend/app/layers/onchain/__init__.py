"""
On-Chain Data Layer — Holder data from GMGN + DEXScreener LP proxy.

GMGN (openapi.gmgn.ai) — sol, eth, bsc, base — holder_count + top_10_holder_rate
DEXScreener LP — all chains — top holder % proxy via LP token share

No Moralis, no Etherscan. Just GMGN + DEXScreener + public RPC.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

import httpx

from app.config import settings

# ── GMGN ─────────────────────────────────────────────────────────────

GMGN_BASE = "https://openapi.gmgn.ai"
GMGN_CHAINS: dict[str, str] = {
    "solana": "sol", "ethereum": "eth", "bsc": "bsc", "base": "base",
}
# GMGN free tier: max 3 concurrent, 0.5s between calls
GMGN_SEM = asyncio.Semaphore(3)
GMGN_DELAY = 0.5

# ── RPC URLs for LP balance check ────────────────────────────────────

RPC_URLS: dict[str, str] = {
    "ethereum": "https://eth.llamarpc.com",
    "bsc": "https://bsc-dataseed.binance.org",
    "polygon": "https://polygon-rpc.com",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "optimism": "https://mainnet.optimism.io",
    "base": "https://mainnet.base.org",
    "avalanche": "https://api.avax.network/ext/bc/C/rpc",
    "fantom": "https://rpcapi.fantom.network",
}

ERC20_TOTAL_SUPPLY = "0x18160ddd"
ERC20_BALANCE_OF = "0x70a08231"


class HolderData:
    """Holder data: GMGN + DEXScreener LP proxy."""

    def __init__(self):
        self._gmgn_key = settings.GMGN_API_KEY
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: dict[str, dict] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._gmgn_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def get_holders(self, chain: str, contract_address: str, pair_address: str = "") -> dict:
        empty = {"holder_count": 0, "meaningful_holders": 0, "top_holder_pct": 0.0}
        cache_key = f"{chain}:{contract_address}".lower()
        if cache_key in self._cache:
            return self._cache[cache_key]

        chain_lower = chain.lower()
        gmgn_chain = GMGN_CHAINS.get(chain_lower)

        # 1) Try GMGN for holder_count + top_10_holder_rate
        holder_count = 0
        top_pct = 0.0
        if self._gmgn_key and gmgn_chain:
            result = await self._fetch_gmgn(gmgn_chain, contract_address)
            holder_count = result.get("holder_count", 0) or 0
            top_pct = result.get("top_holder_pct", 0.0) or 0.0

        # 2) DEXScreener LP proxy — top holder % from LP pool share
        #    Only if GMGN didn't give us a top % AND we have a pair address
        if top_pct == 0.0 and pair_address and chain_lower in RPC_URLS:
            try:
                rpc = RPC_URLS[chain_lower]
                lp_pct = await self._lp_share(rpc, contract_address, pair_address)
                if lp_pct > 0:
                    top_pct = lp_pct
            except Exception:
                pass

        result = {
            "holder_count": holder_count,
            "meaningful_holders": holder_count,
            "top_holder_pct": round(min(top_pct, 100.0), 2),
        }
        self._cache[cache_key] = result
        return result

    # ── GMGN ────────────────────────────────────────────────────────

    async def _fetch_gmgn(self, gmgn_chain: str, address: str) -> dict:
        # Rate limit: max 3 concurrent, 0.5s spacing
        async with GMGN_SEM:
            await asyncio.sleep(GMGN_DELAY)
            client = await self._get_client()
            params = {
                "chain": gmgn_chain, "address": address,
                "timestamp": str(int(time.time())), "client_id": str(uuid.uuid4()),
            }
            try:
                resp = await client.get(
                    f"{GMGN_BASE}/v1/token/info", params=params,
                    headers={"X-APIKEY": self._gmgn_key},
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
            except Exception:
                return {"holder_count": 0, "top_holder_pct": 0.0}

        hc = int(data.get("holder_count", 0) or 0)
        dev = data.get("dev", {}) or {}
        tp = float(dev.get("top_10_holder_rate", 0) or 0) * 100
        return {"holder_count": hc, "top_holder_pct": tp}

    # ── DEXScreener LP proxy ────────────────────────────────────────

    async def _lp_share(self, rpc: str, token: str, pair: str) -> float:
        """
        Calculate what % of total supply is held by the LP pair.
        This is a rough proxy for top holder concentration.
        """
        client = await self._get_client()

        # Get total supply
        sup = await self._eth_call(rpc, token, ERC20_TOTAL_SUPPLY)
        total_supply = int(sup.get("result", "0x0") or "0x0", 16)
        if total_supply == 0:
            return 0.0

        # Get LP pair's token balance
        pair_addr = pair.lower().replace("0x", "").rjust(64, "0")
        bal = await self._eth_call(rpc, token, ERC20_BALANCE_OF + pair_addr)
        lp_balance = int(bal.get("result", "0x0") or "0x0", 16)

        return round((lp_balance / total_supply * 100), 2)

    async def _eth_call(self, rpc: str, to: str, data: str) -> dict:
        client = await self._get_client()
        resp = await client.post(rpc, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
        })
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


_holder_data: Optional[HolderData] = None


def get_holder_data() -> HolderData:
    global _holder_data
    if _holder_data is None:
        _holder_data = HolderData()
    return _holder_data
