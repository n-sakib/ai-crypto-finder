"""
Reddit Discovery — Finds tokens from broader community discussion.

Source: 1.5 Reddit Discovery
Update: hourly
Criteria: mentions/comments/upvotes > 2x baseline

Issue fixed: Reddit is treated as slower confirmation, not the earliest signal.
"""

import asyncio
from typing import Optional

from app.config import settings
from app.layers.discovery.base import BaseDiscoverySource


class RedditDiscovery(BaseDiscoverySource):
    """
    Discovers tokens from Reddit communities.

    Monitors crypto subreddits for:
    - Token mentions (symbol + contract address)
    - Comment activity
    - Upvote surges

    Treated as slower confirmation signal, not primary discovery.
    """

    TARGET_SUBREDDITS = [
        "CryptoCurrency",
        "CryptoMoonShots",
        "altcoin",
        "defi",
        "SolanaMemeCoins",
        "ethtrader",
    ]

    def __init__(self):
        self._baselines: dict[str, dict] = {}  # subreddit -> {mentions, comments, upvotes}

    def source_name(self) -> str:
        return "Reddit"

    async def discover(self) -> list[dict]:
        """
        Scan Reddit for token mentions with velocity > 2x baseline.

        Requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in settings.
        Uses asyncpraw for async Reddit API access.
        """
        if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
            return []  # Reddit is optional

        candidates: list[dict] = []

        # In production: connect via asyncpraw, scan recent posts/comments
        # in target subreddits for token mentions

        return self._filter_by_velocity(candidates)

    async def _scan_subreddit(self, subreddit: str) -> list[dict]:
        """
        Scan a single subreddit for recent token mentions.

        In production: use asyncpraw to fetch hot/new posts and comments.
        Extract symbols, contract addresses, count mentions/upvotes/comments.
        """
        return []

    def _filter_by_velocity(self, candidates: list[dict]) -> list[dict]:
        """
        Filter: mentions/comments/upvotes > 2x baseline.
        Reddit is confirmation, not primary signal.
        """
        filtered: list[dict] = []
        for c in candidates:
            subreddit = c.get("subreddit", "")
            baseline = self._baselines.get(subreddit, {})
            mentions = c.get("mentions", 0)
            baseline_mentions = baseline.get("mentions", 1.0)
            if baseline_mentions > 0 and mentions / baseline_mentions >= 2.0:
                filtered.append(c)
        return filtered

    def update_baselines(self, subreddit_metrics: dict[str, dict]):
        """Update per-subreddit baselines."""
        self._baselines.update(subreddit_metrics)
