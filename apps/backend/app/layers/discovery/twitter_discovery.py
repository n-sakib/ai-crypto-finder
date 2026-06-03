"""
Twitter/X Discovery — Finds tokens mentioned on Twitter.

Source: 1.3 Twitter/X Discovery
Criteria: 3D composite velocity (mentions + accounts + engagement)
Finds: cashtags, token names, contract addresses

Uses Twikit (free scraping) — no API key required.
https://github.com/d60/twikit

Set TWITTER_USERNAME + TWITTER_PASSWORD in .env to enable.
"""

# ── Monkey-patch twikit ClientTransaction for KEY_BYTE fix ────────────
# Twitter changed ondemand.s.js structure on March 18 2026.
# Remove this block when twikit releases an official fix.
# Ref: https://github.com/d60/twikit/issues/408
def _apply_twikit_monkey_patch():
    import re as _re
    _tx_mod = __import__('twikit.x_client_transaction.transaction', fromlist=['ClientTransaction'])
    _tx_mod.ON_DEMAND_FILE_REGEX = _re.compile(
        r""",(\d+):["']ondemand\.s["']""", flags=(_re.VERBOSE | _re.MULTILINE))
    _tx_mod.ON_DEMAND_HASH_PATTERN = r',{}:"([0-9a-f]+)"'

    async def _patched_get_indices(self, home_page_response, session, headers):
        key_byte_indices = []
        response = self.validate_response(home_page_response) or self.home_page_response
        on_demand_file_index = _tx_mod.ON_DEMAND_FILE_REGEX.search(str(response)).group(1)
        regex = _re.compile(_tx_mod.ON_DEMAND_HASH_PATTERN.format(on_demand_file_index))
        filename = regex.search(str(response)).group(1)
        on_demand_file_url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{filename}a.js"
        on_demand_file_response = await session.request(method="GET", url=on_demand_file_url, headers=headers)
        key_byte_indices_match = _tx_mod.INDICES_REGEX.finditer(str(on_demand_file_response.text))
        for item in key_byte_indices_match:
            key_byte_indices.append(item.group(2))
        if not key_byte_indices:
            raise Exception("Couldn't get KEY_BYTE indices")
        key_byte_indices = list(map(int, key_byte_indices))
        return key_byte_indices[0], key_byte_indices[1:]

    _tx_mod.ClientTransaction.get_indices = _patched_get_indices

_apply_twikit_monkey_patch()
# ── End monkey-patch ──────────────────────────────────────────────────
import asyncio
import json
import os
import re
from collections import Counter
from typing import Optional

from app.config import settings
from app.core.redis import get_redis
from app.layers.discovery.base import BaseDiscoverySource
import logging

logger = logging.getLogger(__name__)

# Redis keys for Twitter discovery
TWITTER_BASELINE_KEY = "twitter:mention_baselines"
TWITTER_PREVIOUS_KEY = "twitter:previous_snapshot"
TWITTER_BASELINE_TTL = 7 * 24 * 3600
TWITTER_PREVIOUS_TTL = 3600

# Browser cookies file — export from logged-in Twitter session
TWITTER_COOKIES_JSON = os.path.join(os.path.dirname(__file__), "..", "..", "..", "twitter_cookies.json")
# Legacy twikit cookies file
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
        return "Twitter/X (Twikit)" if os.path.exists(TWITTER_COOKIES_JSON) else "Twitter/X (disabled — export cookies)"

    async def _get_client(self):
        """Get httpx client for Nitter RSS (no auth, no Cloudflare, always works)."""
        if self._twikit_client is not None:
            return self._twikit_client

        import httpx
        client = httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Crypto-Finder/1.0)"},
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )
        self._twikit_client = client
        logger.info("Nitter RSS client ready")
        return client

    # ── Public API ──────────────────────────────────────

    async def discover(self) -> list[dict]:
        """
        Search Twitter for crypto token mentions via Twikit (free scraping).

        Searches run sequentially (not concurrently) to avoid triggering
        Twitter's rate-limiter and anti-bot detection. Each search query
        has a 3s cooldown; running two search streams in parallel would
        double the request rate and risk account suspension.
        """
        await self._load_baselines()
        previous_mentions = await self._load_previous()

        # ⚠️ Sequential only — concurrent searches = account ban risk
        try:
            kw = await self._search_keywords()
        except Exception:
            kw = []
        try:
            addr = await self._search_addresses()
        except Exception:
            addr = []

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

    # ── Nitter RSS Search ──────────────────────────────

    NITTER_INSTANCES = [
        "https://nitter.net",
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
    ]

    SEARCH_TERMS: list[str] = [
        "new launch crypto", "just launched token",
        "fair launch", "stealth launch",
        "AI agent crypto", "AI crypto token",
        "DePIN", "RWA tokenization",
        "memecoin", "meme coin 100x",
        "contract address 0x", "ca: 0x",
    ]

    async def _fetch_rss(self, url: str, retries: int = 3) -> str | None:
        """Fetch RSS feed from Nitter, trying multiple instances."""
        client = await self._get_client()
        if client is None:
            return None

        for instance in self.NITTER_INSTANCES:
            full_url = f"{instance}{url}"
            for attempt in range(retries):
                try:
                    resp = await client.get(full_url)
                    if resp.status_code == 200:
                        return resp.text
                except Exception:
                    if attempt < retries - 1:
                        await asyncio.sleep(2)
                        continue
        return None

    async def _search_rss(self, query: str) -> list[dict]:
        """Search via Nitter RSS and parse results."""
        import xml.etree.ElementTree as ET
        from urllib.parse import quote

        rss_url = f"/search/rss?f=tweets&q={quote(query)}"
        xml_text = await self._fetch_rss(rss_url)
        if not xml_text:
            return []

        tweets = []
        try:
            root = ET.fromstring(xml_text)
            for item in root.findall(".//item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                desc = item.findtext("description", "") or ""
                pub_date = item.findtext("pubDate", "")
                creator = item.findtext("{http://purl.org/dc/elements/1.1/}creator", "")

                text = desc or title
                tweets.append({
                    "id": link,
                    "text": text,
                    "created_at": pub_date,
                    "user": {"name": creator, "id": creator, "screen_name": creator},
                    "retweet_count": 0,
                    "like_count": 0,
                    "reply_count": 0,
                })
        except Exception:
            pass
        return tweets

    async def _search_keywords(self, progress_callback=None) -> list[dict]:
        """Search Twitter via GraphQL for crypto keywords."""
        mention_counter: Counter = Counter()
        engagement_counter: Counter = Counter()
        unique_accounts: dict[str, set[str]] = {}
        authority_counter: Counter = Counter()
        tweet_samples: dict[str, list[str]] = {}
        total_terms = len(self.SEARCH_TERMS)

        for idx, query in enumerate(self.SEARCH_TERMS):
            if progress_callback:
                await progress_callback({
                    "status": "searching",
                    "sources_done": idx,
                    "sources_total": total_terms + 3,  # +3 for address queries
                    "query": query,
                })
            try:
                tweets = await self._search_rss(query)
                for tweet in tweets:
                    text = tweet.get("text", "")
                    user = tweet.get("user", {}) or {}
                    author_id = user.get("id", "")
                    author_name = user.get("name", "")

                    if not text or self._is_spam_text(text):
                        continue

                    engagement = (
                        tweet.get("retweet_count", 0) or 0
                        + (tweet.get("like_count", 0) or 0)
                        + (tweet.get("reply_count", 0) or 0)
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

            # Cooldown between queries — protects against rate limits and account bans
            # 27 search terms × 3s = ~81s total delay, well within 50req/15min limit
            await asyncio.sleep(3.0)

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

    async def _search_addresses(self, progress_callback=None) -> list[dict]:
        """Search Twitter via GraphQL for contract addresses."""
        address_candidates: list[dict] = []
        seen_addresses: set[str] = set()

        address_queries = ["contract address 0x", "ca: 0x", "0x new token"]
        keyword_count = len(self.SEARCH_TERMS)

        for idx, query in enumerate(address_queries):
            if progress_callback:
                await progress_callback({
                    "status": "searching",
                    "sources_done": keyword_count + idx,
                    "sources_total": keyword_count + len(address_queries),
                    "query": query,
                })
            try:
                tweets = await self._search_rss(query)
                for tweet in tweets:
                    text = tweet.get("text", "") or ""
                    if not text.strip():
                        continue

                    engagement = (
                        tweet.get("retweet_count", 0) or 0
                        + (tweet.get("like_count", 0) or 0)
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

            # Cooldown between queries
            await asyncio.sleep(3.0)

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
