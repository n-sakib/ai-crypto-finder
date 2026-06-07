"""
TokenEnricher — Enriches discovered tokens with Dexscreener + GMGN data.

╔══════════════════════════════════════════════════════════════════════════════╗
║                     TELEGRAM DISCOVERY PIPELINE                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  POST /api/v1/telegram/collect?window=60m                                    ║
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │ STEP 1: COLLECT MESSAGES                      (client.py)            │    ║
║  │   • Connect to Telegram via Telethon                                │    ║
║  │   • Read messages from all enabled sources within the time window   │    ║
║  │   • Store: text_hash, sender_hash, reactions, views, forwards       │    ║
║  │   • Store raw_text if TELEGRAM_STORE_RAW_TEXT=true                  │    ║
║  │   • Dedup: skip same text_hash within 10 min per source             │    ║
║  │   • Output: list of (TelegramMessage, TelegramSource, raw_text)      │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                    ↓                                         ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │ STEP 2: EXTRACT TOKEN REFERENCES              (extractor.py)         │    ║
║  │   • Extract contract addresses (0x... + Solana base58)              │    ║
║  │   • Extract DEX links (dexscreener, birdeye, gmgn, geckoterminal)  │    ║
║  │   • Extract cashtags ($SYMBOL)                                       │    ║
║  │   • Create CandidateToken + TelegramTokenMention records             │    ║
║  │   • Cashtags stored as "cashtag:SYMBOL" until resolved               │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                    ↓                                         ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │ STEP 3: ENRICH WITH DEXSCREENER + GMGN  ←  (THIS FILE: enricher.py) │    ║
║  │   • Dexscreener: price_usd, volume_24h, liquidity_usd, market_cap   │    ║
║  │                  price_change_24h, fdv, dex_id, pair_created_at      │    ║
║  │   • GMGN: is_honeypot, has_mint_risk, top_10_holder_pct,            │    ║
║  │           buy_tax_pct, sell_tax_pct, lp_locked_pct, rugpull_risk     │    ║
║  │   • Resolves cashtags → real contract addresses via Dexscreener     │    ║
║  │   • Rate limited: ~3 req/s for Dexscreener                          │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                    ↓                                         ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │ STEP 4: REMOVE DUPLICATES                     (api.py)               │    ║
║  │   • Merge cashtag-resolved tokens into their real CA counterpart    │    ║
║  │   • Same chain:address pair → merge mentions, delete duplicate      │    ║
║  │   • Only one CandidateToken per chain + token_address                │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                    ↓                                         ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │ STEP 5: DEEPSEEK AI EVALUATION               (evaluator.py)          │    ║
║  │   • Build context: social metrics + Dexscreener + GMGN safety       │    ║
║  │   • Auto-discard: honeypots, extreme taxes (>50%), obvious scams     │    ║
║  │   • DeepSeek evaluates: keep / discard / pending                     │    ║
║  │   • Returns: decision, confidence (0-1), reasoning, red_flags        │    ║
║  │   • Max 3 concurrent API calls (semaphore)                           │    ║
║  │   • Skipped gracefully if DEEPSEEK_API_KEY not configured            │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                    ↓                                         ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │ STEP 6: AGGREGATE & RANK                     (aggregator.py)         │    ║
║  │   • Per-group dedup: same token in same group = 1 mention            │    ║
║  │   • mention_count = COUNT(DISTINCT source_id)  — distinct groups     │    ║
║  │   • Rank by: mention_count > unique_users > group_count > recency    │    ║
║  │   • Filters: min_mentions (≥5), min_unique_users (≥3)               │    ║
║  │   • Output: DiscoveryRankingResponse with social indicators + AI     │    ║
║  │   • Endpoint: GET /api/v1/telegram/discovery?window=60m&limit=100    │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                                                              ║
║  DATA STORED PER TOKEN (CandidateToken):                                     ║
║    • Identity: chain, token_address, symbol, name, pair_address, dex_url    ║
║    • Dexscreener: price_usd, volume_24h, liquidity_usd, market_cap, fdv     ║
║    • GMGN safety: is_honeypot, taxes, holder %, lp_locked, rugpull_risk     ║
║    • AI: ai_evaluation (JSON), ai_decision (keep/discard/pending)           ║
║    • Social: total_reactions, total_views, total_forwards                    ║
║    • Mentions: per-group mention count, unique users, source group names     ║
║                                                                              ║
║  DATA STORED PER MESSAGE (TelegramMessage):                                   ║
║    • text_hash, sender_id_hash (privacy-preserving)                          ║
║    • reactions_count, views_count, forwards_count, reply_count               ║
║    • raw_text (optional, off by default)                                     ║
║    • source_id → which Telegram group it came from                           ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

Uses rate limiting to avoid API throttling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select as sa_select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.telegram_discovery.models import CandidateToken, DiscoveryMethod

logger = logging.getLogger(__name__)


class TokenEnricher:
    """
    Enriches candidate tokens with external data.

    Dexscreener: price, volume_24h, liquidity_usd, market_cap, price_change_24h
    GMGN: safety checks, holder distribution, top trader activity
    """

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._dex_interval: float = 0.35  # ~3 req/s
        self._last_dex_call: float = 0.0

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def _rate_limit_dex(self) -> None:
        """Ensure minimum interval between Dexscreener calls."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_dex_call
        if elapsed < self._dex_interval:
            await asyncio.sleep(self._dex_interval - elapsed)
        self._last_dex_call = asyncio.get_event_loop().time()

    async def enrich_token(
        self,
        session: AsyncSession,
        token: CandidateToken,
    ) -> dict:
        """
        Enrich a single candidate token with Dexscreener + GMGN data.

        IMPORTANT: Caller must ensure token attributes are eagerly loaded
        (e.g., via session.refresh) before calling this method, as HTTP
        calls can disrupt the SQLAlchemy greenlet context.
        """
        enriched = {}

        # Step 1: Dexscreener enrichment
        dex_data = await self._enrich_dexscreener(token)
        if dex_data:
            enriched.update(dex_data)
            token.dexscreener_data = dex_data

        # Step 2: GMGN enrichment (if API key configured)
        if settings.GMGN_API_KEY:
            gmgn_data = await self._enrich_gmgn(token)
            if gmgn_data:
                token.gmgn_data = gmgn_data
                enriched["gmgn_enriched"] = True

        token.updated_at = datetime.now(timezone.utc)
        return enriched

    async def enrich_tokens_batch(
        self,
        session: AsyncSession,
        tokens: list[CandidateToken],
        progress_callback=None,
    ) -> tuple[int, int]:
        """
        Enrich a batch of tokens.

        Tokens are eagerly refreshed from DB before enrichment to avoid
        MissingGreenlet errors when accessing lazy-loaded attributes after
        HTTP calls switch the greenlet context.

        Returns (enriched_count, failed_count).
        """
        enriched = 0
        failed = 0

        # Use no_autoflush to prevent deadlocks with concurrent discovery reads.
        # We control flushes manually every 5 tokens.
        with session.no_autoflush:
            for i, token in enumerate(tokens):
                try:
                    # Eagerly refresh to load all attributes and avoid lazy loading
                    # inside HTTP call context (which loses the SQLAlchemy greenlet)
                    await session.refresh(token, attribute_names=[
                        'first_discovery_method', 'token_address', 'symbol',
                        'chain', 'name', 'pair_address', 'dex_url',
                    ])
                    await self.enrich_token(session, token)
                    enriched += 1
                except Exception as e:
                    logger.warning(f"Enrichment failed for token: {e}")
                    failed += 1
                    # Rollback to recover session after deadlock/error
                    try:
                        await session.rollback()
                    except Exception:
                        pass

                if (i + 1) % 5 == 0:
                    try:
                        await session.flush()
                    except Exception:
                        await session.rollback()

                if progress_callback:
                    await progress_callback(i + 1, len(tokens), enriched, failed)

            await session.flush()
        return enriched, failed

    # ── Dexscreener ──────────────────────────────────────────────────

    async def _enrich_dexscreener(self, token: CandidateToken) -> Optional[dict]:
        """Fetch and parse Dexscreener data for a token."""
        await self._rate_limit_dex()

        http = await self._get_http()

        if token.first_discovery_method == DiscoveryMethod.CASHTAG or token.token_address.startswith("cashtag:"):
            url = f"{settings.DEXSCREENER_API_URL}/latest/dex/search?q={token.symbol}"
        else:
            url = f"{settings.DEXSCREENER_API_URL}/latest/dex/tokens/{token.token_address}"

        try:
            resp = await http.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return None

            # Find the best pair (highest liquidity)
            best = max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
            base = best.get("baseToken", {})

            # Update token identity from Dexscreener data
            base_symbol = base.get("symbol", "")
            base_name = base.get("name") or base_symbol
            base_addr = base.get("address", "")

            if token.token_address.startswith("cashtag:") and base_addr:
                # Cashtag resolved to real address
                old_addr = token.token_address
                token.token_address = base_addr
                token.chain = best.get("chainId", token.chain)
                token.symbol = base_symbol
                token.name = base_name
                token.pair_address = best.get("pairAddress")
                token.dex_url = best.get("url")
                logger.info(f"Resolved cashtag {old_addr} → {token.chain}:{token.token_address} ({token.symbol})")
            elif base_symbol and base_name:
                # Always update symbol/name from Dexscreener if they differ from raw address
                current_is_raw = (
                    not token.symbol or
                    token.symbol == token.token_address[:8] or
                    token.symbol.startswith("0x") or
                    len(token.symbol) > 16  # likely a raw address
                )
                if current_is_raw or not token.name:
                    token.symbol = base_symbol
                    token.name = base_name
                    token.chain = best.get("chainId", token.chain)
                    token.pair_address = best.get("pairAddress")
                    token.dex_url = token.dex_url or best.get("url")
                    logger.info(f"Updated identity: {token.symbol} ({token.name})")

            return {
                "price_usd": float(best.get("priceUsd", 0) or 0),
                "volume_24h": float(best.get("volume", {}).get("h24", 0) or 0),
                "liquidity_usd": float(best.get("liquidity", {}).get("usd", 0) or 0),
                "market_cap": float(best.get("marketCap", 0) or 0),
                "fdv": float(best.get("fdv", 0) or 0),
                "price_change_24h": float(best.get("priceChange", {}).get("h24", 0) or 0),
                "pair_created_at": best.get("pairCreatedAt"),
                "dex_id": best.get("dexId"),
            }
        except Exception as e:
            logger.debug(f"Dexscreener enrichment failed for {token.symbol}: {e}")
            return None

    # ── GMGN ──────────────────────────────────────────────────────────

    async def _enrich_gmgn(self, token: CandidateToken) -> Optional[dict]:
        """Fetch GMGN data for safety + holder analysis."""
        if not settings.GMGN_API_KEY:
            return None

        http = await self._get_http()
        chain = token.chain or "solana"
        addr = token.token_address

        # GMGN token security endpoint
        url = f"https://gmgn.ai/defi/router/v1/sol/tx/sol/token_security/{addr}"
        headers = {"Authorization": f"Bearer {settings.GMGN_API_KEY}"}

        try:
            resp = await http.get(url, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()

            security = data.get("data", {})

            return {
                "is_honeypot": security.get("is_honeypot", False),
                "has_mint_risk": security.get("is_mint_authority_renounced") == False,
                "is_mint_renounced": security.get("is_mint_authority_renounced", False),
                "is_freeze_renounced": security.get("is_freeze_authority_renounced", False),
                "top_10_holder_pct": security.get("top_10_holder_rate", 0),
                "creator_balance_pct": security.get("creator_balance", 0),
                "has_burned_lp": security.get("is_burned_lp", False),
                "lp_locked_pct": security.get("lp_locked_rate", 0),
                "buy_tax_pct": security.get("buy_tax", 0),
                "sell_tax_pct": security.get("sell_tax", 0),
                "rugpull_risk": security.get("rugpull_risk", "unknown"),
            }
        except Exception as e:
            logger.debug(f"GMGN enrichment failed for {token.symbol}: {e}")
            return None
