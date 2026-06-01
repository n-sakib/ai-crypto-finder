"""
CLI: Reddit Discovery Post Collector.

Usage:
    python -m app.reddit_discovery.collect

Collects new posts from configured subreddits, extracts token
identifiers, resolves them to canonical tokens, and stores mentions.

Uses Reddit's public JSON API (no auth required for read-only access).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.database import async_session_factory
from app.reddit_discovery.client import RedditClientService
from app.reddit_discovery.config import load_reddit_sources
from app.reddit_discovery.extractor import RedditTokenExtractor
from app.reddit_discovery.resolver import RedditTokenResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("reddit.collect")


async def main() -> None:
    """Main collection flow."""
    start_time = time.monotonic()

    logger.info("=== Reddit Token Discovery Collection ===")

    # Load config
    configs = load_reddit_sources()
    enabled = [c for c in configs if c.enabled]
    if not enabled:
        logger.warning("No enabled Reddit sources configured. Set REDDIT_SUBREDDITS env var.")
        return

    logger.info(f"Configured {len(enabled)} subreddits:")

    client_service = RedditClientService()
    extractor = RedditTokenExtractor()
    resolver = RedditTokenResolver()

    async with async_session_factory() as session:
        # Sync sources
        sources = await client_service.sync_sources(session, enabled)
        if not sources:
            logger.error("No sources synced")
            return

        for src in sources:
            logger.info(f"  r/{src.subreddit_name} ({src.source_type.value})")

        logger.info("Collecting posts...")
        stats, posts = await client_service.collect_posts(session, sources)

        logger.info(
            f"Collected {stats['posts_processed']} new posts "
            f"from {stats['sources_scanned']} subreddits "
            f"({stats['posts_skipped_duplicate']} skipped as duplicates)"
        )

        # Extract token references
        logger.info(f"Extracting tokens from {len(posts)} posts...")
        total_extractions = 0
        total_mentions = 0

        for post in posts:
            text = post.selftext or ""
            extractions = extractor.extract(text, post.title)
            total_extractions += len(extractions)

            if extractions:
                mentions = await resolver.resolve(session, extractions, post)
                total_mentions += mentions

        logger.info(f"Extracted {total_extractions} token references")
        logger.info(f"Created {total_mentions} mentions")

        elapsed = time.monotonic() - start_time
        logger.info(f"Collection complete in {elapsed:.1f}s")

        if stats["errors"]:
            logger.warning(f"Errors: {stats['errors']}")


if __name__ == "__main__":
    asyncio.run(main())
