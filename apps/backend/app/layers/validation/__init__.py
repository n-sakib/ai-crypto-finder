"""
Validation Layer — Confirms the market is starting to notice.

Layer 17: Uses external signals for independent validation.

Validators:
- 17.1 CoinGecko Trending — use only as validation, never primary discovery
- 17.2 CoinMarketCap Trending — use only as validation
- 17.3 News Mentions — use as validation
- 17.4 Exchange Listings — use as validation

Output: Conviction boost based on external validation signals.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ValidationReport:
    """External validation result."""
    total_score: float = 0.0     # 0-100
    conviction_boost: float = 0.0  # Additional boost to momentum (0-15%)

    # Individual validators
    coingecko_trending: bool = False
    coingecko_position: Optional[int] = None
    cmc_trending: bool = False
    cmc_position: Optional[int] = None
    news_mention_count: int = 0
    news_sources: list[str] = field(default_factory=list)
    exchange_listings: list[dict] = field(default_factory=list)
    new_exchange_count: int = 0

    # Flags
    is_validated: bool = False
    validation_signals: list[str] = field(default_factory=list)

    # Metadata
    validated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ValidationLayer:
    """
    Uses external independent signals to validate that the broader market
    is starting to pay attention.

    IMPORTANT: These are CONFIRMATION signals only.
    Never use these for primary discovery — that would create a feedback loop.

    Validation boosts conviction but doesn't replace earlier layer analysis.
    """

    # Boost amounts per signal
    BOOST_COINGECKO_TRENDING = 5.0     # 5% boost
    BOOST_CMC_TRENDING = 5.0           # 5% boost
    BOOST_NEWS_3_PLUS = 5.0            # 5% boost for 3+ news mentions
    BOOST_EXCHANGE_LISTING = 7.0       # 7% boost for new exchange listing
    MAX_CONVICTION_BOOST = 15.0        # Cap total boost at 15%

    async def validate(
        self,
        token_symbol: str,
        token_name: str = "",
        contract_address: str = "",
    ) -> ValidationReport:
        """
        Run all external validators.

        In production: call CoinGecko API, CoinMarketCap API, news APIs,
        and track exchange announcements.
        """
        report = ValidationReport()

        # 17.1 CoinGecko Trending
        cg_result = await self._check_coingecko_trending(token_symbol, token_name)
        report.coingecko_trending = cg_result.get("trending", False)
        report.coingecko_position = cg_result.get("position")

        # 17.2 CoinMarketCap Trending
        cmc_result = await self._check_cmc_trending(token_symbol, token_name)
        report.cmc_trending = cmc_result.get("trending", False)
        report.cmc_position = cmc_result.get("position")

        # 17.3 News Mentions
        news_result = await self._check_news_mentions(token_symbol, token_name)
        report.news_mention_count = news_result.get("count", 0)
        report.news_sources = news_result.get("sources", [])

        # 17.4 Exchange Listings
        exchange_result = await self._check_exchange_listings(token_symbol, contract_address)
        report.exchange_listings = exchange_result.get("listings", [])
        report.new_exchange_count = exchange_result.get("new_count", 0)

        # Calculate conviction boost
        report.conviction_boost = self._calculate_boost(report)

        # Build validation signals
        report.validation_signals = self._build_signals(report)

        # Score
        report.total_score = self._calculate_score(report)
        report.is_validated = report.total_score >= 30

        return report

    async def _check_coingecko_trending(self, symbol: str, name: str) -> dict:
        """
        17.1 CoinGecko Trending.

        Check if token appears in CoinGecko trending lists.
        NEVER use for discovery — validation only.
        """
        # In production: GET /api/v3/search/trending
        return {"trending": False, "position": None}

    async def _check_cmc_trending(self, symbol: str, name: str) -> dict:
        """
        17.2 CoinMarketCap Trending.

        Check if token appears in CMC trending.
        NEVER use for discovery — validation only.
        """
        return {"trending": False, "position": None}

    async def _check_news_mentions(self, symbol: str, name: str) -> dict:
        """
        17.3 News Mentions.

        Check crypto news aggregators for token mentions.
        """
        return {"count": 0, "sources": []}

    async def _check_exchange_listings(self, symbol: str, contract: str) -> dict:
        """
        17.4 Exchange Listings.

        Track recent exchange listings for the token.
        """
        return {"listings": [], "new_count": 0}

    def _calculate_boost(self, report: ValidationReport) -> float:
        """
        Calculate total conviction boost from external signals.

        Capped at MAX_CONVICTION_BOOST (15%).
        """
        boost = 0.0

        if report.coingecko_trending:
            boost += self.BOOST_COINGECKO_TRENDING

        if report.cmc_trending:
            boost += self.BOOST_CMC_TRENDING

        if report.news_mention_count >= 3:
            boost += self.BOOST_NEWS_3_PLUS

        if report.new_exchange_count > 0:
            boost += self.BOOST_EXCHANGE_LISTING * min(report.new_exchange_count, 2)

        return min(boost, self.MAX_CONVICTION_BOOST)

    def _build_signals(self, report: ValidationReport) -> list[str]:
        """Build human-readable validation signal list."""
        signals = []

        if report.coingecko_trending:
            pos = report.coingecko_position
            signals.append(
                f"CoinGecko Trending{' #' + str(pos) if pos else ''}"
            )

        if report.cmc_trending:
            pos = report.cmc_position
            signals.append(
                f"CoinMarketCap Trending{' #' + str(pos) if pos else ''}"
            )

        if report.news_mention_count > 0:
            signals.append(
                f"{report.news_mention_count} news mention(s)"
            )

        if report.new_exchange_count > 0:
            signals.append(
                f"{report.new_exchange_count} new exchange listing(s)"
            )

        return signals

    def _calculate_score(self, report: ValidationReport) -> float:
        """
        Calculate validation score 0-100.

        Higher score = more external validation.
        """
        score = 0.0

        if report.coingecko_trending:
            score += 30.0
        if report.cmc_trending:
            score += 30.0

        # News: up to 20 points
        score += min(report.news_mention_count * 5, 20.0)

        # Exchange listings: up to 20 points
        score += min(report.new_exchange_count * 10, 20.0)

        return min(score, 100.0)
