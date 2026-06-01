"""
Celery task stubs for all scheduled pipeline operations.

These tasks are referenced in the Celery beat schedule (celery_app.py).
Each task corresponds to a specific layer or sub-layer operation.
"""

from celery.utils.log import get_task_logger

from app.tasks.celery_app import celery_app

logger = get_task_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Discovery Layer (1) tasks
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.tasks.discovery.run_dexscreener_discovery")
def run_dexscreener_discovery():
    """Run DEXScreener volume + trending discovery (every 15 min)."""
    logger.info("Running DEXScreener discovery...")
    # In production: import and run DexScreenerDiscovery, persist results


@celery_app.task(name="app.tasks.discovery.run_twitter_discovery")
def run_twitter_discovery():
    """Run Twitter/X discovery (hourly).

    Searches Twitter API v2 for cashtag mentions and contract addresses.
    Filters by mention velocity > 3x baseline.
    Requires TWITTER_BEARER_TOKEN in settings; skips gracefully if absent.
    """
    logger.info("Running Twitter discovery...")
    try:
        import asyncio
        from app.layers.discovery.twitter_discovery import TwitterDiscovery

        async def _run():
            source = TwitterDiscovery()
            candidates = await source.discover()
            logger.info(
                "Twitter discovery complete: %d candidates found (velocity > 3x)",
                len(candidates),
            )
            # Log top 5 mentions for debugging
            for c in candidates[:5]:
                logger.info(
                    "Twitter hit: $%s — %.1f mentions (%.1fx baseline)",
                    c.get("symbol", "?"),
                    c.get("mention_count", 0),
                    c.get("mention_velocity", 0),
                )
            return candidates

        return asyncio.run(_run())
    except Exception as e:
        logger.error("Twitter discovery failed: %s", e, exc_info=True)
        return []


@celery_app.task(name="app.tasks.discovery.run_telegram_discovery")
def run_telegram_discovery():
    """Run Telegram discovery (hourly).

    Collects messages from configured Telegram groups, extracts token
    identifiers, resolves them to canonical tokens, and stores mentions.
    Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in settings.
    """
    logger.info("Running Telegram discovery...")
    try:
        import asyncio
        from app.telegram_discovery.client import TelegramClientService
        from app.telegram_discovery.config import load_telegram_sources

        async def _run():
            configs = load_telegram_sources()
            enabled = [c for c in configs if c.enabled]
            if not enabled:
                logger.info("No enabled Telegram sources — skipping")
                return []

            from app.core.database import async_session_factory

            client_service = TelegramClientService(store_raw_text=False)
            try:
                async with async_session_factory() as session:
                    sources = await client_service.sync_sources(session, enabled)
                    stats = await client_service.collect_messages(session, sources)
                    await session.commit()
                    logger.info(
                        "Telegram collection: %d messages (%d duplicates, %d no tokens)",
                        stats["messages_processed"],
                        stats["messages_skipped_duplicate"],
                        stats["messages_skipped_no_tokens"],
                    )
                    return stats
            finally:
                await client_service.disconnect()

        return asyncio.run(_run())
    except Exception as e:
        logger.error("Telegram discovery failed: %s", e, exc_info=True)
        return []


@celery_app.task(name="app.tasks.discovery.run_reddit_discovery")
def run_reddit_discovery():
    """Run Reddit discovery (hourly)."""
    logger.info("Running Reddit discovery...")


@celery_app.task(name="app.tasks.discovery.run_smart_wallet_discovery")
def run_smart_wallet_discovery():
    """Run smart wallet discovery (every 15 min)."""
    logger.info("Running smart wallet discovery...")


@celery_app.task(name="app.tasks.discovery.run_dormant_discovery")
def run_dormant_discovery():
    """Run dormant awakening discovery (hourly)."""
    logger.info("Running dormant awakening discovery...")


@celery_app.task(name="app.tasks.discovery.run_narrative_discovery")
def run_narrative_discovery():
    """Run narrative discovery (daily)."""
    logger.info("Running narrative discovery...")


# ═══════════════════════════════════════════════════════════════════════
# Safety Layer (4) tasks
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.tasks.safety.run_liquidity_check")
def run_liquidity_check():
    """Run liquidity safety checks (every 6 hours)."""
    logger.info("Running liquidity safety checks...")


# ═══════════════════════════════════════════════════════════════════════
# Adoption Layer (8) tasks
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.tasks.adoption.run_holder_check")
def run_holder_check():
    """Run holder velocity checks (every 6 hours)."""
    logger.info("Running holder velocity checks...")


# ═══════════════════════════════════════════════════════════════════════
# Attention Layer (6) tasks
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.tasks.attention.run_twitter_velocity")
def run_twitter_velocity():
    """Calculate Twitter attention velocity (hourly)."""
    logger.info("Running Twitter velocity...")


@celery_app.task(name="app.tasks.attention.run_telegram_velocity")
def run_telegram_velocity():
    """Calculate Telegram attention velocity (hourly)."""
    logger.info("Running Telegram velocity...")


@celery_app.task(name="app.tasks.attention.run_reddit_velocity")
def run_reddit_velocity():
    """Calculate Reddit attention velocity (hourly)."""
    logger.info("Running Reddit velocity...")


# ═══════════════════════════════════════════════════════════════════════
# Market Flow Layer (7) tasks
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.tasks.market_flow.run_market_flow")
def run_market_flow():
    """Calculate market flow scores (every 15 min)."""
    logger.info("Running market flow scoring...")


# ═══════════════════════════════════════════════════════════════════════
# Smart Money Layer (10) tasks
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.tasks.smart_money.run_smart_money")
def run_smart_money():
    """Calculate smart money scores (every 15 min)."""
    logger.info("Running smart money scoring...")


# ═══════════════════════════════════════════════════════════════════════
# Narrative Layer (11) tasks
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.tasks.narrative.run_narrative_scoring")
def run_narrative_scoring():
    """Calculate narrative strength scores (daily)."""
    logger.info("Running narrative scoring...")


# ═══════════════════════════════════════════════════════════════════════
# Ranking Layer (14-15) tasks
# ═══════════════════════════════════════════════════════════════════════

@celery_app.task(name="app.tasks.ranking.run_momentum_and_ranking")
def run_momentum_and_ranking():
    """Run full momentum scoring and ranking (every 15 min)."""
    logger.info("Running momentum and ranking...")
    # In production: run the full pipeline orchestrator for all tracked tokens
