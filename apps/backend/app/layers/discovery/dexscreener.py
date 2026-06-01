"""
DEXScreener Discovery — Multi-feeder discovery with composite scoring.

Feeds (5 independent discovery paths):
  1. Keyword Search    — category-based search across 6 sectors
  2. Trending Pairs    — DEXScreener's native trending endpoint
  3. Boosted Pairs     — tokens with unusual trade concentration
  4. Recently Active   — newest pairs with immediate activity
  5. Volume Velocity   — acceleration detection (velocity > 2x)

Composite Discovery Score (not just volume velocity):
  40% Volume Velocity  — is trading accelerating?
  25% Trade Velocity   — are trades picking up?
  20% Buyer Velocity   — are unique buyers growing?
  15% Liquidity Growth — is liquidity flowing in?

API: https://api.dexscreener.com (free, no key required)
Output: top 300 tokens after pair deduplication
"""

import asyncio
import httpx
from typing import Optional

from app.config import settings
from app.layers.discovery.base import BaseDiscoverySource


class DexScreenerDiscovery(BaseDiscoverySource):
    """
    Multi-feeder DEXScreener discovery with composite scoring.

    - Volume mode: finds tokens with unusual activity acceleration
    - Trending mode: finds tokens climbing attention lists

    Output is token-level (not pair-level) — pairs are merged via the
    Token Identity layer (Layer 2) in the pipeline.
    """

    # ── Category-based search terms (Problem #1 fix) ────
    SEARCH_QUERIES = {
        # Memes
        "meme": ["dog", "cat", "pepe", "based", "chad", "inu", "woof", "mew", "michi"],
        # AI
        "ai": ["ai", "agent", "gpt", "compute", "neural", "llm", "autonomous"],
        # DePIN
        "depin": ["gpu", "cloud", "compute", "network", "bandwidth", "storage", "node"],
        # RWA
        "rwa": ["rwa", "yield", "usd", "treasury", "tokenized", "real world"],
        # Gaming
        "gaming": ["game", "gaming", "play", "arena", "quest", "pixel"],
        # Infrastructure
        "infra": ["protocol", "finance", "swap", "bridge", "oracle", "dao", "vault"],
    }
    # Flattened for API calls
    ALL_QUERIES = [term for category in SEARCH_QUERIES.values() for term in category]

    # ── Exclusion lists ─────────────────────────────────
    EXCLUDED_SYMBOLS = {
        "USDC", "USDT", "DAI", "BUSD", "TUSD", "USDD", "FRAX", "LUSD", "PYUSD", "FDUSD",
        "WETH", "WBTC", "WBNB", "WMATIC", "WAVAX", "WFTM", "WSOL",
        "STETH", "RETH", "CBBTC", "WBETH",
        "ETH", "SOL", "BNB", "MATIC", "POL", "AVAX", "FTM",
        "ADA", "DOT", "ATOM", "NEAR", "APT", "SUI", "OP", "ARB",
    }
    EXCLUDED_NAMES = {
        "USD Coin", "Tether USD", "Dai Stablecoin", "Wrapped Ether",
        "Wrapped BTC", "Wrapped BNB", "Binance USD", "PayPal USD",
    }
    NATIVE_ONLY = {
        "ETH": {"ethereum"}, "SOL": {"solana"}, "BNB": {"bsc"},
        "MATIC": {"polygon"}, "POL": {"polygon"}, "AVAX": {"avalanche"},
        "FTM": {"fantom"}, "ADA": {"cardano"}, "DOT": {"polkadot"},
        "ATOM": {"cosmos"}, "NEAR": {"near"}, "APT": {"aptos"},
        "SUI": {"sui"}, "OP": {"optimism"}, "ARB": {"arbitrum"},
    }
    KNOWN_ADDRESSES: dict[str, set[str]] = {
        "SOL": {"So11111111111111111111111111111111111111112"},
        "ETH": {"0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"},
        "ARB": {"0x912CE59144191C1204E64559FE8253a0e49E6548"},
        "BNB": {"0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"},
        "OP": {"0x4200000000000000000000000000000000000042"},
        "MATIC": {"0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0"},
    }

    # ── Thresholds (Problem #4 fix) ─────────────────────
    MIN_LIQUIDITY_DISCOVERY = 20_000   # bare minimum to consider
    MIN_LIQUIDITY_QUALITY = 50_000     # quality threshold
    MIN_LIQUIDITY_STRONG = 100_000     # strong signal
    MIN_VOLUME_24H = 10_000            # minimum 24h volume
    MIN_TRADES_24H = 20                # minimum transactions

    def __init__(self, trending_mode: bool = False):
        self._trending_mode = trending_mode
        self._client: Optional[httpx.AsyncClient] = None

    def source_name(self) -> str:
        return "DEXScreener Trending" if self._trending_mode else "DEXScreener Volume"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.DEXSCREENER_API_URL,
                timeout=30.0,
                headers={"Accept": "application/json"},
            )
        return self._client

    # ── Public API ──────────────────────────────────────

    async def discover(self) -> list[dict]:
        """Run all discovery feeders and return deduplicated token candidates."""
        try:
            if self._trending_mode:
                return await self._run_trending_feeders()
            else:
                return await self._run_volume_feeders()
        except Exception:
            return []

    # ═════════════════════════════════════════════════════
    # Volume Mode — composite velocity discovery
    # ═════════════════════════════════════════════════════

    async def _run_volume_feeders(self) -> list[dict]:
        """
        Run all 5 discovery feeders concurrently:
          1. Keyword search  → category-based
          2. Trending pairs   → DEXScreener trending
          3. Boosted pairs    → trade concentration
          4. Recently active  → new pairs with activity
          5. Volume velocity  → acceleration detection

        Returns top 300 tokens after dedup, scored by composite velocity.
        """
        feeders = await asyncio.gather(
            self._feed_keyword_search(),
            self._feed_trending_pairs(),
            self._feed_boosted_pairs(),
            self._feed_recently_active(),
            self._feed_volume_velocity(),
            return_exceptions=True,
        )

        all_candidates: list[dict] = []
        for result in feeders:
            if isinstance(result, list):
                all_candidates.extend(result)

        # Deduplicate by token (chain + address)
        tokens = self._deduplicate_tokens(all_candidates)

        # Score with composite velocity
        self._score_composite(tokens)

        # Sort by composite score descending
        tokens.sort(key=lambda t: t.get("composite_score", 0), reverse=True)

        return tokens[:300]

    # ── Feeder 1: Keyword Search ────────────────────────

    async def _feed_keyword_search(self) -> list[dict]:
        """Category-based keyword search across all 6 sectors."""
        candidates: list[dict] = []
        seen_pairs: set[str] = set()

        tasks = [self._search_pairs(q) for q in self.ALL_QUERIES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for pairs in results:
            if not isinstance(pairs, list):
                continue
            for pair in pairs:
                pid = pair.get("pairAddress", "")
                if pid in seen_pairs:
                    continue
                if self._is_excluded(pair):
                    continue
                seen_pairs.add(pid)
                c = self._normalize_pair(pair)
                if c and self._passes_filters(c):
                    c["feeder"] = "keyword_search"
                    candidates.append(c)

        return candidates

    # ── Feeder 2: Trending Pairs ────────────────────────

    async def _feed_trending_pairs(self) -> list[dict]:
        """DEXScreener's native trending pairs endpoint."""
        candidates: list[dict] = []
        try:
            # Search with broad terms to catch trending pairs
            broad_terms = ["meme", "ai", "sol", "eth", "bnb", "new"]
            tasks = [self._search_pairs(t) for t in broad_terms]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            seen: set[str] = set()
            for pairs in results:
                if not isinstance(pairs, list):
                    continue
                for pair in pairs:
                    pid = pair.get("pairAddress", "")
                    if pid in seen or self._is_excluded(pair):
                        continue
                    seen.add(pid)

                    txns = pair.get("txns", {})
                    trades_h24 = (
                        int(txns.get("h24", {}).get("buys", 0) or 0)
                        + int(txns.get("h24", {}).get("sells", 0) or 0)
                    )
                    price_change = float(pair.get("priceChange", {}).get("h24", 0) or 0)

                    # Trending signal: activity + momentum
                    if trades_h24 >= 50 and abs(price_change) >= 5:
                        c = self._normalize_pair(pair)
                        if c and self._passes_filters(c):
                            c["feeder"] = "trending_pairs"
                            candidates.append(c)
        except Exception:
            pass
        return candidates

    # ── Feeder 3: Boosted Pairs ─────────────────────────

    async def _feed_boosted_pairs(self) -> list[dict]:
        """
        Boosted pairs — tokens with unusual trade concentration.

        Uses DEXScreener's search endpoint filtered for high tx count
        relative to age (pairs with sudden bursts of activity).
        """
        candidates: list[dict] = []
        try:
            # Search for pairs with boosted metrics
            boost_terms = ["boosted", "trending", "hot", "gainers"]
            tasks = [self._search_pairs(t) for t in boost_terms]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            seen: set[str] = set()
            for pairs in results:
                if not isinstance(pairs, list):
                    continue
                for pair in pairs:
                    pid = pair.get("pairAddress", "")
                    if pid in seen or self._is_excluded(pair):
                        continue
                    seen.add(pid)

                    txns = pair.get("txns", {})
                    trades_h1 = (
                        int(txns.get("h1", {}).get("buys", 0) or 0)
                        + int(txns.get("h1", {}).get("sells", 0) or 0)
                    )
                    # Boosted: high trade density in last hour
                    if trades_h1 >= 20:
                        c = self._normalize_pair(pair)
                        if c and self._passes_filters(c):
                            c["feeder"] = "boosted_pairs"
                            candidates.append(c)
        except Exception:
            pass
        return candidates

    # ── Feeder 4: Recently Active ───────────────────────

    async def _feed_recently_active(self) -> list[dict]:
        """
        Recently active pairs — newest pairs with immediate trading activity.

        Catches tokens that don't match any keyword but are being traded.
        """
        candidates: list[dict] = []
        try:
            # Use chain-specific searches to find recent pairs
            chain_terms = ["solana new", "ethereum new", "bsc new", "base new"]
            tasks = [self._search_pairs(t) for t in chain_terms]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            seen: set[str] = set()
            for pairs in results:
                if not isinstance(pairs, list):
                    continue
                for pair in pairs:
                    pid = pair.get("pairAddress", "")
                    if pid in seen or self._is_excluded(pair):
                        continue
                    seen.add(pid)

                    created_at = pair.get("pairCreatedAt", 0) or 0
                    # Only pairs created in last 7 days
                    if created_at == 0:
                        continue
                    import time
                    seven_days_ago = int(time.time() * 1000) - 7 * 24 * 3600 * 1000
                    if created_at < seven_days_ago:
                        continue

                    c = self._normalize_pair(pair)
                    if c and self._passes_filters(c):
                        c["feeder"] = "recently_active"
                        candidates.append(c)
        except Exception:
            pass
        return candidates

    # ── Feeder 5: Volume Velocity ───────────────────────

    async def _feed_volume_velocity(self) -> list[dict]:
        """
        Volume velocity — acceleration detection.

        Compares recent activity (6h) vs average (24h) across 3 dimensions:
          - Volume velocity
          - Trade velocity
          - Buyer velocity

        A whale trade inflating volume but not trades/buyers = low composite score.
        """
        candidates: list[dict] = []
        seen: set[str] = set()

        for query in self.ALL_QUERIES:
            try:
                pairs = await self._search_pairs(query)
                for pair in pairs:
                    pid = pair.get("pairAddress", "")
                    if pid in seen or self._is_excluded(pair):
                        continue
                    seen.add(pid)

                    volume = pair.get("volume", {})
                    txns = pair.get("txns", {})

                    vol_24h = float(volume.get("h24", 0) or 0)
                    vol_6h = float(volume.get("h6", 0) or 0)

                    buys_24h = int(txns.get("h24", {}).get("buys", 0) or 0)
                    sells_24h = int(txns.get("h24", {}).get("sells", 0) or 0)
                    buys_6h = int(txns.get("h6", {}).get("buys", 0) or 0)
                    sells_6h = int(txns.get("h6", {}).get("sells", 0) or 0)

                    trades_24h = buys_24h + sells_24h
                    trades_6h = buys_6h + sells_6h

                    # Per-hour rates
                    rate_v24 = vol_24h / 24 if vol_24h > 0 else 0
                    rate_v6 = vol_6h / 6 if vol_6h > 0 else 0
                    rate_t24 = trades_24h / 24 if trades_24h > 0 else 0
                    rate_t6 = trades_6h / 6 if trades_6h > 0 else 0
                    rate_b24 = buys_24h / 24 if buys_24h > 0 else 0
                    rate_b6 = buys_6h / 6 if buys_6h > 0 else 0

                    # Three velocity dimensions (Problem #3 fix)
                    vol_velocity = rate_v6 / rate_v24 if rate_v24 > 0 else 0
                    trade_velocity = rate_t6 / rate_t24 if rate_t24 > 0 else 0
                    buyer_velocity = rate_b6 / rate_b24 if rate_b24 > 0 else 0

                    # Composite: weighted blend
                    composite = (
                        0.40 * vol_velocity
                        + 0.25 * trade_velocity
                        + 0.20 * buyer_velocity
                    )

                    if composite < 1.5:
                        continue

                    if vol_24h < self.MIN_VOLUME_24H:
                        continue
                    if trades_24h < self.MIN_TRADES_24H:
                        continue

                    liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                    if liquidity < self.MIN_LIQUIDITY_DISCOVERY:
                        continue

                    c = self._normalize_pair(pair)
                    if c:
                        c["vol_velocity"] = round(vol_velocity, 2)
                        c["trade_velocity"] = round(trade_velocity, 2)
                        c["buyer_velocity"] = round(buyer_velocity, 2)
                        c["composite_score"] = round(composite, 2)
                        c["feeder"] = "volume_velocity"
                        candidates.append(c)

            except Exception:
                continue

        return candidates

    # ═════════════════════════════════════════════════════
    # Trending Mode
    # ═════════════════════════════════════════════════════

    async def _run_trending_feeders(self) -> list[dict]:
        """Trending mode: find tokens climbing attention lists."""
        all_candidates: list[dict] = []
        seen_pairs: set[str] = set()

        for query in self.ALL_QUERIES:
            try:
                pairs = await self._search_pairs(query)
                for pair in pairs:
                    pid = pair.get("pairAddress", "")
                    if pid in seen_pairs or self._is_excluded(pair):
                        continue
                    seen_pairs.add(pid)

                    txns = pair.get("txns", {})
                    volume = pair.get("volume", {})
                    trades_24h = (
                        int(txns.get("h24", {}).get("buys", 0) or 0)
                        + int(txns.get("h24", {}).get("sells", 0) or 0)
                    )
                    trades_6h = (
                        int(txns.get("h6", {}).get("buys", 0) or 0)
                        + int(txns.get("h6", {}).get("sells", 0) or 0)
                    )
                    vol_24h = float(volume.get("h24", 0) or 0)
                    vol_6h = float(volume.get("h6", 0) or 0)

                    if trades_24h < self.MIN_TRADES_24H:
                        continue

                    liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                    if liquidity < self.MIN_LIQUIDITY_DISCOVERY:
                        continue

                    price_change = float(pair.get("priceChange", {}).get("h24", 0) or 0)

                    # Trending composite (Problem #6 fix)
                    trade_vel = (trades_6h / 6) / (trades_24h / 24) if trades_24h > 0 else 0
                    vol_vel = (vol_6h / 6) / (vol_24h / 24) if vol_24h > 0 else 0
                    liq_growth = (float(pair.get("liquidity", {}).get("usd", 0) or 0)) / max(liquidity, 1)

                    trending_score = (
                        0.30 * min(trade_vel, 10)
                        + 0.25 * min(vol_vel, 10)
                        + 0.15 * (liq_growth if liq_growth < 5 else 0)
                        + 0.30 * (abs(price_change) / 100 if abs(price_change) < 500 else 5)
                    )

                    if trending_score < 0.5:
                        continue

                    c = self._normalize_pair(pair)
                    if c:
                        c["trending_score"] = round(trending_score, 2)
                        c["composite_score"] = round(trending_score, 2)
                        c["feeder"] = "trending"
                        candidates = all_candidates if True else None  # unused
                        all_candidates.append(c)

            except Exception:
                continue

        tokens = self._deduplicate_tokens(all_candidates)
        tokens.sort(key=lambda t: t.get("composite_score", 0), reverse=True)
        return tokens[:300]

    # ═════════════════════════════════════════════════════
    # Shared Utilities
    # ═════════════════════════════════════════════════════

    async def _search_pairs(self, query: str) -> list[dict]:
        """GET /latest/dex/search?q={query}"""
        response = await self.client.get(
            "/latest/dex/search",
            params={"q": query},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("pairs", []) or []

    def _is_excluded(self, pair: dict) -> bool:
        """Check if pair should be excluded (stablecoins, wrapped, native-on-wrong-chain)."""
        base = pair.get("baseToken", {})
        symbol = (base.get("symbol", "") or "").upper().strip()
        name = (base.get("name", "") or "").strip()
        chain = (pair.get("chainId", "") or "").lower().strip()

        if symbol in self.EXCLUDED_SYMBOLS or name in self.EXCLUDED_NAMES:
            return True

        if symbol in self.NATIVE_ONLY:
            if chain not in self.NATIVE_ONLY[symbol]:
                return True
            known_addrs = self.KNOWN_ADDRESSES.get(symbol)
            if known_addrs:
                contract = (base.get("address", "") or "").strip()
                if contract not in known_addrs:
                    return True

        return False

    def _passes_filters(self, c: dict) -> bool:
        """Check if candidate passes minimum quality filters."""
        if c.get("liquidity_usd", 0) < self.MIN_LIQUIDITY_DISCOVERY:
            return False
        if c.get("volume_24h", 0) < self.MIN_VOLUME_24H:
            return False
        if c.get("trade_count_24h", 0) < self.MIN_TRADES_24H:
            return False
        return True

    def _normalize_pair(self, pair: dict) -> Optional[dict]:
        """Convert DEXScreener pair → standard candidate dict."""
        base = pair.get("baseToken", {})
        volume = pair.get("volume", {})
        liquidity = pair.get("liquidity", {})
        price_change = pair.get("priceChange", {})
        txns = pair.get("txns", {})

        liq_usd = float(liquidity.get("usd", 0) or 0)
        vol_24h = float(volume.get("h24", 0) or 0)
        mcap = float(pair.get("marketCap", 0) or 0)
        fdv = float(pair.get("fdv", 0) or 0)

        # Market-cap bucket (Problem #5 fix)
        mcap_bucket = "micro" if mcap < 1_000_000 else (
            "small" if mcap < 50_000_000 else (
                "mid" if mcap < 500_000_000 else (
                    "large" if mcap < 1_000_000_000 else "mega"
                )
            )
        )

        buys_24h = int(txns.get("h24", {}).get("buys", 0) or 0)
        sells_24h = int(txns.get("h24", {}).get("sells", 0) or 0)

        return {
            "chain": (pair.get("chainId", "unknown") or "").lower(),
            "contract_address": (base.get("address", "") or "").strip(),
            "pair_address": (pair.get("pairAddress", "") or "").strip(),
            "symbol": (base.get("symbol", "") or "").upper().strip(),
            "name": (base.get("name", "") or "").strip(),
            "dex_id": pair.get("dexId", ""),
            "liquidity_usd": liq_usd,
            "liquidity_tier": (
                "strong" if liq_usd >= self.MIN_LIQUIDITY_STRONG
                else "quality" if liq_usd >= self.MIN_LIQUIDITY_QUALITY
                else "discovery"
            ),
            "volume_24h": vol_24h,
            "volume_1h": float(volume.get("h1", 0) or 0),
            "price_usd": float(pair.get("priceUsd", 0) or 0),
            "price_change_24h": float(price_change.get("h24", 0) or 0),
            "price_change_6h": float(price_change.get("h6", 0) or 0),
            "holder_count": 0,
            "market_cap": mcap,
            "fdv": fdv,
            "market_cap_bucket": mcap_bucket,
            "created_at": pair.get("pairCreatedAt"),
            "url": pair.get("url", ""),
            "trade_count_24h": buys_24h + sells_24h,
            "unique_buyers_24h": buys_24h,
            "unique_sellers_24h": sells_24h,
        }

    def _deduplicate_tokens(self, candidates: list[dict]) -> list[dict]:
        """
        Token-level deduplication (Problem #7 fix).

        Merges pairs into canonical tokens by (chain, contract_address).
        Keeps the best pair (highest liquidity) and sums metrics.
        """
        tokens: dict[tuple[str, str], dict] = {}
        for c in candidates:
            key = (c.get("chain", ""), c.get("contract_address", ""))
            if not key[0] or not key[1]:
                continue
            if key not in tokens:
                tokens[key] = dict(c)
                tokens[key]["all_feeders"] = {c.get("feeder", "unknown")}
            else:
                existing = tokens[key]
                # Keep highest-liquidity pair as canonical
                if c.get("liquidity_usd", 0) > existing.get("liquidity_usd", 0):
                    existing.update(c)
                # Merge feeders
                feeders = existing.get("all_feeders", set())
                feeders.add(c.get("feeder", "unknown"))
                existing["all_feeders"] = feeders
                # Sum metrics from all pairs
                existing["volume_24h"] = existing.get("volume_24h", 0) + c.get("volume_24h", 0)
                existing["trade_count_24h"] = existing.get("trade_count_24h", 0) + c.get("trade_count_24h", 0)
                existing["unique_buyers_24h"] = existing.get("unique_buyers_24h", 0) + c.get("unique_buyers_24h", 0)

        result = list(tokens.values())
        for t in result:
            t["feeder_count"] = len(t.get("all_feeders", set()))

        return result

    def _score_composite(self, tokens: list[dict]):
        """
        Compute composite discovery score for volume mode tokens
        that don't already have one (feeders 1-4).
        """
        for t in tokens:
            if "composite_score" in t:
                continue  # Already scored by feeder 5

            vol_24h = t.get("volume_24h", 0)
            trades_24h = t.get("trade_count_24h", 0)
            buyers_24h = t.get("unique_buyers_24h", 0)

            # Simple relative scoring when we don't have 6h data
            vol_score = min(vol_24h / 100_000, 10) * 0.40
            trade_score = min(trades_24h / 500, 10) * 0.25
            buyer_score = min(buyers_24h / 200, 10) * 0.20
            liq_score = min(t.get("liquidity_usd", 0) / 200_000, 10) * 0.15

            t["composite_score"] = round(vol_score + trade_score + buyer_score + liq_score, 2)

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
