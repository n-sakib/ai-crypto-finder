"""
Playwright-based Twitter collector. Uses the active browser session to search
Twitter and extract token mentions. Feeds results into the backend API.

Run from host machine: python collect_twitter_playwright.py
"""
import asyncio
import re
import json
import httpx
from datetime import datetime, timezone

# Config
BACKEND = "http://localhost:8000/api/v1"
SEARCH_TERMS = [
    "new launch crypto", "fair launch token", "AI agent crypto token",
    "DePIN crypto", "memecoin 100x", "just launched token",
    "contract address 0x", "ca: 0x token",
]
CASHTAG_RE = re.compile(r"\$([A-Z]{2,10})\b")
ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")


async def search_twitter(page, query: str, max_tweets: int = 10) -> list[dict]:
    """Search Twitter and extract tweet text from the page DOM."""
    url = f"https://x.com/search?q={query}&src=typed_query&f=live"
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    tweets = []
    for _ in range(3):  # Scroll up to 3 times
        items = await page.evaluate("""
            () => {
                const articles = document.querySelectorAll('article[data-testid="tweet"]');
                return Array.from(articles).map(a => {
                    const text = a.querySelector('[data-testid="tweetText"]')?.innerText || '';
                    const time = a.querySelector('time')?.getAttribute('datetime') || '';
                    const author = a.querySelector('[data-testid="User-Name"]')?.innerText?.split('\\n')[0] || '';
                    return {text, time, author};
                });
            }
        """)
        for item in items:
            if item["text"] and item not in tweets:
                tweets.append(item)
                if len(tweets) >= max_tweets:
                    break
        if len(tweets) >= max_tweets:
            break
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(2000)

    return tweets[:max_tweets]


async def extract_tokens(tweets: list[dict]) -> list[dict]:
    """Extract cashtags and contract addresses from tweet text."""
    candidates = []
    for tw in tweets:
        text = tw["text"]
        cashtags = CASHTAG_RE.findall(text)
        for sym in cashtags:
            sym_u = sym.upper()
            if len(sym_u) >= 2:
                candidates.append({
                    "symbol": sym_u, "contract_address": "", "chain": "",
                    "mention_count": 1.0, "unique_accounts": 1,
                    "total_engagement": 0, "authority_mentions": 0,
                    "source": f"playwright:{tw.get('author','')}",
                    "sample_tweets": [text[:200]],
                })
        for addr in ADDRESS_RE.findall(text):
            candidates.append({
                "symbol": "UNKNOWN", "contract_address": addr, "chain": "ethereum",
                "mention_count": 1.0, "unique_accounts": 1,
                "total_engagement": 0, "authority_mentions": 0,
                "source": f"playwright:{tw.get('author','')}",
                "sample_tweets": [text[:200]],
            })
    return candidates


async def store_candidates(candidates: list[dict]):
    """Send candidates to the backend for storage."""
    if not candidates:
        return {"stored": 0}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BACKEND}/twitter/ingest",
            json={"candidates": candidates},
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": resp.text}


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            storage_state="twitter_session.json" if False else None,
        )
        page = await context.new_page()

        # Navigate to Twitter first to check login
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        is_logged_in = await page.evaluate(
            "() => !!document.querySelector('a[data-testid=\"AppTabBar_Profile_Link\"]')"
        )
        if not is_logged_in:
            print("Not logged into Twitter. Please log in manually.")
            print("Waiting 60 seconds for login...")
            await page.wait_for_timeout(60000)
            is_logged_in = await page.evaluate(
                "() => !!document.querySelector('a[data-testid=\"AppTabBar_Profile_Link\"]')"
            )
            if not is_logged_in:
                print("Still not logged in. Aborting.")
                return

        print("Logged in. Starting searches...")

        all_candidates = []
        for i, query in enumerate(SEARCH_TERMS):
            print(f"  [{i+1}/{len(SEARCH_TERMS)}] Searching: {query}...")
            try:
                tweets = await search_twitter(page, query, max_tweets=10)
                candidates = await extract_tokens(tweets)
                all_candidates.extend(candidates)
                print(f"    {len(tweets)} tweets, {len(candidates)} tokens found")
            except Exception as e:
                print(f"    Error: {e}")
            await page.wait_for_timeout(2000)  # Cooldown

        print(f"\nTotal candidates: {len(all_candidates)}")
        if all_candidates:
            result = await store_candidates(all_candidates)
            print(f"Stored: {result}")
        else:
            print("No tokens found.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
