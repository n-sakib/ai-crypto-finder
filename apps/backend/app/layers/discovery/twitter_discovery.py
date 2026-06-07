"""
Twitter/X Discovery — Finds tokens mentioned on Twitter.

Source: 1.3 Twitter/X Discovery
Criteria: 3D composite velocity (mentions + accounts + engagement)
Finds: cashtags, token names, contract addresses

Uses Playwright to scrape public X.com profile pages — no API key or login required.
"""

import asyncio
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.config import settings
from app.core.redis import get_redis
from app.layers.discovery.base import BaseDiscoverySource
import logging

logger = logging.getLogger(__name__)

TWITTER_BASELINE_KEY = "twitter:mention_baselines"
TWITTER_PREVIOUS_KEY = "twitter:previous_snapshot"
TWITTER_BASELINE_TTL = 7 * 24 * 3600
TWITTER_PREVIOUS_TTL = 3600

VELOCITY_WEIGHT_MENTIONS = 0.35
VELOCITY_WEIGHT_ACCOUNTS = 0.35
VELOCITY_WEIGHT_ENGAGEMENT = 0.30


class TwitterDiscovery(BaseDiscoverySource):
    """Discovers tokens from Twitter/X mentions by scraping public profile pages.

    Uses Playwright to visit x.com/{handle} and extract tweets from the DOM.
    No authentication required for public profiles.
    """

    CASHTAG_RE = re.compile(r"\$([A-Z]{2,10})\b")
    CONTRACT_ADDRESS_EVM_RE = re.compile(r"0x[a-fA-F0-9]{40}")
    CONTRACT_ADDRESS_SOL_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")

    SPAM_CASHTAGS: set[str] = {
        "GIVEAWAY", "AIRDROP", "CLAIM", "FREE", "DROP", "REWARD",
        "PRESALE", "PRESELL", "WL", "WHITELIST", "DM", "PM",
    }

    REPUTABLE_ACCOUNTS: set[str] = {
        "cz_binance", "saylor", "brian_armstrong", "vitalikbuterin",
        "stani", "haydenzadams", "aeyakovenko",
        "theunipcs", "0xdete", "murocrypto", "s4mmyeth",
        "mandoct", "zeneca", "pentosh1", "cryptohayes",
        "pauly0x", "ansem", "wale", "banditxbt", "cryptokoryo",
        "lookonchain", "spotonchain", "onchainlens", "ai_9684xtpa", "whale_alert",
        "defiignas", "route2fi", "hsakatrades",
    }
    REPUTABLE_WEIGHT = 5.0

    SEARCH_TERMS: list[str] = [
        "new launch crypto", "just launched token",
        "fair launch", "stealth launch",
        "AI agent crypto", "AI crypto token",
        "DePIN", "RWA tokenization",
        "memecoin", "meme coin 100x",
        "contract address 0x", "ca: 0x",
    ]

    SPAM_TEXT_PATTERNS: list[str] = [
        "airdrop", "giveaway", "claim now",
        "presale", "whitelist", "100x guaranteed",
        "dm me", "send dm", "join tg", "join telegram",
        "no rug", "doxxed team", "based dev",
        "send sol", "send eth",
    ]

    def __init__(self):
        self._baseline_mentions: dict[str, float] = {}
        self._baseline_accounts: dict[str, float] = {}
        self._baseline_engagement: dict[str, float] = {}

    def source_name(self) -> str:
        return "Twitter/X (Playwright)"

    async def discover(self) -> list[dict]:
        """Run discovery: scrape monitored accounts and extract token mentions."""
        await self._load_baselines()
        previous_mentions = await self._load_previous()

        # This method is called from the API server (Docker) where Playwright
        # isn't available. The actual scraping happens via collect_twitter_playwright.py
        # which runs on the host and feeds results via the /twitter/ingest API.
        # Here we return any pending results from Redis.
        candidates: list[dict] = []
        try:
            redis = await get_redis()
            raw = await redis.get("twitter:pending_candidates")
            if raw:
                import json
                candidates = json.loads(raw)
                await redis.delete("twitter:pending_candidates")
        except Exception as e:
            logger.warning("Failed to load pending Twitter candidates: %s", e)

        candidates = self._deduplicate_by_symbol(candidates)
        result = self._filter_by_velocity(candidates, previous_mentions)
        await self._save_baselines()
        await self._save_previous(candidates)
        return result

    def extract_cashtags_from_text(self, text: str) -> list[str]:
        """Extract unique cashtags from tweet text, filtering spam."""
        symbols = []
        for sym in self.CASHTAG_RE.findall(text):
            sym_u = sym.upper()
            if sym_u not in self.SPAM_CASHTAGS and len(sym_u) >= 2:
                symbols.append(sym_u)
        return list(set(symbols))

    def extract_addresses_from_text(self, text: str) -> list[tuple[str, str]]:
        """Extract contract addresses from tweet text. Returns [(address, chain), ...]."""
        addresses = []
        for addr in self.CONTRACT_ADDRESS_EVM_RE.findall(text):
            addresses.append((addr, "ethereum"))
        for addr in self.CONTRACT_ADDRESS_SOL_RE.findall(text):
            addresses.append((addr, "solana"))
        return addresses

    def _is_spam_text(self, text: str) -> bool:
        text_lower = text.lower()
        return any(p in text_lower for p in self.SPAM_TEXT_PATTERNS)

    # ── Baseline / Velocity helpers ──────────────────────────────────

    async def _load_baselines(self):
        try:
            redis = await get_redis()
            data = await redis.hgetall(TWITTER_BASELINE_KEY)
            for key, val in data.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                val_float = float(val.decode() if isinstance(val, bytes) else val)
                if key_str.startswith("mention:"):
                    self._baseline_mentions[key_str[8:]] = val_float
                elif key_str.startswith("account:"):
                    self._baseline_accounts[key_str[8:]] = val_float
                elif key_str.startswith("engage:"):
                    self._baseline_engagement[key_str[7:]] = val_float
        except Exception:
            pass

    async def _save_baselines(self):
        try:
            redis = await get_redis()
            pipe = redis.pipeline()
            for sym, val in self._baseline_mentions.items():
                pipe.hset(TWITTER_BASELINE_KEY, f"mention:{sym}", str(val))
            for sym, val in self._baseline_accounts.items():
                pipe.hset(TWITTER_BASELINE_KEY, f"account:{sym}", str(val))
            for sym, val in self._baseline_engagement.items():
                pipe.hset(TWITTER_BASELINE_KEY, f"engage:{sym}", str(val))
            pipe.expire(TWITTER_BASELINE_KEY, TWITTER_BASELINE_TTL)
            await pipe.execute()
        except Exception:
            pass

    async def _load_previous(self) -> dict[str, float]:
        try:
            redis = await get_redis()
            data = await redis.hgetall(TWITTER_PREVIOUS_KEY)
            result: dict[str, float] = {}
            for key, val in data.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                val_float = float(val.decode() if isinstance(val, bytes) else val)
                result[key_str] = val_float
            return result
        except Exception:
            return {}

    async def _save_previous(self, candidates: list[dict]):
        try:
            redis = await get_redis()
            pipe = redis.pipeline()
            pipe.delete(TWITTER_PREVIOUS_KEY)
            for c in candidates:
                sym = c.get("symbol", "")
                if sym:
                    pipe.hset(TWITTER_PREVIOUS_KEY, sym, str(c.get("mention_count", 0)))
            pipe.expire(TWITTER_PREVIOUS_KEY, TWITTER_PREVIOUS_TTL)
            await pipe.execute()
        except Exception:
            pass

    def _deduplicate_by_symbol(self, candidates: list[dict]) -> list[dict]:
        seen: dict[str, dict] = {}
        for c in candidates:
            sym = c.get("symbol", "")
            if not sym or sym == "UNKNOWN":
                continue
            if sym in seen:
                seen[sym]["mention_count"] += c.get("mention_count", 0)
                seen[sym]["unique_accounts"] = max(
                    seen[sym].get("unique_accounts", 0),
                    c.get("unique_accounts", 0),
                )
                seen[sym]["total_engagement"] += c.get("total_engagement", 0)
                seen[sym]["authority_mentions"] += c.get("authority_mentions", 0)
                existing_tweets = seen[sym].get("sample_tweets", [])
                new_tweets = c.get("sample_tweets", [])
                seen[sym]["sample_tweets"] = (existing_tweets + new_tweets)[:5]
            else:
                seen[sym] = dict(c)
        return list(seen.values())

    def _filter_by_velocity(
        self, candidates: list[dict], previous: dict[str, float],
    ) -> list[dict]:
        result = []
        for c in candidates:
            sym = c.get("symbol", "")
            mc = c.get("mention_count", 0)
            prev = previous.get(sym, 0)
            baseline = self._baseline_mentions.get(sym, 0)
            velocity = mc / max(prev, 0.01)
            c["mention_velocity"] = round(velocity, 2)
            c["baseline_mentions"] = round(baseline, 2)
            if velocity >= 1.5 or mc >= 3:
                result.append(c)
        return sorted(result, key=lambda x: x.get("mention_count", 0), reverse=True)
