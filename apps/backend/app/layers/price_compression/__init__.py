"""
Price Compression Layer — Finds attention before price fully reacts.

Layer 12: Detects tokens where attention and flow are rising but price hasn't moved much yet.

Metrics:
- 12.1 Price Change Windows: 1h, 6h, 24h, 7d
- 12.2 Distance From High: 24h, 7d, 30d (mature)
- 12.3 Ideal Compression: attention ↑, flow ↑, holders ↑, price < +15%
- 12.4 Warning: price +30% to +50%
- 12.5 Penalize/Reject: price +100%+ or near blow-off high
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CompressionScore:
    """Price compression scoring result."""
    total_score: float = 0.0  # 0-100 (higher = more compressed = better early entry)
    multiplier: float = 1.0   # Multiplier for momentum score

    # Price changes
    price_change_1h: float = 0.0
    price_change_6h: float = 0.0
    price_change_24h: float = 0.0
    price_change_7d: float = 0.0

    # Distance from highs
    distance_from_24h_high: float = 0.0  # Negative = below high
    distance_from_7d_high: float = 0.0
    distance_from_30d_high: float = 0.0

    # Current price context
    current_price: float = 0.0
    is_near_blowoff_high: bool = False

    # Flags
    is_ideal_compression: bool = False
    is_warning_zone: bool = False
    is_penalized: bool = False

    @property
    def level(self) -> str:
        if self.is_penalized:
            return "penalized"
        if self.is_warning_zone:
            return "warning"
        if self.is_ideal_compression:
            return "ideal"
        return "neutral"


class PriceCompressionLayer:
    """
    Scores tokens based on price compression — the gap between
    rising attention/flow and lagging price movement.

    The best entries occur when:
    - Attention and market flow are rising
    - Holders are growing
    - But price is still < +15% over relevant window
    """

    # Thresholds
    IDEAL_COMPRESSION_PRICE = 15.0    # < +15% = ideal
    WARNING_PRICE_LOW = 30.0          # +30%
    WARNING_PRICE_HIGH = 50.0         # +50%
    PENALIZE_PRICE = 100.0            # +100%+
    BLOWOFF_THRESHOLD = 5.0           # Within 5% of local high

    async def score(
        self,
        token_data: dict,
        attention_rising: bool = False,
        flow_rising: bool = False,
        holders_rising: bool = False,
    ) -> CompressionScore:
        """
        Calculate price compression score.

        Args:
            token_data: Price and high data
            attention_rising: Is attention velocity above threshold?
            flow_rising: Is market flow above threshold?
            holders_rising: Are holders growing above threshold?
        """
        result = CompressionScore()

        # Extract price data
        result.price_change_1h = float(token_data.get("price_change_1h", 0))
        result.price_change_6h = float(token_data.get("price_change_6h", 0))
        result.price_change_24h = float(token_data.get("price_change_24h", 0))
        result.price_change_7d = float(token_data.get("price_change_7d", 0))
        result.distance_from_24h_high = float(token_data.get("distance_from_24h_high", 0))
        result.distance_from_7d_high = float(token_data.get("distance_from_7d_high", 0))
        result.distance_from_30d_high = float(token_data.get("distance_from_30d_high", 0))
        result.current_price = float(token_data.get("price_usd", 0))

        # 12.5 Check blow-off proximity
        result.is_near_blowoff_high = self._check_blowoff(result)

        # 12.1-12.3 Evaluate compression across windows
        compression_score = self._evaluate_compression(result)

        # 12.4-12.5 Evaluate warnings and penalties
        result.is_penalized = self._is_penalized(result)
        result.is_warning_zone = self._is_warning(result)
        result.is_ideal_compression = (
            not result.is_penalized
            and not result.is_warning_zone
            and attention_rising
            and flow_rising
            and holders_rising
            and self._max_price_change(result) <= self.IDEAL_COMPRESSION_PRICE
        )

        # Calculate score
        if result.is_penalized:
            result.total_score = 0.0
            result.multiplier = 0.7  # Penalty on momentum
        elif result.is_warning_zone:
            result.total_score = 30.0
            result.multiplier = 0.85
        elif result.is_ideal_compression:
            result.total_score = 100.0
            result.multiplier = 1.25  # Bonus for ideal early entry
        else:
            result.total_score = compression_score
            result.multiplier = 1.0

        # Additional penalty for blow-off proximity
        if result.is_near_blowoff_high:
            result.total_score = max(result.total_score * 0.5, 0.0)
            result.multiplier = min(result.multiplier, 0.8)

        return result

    def _evaluate_compression(self, result: CompressionScore) -> float:
        """
        Evaluate compression across multiple time windows.

        Ideal: attention/fow rising but price still subdued.
        """
        max_change = self._max_price_change(result)

        # Score based on how subdued the price is
        if max_change <= 5.0:
            return 100.0  # Almost no price movement
        elif max_change <= self.IDEAL_COMPRESSION_PRICE:
            return 80.0 + (self.IDEAL_COMPRESSION_PRICE - max_change) / 15 * 20
        elif max_change <= self.WARNING_PRICE_LOW:
            return 50.0 + (self.WARNING_PRICE_LOW - max_change) / 15 * 30
        elif max_change <= self.WARNING_PRICE_HIGH:
            return 20.0 + (self.WARNING_PRICE_HIGH - max_change) / 20 * 30
        else:
            return max(100.0 - max_change, 0.0)

    def _max_price_change(self, result: CompressionScore) -> float:
        """Get the maximum price change across tracked windows."""
        return max(
            abs(result.price_change_1h),
            abs(result.price_change_6h),
            abs(result.price_change_24h),
            abs(result.price_change_7d),
        )

    def _check_blowoff(self, result: CompressionScore) -> bool:
        """
        Check if price is near a local blow-off high.
        Within 5% of 24h or 7d high is concerning.
        """
        if result.distance_from_24h_high >= -self.BLOWOFF_THRESHOLD:
            return True  # Within 5% of 24h high
        if result.distance_from_7d_high >= -self.BLOWOFF_THRESHOLD:
            return True  # Within 5% of 7d high
        if result.distance_from_30d_high >= -self.BLOWOFF_THRESHOLD and abs(result.distance_from_30d_high) > 0:
            return True
        return False

    def _is_warning(self, result: CompressionScore) -> bool:
        """
        12.4 Warning: price +30% to +50%.
        Still possible entry, but less early.
        """
        max_change = self._max_price_change(result)
        return self.WARNING_PRICE_LOW <= max_change <= self.WARNING_PRICE_HIGH

    def _is_penalized(self, result: CompressionScore) -> bool:
        """
        12.5 Penalize/Reject: price +100%+ or near blow-off high.
        """
        max_change = self._max_price_change(result)
        return max_change >= self.PENALIZE_PRICE or result.is_near_blowoff_high
