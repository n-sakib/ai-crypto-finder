"""
TokenResolver — Converts extracted token references into canonical CandidateToken records.

Resolution priorities:
    1. CONTRACT_ADDRESS: Highest priority — creates candidate immediately.
    2. DEX_LINK: Parse token/pair data, resolve token address.
    3. CASHTAG: Only resolve if confident match from DEX API lookup.
    4. TOKEN_NAME: Low priority, not resolved unless confidently matched.

Every discovered token must normalize to: chain + token_address + symbol + name.
Never stores or ranks symbol alone.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.telegram_discovery.models import (
    CandidateToken, TelegramMessage, TelegramTokenMention,
    TelegramSource, DiscoveryMethod, DiscoveryConfidence,
)
from app.telegram_discovery.schemas import ExtractedTokenReference

logger = logging.getLogger(__name__)


class TokenResolver:
    """
    Resolves extracted token references into canonical CandidateToken records.

    Contract addresses create candidates immediately.
    DEX links are parsed for token addresses.
    Cashtags require DEX API confirmation (rate-limited).
    Token names are optional and low confidence.
    """

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._last_dex_call: float = 0.0
        self._dex_call_interval: float = 0.35  # ~3 req/s to avoid 429s
        self._cashtag_cache: dict[str, Optional[dict]] = {}  # symbol → resolved data

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=15.0)
        return self._http_client

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def resolve_and_store_mentions(
        self,
        session: AsyncSession,
        source: TelegramSource,
        message: TelegramMessage,
        refs: list[ExtractedTokenReference],
    ) -> int:
        """
        Resolve extracted references and store mentions.

        Returns the number of mentions created.
        """
        mentions_created = 0

        for ref in refs:
            try:
                candidate = await self._resolve_reference(session, source, ref)
                if candidate is None:
                    continue

                # Create mention (idempotent — ON CONFLICT DO NOTHING)
                mention_created = await self._store_mention(
                    session, candidate, source, message, ref,
                )
                if mention_created:
                    mentions_created += 1

            except Exception as e:
                logger.warning(
                    "Failed to resolve reference %s: %s",
                    ref.raw_value, e,
                )

        return mentions_created

    async def _resolve_reference(
        self,
        session: AsyncSession,
        source: TelegramSource,
        ref: ExtractedTokenReference,
    ) -> Optional[CandidateToken]:
        """Resolve a single extracted reference to a CandidateToken."""

        if ref.discovery_method == DiscoveryMethod.CONTRACT_ADDRESS:
            return await self._resolve_contract_address(session, source, ref)

        elif ref.discovery_method == DiscoveryMethod.DEX_LINK:
            return await self._resolve_dex_link(session, source, ref)

        elif ref.discovery_method == DiscoveryMethod.CASHTAG:
            return await self._resolve_cashtag(session, source, ref)

        elif ref.discovery_method == DiscoveryMethod.TOKEN_NAME:
            # Low confidence — skip unless explicitly resolved
            return None

        return None

    async def _resolve_contract_address(
        self,
        session: AsyncSession,
        source: TelegramSource,
        ref: ExtractedTokenReference,
    ) -> Optional[CandidateToken]:
        """
        Resolve a contract address reference.

        Contract addresses create candidates immediately.
        Chain detection: if chain is None and it's an EVM address,
        default to 'ethereum' with a note.
        """
        token_address = (ref.token_address or "").lower().strip()
        if not token_address:
            return None

        # Determine chain
        chain = (ref.chain or self._infer_chain(token_address)).lower()

        # Find or create candidate
        now = datetime.now(timezone.utc)
        return await self._upsert_candidate(
            session=session,
            chain=chain,
            token_address=token_address,
            symbol=ref.symbol or token_address[:8],
            name=ref.name,
            source=source,
            discovery_method=ref.discovery_method,
            pair_address=ref.pair_address,
            dex_url=ref.dex_url,
            now=now,
        )

    async def _resolve_dex_link(
        self,
        session: AsyncSession,
        source: TelegramSource,
        ref: ExtractedTokenReference,
    ) -> Optional[CandidateToken]:
        """
        Resolve a DEX link reference.

        If token_address is available from URL parsing, use it directly.
        Otherwise, try to fetch pair data from the DEX API.
        """
        token_address = (ref.token_address or "").strip()
        chain = (ref.chain or "").lower()
        now = datetime.now(timezone.utc)

        # If we already have token address from URL parsing
        if token_address and chain:
            return await self._upsert_candidate(
                session=session,
                chain=chain,
                token_address=token_address,
                symbol=ref.symbol or token_address[:8],
                name=ref.name,
                source=source,
                discovery_method=ref.discovery_method,
                pair_address=ref.pair_address or token_address,
                dex_url=ref.dex_url,
                now=now,
            )

        # Try to resolve pair address from DEX API
        if ref.pair_address and chain:
            try:
                resolved = await self._resolve_pair_from_dex_api(
                    chain, ref.pair_address,
                )
                if resolved and resolved.get("token_address"):
                    return await self._upsert_candidate(
                        session=session,
                        chain=chain,
                        token_address=resolved["token_address"],
                        symbol=resolved.get("symbol", token_address[:8] if token_address else "???"),
                        name=resolved.get("name"),
                        source=source,
                        discovery_method=ref.discovery_method,
                        pair_address=ref.pair_address,
                        dex_url=ref.dex_url,
                        now=now,
                    )
            except Exception as e:
                logger.debug("DEX API resolution failed for %s: %s", ref.dex_url, e)

        return None

    async def _resolve_cashtag(
        self,
        session: AsyncSession,
        source: TelegramSource,
        ref: ExtractedTokenReference,
    ) -> Optional[CandidateToken]:
        """
        Resolve a cashtag reference.

        Only succeeds if there is a confident match from a known registry
        or DEX API lookup. Unresolved cashtags are ignored.
        """
        symbol = (ref.symbol or "").upper().strip()
        if not symbol:
            return None

        # Try DEXScreener search for the symbol
        try:
            resolved = await self._search_symbol_on_dex(symbol)
            if resolved and resolved.get("token_address") and resolved.get("chain"):
                now = datetime.now(timezone.utc)
                return await self._upsert_candidate(
                    session=session,
                    chain=resolved["chain"],
                    token_address=resolved["token_address"],
                    symbol=symbol,
                    name=resolved.get("name"),
                    source=source,
                    discovery_method=ref.discovery_method,
                    pair_address=resolved.get("pair_address"),
                    dex_url=resolved.get("dex_url"),
                    now=now,
                )
        except Exception as e:
            logger.debug("Cashtag resolution failed for $%s: %s", symbol, e)

        # Unresolved cashtag — do not create candidate
        return None

    # ── DEX API Helpers ────────────────────────────────────────────────

    async def _resolve_pair_from_dex_api(
        self, chain: str, pair_address: str,
    ) -> Optional[dict]:
        """Resolve a pair address via DEXScreener API."""
        await self._rate_limit_dex()

        client = await self._get_http_client()
        url = f"{settings.DEXSCREENER_API_URL}/latest/dex/pairs/{chain}/{pair_address}"
        resp = await client.get(url)
        self._last_dex_call = asyncio.get_event_loop().time()
        if resp.status_code != 200:
            return None

        data = resp.json()
        pairs = data.get("pairs", [])
        if not pairs:
            return None

        pair = pairs[0]
        return {
            "token_address": pair.get("baseToken", {}).get("address", ""),
            "symbol": pair.get("baseToken", {}).get("symbol", ""),
            "name": pair.get("baseToken", {}).get("name"),
            "chain": pair.get("chainId", chain),
            "pair_address": pair.get("pairAddress"),
            "dex_url": pair.get("url"),
        }

    async def _search_symbol_on_dex(self, symbol: str) -> Optional[dict]:
        """Search for a token by symbol on DEXScreener (with caching + rate limiting)."""
        symbol_upper = symbol.upper()

        # Return cached result if available
        if symbol_upper in self._cashtag_cache:
            return self._cashtag_cache[symbol_upper]

        # Rate limit: ensure minimum interval between calls
        await self._rate_limit_dex()

        client = await self._get_http_client()
        url = f"{settings.DEXSCREENER_API_URL}/latest/dex/search?q={symbol}"
        try:
            resp = await client.get(url)
            self._last_dex_call = asyncio.get_event_loop().time()

            if resp.status_code == 429:
                # Rate limited — back off and skip
                logger.debug("DEXScreener rate limited for $%s, skipping", symbol)
                self._cashtag_cache[symbol_upper] = None
                self._dex_call_interval = min(self._dex_call_interval * 2, 5.0)
                return None

            if resp.status_code != 200:
                self._cashtag_cache[symbol_upper] = None
                return None

            data = resp.json()
            pairs = data.get("pairs", [])
            if not pairs:
                self._cashtag_cache[symbol_upper] = None
                return None

            # Find the best match (highest liquidity/volume pair with matching symbol)
            best = None
            best_score = 0
            for pair in pairs:
                base = pair.get("baseToken", {})
                if base.get("symbol", "").upper() != symbol_upper:
                    continue
                score = (pair.get("liquidity", {}).get("usd", 0) or 0)
                if score > best_score:
                    best_score = score
                    best = pair

            if best:
                base = best.get("baseToken", {})
                result = {
                    "token_address": base.get("address", ""),
                    "symbol": base.get("symbol", symbol),
                    "name": base.get("name"),
                    "chain": best.get("chainId", ""),
                    "pair_address": best.get("pairAddress"),
                    "dex_url": best.get("url"),
                }
                self._cashtag_cache[symbol_upper] = result
                return result

            self._cashtag_cache[symbol_upper] = None
            return None
        except Exception:
            self._cashtag_cache[symbol_upper] = None
            return None

    async def _rate_limit_dex(self) -> None:
        """Ensure minimum interval between DEX API calls."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_dex_call
        if elapsed < self._dex_call_interval:
            await asyncio.sleep(self._dex_call_interval - elapsed)

    # ── Candidate Token Management ─────────────────────────────────────

    async def _upsert_candidate(
        self,
        session: AsyncSession,
        chain: str,
        token_address: str,
        symbol: str,
        name: Optional[str],
        source: TelegramSource,
        discovery_method: DiscoveryMethod,
        pair_address: Optional[str],
        dex_url: Optional[str],
        now: datetime,
    ) -> CandidateToken:
        """Find or create a CandidateToken, merging if exists."""
        result = await session.execute(
            select(CandidateToken).where(
                CandidateToken.chain == chain,
                CandidateToken.token_address == token_address,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Merge new data (e.g., if discovered via DEX link, update pair/dex info)
            updated = False
            if pair_address and not existing.pair_address:
                existing.pair_address = pair_address
                updated = True
            if dex_url and not existing.dex_url:
                existing.dex_url = dex_url
                updated = True
            if name and not existing.name:
                existing.name = name
                updated = True
            if updated:
                existing.updated_at = now
            return existing

        candidate = CandidateToken(
            chain=chain,
            token_address=token_address,
            symbol=symbol,
            name=name,
            first_discovered_at=now,
            first_discovered_source_id=source.id,
            first_discovery_method=discovery_method,
            pair_address=pair_address,
            dex_url=dex_url,
        )
        session.add(candidate)
        await session.flush()
        return candidate

    async def _store_mention(
        self,
        session: AsyncSession,
        candidate: CandidateToken,
        source: TelegramSource,
        message: TelegramMessage,
        ref: ExtractedTokenReference,
    ) -> bool:
        """
        Store a mention. Idempotent via unique constraint.

        Returns True if a new mention was created, False if duplicate.
        """
        try:
            mention = TelegramTokenMention(
                candidate_token_id=candidate.id,
                source_id=source.id,
                telegram_message_id=message.id,
                message_timestamp=message.message_timestamp,
                sender_id_hash=message.sender_id_hash,
                discovery_method=ref.discovery_method,
                confidence=ref.confidence,
            )
            session.add(mention)
            return True
        except Exception:
            # Duplicate or constraint violation — skip
            return False

    @staticmethod
    def _infer_chain(token_address: str) -> str:
        """Infer chain from address format."""
        addr = token_address.lower()
        # EVM addresses start with 0x
        if addr.startswith("0x"):
            return "ethereum"  # Default, could be any EVM chain
        # Solana addresses are base58, 32-44 chars
        if all(c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz" for c in token_address):
            return "solana"
        return "unknown"
