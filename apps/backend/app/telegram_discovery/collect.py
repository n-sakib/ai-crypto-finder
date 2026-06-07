"""
CLI: Telegram Discovery Message Collector.

Usage:
    python -m app.telegram_discovery.collect

Collects new messages from configured Telegram sources, extracts token
identifiers, resolves them to canonical tokens, and stores mentions.

Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in environment.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add backend to path if running directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.database import async_session_factory
from app.telegram_discovery.client import TelegramClientService
from app.telegram_discovery.config import load_telegram_sources
from app.telegram_discovery.extractor import TokenExtractor
from app.telegram_discovery.resolver import TokenResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("telegram.collect")


async def main() -> None:
    """
    Main collection flow:
    1. Load configured sources
    2. Sync sources to database
    3. Read new messages from each source
    4. Extract token references
    5. Resolve and store mentions
    """
    start_time = time.monotonic()

    logger.info("=== Telegram Token Discovery Collection ===")

    # Load config
    configs = load_telegram_sources()
    enabled_configs = [c for c in configs if c.enabled]
    logger.info(
        "Loaded %d sources from config (%d enabled)",
        len(configs), len(enabled_configs),
    )

    if not enabled_configs:
        logger.warning(
            "No enabled sources found. Edit telegram_sources.yaml to add your groups."
        )
        return

    # Initialize services
    client_service = TelegramClientService(store_raw_text=False)
    extractor = TokenExtractor()
    resolver = TokenResolver()

    stats = {
        "sources_scanned": 0,
        "messages_processed": 0,
        "messages_skipped_duplicate": 0,
        "messages_skipped_no_tokens": 0,
        "tokens_extracted": 0,
        "tokens_resolved": 0,
        "mentions_created": 0,
        "errors": [],
    }

    try:
        async with async_session_factory() as session:
            # Sync sources
            enabled_sources = await client_service.sync_sources(session, enabled_configs)
            stats["sources_scanned"] = len(enabled_sources)
            logger.info("Synced %d enabled sources to database", len(enabled_sources))

            if not enabled_sources:
                logger.warning("No enabled sources in database. Set TELEGRAM_GROUPS=@group1,@group2 in .env")
                return

            # Collect messages — returns stats + collected (msg, source, text) tuples
            collect_stats, collected_messages = await client_service.collect_messages(
                session, enabled_sources,
            )
            stats["messages_processed"] = collect_stats["messages_processed"]
            stats["messages_skipped_duplicate"] = collect_stats["messages_skipped_duplicate"]
            stats["messages_skipped_no_tokens"] = collect_stats["messages_skipped_no_tokens"]
            stats["errors"].extend(collect_stats["errors"])

            logger.info(
                "Collected %d new messages (%d duplicates, %d without tokens)",
                stats["messages_processed"],
                stats["messages_skipped_duplicate"],
                stats["messages_skipped_no_tokens"],
            )

            # Extract and resolve tokens from collected messages (inline)
            for db_msg, src, text in collected_messages:
                refs = extractor.extract(text)
                stats["tokens_extracted"] += len(refs)

                if refs:
                    mentions = await resolver.resolve_and_store_mentions(
                        session, src, db_msg, refs,
                    )
                    stats["tokens_resolved"] += len([r for r in refs if r.token_address or r.symbol])
                    stats["mentions_created"] += mentions

            # Commit with deadlock retry (concurrent discovery reads can cause
            # deadlocks on the telegram_sources UPDATE batch)
            for attempt in range(3):
                try:
                    with session.no_autoflush:
                        await session.commit()
                    break
                except Exception as commit_err:
                    if "deadlock" in str(commit_err).lower() and attempt < 2:
                        await session.rollback()
                        logger.warning("Deadlock on commit, retrying (%d/3)...", attempt + 1)
                        await asyncio.sleep(0.5 * (attempt + 1))
                    else:
                        raise
            logger.info(
                "Resolved tokens: %d references → %d mentions created",
                stats["tokens_extracted"], stats["mentions_created"],
            )
    except Exception as e:
        logger.error("Collection failed: %s", e, exc_info=True)
        stats["errors"].append(str(e))
    finally:
        await client_service.disconnect()
        await resolver.close()

    elapsed = time.monotonic() - start_time
    logger.info("=== Collection Complete in %.1fs ===", elapsed)
    logger.info("Sources scanned:       %d", stats["sources_scanned"])
    logger.info("Messages processed:    %d", stats["messages_processed"])
    logger.info("Duplicates skipped:    %d", stats["messages_skipped_duplicate"])
    logger.info("No-token skipped:      %d", stats["messages_skipped_no_tokens"])
    logger.info("Tokens extracted:      %d", stats["tokens_extracted"])
    logger.info("Mentions created:      %d", stats["mentions_created"])
    if stats["errors"]:
        logger.warning("Errors: %d", len(stats["errors"]))
        for err in stats["errors"]:
            logger.warning("  - %s", err)


if __name__ == "__main__":
    asyncio.run(main())
