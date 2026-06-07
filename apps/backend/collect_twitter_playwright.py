"""
Twitter/X Crypto Discovery — Playwright Profile Scraper
========================================================
Scrapes X.com profiles for crypto token mentions ($CASHTAGS, 0x addresses).
Designed to be triggered manually (button press in frontend → backend → this script).

  • Read-only — never posts, likes, or follows
  • Human-like delays & scrolling to avoid detection
  • Session-aware — auto-detects login, prompts if needed

Usage:
    python collect_twitter_playwright.py                           # default accounts
    python collect_twitter_playwright.py --search "HYPE"           # discover + scrape accounts for a token
    python collect_twitter_playwright.py --accounts "MuroCrypto,lookonchain"  # specific accounts
    python collect_twitter_playwright.py --login                   # save session
    python collect_twitter_playwright.py --status                  # check auth
"""

import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ── Logging ─────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).with_suffix(".log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("twitter_collector")

# ── Config ──────────────────────────────────────────────────────────────
BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000/api/v1")
STATE_FILE = Path(__file__).parent / "x_session.json"

# ── Scraping limits (per-run, not per-day) ─────────────────────────────
MAX_ACCOUNTS = 15
MAX_TWEETS_PER_ACCOUNT = 15
MIN_DELAY = 3   # seconds between accounts (randomized 3–8s)
MAX_DELAY = 8
PAGE_LOAD_TIMEOUT = 30_000  # ms

# ── User agents ─────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# ── Default monitored accounts ──────────────────────────────────────────
DEFAULT_ACCOUNTS = [
    "lookonchain", "spotonchain", "ai_9684xtpa",
    "0xDete", "s4mmyeth", "MandoCT", "Zeneca", "CryptoHayes",
    "MuroCrypto", "DefiIgnas", "route2fi", "hsakaTrades",
    "Pauly0x", "Ansem", "Wale", "BanditXBT", "CryptoKoryo",
    "theunipcs", "OnchainLens", "Whale_Alert", "Pentosh1",
]

# ── Regex ───────────────────────────────────────────────────────────────
CASHTAG_RE = re.compile(r"\$([A-Z]{2,10})\b")
ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")

SPAM_CASHTAGS = {
    "GIVEAWAY", "AIRDROP", "CLAIM", "FREE", "DROP", "REWARD",
    "PRESALE", "PRESELL", "WL", "WHITELIST", "DM", "PM",
}

# Tokens to ignore — major L1s, base pairs, stablecoins, top-50 mega caps
IGNORE_TOKENS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX",
    "DOT", "MATIC", "POL", "LINK", "UNI", "ATOM", "LTC", "ETC",
    "OP", "ARB", "NEAR", "APT", "SUI", "SEI", "INJ", "TIA",
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FRAX",
    "WBTC", "WETH", "STETH", "WBETH",
    "TRX", "TON", "SHIB", "PEPE", "WIF", "BONK",
    "XLM", "XMR", "FIL", "ICP", "KAS", "RUNE", "MNT",
    "FET", "RNDR", "TAO", "IMX", "STX", "GRT", "AAVE",
    "MKR", "QNT", "EGLD", "ALGO", "FLOW", "AXS", "SAND",
    "MANA", "THETA", "HNT", "FTM", "ONE", "ROSE",
}

REPUTABLE_ACCOUNTS = {
    "cz_binance", "saylor", "brian_armstrong", "vitalikbuterin",
    "theunipcs", "0xdete", "murocrypto", "s4mmyeth",
    "mandoct", "zeneca", "pentosh1", "cryptohayes",
    "pauly0x", "ansem", "wale", "banditxbt", "cryptokoryo",
    "lookonchain", "spotonchain", "onchainlens", "ai_9684xtpa", "whale_alert",
    "defiignas", "route2fi", "hsakatrades",
}


# ══════════════════════════════════════════════════════════════════════════
#  Auth
# ══════════════════════════════════════════════════════════════════════════

def check_auth_state() -> dict:
    if not STATE_FILE.exists():
        return {"valid": False, "reason": "No session file"}
    try:
        data = json.loads(STATE_FILE.read_text())
    except Exception as e:
        return {"valid": False, "reason": f"Corrupt: {e}"}
    cookies = data.get("cookies", [])
    auth_token = next((c for c in cookies if c["name"] == "auth_token"), None)
    ct0 = next((c for c in cookies if c["name"] == "ct0"), None)
    if not auth_token or not ct0:
        return {"valid": False, "reason": "Missing auth_token or ct0"}
    expires = auth_token.get("expires", 0)
    if expires > 0 and datetime.fromtimestamp(expires, tz=timezone.utc) < datetime.now(timezone.utc):
        return {"valid": False, "reason": "auth_token expired"}
    return {"valid": True, "cookie_count": len(cookies),
            "days_left": (datetime.fromtimestamp(expires, tz=timezone.utc) - datetime.now(timezone.utc)).days if expires else None}


async def verify_auth_live(context) -> bool:
    page = await context.new_page()
    try:
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20_000)
        await page.wait_for_timeout(3000)
        ok = await page.evaluate(
            "() => !!document.querySelector('a[data-testid=\"AppTabBar_Profile_Link\"]')"
        )
        if ok:
            h = await page.evaluate(
                "() => document.querySelector('a[data-testid=\"AppTabBar_Profile_Link\"]')?.href?.split('/').pop() || ''"
            )
            logger.info("Auth live: @%s", h)
        return ok
    except Exception as e:
        logger.error("Auth check failed: %s", e)
        return False
    finally:
        await page.close()


async def login_flow():
    from playwright.async_api import async_playwright
    print("\n" + "=" * 60)
    print("TWITTER/X LOGIN — credentials NEVER captured")
    print("=" * 60)
    input("Press Enter to open browser...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        try:
            await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)

        input("\nLog in manually, then press Enter... ")

        try:
            await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20_000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        if await page.evaluate("() => !!document.querySelector('a[data-testid=\"AppTabBar_Profile_Link\"]')"):
            handle = await page.evaluate(
                "() => document.querySelector('a[data-testid=\"AppTabBar_Profile_Link\"]')?.href?.split('/').pop() || ''"
            )
            await context.storage_state(path=str(STATE_FILE))
            print(f"\n✅ Logged in as @{handle} — session saved.")
        else:
            print("\n⚠️ Login not detected. Try again.")
        await browser.close()


# ══════════════════════════════════════════════════════════════════════════
#  Account discovery via X search
# ══════════════════════════════════════════════════════════════════════════

async def discover_accounts(page, query: str, max_accounts: int = 10) -> list[str]:
    """Search X.com for accounts tweeting about a token/topic.
    Returns list of @handles (without @) found in search results.
    """
    search_url = f"https://x.com/search?q={query}%20crypto&src=typed_query&f=user"
    logger.info("Discovering accounts for: %s", query)

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await page.wait_for_timeout(random.randint(2000, 4000))
    except Exception as e:
        logger.warning("Search failed: %s", e)
        return []

    # Scroll to load results
    for _ in range(3):
        await page.evaluate(f"window.scrollBy({{top: {random.randint(600, 1200)}, behavior: 'smooth'}})")
        await page.wait_for_timeout(random.randint(800, 1500))

    # Extract handles from People results
    handles = await page.evaluate("""
        () => {
            const cells = document.querySelectorAll('div[data-testid="UserCell"]');
            const handles = new Set();
            cells.forEach(c => {
                const links = c.querySelectorAll('a[href^="/"]');
                links.forEach(l => {
                    const href = l.getAttribute('href');
                    if (href && !href.includes('/status/') && !href.includes('/search') && !href.includes('/i/')) {
                        const handle = href.replace('/', '').split('?')[0];
                        if (handle && !handle.includes('/') && handle.length > 0 && handle.length < 30) {
                            handles.add(handle);
                        }
                    }
                });
            });
            return Array.from(handles);
        }
    """)

    # Also try extracting from tweet authors in "Latest" tab
    if len(handles) < 3:
        await page.goto(
            f"https://x.com/search?q={query}&src=typed_query&f=live",
            wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT,
        )
        await page.wait_for_timeout(3000)
        for _ in range(2):
            await page.evaluate(f"window.scrollBy({{top: {random.randint(600, 1200)}, behavior: 'smooth'}})")
            await page.wait_for_timeout(random.randint(800, 1500))

        tweet_handles = await page.evaluate("""
            () => {
                const articles = document.querySelectorAll('article[data-testid="tweet"]');
                const handles = new Set();
                articles.forEach(a => {
                    const userLinks = a.querySelectorAll('a[href^="/"]');
                    userLinks.forEach(l => {
                        const href = l.getAttribute('href');
                        if (href && href.split('/').filter(Boolean).length === 1) {
                            handles.add(href.replace('/', ''));
                        }
                    });
                });
                return Array.from(handles);
            }
        """)
        handles.extend(tweet_handles)

    # Deduplicate and filter
    unique = list(dict.fromkeys(h for h in handles if h and ' ' not in h and len(h) < 30))
    logger.info("Found %d accounts for '%s': %s", len(unique), query, unique[:10])
    return unique[:max_accounts]


# ══════════════════════════════════════════════════════════════════════════
#  Profile scraping
# ══════════════════════════════════════════════════════════════════════════

async def scrape_profile(page, handle: str) -> list[dict]:
    url = f"https://x.com/{handle}"
    logger.info("  @%s", handle)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await page.wait_for_timeout(random.randint(2000, 4000))
    except Exception as e:
        logger.warning("  @%s load failed: %s", handle, e)
        return []

    # Human-like scroll
    for _ in range(4):
        d = random.randint(600, 1500)
        await page.evaluate(f"window.scrollBy({{top: {d}, behavior: 'smooth'}})")
        await page.wait_for_timeout(random.randint(800, 2000))

    limit = MAX_TWEETS_PER_ACCOUNT
    tweets = await page.evaluate(f"""
        () => {{
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            return Array.from(articles).map(a => {{
                const text = a.querySelector('[data-testid="tweetText"]')?.innerText || '';
                const time = a.querySelector('time')?.getAttribute('datetime') || '';
                const links = Array.from(a.querySelectorAll('a')).map(el => el.href);
                const sl = links.find(l => l.includes('/status/'));
                const tid = sl ? sl.match(/\\/status\\/(\\d+)/)?.[1] || '0' : '0';
                return {{
                    text, time, tweet_id: tid,
                    replies: a.querySelector('[data-testid="reply"]')?.innerText || '0',
                    retweets: a.querySelector('[data-testid="retweet"]')?.innerText || '0',
                    likes: a.querySelector('[data-testid="like"]')?.innerText || '0',
                }};
            }}).slice(0, {limit});
        }}
    """)

    tweets.sort(key=lambda t: int(t.get("tweet_id", "0")), reverse=True)
    return tweets


# ══════════════════════════════════════════════════════════════════════════
#  Extraction
# ══════════════════════════════════════════════════════════════════════════

def parse_engagement(r: str, rt: str, lk: str) -> int:
    def p(v: str) -> int:
        v = v.strip().replace(",", "")
        if not v or v == "0": return 0
        try:
            if "K" in v.upper(): return int(float(v.upper().replace("K", "")) * 1000)
            if "M" in v.upper(): return int(float(v.upper().replace("M", "")) * 1_000_000)
            return int(v)
        except ValueError:
            return 0
    return p(r) + p(rt) + p(lk)


def extract_candidates(handle: str, tweets: list[dict]) -> list[dict]:
    candidates = []
    is_reputable = handle.lower() in REPUTABLE_ACCOUNTS
    mult = 5.0 if is_reputable else 1.0
    for tw in tweets:
        text = tw.get("text", "")
        if not text: continue
        eng = parse_engagement(tw.get("replies", "0"), tw.get("retweets", "0"), tw.get("likes", "0"))
        for sym in CASHTAG_RE.findall(text):
            s = sym.upper()
            if s in SPAM_CASHTAGS or s in IGNORE_TOKENS or len(s) < 2: continue
            candidates.append({"symbol": s, "contract_address": "", "chain": "",
                "mention_count": round(1.0 * mult, 2), "unique_accounts": 1,
                "total_engagement": eng, "authority_mentions": 1 if is_reputable else 0,
                "source": f"@{handle}", "sample_tweets": [text[:200]]})
        for addr in ADDRESS_RE.findall(text):
            candidates.append({"symbol": "UNKNOWN", "contract_address": addr, "chain": "ethereum",
                "mention_count": round(1.0 * mult, 2), "unique_accounts": 1,
                "total_engagement": eng, "authority_mentions": 1 if is_reputable else 0,
                "source": f"@{handle}", "sample_tweets": [text[:200]]})
    return candidates


def deduplicate(candidates: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for c in candidates:
        key = c.get("contract_address") or c.get("symbol", "")
        if not key or key == "UNKNOWN": continue
        if key in deduped:
            deduped[key]["mention_count"] += c.get("mention_count", 0)
            deduped[key]["total_engagement"] += c.get("total_engagement", 0)
            deduped[key]["authority_mentions"] += c.get("authority_mentions", 0)
            deduped[key]["sample_tweets"] = (deduped[key].get("sample_tweets", []) + c.get("sample_tweets", []))[:5]
            src, ns = deduped[key].get("source", ""), c.get("source", "")
            if ns and ns not in src: deduped[key]["source"] = f"{src}, {ns}" if src else ns
        else:
            deduped[key] = dict(c)
    result = list(deduped.values())
    result.sort(key=lambda x: x.get("mention_count", 0), reverse=True)
    return result


async def send_to_backend(candidates: list[dict]) -> dict:
    if not candidates: return {"stored": 0}
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(f"{BACKEND}/twitter/ingest", json={"candidates": candidates})
            if resp.status_code == 200: return resp.json()
            return {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════

async def main():
    from playwright.async_api import async_playwright

    # ── CLI flags ──────────────────────────────────────────────────────
    if "--login" in sys.argv:
        await login_flow()
        return
    if "--status" in sys.argv:
        print(json.dumps(check_auth_state(), indent=2))
        return

    # Parse --search and --accounts
    search_term = None
    account_list = None
    for i, arg in enumerate(sys.argv):
        if arg == "--search" and i + 1 < len(sys.argv):
            search_term = sys.argv[i + 1]
        elif arg == "--accounts" and i + 1 < len(sys.argv):
            account_list = [a.strip() for a in sys.argv[i + 1].split(",") if a.strip()]

    # ── Auth ───────────────────────────────────────────────────────────
    # --search and --accounts are backend-triggered: REQUIRE auth
    requires_auth = bool(search_term or account_list)

    auth = check_auth_state()
    if not auth["valid"]:
        if requires_auth:
            print(f"ERROR: Not logged in — {auth['reason']}", file=sys.stderr)
            print("Run: python collect_twitter_playwright.py --login", file=sys.stderr)
            sys.exit(1)
        print(f"\n⚠️  No valid session: {auth['reason']}")
        c = input("Log in now? [Y/n]: ").strip().lower()
        if c in ("", "y", "yes"):
            await login_flow()
            auth = check_auth_state()
            if not auth["valid"]:
                print("Login failed. Exiting."); sys.exit(1)
        else:
            print("Running in guest mode (Top tweets only).")

    authenticated = auth["valid"]
    mode = "🔐 Authenticated" if authenticated else "👤 Guest"

    # ── Determine accounts ─────────────────────────────────────────────
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=str(STATE_FILE) if authenticated else None,
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 900},
        )

        if authenticated:
            if not await verify_auth_live(context):
                print("Session expired! Run --login to re-auth.")
                STATE_FILE.unlink(missing_ok=True)
                await browser.close(); sys.exit(1)

        page = await context.new_page()

        if account_list:
            accounts = account_list
            print(f"\n{'='*60}\n{mode} | Scraping {len(accounts)} specified accounts\n{'='*60}")
        elif search_term:
            print(f"\n{'='*60}\n{mode} | Discovering accounts for: {search_term}\n{'='*60}")
            discovered = await discover_accounts(page, search_term, max_accounts=MAX_ACCOUNTS)
            if not discovered:
                print("No accounts found. Falling back to defaults.")
                accounts = DEFAULT_ACCOUNTS[:MAX_ACCOUNTS]
            else:
                accounts = discovered
            print(f"Accounts to scrape: {accounts}")
        else:
            accounts = DEFAULT_ACCOUNTS[:MAX_ACCOUNTS]
            print(f"\n{'='*60}\n{mode} | Default accounts ({len(accounts)})\n{'='*60}")

        # ── Scrape ────────────────────────────────────────────────────
        all_candidates = []
        total = len(accounts)

        for idx, handle in enumerate(accounts):
            print(f"\n[{idx+1}/{total}] @{handle}")
            try:
                tweets = await scrape_profile(page, handle)
                candidates = extract_candidates(handle, tweets)
                all_candidates.extend(candidates)
                c_cnt = sum(1 for c in candidates if c["symbol"] != "UNKNOWN")
                a_cnt = sum(1 for c in candidates if c["contract_address"])
                print(f"    {len(tweets)} tweets → {c_cnt} cashtags, {a_cnt} addresses")
            except Exception as e:
                logger.warning("@%s error: %s", handle, e)

            if idx < total - 1:
                d = random.uniform(MIN_DELAY, MAX_DELAY)
                await asyncio.sleep(d)

        await page.close()
        await context.close()
        await browser.close()

    # ── Results ────────────────────────────────────────────────────────
    final = deduplicate(all_candidates)
    print(f"\n{'='*60}")
    print(f"Done. {len(accounts)} accounts → {len(final)} unique tokens")
    if final:
        print("Top mentions:")
        for c in final[:10]:
            print(f"  ${c.get('symbol', '?'):10s} — {c['mention_count']:.1f} mentions | {c.get('source', '?')}")

    if final:
        print(f"\nSending to {BACKEND}/twitter/ingest ...")
        result = await send_to_backend(final)
        print(json.dumps(result, indent=2))

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
