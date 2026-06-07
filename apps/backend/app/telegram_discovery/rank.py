"""
CLI: Telegram Discovery Ranking.

Usage:
    python -m app.telegram_discovery.rank --window 1h --limit 100

Computes token discovery rankings for a specified time window based on
Telegram mention data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Add backend to path if running directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.database import async_session_factory
from app.telegram_discovery.aggregator import TelegramDiscoveryAggregator
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("telegram.rank")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank Telegram-discovered tokens by mention frequency.",
    )
    parser.add_argument(
        "--window", "-w",
        default=f"{settings.DISCOVERY_WINDOW_MINUTES}m",
        help=f"Time window (e.g., 30m, 1h, 6h, 24h). Default: {settings.DISCOVERY_WINDOW_MINUTES}m",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=settings.TOP_DISCOVERY_LIMIT,
        help=f"Maximum number of tokens to rank. Default: {settings.TOP_DISCOVERY_LIMIT}",
    )
    parser.add_argument(
        "--min-mentions",
        type=int,
        default=settings.MIN_MENTIONS,
        help=f"Minimum mention count to include. Default: {settings.MIN_MENTIONS}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    start_time = time.monotonic()

    logger.info("=== Telegram Discovery Ranking ===")
    logger.info("Window: %s | Limit: %d | Min mentions: %d",
                args.window, args.limit, args.min_mentions)

    aggregator = TelegramDiscoveryAggregator(
        min_mention_count=args.min_mentions,
    )

    async with async_session_factory() as session:
        result = await aggregator.rank(
            session,
            window=args.window,
            limit=args.limit,
        )
        await session.commit()

    elapsed = time.monotonic() - start_time

    if args.json:
        import json
        from datetime import datetime

        def json_serial(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, "value"):  # Enum
                return obj.value
            return str(obj)

        output = {
            "window": result.window,
            "window_start": result.window_start.isoformat(),
            "window_end": result.window_end.isoformat(),
            "total_tokens": result.total_tokens,
            "elapsed_seconds": round(elapsed, 2),
            "tokens": [
                {
                    "rank": t.rank,
                    "chain": t.chain,
                    "token_address": t.token_address,
                    "symbol": t.symbol,
                    "name": t.name,
                    "mention_count": t.mention_count,
                    "unique_user_count": t.unique_user_count,
                    "group_count": t.group_count,
                    "discovery_methods": [m.value for m in t.discovery_methods],
                    "source_names": t.source_names,
                    "dex_url": t.dex_url,
                }
                for t in result.tokens
            ],
        }
        print(json.dumps(output, indent=2, default=json_serial))
    else:
        logger.info("=== Ranking Results (%s, %.1fs) ===", result.window, elapsed)
        logger.info("Total candidates: %d", result.total_tokens)
        print()
        print(f"{'Rank':<5} {'Symbol':<10} {'Chain':<10} {'Mentions':<10} {'Users':<8} {'Groups':<8} {'Sources'}")
        print("-" * 80)
        for t in result.tokens:
            print(
                f"{t.rank:<5} {t.symbol:<10} {t.chain:<10} "
                f"{t.mention_count:<10} {t.unique_user_count:<8} "
                f"{t.group_count:<8} {', '.join(t.source_names[:3])}"
            )
        print("-" * 80)
        if result.total_tokens == 0:
            print("\nNo tokens met the minimum thresholds.")
            print("Try lowering --min-mentions or --min-users, or expanding the --window.")


if __name__ == "__main__":
    asyncio.run(main())
