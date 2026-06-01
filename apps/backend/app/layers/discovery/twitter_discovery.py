"""
Twitter/X Discovery — Finds tokens mentioned on Twitter.

Source: 1.3 Twitter/X Discovery
Criteria: 3D composite velocity (mentions + accounts + engagement)
Finds: cashtags, token names, contract addresses

Uses Twikit (free scraping) — no API key required.
https://github.com/d60/twikit

Set TWITTER_USERNAME + TWITTER_PASSWORD in .env to enable.
"""

import asyncio
import json
import os
import re
from collections import Counter
from typing import Optional

from app.config import settings
from app.core.redis import get_redis
from app.layers.discovery.base import BaseDiscoverySource

# Redis keys for Twitter discovery
TWITTER_BASELINE_KEY = "twitter:mention_baselines"
TWITTER_PREVIOUS_KEY = "twitter:previous_snapshot"
TWITTER_BASELINE_TTL = 7 * 24 * 3600
TWITTER_PREVIOUS_TTL = 3600

# Twikit cookies file — persists login session across runs
TWIKIT_COOKIES_FILE = os.path.join(os.path.dirname(__file__), ".twikit_cookies.json")

# ── 3-Dimension Velocity Weights ─────────────────────
VELOCITY_WEIGHT_MENTIONS = 0.35
VELOCITY_WEIGHT_ACCOUNTS = 0.35
VELOCITY_WEIGHT_ENGAGEMENT = 0.30


class TwitterDiscovery(BaseDiscoverySource):
    """
    Discovers tokens from Twitter/X mentions.

    Searches for cashtags ($TOKEN), contract addresses, and crypto keywords.
    Uses Twitter API v2 recent search (free tier, last 7 days).
    Filters by mention velocity vs stored baseline.

    Rate limits: 450 requests per 15-minute window (app-only auth).
    Each search query counts as 1 request regardless of result count.
    """

    # Regex patterns for extracting tokens from tweet text
    CASHTAG_RE = re.compile(r"\$([A-Z]{2,10})\b")
    CONTRACT_ADDRESS_EVM_RE = re.compile(r"0x[a-fA-F0-9]{40}")
    CONTRACT_ADDRESS_SOL_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")

    # Known spam/scam cashtags to ignore
    SPAM_CASHTAGS: set[str] = {
        "GIVEAWAY", "AIRDROP", "CLAIM", "FREE", "DROP", "REWARD",
        "PRESALE", "PRESELL", "WL", "WHITELIST", "DM", "PM",
    }

    # ── Authority System ────────────────────────────────
    # Reputable crypto accounts whose mentions carry extra weight.
    # These are founders, VCs, exchanges, and known analysts — people
    # whose follows/mentions signal legitimacy (mutuals are hard to fake).
    # Usernames are lowercase, matched against tweet author_id or text.
    REPUTABLE_ACCOUNTS: set[str] = {
        # Tier 1 — CEX founders & execs
        "cz_binance", "saylor", "brian_armstrong", "tyler", "cameron",
        "justinsuntron", "heyibinance",
        # Tier 1 — VC / fund partners
        "cdixon", "balajis", "pmarca", "novogratz", "zhusu",
        "hasufl", "cobie", "dcfgod", "donalt", "zackvoell",
        "0xmons", "doveywan", "iamdcfr", "gokunocool",
        # Tier 1 — DeFi / infra founders
        "vitalikbuterin", "stani", "haydenzadams", "rleshner",
        "kaiynne", "sandeepnailwal", "toghrulmaharram",
        "aeyakovenko", "0xmid", "kainwarwick",
        "kmets_", "0xlawliet", "defiignas",
        # Tier 2 — Respected analysts / researchers
        "rektcapital", "intocryptoverse", "cryptodog",
        "inversebrah", "macnbtc", "traderxz", "cryptokaleo",
        "thecryptodog", "hsakatrades", "bluntzcapital",
        "cryptocobain", "0xngmi", "thiccyth0t",
        "route2fi", "alphapls", "defi_mochi",
        # Tier 3 — On-chain sleuths / security
        "zachxbt", "peckshield", "certikalert", "slowmist_team",
        "lookonchain", "spotonchain", "nansen_ai", "arkhamintel",
        "duneanalytics", "messaricrypto", "santimentfeed",
        # Exchanges / platforms
        "binance", "coinbase", "krakenfx", "kucoin", "bybit_official",
        "okx", "bitgetglobal", "gate_io", "mexc_official",
    }
    # Multiplier for mentions from reputable accounts
    REPUTABLE_WEIGHT = 5.0

    # ── Spam patterns ───────────────────────────────────
    # Text patterns that indicate scam/pump-and-dump content
    SPAM_TEXT_PATTERNS: list[str] = [
        "airdrop", "giveaway", "claim now", "free nft",
        "presale", "whitelist", "100x guaranteed", "1000x guaranteed",
        "dm me", "send dm", "join tg", "join telegram",
        "only 10 spots", "limited supply", "buy before",
        "no rug", "doxxed team", "based dev",
        "send sol", "send eth",
    ]
    # Link patterns — tweets that are just link dumps
    LINK_ONLY_PATTERNS: list[str] = [
        "t.me/", "discord.gg/", "dexscreener.com/",
        "dextools.io/", "birdeye.so/", "pump.fun/",
    ]

    def __init__(self):
        self._baseline_mentions: dict[str, float] = {}
        self._baseline_accounts: dict[str, float] = {}
        self._baseline_engagement: dict[str, float] = {}
        self._twikit_client = None  # lazy-init

    def source_name(self) -> str:
        return "Twitter/X (Twikit)" if settings.TWITTER_USERNAME else "Twitter/X (disabled — set TWITTER_USERNAME)"

    async def _get_twikit_client(self):
        """Get or create a twikit Client (lazy, reuses cookies)."""
        if self._twikit_client is not None:
            return self._twikit_client

        from twikit import Client as TwikitClient

        client = TwikitClient("en-US")

        if os.path.exists(TWIKIT_COOKIES_FILE):
            try:
                client.load_cookies(TWIKIT_COOKIES_FILE)
                await client.user()
                self._twikit_client = client
                return client
            except Exception:
                pass

        if settings.TWITTER_USERNAME and settings.TWITTER_PASSWORD:
            try:
                await client.login(
                    auth_info_1=settings.TWITTER_USERNAME,
                    auth_info_2=settings.TWITTER_EMAIL or settings.TWITTER_USERNAME,
                    password=settings.TWITTER_PASSWORD,
                    cookies_file=TWIKIT_COOKIES_FILE,
                )
                client.save_cookies(TWIKIT_COOKIES_FILE)
                self._twikit_client = client
                return client
            except Exception:
                pass

        return None

    # ── Public API ──────────────────────────────────────

    async def discover(self) -> list[dict]:
        """
        Search Twitter for crypto token mentions via Twikit (free scraping).
        """
        await self._load_baselines()
        previous_mentions = await self._load_previous()

        kw, addr = await asyncio.gather(
            self._search_keywords_twikit(),
            self._search_addresses_twikit(),
            return_exceptions=True,
        )

        candidates: list[dict] = []
        if isinstance(kw, list):
            candidates.extend(kw)
        if isinstance(addr, list):
            candidates.extend(addr)

        candidates = self._deduplicate_by_symbol(candidates)
        result = self._filter_by_velocity(candidates, previous_mentions)

        await self._save_baselines()
        await self._save_previous(candidates)

        return result

    def update_baselines(self, mention_counts: dict[str, float]):
        """Update mention baselines for velocity calculation."""
        self._baseline_mentions.update(mention_counts)

    # ── Baselines (Redis-backed) ────────────────────────

    async def _load_baselines(self):
        """Load stored baselines from Redis. Supports legacy (1D) and new (3D) formats."""
        try:
            redis = await get_redis()
            raw = await redis.get(TWITTER_BASELINE_KEY)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    # Check if legacy format: {symbol: float} → convert to 3D
                    first_val = next(iter(data.values()), None) if data else None
                    if isinstance(first_val, (int, float)):
                        self._baseline_mentions = data
                        self._baseline_accounts = {}
                        self._baseline_engagement = {}
                    else:
                        self._baseline_mentions = data.get("mentions", {})
                        self._baseline_accounts = data.get("accounts", {})
                        self._baseline_engagement = data.get("engagement", {})
        except Exception:
            self._baseline_mentions = {}
            self._baseline_accounts = {}
            self._baseline_engagement = {}

    async def _save_baselines(self):
        """Save 3D baselines to Redis."""
        try:
            redis = await get_redis()
            await redis.set(
                TWITTER_BASELINE_KEY,
                json.dumps({
                    "mentions": self._baseline_mentions,
                    "accounts": self._baseline_accounts,
                    "engagement": self._baseline_engagement,
                }),
                ex=TWITTER_BASELINE_TTL,
            )
        except Exception:
            pass

    async def _load_previous(self) -> dict:
        """Load previous run's 3D snapshot: {symbol: {m, a, e}}."""
        try:
            redis = await get_redis()
            raw = await redis.get(TWITTER_PREVIOUS_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return {}

    async def _save_previous(self, candidates: list[dict]):
        """Save 3D snapshot for next acceleration calc."""
        snapshot: dict[str, dict] = {}
        for c in candidates:
            sym = c.get("symbol", "")
            if sym:
                snapshot[sym] = {
                    "m": c.get("mention_count", 0),
                    "a": c.get("unique_accounts", 0),
                    "e": c.get("total_engagement", 0),
                }
        try:
            redis = await get_redis()
            await redis.set(
                TWITTER_PREVIOUS_KEY,
                json.dumps(snapshot),
                ex=TWITTER_PREVIOUS_TTL,
            )
        except Exception:
            pass

    # ── Twikit Search ───────────────────────────────────

    # Search terms for twikit (simple strings, no advanced operators)
    TWIKIT_SEARCH_TERMS: list[str] = [
        "$PEPE", "$WIF", "$BONK", "$GOAT", "$TAO", "$AERO",
        "$SOL", "$ETH", "$BTC", "$BNB", "$SUI", "$APT",
        "$DOGE", "$SHIB", "$FLOKI",
        "new launch crypto", "just launched token",
        "fair launch", "stealth launch",
        "AI agent crypto", "AI crypto token",
        "DePIN", "RWA tokenization",
        "memecoin", "meme coin 100x",
        "contract address 0x", "ca: 0x",
    ]

    async def _search_twikit(self, query: str, max_tweets: int = 30) -> list:
        """Search Twitter via twikit scraping. Returns list of Tweet objects."""
        client = await self._get_twikit_client()
        if client is None:
            return []
        try:
            tweets = await client.search_tweet(query, "Latest")
            # Collect up to max_tweets
            results = []
            count = 0
            async for tweet in tweets:
                results.append(tweet)
                count += 1
                if count >= max_tweets:
                    break
            return results
        except Exception:
            return []

    async def _search_keywords_twikit(self) -> list[dict]:
        """Search Twitter via twikit for crypto keywords — tracks 3D velocity."""
        mention_counter: Counter = Counter()
        engagement_counter: Counter = Counter()
        unique_accounts: dict[str, set[str]] = {}
        authority_counter: Counter = Counter()
        tweet_samples: dict[str, list[str]] = {}

        for query in self.TWIKIT_SEARCH_TERMS:
            try:
                tweets = await self._search_twikit(query)
                for tweet in tweets:
                    text = getattr(tweet, "text", "") or ""
                    user = getattr(tweet, "user", None)
                    author_id = getattr(user, "id", "") if user else ""
                    author_name = getattr(user, "name", "") if user else ""

                    if not text or self._is_spam_text(text):
                        continue

                    engagement = (
                        getattr(tweet, "retweet_count", 0) or 0
                        + (getattr(tweet, "like_count", 0) or 0)
                        + (getattr(tweet, "reply_count", 0) or 0)
                    )

                    # Check authority by author name
                    is_reputable = self._is_reputable_account("", author_name)
                    authority_bonus = self.REPUTABLE_WEIGHT if is_reputable else 1.0

                    found = self.CASHTAG_RE.findall(text)
                    for symbol in found:
                        symbol_upper = symbol.upper()
                        if symbol_upper in self.SPAM_CASHTAGS or len(symbol_upper) < 2:
                            continue

                        mention_counter[symbol_upper] += authority_bonus
                        engagement_counter[symbol_upper] += engagement * authority_bonus

                        if symbol_upper not in unique_accounts:
                            unique_accounts[symbol_upper] = set()
                        if author_id:
                            unique_accounts[symbol_upper].add(str(author_id))

                        if is_reputable:
                            authority_counter[symbol_upper] += 1
                        if symbol_upper not in tweet_samples:
                            tweet_samples[symbol_upper] = []
                        if len(tweet_samples[symbol_upper]) < 3:
                            prefix = "🔷 " if is_reputable else ""
                            tweet_samples[symbol_upper].append(prefix + text[:200])

            except Exception:
                continue

        candidates = []
        for symbol in mention_counter:
            mc = mention_counter[symbol]
            if mc < 1.5:
                continue
            candidates.append({
                "symbol": symbol,
                "contract_address": "",
                "chain": "",
                "mention_count": mc,
                "unique_accounts": len(unique_accounts.get(symbol, set())),
                "total_engagement": engagement_counter.get(symbol, 0),
                "authority_mentions": authority_counter.get(symbol, 0),
                "source": "twikit_cashtag",
                "sample_tweets": tweet_samples.get(symbol, [])[:3],
            })
        return candidates

    async def _search_addresses_twikit(self) -> list[dict]:
        """Search Twitter via twikit for contract addresses."""
        address_candidates: list[dict] = []
        seen_addresses: set[str] = set()

        address_queries = ["contract address 0x", "ca: 0x", "0x new token"]

        for query in address_queries:
            try:
                tweets = await self._search_twikit(query)
                for tweet in tweets:
                    text = getattr(tweet, "text", "") or ""
                    if not text.strip():
                        continue

                    engagement = (
                        getattr(tweet, "retweet_count", 0) or 0
                        + (getattr(tweet, "like_count", 0) or 0)
                    )

                    for addr in self.CONTRACT_ADDRESS_EVM_RE.findall(text):
                        addr_lower = addr.lower()
                        if addr_lower in seen_addresses:
                            continue
                        seen_addresses.add(addr_lower)
                        cashtags = self.CASHTAG_RE.findall(text)
                        symbol = cashtags[0].upper() if cashtags else "UNKNOWN"
                        address_candidates.append({
                            "symbol": symbol,
                            "contract_address": addr,
                            "chain": "ethereum",
                            "mention_count": 1.0 + min(engagement / 100.0, 5.0),
                            "source": "twikit_address",
                            "snippet": text[:200],
                        })

                    for addr in self.CONTRACT_ADDRESS_SOL_RE.findall(text):
                        if addr in seen_addresses:
                            continue
                        seen_addresses.add(addr)
                        cashtags = self.CASHTAG_RE.findall(text)
                        symbol = cashtags[0].upper() if cashtags else "UNKNOWN"
                        address_candidates.append({
                            "symbol": symbol,
                            "contract_address": addr,
                            "chain": "solana",
                            "mention_count": 1.0 + min(engagement / 100.0, 5.0),
                            "source": "twikit_address",
                            "snippet": text[:200],
                        })

            except Exception:
                continue

        return address_candidates

    # ── Filtering & Deduplication ───────────────────────

    def _is_spam_text(self, text: str) -> bool:
        """
        Detect scam/pump-and-dump patterns in tweet text.

        Returns True if the text matches known spam patterns.
        """
        text_lower = text.lower()
        # Check for too many spam patterns — 3+ is a strong signal
        spam_count = sum(1 for p in self.SPAM_TEXT_PATTERNS if p in text_lower)
        if spam_count >= 3:
            return True
        # Single strong patterns: "100x guaranteed" or "dm me" with link
        if ("100x guaranteed" in text_lower or "1000x guaranteed" in text_lower):
            return True
        if "dm me" in text_lower and any(p in text_lower for p in self.LINK_ONLY_PATTERNS):
            return True
        return False

    def _is_link_only_post(self, text: str) -> bool:
        """
        Filter out posts that are primarily link-sharing (not analysis).

        Posts consisting mostly of a t.me/, dexscreener, or similar link
        with minimal commentary are usually bots or shills.
        """
        text_lower = text.lower()
        link_count = sum(1 for p in self.LINK_ONLY_PATTERNS if p in text_lower)
        if link_count == 0:
            return False
        # If the text is mostly links (short text with links), it's spam
        words = [w for w in text_lower.split() if w]
        if len(words) < 15 and link_count >= 1:
            return True
        return False

    def _is_reputable_account(self, author_id: str = "", text: str = "") -> bool:
        """
        Check if a mention comes from a reputable crypto account.

        For v2 API: checks author_id against known accounts (requires user lookup).
        For Nitter RSS: checks if the tweet text/summary mentions a known account.

        Strategy from Crypto Twitter guide: "mutuals over numbers" — if known
        founders/VCs/analysts are discussing a token, it's more likely legitimate.
        """
        # Check if any reputable account username appears in the text
        # (Nitter RSS embeds the username in titles/descriptions)
        text_lower = text.lower()
        for account in self.REPUTABLE_ACCOUNTS:
            if account in text_lower:
                return True
        # For v2 API, we'd need a user lookup by author_id — skip for now
        # (Would require GET /2/users/{id} which consumes rate limits)
        return False

    def _counter_to_candidates(
        self, counter: Counter, samples: dict[str, list[str]]
    ) -> list[dict]:
        """Convert a Counter of symbol→mentions into candidate dicts."""
        candidates: list[dict] = []
        for symbol, mention_count in counter.most_common(200):
            # Skip single-mention noise (need at least some signal)
            if mention_count < 1.5:
                continue
            candidates.append({
                "symbol": symbol,
                "contract_address": "",
                "chain": "",
                "mention_count": mention_count,
                "source": "twitter_cashtag",
                "sample_tweets": samples.get(symbol, [])[:3],
            })
        return candidates

    def _deduplicate_by_symbol(self, candidates: list[dict]) -> list[dict]:
        """Deduplicate by symbol, merging 3D metrics from multiple sources."""
        best: dict[str, dict] = {}
        for c in candidates:
            sym = c.get("symbol", "").upper()
            if not sym:
                continue
            if sym not in best:
                best[sym] = dict(c)
            else:
                existing = best[sym]
                existing["mention_count"] = existing.get("mention_count", 0) + c.get("mention_count", 0)
                existing["unique_accounts"] = max(existing.get("unique_accounts", 0), c.get("unique_accounts", 0))
                existing["total_engagement"] = existing.get("total_engagement", 0) + c.get("total_engagement", 0)
                existing["authority_mentions"] = max(
                    existing.get("authority_mentions", 0),
                    c.get("authority_mentions", 0),
                )
                if c.get("contract_address") and not existing.get("contract_address"):
                    existing["contract_address"] = c["contract_address"]
                    existing["chain"] = c.get("chain", "")
                existing_samples = existing.get("sample_tweets", [])
                for s in c.get("sample_tweets", []):
                    if s not in existing_samples and len(existing_samples) < 5:
                        existing_samples.append(s)
                existing["sample_tweets"] = existing_samples
        return list(best.values())

    def _filter_by_velocity(
        self, candidates: list[dict], previous_mentions: Optional[dict] = None
    ) -> list[dict]:
        """
        Filter by 3-dimension velocity composite score.

        Three independent signals per token:
          1. Mention velocity  — current_mentions / baseline_mentions
          2. Account velocity  — current_unique_accounts / baseline_accounts
          3. Engagement velocity — current_engagement / baseline_engagement

        Composite = weighted blend of all three velocities.
        Each baseline is EMA-updated independently.

        Signal tiers (based on composite velocity):
          - 🔷 VERIFIED:  composite > 4.0 + authority mention
          - 🔴 BREAKOUT:  composite > 5.0
          - 🟠 RISING:    composite > 3.0 + accelerating
          - 🟡 ELEVATED:  composite > 2.5
          - 🔍 EARLY:     composite > 1.8 + new token
        """
        if previous_mentions is None:
            previous_mentions = {}

        filtered: list[dict] = []
        for c in candidates:
            symbol = c.get("symbol", "")
            mentions = c.get("mention_count", 0)
            accounts = c.get("unique_accounts", 0)
            engagement = c.get("total_engagement", 0)
            authority = c.get("authority_mentions", 0)

            # ── Get baselines (default to 0.5 to avoid div-by-zero) ──
            bl_m = max(self._baseline_mentions.get(symbol, 0.5), 0.3)
            bl_a = max(self._baseline_accounts.get(symbol, 0.5), 0.3)
            bl_e = max(self._baseline_engagement.get(symbol, 0.5), 0.3)

            # ── 3D velocity computation ──
            v_m = mentions / bl_m     # mention velocity
            v_a = accounts / bl_a     # unique-account velocity
            v_e = engagement / bl_e   # engagement velocity

            # ── Composite velocity (weighted blend) ──
            composite = (
                VELOCITY_WEIGHT_MENTIONS * v_m
                + VELOCITY_WEIGHT_ACCOUNTS * v_a
                + VELOCITY_WEIGHT_ENGAGEMENT * v_e
            )

            # ── Acceleration: is this run's mentions > previous run's? ──
            prev = previous_mentions.get(symbol, {})
            prev_m = prev.get("m", 0) if isinstance(prev, dict) else prev
            acceleration = mentions / prev_m if prev_m > 0 else 99.0
            is_new = prev_m == 0

            # ── Update 3D baselines (EMA: 85% old, 15% new) ──
            self._baseline_mentions[symbol] = bl_m * 0.85 + mentions * 0.15
            self._baseline_accounts[symbol] = bl_a * 0.85 + accounts * 0.15
            self._baseline_engagement[symbol] = bl_e * 0.85 + engagement * 0.15

            # ── Signal classification ──
            if composite >= 5.0:
                signal = "BREAKOUT"
            elif composite >= 3.0 and acceleration >= 1.5:
                signal = "RISING"
            elif composite >= 3.0:
                signal = "ELEVATED"
            elif composite >= 2.5:
                signal = "ELEVATED"
            elif composite >= 1.8 and is_new:
                signal = "EARLY"
            else:
                continue

            if signal in ("BREAKOUT", "RISING") and authority >= 1:
                signal = "VERIFIED"

            c["signal"] = signal
            c["composite_velocity"] = round(composite, 1)
            c["mention_velocity"] = round(v_m, 1)
            c["account_velocity"] = round(v_a, 1)
            c["engagement_velocity"] = round(v_e, 1)
            c["mention_acceleration"] = round(min(acceleration, 99.0), 1)
            c["baseline_mentions"] = round(bl_m, 2)
            c["baseline_accounts"] = round(bl_a, 2)
            c["baseline_engagement"] = round(bl_e, 2)
            c["is_new"] = is_new
            filtered.append(c)

        # Sort: VERIFIED → BREAKOUT → RISING → EARLY → ELEVATED, then by composite
        signal_order = {"VERIFIED": 0, "BREAKOUT": 1, "RISING": 2, "EARLY": 3, "ELEVATED": 4}
        filtered.sort(
            key=lambda x: (
                signal_order.get(x.get("signal", "ELEVATED"), 4),
                -x.get("composite_velocity", 0),
            )
        )
        return filtered[:100]
