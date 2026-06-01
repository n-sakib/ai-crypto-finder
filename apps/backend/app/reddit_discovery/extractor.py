"""
Reddit Token Extractor — Extracts token identifiers from Reddit posts.

Extracts:
    - Contract addresses (0x... / Solana base58 addresses)
    - DEX links (dexscreener, birdeye, gmgn, geckoterminal)
    - Cashtags ($SYMBOL)
    - Token names from narrative context
"""

from __future__ import annotations

import re
import logging
from typing import Optional

from app.config import settings
from app.reddit_discovery.models import (
    RedditDiscoveryMethod, RedditDiscoveryConfidence,
)

logger = logging.getLogger(__name__)

# ── Regex Patterns ─────────────────────────────────────────────────────

ETH_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
SOLANA_ADDRESS_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")

DEX_DOMAINS = getattr(settings, "TELEGRAM_DEX_DOMAINS", "dexscreener.com,birdeye.so,gmgn.ai,geckoterminal.com")
DEX_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?("
    + "|".join(re.escape(d.strip()) for d in DEX_DOMAINS.split(","))
    + r")/\S*"
)

CASHTAG_RE = re.compile(r"\$([A-Z]{2,12})\b")

# Known chain prefixes for contract addresses
CHAIN_FOCUS = getattr(settings, "TELEGRAM_CHAIN_FOCUS", "solana,base,ethereum,bsc")
FOCUS_CHAINS = [c.strip() for c in CHAIN_FOCUS.split(",")]


class RedditTokenExtractor:
    """Extracts token identifiers from Reddit post text."""

    def __init__(self):
        pass

    def extract(self, post_text: str, post_title: str = "") -> list[dict]:
        """
        Extract token references from Reddit post text.

        Returns a list of dicts with:
            - discovery_method
            - confidence
            - chain
            - token_address
            - symbol
            - name
            - dex_url
            - raw_value
        """
        # Combine title and body for extraction, with title weighted higher
        text = f"{post_title}\n{post_title}\n{post_text}"
        results: list[dict] = []

        results.extend(self._extract_dex_links(text))
        results.extend(self._extract_contract_addresses(text))
        results.extend(self._extract_cashtags(text))

        # Deduplicate by token_address (or by raw_value if no address)
        seen: set[str] = set()
        deduped: list[dict] = []
        for r in results:
            key = r.get("token_address") or r.get("raw_value", "")
            if key and key not in seen:
                seen.add(key)
                deduped.append(r)

        return deduped

    def _extract_contract_addresses(self, text: str) -> list[dict]:
        """Extract Ethereum and Solana contract addresses."""
        results: list[dict] = []

        # Ethereum addresses
        for match in ETH_ADDRESS_RE.finditer(text):
            addr = match.group(0)
            results.append({
                "discovery_method": RedditDiscoveryMethod.CONTRACT_ADDRESS.value,
                "confidence": RedditDiscoveryConfidence.VERY_HIGH.value,
                "chain": "ethereum",
                "token_address": addr,
                "symbol": None,
                "name": None,
                "dex_url": None,
                "raw_value": addr,
            })

        # Solana addresses
        for match in SOLANA_ADDRESS_RE.finditer(text):
            addr = match.group(0)
            # Exclude known non-address patterns
            if self._looks_like_solana_address(addr):
                results.append({
                    "discovery_method": RedditDiscoveryMethod.CONTRACT_ADDRESS.value,
                    "confidence": RedditDiscoveryConfidence.VERY_HIGH.value,
                    "chain": "solana",
                    "token_address": addr,
                    "symbol": None,
                    "name": None,
                    "dex_url": None,
                    "raw_value": addr,
                })

        return results

    def _extract_dex_links(self, text: str) -> list[dict]:
        """Extract DEX screener/birdeye/etc links."""
        results: list[dict] = []
        for match in DEX_URL_PATTERN.finditer(text):
            url = match.group(0)
            domain = match.group(1)

            # Try to extract chain + address from the URL
            chain = None
            token_address = None

            # dexscreener.com/{chain}/{address}
            dexscreener = re.search(r"dexscreener\.com/(\w+)/([0-9a-zA-Z]+)", url)
            if dexscreener:
                chain = dexscreener.group(1).lower()
                token_address = dexscreener.group(2)
            else:
                # Generic: try to find an address in the URL path
                addr_match = re.search(r"/(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})", url)
                if addr_match:
                    token_address = addr_match.group(1)
                    # Guess chain from address format
                    if token_address.startswith("0x"):
                        chain = "ethereum"
                    else:
                        chain = "solana"

            results.append({
                "discovery_method": RedditDiscoveryMethod.DEX_LINK.value,
                "confidence": RedditDiscoveryConfidence.HIGH.value,
                "chain": chain or "ethereum",
                "token_address": token_address,
                "symbol": None,
                "name": None,
                "dex_url": url,
                "raw_value": url,
            })

        return results

    def _extract_cashtags(self, text: str) -> list[dict]:
        """Extract $SYMBOL cashtags."""
        results: list[dict] = []
        for match in CASHTAG_RE.finditer(text):
            symbol = match.group(1)
            # Filter out common non-token cashtags
            if symbol.upper() in {"USD", "EUR", "BTC", "ETH", "SOL", "BNB", "USDT", "USDC"}:
                continue
            results.append({
                "discovery_method": RedditDiscoveryMethod.CASHTAG.value,
                "confidence": RedditDiscoveryConfidence.MEDIUM.value,
                "chain": None,
                "token_address": None,
                "symbol": symbol.upper(),
                "name": None,
                "dex_url": None,
                "raw_value": f"${symbol}",
            })
        return results

    def _looks_like_solana_address(self, s: str) -> bool:
        """Heuristic check: does this string look like a Solana base58 address?"""
        if len(s) < 32 or len(s) > 44:
            return False
        # Must contain both letters and numbers
        has_letter = any(c.isalpha() for c in s)
        has_digit = any(c.isdigit() for c in s)
        return has_letter and has_digit
