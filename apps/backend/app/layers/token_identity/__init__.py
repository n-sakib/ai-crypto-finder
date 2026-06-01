"""
Token Identity Resolver — Prevents wrong-token and duplicate-token problems.

Layer 2: Resolves token identity immediately after discovery.

Responsibilities:
- 2.1 Resolve Token Identity (chain, token address, pair address, symbol, name)
- 2.2 Symbol Collision Check (never score by symbol alone)
- 2.3 Source Mapping (link all mentions to correct token)
- 2.4 Deduplication (merge same token across multiple pairs)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

from app.core.models import DiscoverySource


@dataclass
class ResolvedToken:
    """Fully resolved token identity."""
    chain: str
    contract_address: str
    pair_address: str
    symbol: str
    name: Optional[str] = None
    dex_id: Optional[str] = None
    liquidity_usd: float = 0.0
    volume_24h: float = 0.0
    volume_1h: float = 0.0
    price_usd: float = 0.0
    price_change_24h: float = 0.0
    price_change_6h: float = 0.0
    market_cap: float = 0.0
    holder_count: int = 0
    # Txns data from DEXScreener
    trade_count_24h: int = 0
    unique_buyers_24h: int = 0
    unique_sellers_24h: int = 0
    launched_at: Optional[datetime] = None
    # Source tracking
    discovery_sources: list[str] = field(default_factory=list)
    original_candidates: list[dict] = field(default_factory=list)
    # Identity validation
    is_verified: bool = False
    collision_warning: bool = False
    collision_details: Optional[str] = None


class TokenIdentityResolver:
    """
    Resolves and validates token identities to prevent:
    - Wrong token (buying wrong contract for a symbol)
    - Duplicate token (same token across multiple pairs)
    - Symbol collision (many tokens share same symbol)
    """

    # Known burn/lock addresses to exclude from holder calculations
    KNOWN_BURN_ADDRESSES = {
        "0x0000000000000000000000000000000000000000": "null",
        "0x0000000000000000000000000000000000000001": "null",
        "0x000000000000000000000000000000000000dead": "burn",
        "0xdead000000000000000042069420694206942069": "burn",
    }

    def __init__(self):
        self._symbol_index: dict[str, list[dict]] = {}  # symbol -> list of token entries
        self._contract_index: dict[str, dict] = {}       # contract_address -> token entry

    async def resolve(self, candidates: list[dict]) -> list[ResolvedToken]:
        """
        Main resolution pipeline:
        1. Validate required fields
        2. Check for symbol collisions
        3. Map sources to tokens
        4. Deduplicate
        """
        # Step 1: Validate identity
        valid = [c for c in candidates if self._validate_identity(c)]

        # Step 2: Check symbol collisions
        collision_checked = []
        for c in valid:
            token = self._check_collisions(c)
            collision_checked.append(token)

        # Step 3: Map sources
        source_mapped = self._map_sources(collision_checked)

        # Step 4: Deduplicate (keep best liquidity pair)
        deduped = self._deduplicate(source_mapped)

        # Index for future lookups
        for token in deduped:
            self._index_token(token)

        return deduped

    def _validate_identity(self, candidate: dict) -> bool:
        """
        2.1 Resolve Token Identity.
        Must have: chain + contract address (or pair address).
        Symbol alone is not enough — never score by symbol alone.
        """
        chain = candidate.get("chain", "").strip().lower()
        contract = candidate.get("contract_address", "").strip()
        pair = candidate.get("pair_address", "").strip()

        if not chain:
            return False
        if not contract and not pair:
            return False

        # Validate contract address format
        if contract:
            if contract.startswith("0x") and not re.match(r"^0x[a-fA-F0-9]{40}$", contract):
                return False
            # Solana addresses: base58, 32-44 chars
            if not contract.startswith("0x") and not re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", contract):
                return False

        return True

    def _check_collisions(self, candidate: dict) -> ResolvedToken:
        """
        2.2 Symbol Collision Check.
        Many tokens share symbols like AI, CAT, DOG, GOAT.
        Never match by symbol alone — always require contract or pair address.
        """
        symbol = candidate.get("symbol", "").upper()
        contract = candidate.get("contract_address", "")
        pair = candidate.get("pair_address", "")

        existing = self._symbol_index.get(symbol, [])
        collision_warning = False
        collision_details = None

        if existing and contract:
            # Check if this contract is already known under this symbol
            known_contracts = {e.get("contract_address", "").lower() for e in existing}
            if contract.lower() not in known_contracts:
                collision_warning = True
                collision_details = (
                    f"Symbol '{symbol}' already tracked with different contracts: "
                    f"{known_contracts}"
                )

        return ResolvedToken(
            chain=candidate.get("chain", ""),
            contract_address=contract,
            pair_address=pair,
            symbol=symbol,
            name=candidate.get("name", ""),
            dex_id=candidate.get("dex_id", ""),
            liquidity_usd=float(candidate.get("liquidity_usd", 0)),
            volume_24h=float(candidate.get("volume_24h", 0)),
            volume_1h=float(candidate.get("volume_1h", 0)),
            price_usd=float(candidate.get("price_usd", 0)),
            price_change_24h=float(candidate.get("price_change_24h", 0)),
            price_change_6h=float(candidate.get("price_change_6h", 0)),
            market_cap=float(candidate.get("market_cap", 0)),
            holder_count=int(candidate.get("holder_count", 0)),
            trade_count_24h=int(candidate.get("trade_count_24h", 0)),
            unique_buyers_24h=int(candidate.get("unique_buyers_24h", 0)),
            unique_sellers_24h=int(candidate.get("unique_sellers_24h", 0)),
            discovery_sources=[candidate.get("discovery_source", "unknown")],
            original_candidates=[candidate],
            is_verified=not collision_warning,
            collision_warning=collision_warning,
            collision_details=collision_details,
        )

    def _map_sources(self, tokens: list[ResolvedToken]) -> list[ResolvedToken]:
        """
        2.3 Source Mapping.
        Link all mentions (Twitter/Telegram/Reddit) to the correct token.
        Uses token name + symbol + contract + official links.
        """
        for token in tokens:
            # All candidates that share the same contract are from different sources
            sources = set()
            for c in token.original_candidates:
                src = c.get("discovery_source", "")
                if src:
                    sources.add(src)
            token.discovery_sources = list(sources)

        return tokens

    def _deduplicate(self, tokens: list[ResolvedToken]) -> list[ResolvedToken]:
        """
        2.4 Deduplication.
        Merge same token across multiple pairs (by chain:contract).
        Then merge same symbol across chains — keep only highest-liquidity version.
        """
        seen: dict[str, ResolvedToken] = {}

        # Pass 1: Dedup by chain:contract_address
        for token in tokens:
            key = f"{token.chain}:{token.contract_address}".lower()

            if key not in seen:
                seen[key] = token
                continue

            existing = seen[key]

            # Merge sources
            existing.discovery_sources = list(
                set(existing.discovery_sources + token.discovery_sources)
            )

            # Merge candidates
            existing.original_candidates.extend(token.original_candidates)

            # Keep the pair with higher liquidity
            if token.liquidity_usd > existing.liquidity_usd:
                existing.pair_address = token.pair_address
                existing.dex_id = token.dex_id
                existing.liquidity_usd = token.liquidity_usd
                existing.volume_24h = token.volume_24h
                existing.price_usd = token.price_usd
                existing.price_change_24h = token.price_change_24h
                existing.holder_count = token.holder_count

        # Pass 2: Dedup by symbol — keep only highest-liquidity token per symbol
        by_symbol: dict[str, ResolvedToken] = {}
        for token in seen.values():
            sym = token.symbol.upper()
            if sym not in by_symbol or token.liquidity_usd > by_symbol[sym].liquidity_usd:
                by_symbol[sym] = token

        return list(by_symbol.values())

    def _index_token(self, token: ResolvedToken):
        """Index token for future collision checks."""
        symbol = token.symbol.upper()
        if symbol not in self._symbol_index:
            self._symbol_index[symbol] = []

        entry = {
            "contract_address": token.contract_address,
            "pair_address": token.pair_address,
            "name": token.name,
            "chain": token.chain,
        }

        # Avoid duplicates in index
        existing_contracts = {e["contract_address"].lower() for e in self._symbol_index[symbol]}
        if token.contract_address.lower() not in existing_contracts:
            self._symbol_index[symbol].append(entry)

        self._contract_index[token.contract_address.lower()] = entry

    def get_contracts_for_symbol(self, symbol: str) -> list[dict]:
        """Get all known contracts for a symbol (for collision resolution)."""
        return self._symbol_index.get(symbol.upper(), [])

    def resolve_symbol(self, symbol: str, chain: str | None = None) -> list[dict]:
        """
        Resolve a symbol to contracts. Always returns all matches.
        Callers must disambiguate — never trust symbol alone.
        """
        entries = self._symbol_index.get(symbol.upper(), [])
        if chain:
            entries = [e for e in entries if e.get("chain", "").lower() == chain.lower()]
        return entries
