"""
Reddit API Client — Fetches posts from monitored subreddits.

Uses asyncpraw (async Reddit API wrapper) for data collection.
Requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in settings.

Reddit is treated as a slower confirmation signal, not primary discovery.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select as sa_select

from app.config import settings
from app.reddit_discovery.config import RedditSourceConfig, load_reddit_sources_async
from app.reddit_discovery.models import (
    RedditSource, RedditPost, RedditSourceType,
    RedditCandidateToken, RedditTokenMention,
    RedditDiscoveryMethod, RedditDiscoveryConfidence,
)

logger = logging.getLogger(__name__)


class RedditClientService:
    """
    Service for collecting posts from Reddit subreddits.

    Uses OAuth (script app) when REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET
    are configured. Falls back to old.reddit.com JSON API otherwise.
    """

    def __init__(self):
        self._client_id = settings.REDDIT_CLIENT_ID
        self._client_secret = settings.REDDIT_CLIENT_SECRET
        self._base_url = "https://oauth.reddit.com"
        self._public_url = "https://old.reddit.com"
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0

    async def _get_access_token(self) -> Optional[str]:
        """Obtain an OAuth access token via client credentials grant."""
        import time as _time
        import aiohttp

        if self._access_token and _time.monotonic() < self._token_expiry:
            return self._access_token

        if not self._client_id or not self._client_secret:
            return None

        # Skip if placeholders
        if self._client_id in ("your_reddit_client_id", "") or self._client_secret in ("your_reddit_client_secret", ""):
            return None

        try:
            auth = aiohttp.BasicAuth(self._client_id, self._client_secret)
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    "https://www.reddit.com/api/v1/access_token",
                    data={"grant_type": "client_credentials"},
                    headers={"User-Agent": "AI-Crypto-Finder/0.1.0 (by /u/crypto-bot)"},
                    auth=auth,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._access_token = data.get("access_token")
                        expires_in = data.get("expires_in", 3600)
                        self._token_expiry = _time.monotonic() + expires_in - 60
                        logger.info("Reddit OAuth token obtained")
                        return self._access_token
                    else:
                        body = await resp.text()
                        logger.warning(f"Reddit OAuth failed: {resp.status} — {body[:200]}")
        except Exception as e:
            logger.warning(f"Reddit OAuth error: {e}")

        return None

    async def sync_sources(
        self,
        session: AsyncSession,
        configs: list[RedditSourceConfig],
    ) -> list[RedditSource]:
        """Sync configured sources to the database."""
        sources: list[RedditSource] = []
        for cfg in configs:
            result = await session.execute(
                sa_select(RedditSource).where(RedditSource.source_id == cfg.source_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.name = cfg.name
                existing.subreddit_name = cfg.subreddit_name
                existing.source_type = RedditSourceType(cfg.source_type)
                existing.enabled = cfg.enabled
                sources.append(existing)
            else:
                src = RedditSource(
                    source_id=cfg.source_id,
                    name=cfg.name,
                    subreddit_name=cfg.subreddit_name,
                    source_type=RedditSourceType(cfg.source_type),
                    enabled=cfg.enabled,
                )
                session.add(src)
                sources.append(src)

        await session.commit()
        return sources

    async def collect_posts(
        self,
        session: AsyncSession,
        sources: list[RedditSource],
        progress_callback: Optional[Callable[[RedditSource, dict], Awaitable[None]]] = None,
        offset_date: Optional[datetime] = None,
        limit_per_source: int = 100,
    ) -> tuple[dict, list[RedditPost]]:
        """
        Collect new posts from each Reddit source.

        Tries in order:
        1. OAuth JSON API (requires REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET)
        2. RSS feed (no auth required, works for public subreddits)

        Returns:
            Tuple of (stats dict, list of collected RedditPost records).
        """
        token = await self._get_access_token()

        if token:
            return await self._collect_via_json(session, sources, progress_callback, offset_date, limit_per_source, token)
        else:
            logger.info("No OAuth token — using RSS feeds (set REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET for JSON API)")
            return await self._collect_via_rss(session, sources, progress_callback, offset_date, limit_per_source)

    async def _collect_via_json(
        self,
        session: AsyncSession,
        sources: list[RedditSource],
        progress_callback: Optional[Callable[[RedditSource, dict], Awaitable[None]]],
        offset_date: Optional[datetime],
        limit_per_source: int,
        token: str,
    ) -> tuple[dict, list[RedditPost]]:
        import aiohttp

        stats = {
            "sources_scanned": 0,
            "posts_processed": 0,
            "posts_skipped_duplicate": 0,
            "errors": [],
        }
        all_posts: list[RedditPost] = []

        headers = {
            "User-Agent": "AI-Crypto-Finder/0.1.0 (by /u/crypto-bot)",
            "Authorization": f"Bearer {token}",
        }
        logger.info("Using OAuth authentication for Reddit API")

        async with aiohttp.ClientSession(headers=headers) as http:
            for idx, source in enumerate(sources):
                if idx > 0:
                    await asyncio.sleep(1.0)  # OAuth: 60 req/min

                source_stats = {"processed": 0, "skipped": 0}
                try:
                    url = f"{self._base_url}/r/{source.subreddit_name}/new.json"
                    params = {"limit": str(limit_per_source), "raw_json": "1"}
                    if source.last_post_id:
                        params["before"] = source.last_post_id

                    async with http.get(url, params=params) as resp:
                        if resp.status == 429:
                            logger.warning(f"Rate limited on r/{source.subreddit_name}, backing off 5s...")
                            await asyncio.sleep(5)
                            async with http.get(url, params=params) as retry_resp:
                                resp = retry_resp

                        if resp.status != 200:
                            logger.warning(f"Reddit API returned {resp.status} for r/{source.subreddit_name}")
                            stats["errors"].append(f"HTTP {resp.status} for r/{source.subreddit_name}")
                            stats["sources_scanned"] += 1
                            if progress_callback:
                                await progress_callback(source, source_stats)
                            continue

                        data = await resp.json()
                        posts_data = data.get("data", {}).get("children", [])
                        all_posts, source_stats, stats = await self._process_posts(
                            session, source, posts_data, all_posts,
                            source_stats, stats, offset_date,
                        )

                        if posts_data:
                            source.last_post_id = posts_data[0].get("data", {}).get("name", source.last_post_id)
                        source.last_collected_at = datetime.now(timezone.utc)

                    stats["sources_scanned"] += 1
                except Exception as e:
                    logger.error(f"Error collecting from r/{source.subreddit_name}: {e}")
                    stats["errors"].append(f"r/{source.subreddit_name}: {str(e)}")
                    stats["sources_scanned"] += 1

                if progress_callback:
                    await progress_callback(source, source_stats)

            await session.commit()
        return stats, all_posts

    async def _collect_via_rss(
        self,
        session: AsyncSession,
        sources: list[RedditSource],
        progress_callback: Optional[Callable[[RedditSource, dict], Awaitable[None]]],
        offset_date: Optional[datetime],
        limit_per_source: int,
    ) -> tuple[dict, list[RedditPost]]:
        """
        Collect posts via Reddit RSS feeds (no auth required).
        """
        import aiohttp
        import xml.etree.ElementTree as ET

        stats = {
            "sources_scanned": 0,
            "posts_processed": 0,
            "posts_skipped_duplicate": 0,
            "errors": [],
        }
        all_posts: list[RedditPost] = []

        headers = {"User-Agent": "AI-Crypto-Finder/0.1.0 (by /u/crypto-bot)"}

        async with aiohttp.ClientSession(headers=headers) as http:
            for idx, source in enumerate(sources):
                if idx > 0:
                    await asyncio.sleep(2.0)  # Be gentle with RSS

                source_stats = {"processed": 0, "skipped": 0}
                try:
                    url = f"https://www.reddit.com/r/{source.subreddit_name}/new/.rss"
                    params = {"limit": str(limit_per_source)}

                    async with http.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status != 200:
                            logger.warning(f"Reddit RSS returned {resp.status} for r/{source.subreddit_name}")
                            stats["errors"].append(f"HTTP {resp.status} for r/{source.subreddit_name}")
                            stats["sources_scanned"] += 1
                            if progress_callback:
                                await progress_callback(source, source_stats)
                            continue

                        raw_xml = await resp.text()
                        root = ET.fromstring(raw_xml)

                        # Parse RSS entries
                        ns = {"atom": "http://www.w3.org/2005/Atom"}
                        posts_data = []
                        for entry in root.findall(".//entry", ns) or root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                            post_data = self._parse_rss_entry(entry, ns)
                            if post_data:
                                posts_data.append({"data": post_data})

                        if not posts_data:
                            # Fallback: try without namespace
                            for entry in root.iter("entry"):
                                post_data = self._parse_rss_entry(entry, {})
                                if post_data:
                                    posts_data.append({"data": post_data})

                        all_posts, source_stats, stats = await self._process_posts(
                            session, source, posts_data, all_posts,
                            source_stats, stats, offset_date,
                        )

                        if posts_data:
                            first_id = posts_data[0].get("data", {}).get("name", "")
                            source.last_post_id = first_id or source.last_post_id
                        source.last_collected_at = datetime.now(timezone.utc)

                    stats["sources_scanned"] += 1
                except ET.ParseError as e:
                    # Some subreddits may return HTML instead of RSS
                    logger.warning(f"RSS parse error for r/{source.subreddit_name}: {e}")
                    stats["errors"].append(f"r/{source.subreddit_name}: RSS parse error")
                    stats["sources_scanned"] += 1
                except Exception as e:
                    logger.error(f"Error collecting from r/{source.subreddit_name}: {e}")
                    stats["errors"].append(f"r/{source.subreddit_name}: {str(e)}")
                    stats["sources_scanned"] += 1

                if progress_callback:
                    await progress_callback(source, source_stats)

            await session.commit()
        return stats, all_posts

    def _parse_rss_entry(self, entry, ns: dict) -> dict | None:
        """Parse a single RSS entry into a post dict."""
        import xml.etree.ElementTree as ET

        def _text(tag: str) -> str:
            el = entry.find(tag) if not ns else entry.find(tag, ns)
            return el.text if el is not None and el.text else ""

        def _text_ns(local: str) -> str:
            ns_uri = "http://www.w3.org/2005/Atom"
            el = entry.find(f"{{{ns_uri}}}{local}")
            return el.text if el is not None and el.text else ""

        try:
            # Try Atom namespace first
            post_id = _text_ns("id") or _text("id")
            title = _text_ns("title") or _text("title")
            author_name = _text_ns("author")
            if not author_name:
                author_el = entry.find("{http://www.w3.org/2005/Atom}author")
                if author_el is not None:
                    name_el = author_el.find("{http://www.w3.org/2005/Atom}name")
                    author_name = name_el.text if name_el is not None and name_el.text else "[deleted]"
            if not author_name:
                author_name = _text("author") or "[deleted]"

            updated = _text_ns("updated") or _text("updated") or ""
            link = ""
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            if link_el is not None:
                link = link_el.get("href", "")
            if not link:
                link = _text("link") or ""

            content = _text_ns("content") or _text_ns("summary") or _text("description") or ""
            category = _text_ns("category") or _text("category") or ""

            if not post_id or not title:
                return None

            # Extract Reddit fullname from ID (format: t3_xxxxxx)
            reddit_id = post_id.split("/")[-1] if "/" in post_id else post_id
            reddit_fullname = f"t3_{reddit_id}" if not reddit_id.startswith("t3_") else reddit_id

            # Parse timestamp
            try:
                post_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                post_dt = datetime.now(timezone.utc)

            return {
                "name": reddit_fullname,
                "title": title,
                "author": author_name,
                "created_utc": post_dt.timestamp(),
                "selftext": content if len(content) < 5000 else content[:5000],
                "permalink": link.replace("https://www.reddit.com", ""),
                "link_flair_text": category,
            }
        except Exception:
            return None

    async def _process_posts(
        self,
        session: AsyncSession,
        source: RedditSource,
        posts_data: list[dict],
        all_posts: list[RedditPost],
        source_stats: dict,
        stats: dict,
        offset_date: Optional[datetime],
    ) -> tuple[list[RedditPost], dict, dict]:
        """Process a batch of posts and store new ones."""
        for post_data in posts_data:
            post = post_data.get("data", {})
            post_id = post.get("name", "")
            created_utc = post.get("created_utc", 0)
            post_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)

            if offset_date and post_dt < offset_date:
                continue

            # Check for duplicate
            existing = await session.execute(
                sa_select(RedditPost).where(
                    RedditPost.source_id == source.id,
                    RedditPost.reddit_post_id == post_id,
                )
            )
            if existing.scalar_one_or_none():
                source_stats["skipped"] += 1
                stats["posts_skipped_duplicate"] += 1
                continue

            title = post.get("title", "")
            selftext = post.get("selftext", "")
            combined = f"{title}\n{selftext}"

            reddit_post = RedditPost(
                source_id=source.id,
                reddit_post_id=post_id,
                post_timestamp=post_dt,
                author=post.get("author", "[deleted]"),
                title=title,
                text_hash=hashlib.sha256(combined.encode()).hexdigest(),
                selftext=selftext if settings.REDDIT_STORE_RAW_TEXT else None,
                post_url=f"https://reddit.com{post.get('permalink', '')}",
            )
            session.add(reddit_post)
            all_posts.append(reddit_post)
            source_stats["processed"] += 1
            stats["posts_processed"] += 1

        return all_posts, source_stats, stats
