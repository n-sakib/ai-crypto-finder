"""
TokenExtractor — Extracts token identifiers from Telegram message text.

Detection targets (priority order):
    1. EVM contract addresses (0x + 40 hex chars)     — confidence: very_high
    2. Solana-style addresses (base58, 32-44 chars)   — confidence: very_high
    3. DEX links (configurable domains)               — confidence: very_high
    4. Cashtags ($SYMBOL, 2-15 alphanumeric chars)    — confidence: medium
    5. Token names (optional, low confidence)          — confidence: low

Configurable via env vars:
    TELEGRAM_DEX_DOMAINS — DEX link domains to detect
    TELEGRAM_DISCOVERY_TERMS — keywords for extraction boosting
    TELEGRAM_NARRATIVE_TERMS — narrative keywords for tagging
"""

from __future__ import annotations

import re
import hashlib
import logging
from typing import Optional
from urllib.parse import urlparse

from app.telegram_discovery.models import DiscoveryMethod, DiscoveryConfidence
from app.telegram_discovery.schemas import ExtractedTokenReference

logger = logging.getLogger(__name__)

# ── Compiled Regex Patterns ────────────────────────────────────────────

# EVM address: 0x followed by exactly 40 hex characters
# Uses lookbehind/lookahead to also match addresses in URLs (after / or -)
EVM_ADDRESS_RE = re.compile(r"(?<![a-zA-Z0-9])(0x[a-fA-F0-9]{40})(?![a-zA-Z0-9])")

# Solana-style address: base58 string, 32-44 chars
# Uses non-word-boundary matching to capture addresses in URLs (/solana/ADDR, SOL-ADDR)
SOLANA_ADDRESS_RE = re.compile(r"(?<![a-zA-Z0-9])([1-9A-HJ-NP-Za-km-z]{32,44})(?![a-zA-Z0-9])")

# Cashtags: $ followed by 2-15 uppercase/lowercase alphanumeric chars
CASHTAG_RE = re.compile(r"\$([A-Za-z]{2,15})\b")

# DEX URL pattern: built dynamically from configured domains
# Falls back to default domains if config is empty

# Non-address words to exclude from Solana address matching
NON_ADDRESS_WORDS = re.compile(
    r"^(https?|www|http|com|org|io|net|tg|me|join|channel|group|bot|"
    r"admin|owner|moderator|subscribe|forward|message)$",
    re.IGNORECASE,
)


class TokenExtractor:
    """
    Extracts token identifiers from raw Telegram message text.

    Priority order:
        1. Contract addresses (very_high)
        2. DEX links (very_high)
        3. Cashtags (medium)
        4. Token names (low, optional)

    All domains and keywords are configurable via env vars.

    Usage:
        extractor = TokenExtractor()
        refs = extractor.extract("Check out $PEPE at 0x1234...abc on dexscreener.com/...")
    """

    def __init__(self) -> None:
        self._dex_domains: list[str] = []
        self._dex_url_re: Optional[re.Pattern] = None
        self._discovery_terms: list[str] = []
        self._narrative_terms: list[str] = []
        self._chain_focus: list[str] = []
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy-load config to avoid import-time settings access."""
        if self._initialized:
            return
        from app.telegram_discovery.config import (
            get_dex_domains, get_discovery_terms,
            get_narrative_terms, get_chain_focus,
        )
        self._dex_domains = get_dex_domains()
        self._discovery_terms = get_discovery_terms()
        self._narrative_terms = get_narrative_terms()
        self._chain_focus = get_chain_focus()

        # Build DEX URL regex from configured domains
        if self._dex_domains:
            escaped = [re.escape(d) for d in self._dex_domains]
            pattern = r"https?://(?:www\.)?(" + "|".join(escaped) + r")[/\S]*"
            self._dex_url_re = re.compile(pattern, re.IGNORECASE)
        self._initialized = True

    # ── Public API ────────────────────────────────────────────────────

    def extract(self, text: str) -> list[ExtractedTokenReference]:
        """
        Extract all token references from a message text.

        Returns a list of ExtractedTokenReference objects.
        Deduplication: if the same address appears via both EVM pattern and
        DEX link, both references are returned (resolver handles merging).
        """
        self._ensure_initialized()

        if not text:
            return []

        refs: list[ExtractedTokenReference] = []

        # Priority 1: Contract addresses
        refs.extend(self._extract_evm_addresses(text))
        refs.extend(self._extract_solana_addresses(text))

        # Priority 2: DEX links
        refs.extend(self._extract_dex_links(text))

        # Priority 3: Cashtags
        refs.extend(self._extract_cashtags(text))

        # Priority 4: Token names (low confidence, optional)
        # refs.extend(self._extract_token_names(text))

        return refs

    def is_discovery_context(self, text: str) -> bool:
        """
        Check if a message contains discovery-related keywords.

        Used to boost/prioritize messages that are likely about token discovery.
        """
        self._ensure_initialized()
        text_lower = text.lower()
        return any(term in text_lower for term in self._discovery_terms)

    def get_narrative_tags(self, text: str) -> list[str]:
        """
        Extract narrative tags from message text.

        Returns list of matching narrative terms (e.g., ['ai', 'rwa']).
        """
        self._ensure_initialized()
        text_lower = text.lower()
        return [term for term in self._narrative_terms if term in text_lower]

    def get_chain_tags(self, text: str) -> list[str]:
        """
        Extract chain mentions from message text.

        Returns list of matching chain names (e.g., ['solana', 'base']).
        """
        self._ensure_initialized()
        text_lower = text.lower()
        return [chain for chain in self._chain_focus if chain in text_lower]

    # ── Private Extraction Methods ────────────────────────────────────

    def _extract_evm_addresses(self, text: str) -> list[ExtractedTokenReference]:
        """Extract EVM contract addresses (0x...), including from URLs."""
        refs: list[ExtractedTokenReference] = []
        seen: set[str] = set()

        for match in EVM_ADDRESS_RE.finditer(text):
            addr = match.group(1).lower()  # group 1 is the address only
            if addr in seen:
                continue
            seen.add(addr)

            refs.append(ExtractedTokenReference(
                discovery_method=DiscoveryMethod.CONTRACT_ADDRESS,
                confidence=DiscoveryConfidence.VERY_HIGH,
                chain=None,
                token_address=addr,
                raw_value=addr,
            ))

        return refs

    def _extract_solana_addresses(self, text: str) -> list[ExtractedTokenReference]:
        """Extract Solana-style base58 addresses, including from URLs."""
        refs: list[ExtractedTokenReference] = []
        seen: set[str] = set()

        for match in SOLANA_ADDRESS_RE.finditer(text):
            candidate = match.group(1)  # group 1 is the address only

            # Skip if it looks like a common word
            if NON_ADDRESS_WORDS.match(candidate):
                continue

            if candidate in seen:
                continue
            seen.add(candidate)

            refs.append(ExtractedTokenReference(
                discovery_method=DiscoveryMethod.CONTRACT_ADDRESS,
                confidence=DiscoveryConfidence.VERY_HIGH,
                chain="solana",  # Assume Solana for base58 addresses
                token_address=candidate,
                raw_value=candidate,
            ))

        return refs

    def _extract_dex_links(self, text: str) -> list[ExtractedTokenReference]:
        """Extract and parse DEX links (domains from TELEGRAM_DEX_DOMAINS)."""
        refs: list[ExtractedTokenReference] = []
        seen_urls: set[str] = set()

        if not self._dex_url_re:
            return refs

        for match in self._dex_url_re.finditer(text):
            url = match.group(0).rstrip(".,;:!?\"')]}")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            parsed = self._parse_dex_url(url)
            refs.append(ExtractedTokenReference(
                discovery_method=DiscoveryMethod.DEX_LINK,
                confidence=DiscoveryConfidence.VERY_HIGH,
                chain=parsed.get("chain"),
                token_address=parsed.get("token_address"),
                pair_address=parsed.get("pair_address"),
                dex_url=url,
                raw_value=url,
            ))

        return refs

    def _extract_cashtags(self, text: str) -> list[ExtractedTokenReference]:
        """Extract cashtags ($SYMBOL)."""
        refs: list[ExtractedTokenReference] = []
        seen: set[str] = set()

        for match in CASHTAG_RE.finditer(text):
            symbol = match.group(1).upper()

            # Skip common non-token symbols
            if self._is_common_non_token(symbol):
                continue

            if symbol in seen:
                continue
            seen.add(symbol)

            refs.append(ExtractedTokenReference(
                discovery_method=DiscoveryMethod.CASHTAG,
                confidence=DiscoveryConfidence.MEDIUM,
                symbol=symbol,
                raw_value=f"${symbol}",
            ))

        return refs

    # ── Helper Methods ────────────────────────────────────────────────

    def _parse_dex_url(self, url: str) -> dict:
        """
        Parse a DEX link to extract chain and token address.

        Supports:
            - dexscreener.com/{chain}/{pair_address}
            - dexscreener.com/{chain}/{token_address}
            - birdeye.so/token/{token_address}?chain={chain}
            - gmgn.ai/{chain}/token/{token_address}
            - geckoterminal.com/{chain}/pools/{pair_address}
        """
        result: dict = {}
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().replace("www.", "")

            if "dexscreener.com" in host:
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    result["chain"] = parts[0].lower()
                    # The second part could be token or pair address
                    result["token_address"] = parts[1]
                    result["pair_address"] = parts[1]  # could be either

            elif "birdeye.so" in host:
                parts = [p for p in parsed.path.split("/") if p]
                if "token" in parts:
                    idx = parts.index("token")
                    if idx + 1 < len(parts):
                        result["token_address"] = parts[idx + 1]
                # Check query string for chain
                from urllib.parse import parse_qs
                qs = parse_qs(parsed.query)
                if "chain" in qs:
                    result["chain"] = qs["chain"][0].lower()

            elif "gmgn.ai" in host:
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 3 and parts[1] == "token":
                    result["chain"] = parts[0].lower()
                    result["token_address"] = parts[2]
                elif len(parts) >= 2:
                    result["chain"] = parts[0].lower()
                    result["token_address"] = parts[1] if len(parts) > 1 else None

            elif "geckoterminal.com" in host:
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    result["chain"] = parts[0].lower()
                if "pools" in parts:
                    idx = parts.index("pools")
                    if idx + 1 < len(parts):
                        result["pair_address"] = parts[idx + 1]

        except Exception:
            pass

        return result

    @staticmethod
    def _is_part_of_url(text: str, start: int, end: int) -> bool:
        """Check if a match is part of a URL."""
        before = text[max(0, start - 10):start]
        after = text[end:end + 10]
        return "http://" in before or "https://" in before or ".com" in after[:10]

    @staticmethod
    def _is_common_non_token(symbol: str) -> bool:
        """Filter out common non-token cashtags."""
        common = {
            "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CNY", "RUB",
            "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "DOT",
            "USDT", "USDC", "BUSD", "DAI",
            "LONG", "SHORT", "BUY", "SELL", "HOLD",
            "DEFI", "NFT", "WEB3", "AI", "CEO", "CTO",
            "TG", "DM", "AMA", "KYC", "KYB", "CEX", "DEX",
        }
        return symbol.upper() in common

    @staticmethod
    def hash_text(text: str) -> str:
        """Create a SHA-256 hash of message text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_sender_id(sender_id: int) -> str:
        """Hash a sender ID for privacy-preserving storage."""
        return hashlib.sha256(str(sender_id).encode("utf-8")).hexdigest()
