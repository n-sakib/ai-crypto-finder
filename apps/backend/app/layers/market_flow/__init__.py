"""
Market Flow Layer — Confirms real money is entering.

Layer 7: Tracks on-chain volume and trade activity.

Metrics:
- 7.1 Volume Velocity: current vs age-adjusted baseline
- 7.2 Trade Count Velocity: trades/hour vs baseline
- 7.3 Buyer/Seller Ratio: unique buyers vs unique sellers
- 7.4 Liquidity Trend: stable, increasing, or falling
"""

from dataclasses import dataclass, field
from typing import Optional

from app.core.models import AgeBucket


@dataclass
class MarketFlowScore:
    """Market flow scoring result."""
    total_score: float = 0.0  # 0-100

    # Component scores
    volume_velocity_score: float = 0.0
    trade_count_score: float = 0.0
    buyer_seller_ratio_score: float = 0.0
    liquidity_trend_score: float = 0.0

    # Raw metrics
    current_volume: float = 0.0
    baseline_volume: float = 0.0
    volume_velocity: float = 0.0
    trade_count: int = 0
    trades_per_hour: float = 0.0
    baseline_trades_per_hour: float = 0.0
    trade_velocity: float = 0.0
    unique_buyers: int = 0
    unique_sellers: int = 0
    buyer_seller_ratio: float = 0.0
    liquidity_trend: str = "stable"
    liquidity_current: float = 0.0
    liquidity_previous: float = 0.0

    # Flags
    is_interesting: bool = False
    is_strong: bool = False
    has_buyer_warning: bool = False  # volume high but buyer count low

    @property
    def level(self) -> str:
        if self.is_strong:
            return "strong"
        if self.is_interesting:
            return "interesting"
        return "low"


class MarketFlowLayer:
    """
    Analyzes on-chain market flow to confirm real money is entering.

    Volume velocity is the primary signal, supported by trade count,
    buyer/seller ratio, and liquidity trend.
    """

    # Velocity thresholds
    INTERESTING_VOLUME = 2.0
    STRONG_VOLUME = 5.0
    INTERESTING_TRADES = 2.0
    STRONG_TRADES = 5.0

    # Component weights — lean more on volume & buyer/seller ratio
    WEIGHT_VOLUME = 0.40
    WEIGHT_TRADES = 0.25
    WEIGHT_BUYER_SELLER = 0.25
    WEIGHT_LIQUIDITY = 0.10

    async def score(
        self,
        token_data: dict,
        baselines: Optional[dict] = None,
    ) -> MarketFlowScore:
        """
        Calculate market flow score.

        Args:
            token_data: Current token metrics
            baselines: Age-adjusted baselines for comparison
        """
        result = MarketFlowScore()
        baselines = baselines or {}

        # Extract current data
        result.current_volume = float(token_data.get("volume_24h", 0))
        result.trade_count = int(token_data.get("trade_count_24h", 0))
        result.unique_buyers = int(token_data.get("unique_buyers_24h", 0))
        result.unique_sellers = int(token_data.get("unique_sellers_24h", 0))
        result.liquidity_current = float(token_data.get("liquidity_usd", 0))
        result.liquidity_trend = token_data.get("liquidity_trend", "stable")

        # 7.1 Volume Velocity
        self._score_volume_velocity(result, baselines)

        # 7.2 Trade Count Velocity
        self._score_trade_count(result, baselines)

        # 7.3 Buyer/Seller Ratio
        self._score_buyer_seller_ratio(result)

        # 7.4 Liquidity Trend
        self._score_liquidity_trend(result, token_data)

        # Calculate total score
        # Calculate total score
        result.total_score = (
            result.volume_velocity_score * self.WEIGHT_VOLUME +
            result.trade_count_score * self.WEIGHT_TRADES +
            result.buyer_seller_ratio_score * self.WEIGHT_BUYER_SELLER +
            result.liquidity_trend_score * self.WEIGHT_LIQUIDITY
        )

        # Determine level
        if result.total_score >= 70:
            result.is_strong = True
            result.is_interesting = True
        elif result.total_score >= 40:
            result.is_interesting = True

        return result

    def _score_volume_velocity(self, result: MarketFlowScore, baselines: dict):
        """
        7.1 Volume Velocity — log-scaled for differentiation.

        Uses absolute volume on a log scale so $10k vs $500k tokens
        get meaningfully different scores, not just a flat floor.
        """
        result.baseline_volume = baselines.get("avg_volume_24h", 1.0)

        if result.baseline_volume > 0:
            result.volume_velocity = result.current_volume / result.baseline_volume
        else:
            result.volume_velocity = 0.0

        # Score from velocity (2x=40, 5x=70, 10x=100)
        v = result.volume_velocity
        if v >= 10:
            vel_score = 100.0
        elif v >= self.STRONG_VOLUME:
            vel_score = 70.0 + (v - 5) * 6
        elif v >= self.INTERESTING_VOLUME:
            vel_score = 40.0 + (v - 2) * 10
        elif v >= 1.2:
            vel_score = 20.0 + (v - 1.2) * 25
        else:
            vel_score = max(v * 16, 0.0)

        # Absolute volume score — log scale: $1k→5, $10k→30, $100k→55, $1M→80
        import math
        vol = max(result.current_volume, 1)
        abs_score = min((math.log10(vol) - 3) * 28, 100.0)
        abs_score = max(abs_score, 5.0)

        # Blend: 60% velocity, 40% absolute (when velocity data is weak)
        if result.volume_velocity > 1.0:
            result.volume_velocity_score = min(vel_score * 0.6 + abs_score * 0.4, 100.0)
        else:
            result.volume_velocity_score = min(abs_score * 0.75 + 10, 100.0)

        result.volume_velocity_score = min(result.volume_velocity_score, 100.0)

    def _score_trade_count(self, result: MarketFlowScore, baselines: dict):
        """
        7.2 Trade Count Velocity.

        Trades/hour vs baseline.
        Interesting: > 2x. Strong: > 5x.
        """
        result.trades_per_hour = result.trade_count / 24.0 if result.trade_count > 0 else 0.0
        result.baseline_trades_per_hour = max(baselines.get("avg_trades_1h", 0.1), 0.1)

        if result.baseline_trades_per_hour > 0:
            result.trade_velocity = result.trades_per_hour / result.baseline_trades_per_hour
        else:
            result.trade_velocity = 0.0

        tv = result.trade_velocity

        if tv >= 10:
            result.trade_count_score = 100.0
        elif tv >= self.STRONG_TRADES:
            result.trade_count_score = 70.0 + (tv - 5) * 6
        elif tv >= self.INTERESTING_TRADES:
            result.trade_count_score = 40.0 + (tv - 2) * 10
        elif tv >= 1.2:
            result.trade_count_score = 20.0 + (tv - 1.2) * 25
        else:
            result.trade_count_score = max(tv * 16, 0.0)

        result.trade_count_score = min(result.trade_count_score, 100.0)

    def _score_buyer_seller_ratio(self, result: MarketFlowScore):
        """
        7.3 Buyer/Seller Ratio.

        Good: unique buyers > unique sellers.
        Strong: buyers/sellers > 2.
        Warning: volume high but buyer count low.
        """
        if result.unique_sellers > 0:
            result.buyer_seller_ratio = result.unique_buyers / result.unique_sellers
        elif result.unique_buyers > 0:
            result.buyer_seller_ratio = result.unique_buyers  # All buyers, no sellers
        else:
            result.buyer_seller_ratio = 0.0

        ratio = result.buyer_seller_ratio

        # Volume high but buyer count low = warning
        if result.current_volume > 50_000 and result.unique_buyers < 5:
            result.has_buyer_warning = True
            result.buyer_seller_ratio_score = 10.0  # Penalize
        elif ratio > 3.0:
            result.buyer_seller_ratio_score = 100.0
        elif ratio > 2.0:
            result.buyer_seller_ratio_score = 80.0 + (ratio - 2.0) * 20
        elif ratio > 1.0:
            result.buyer_seller_ratio_score = 50.0 + (ratio - 1.0) * 30
        elif ratio > 0.5:
            result.buyer_seller_ratio_score = 20.0 + (ratio - 0.5) * 60
        else:
            result.buyer_seller_ratio_score = 0.0

        result.buyer_seller_ratio_score = min(result.buyer_seller_ratio_score, 100.0)

    def _score_liquidity_trend(self, result: MarketFlowScore, token_data: dict):
        """
        7.4 Liquidity Trend.

        Good: liquidity stable or increasing.
        Warning: liquidity falling while volume rises.
        """
        trend = token_data.get("liquidity_trend", "stable")
        result.liquidity_trend = trend or "stable"

        if trend == "increasing":
            result.liquidity_trend_score = 100.0
            # Bonus: increasing liquidity during volume spike = very bullish
            if result.volume_velocity >= self.INTERESTING_VOLUME:
                result.liquidity_trend_score = 100.0
        elif trend == "stable":
            result.liquidity_trend_score = 60.0
        elif trend == "falling":
            # Warning: liquidity falling while volume rises
            if result.volume_velocity >= self.INTERESTING_VOLUME:
                result.liquidity_trend_score = 10.0  # Strong penalty
            else:
                result.liquidity_trend_score = 25.0
        else:
            result.liquidity_trend_score = 50.0  # Unknown
