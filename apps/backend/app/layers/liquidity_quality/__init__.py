"""
Liquidity Quality Layer — Checks whether trading conditions are healthy.

Layer 9: Evaluates liquidity depth, stability, and lock status.

Checks:
- 9.1 Liquidity Amount: $100k minimum, $500k+ preferred
- 9.2 Liquidity Stability: stable/increasing vs falling
- 9.3 Liquidity Lock / Ownership: locked or burned LP
- 9.4 Slippage Risk: penalty for large slippage on reasonable trade sizes
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LiquidityQualityScore:
    """Liquidity quality scoring result."""
    total_score: float = 0.0  # 0-100

    # Component scores
    amount_score: float = 0.0
    stability_score: float = 0.0
    lock_score: float = 0.0
    slippage_score: float = 0.0

    # Raw metrics
    liquidity_usd: float = 0.0
    liquidity_trend: str = "stable"
    is_locked: bool = False
    is_burned: bool = False
    slippage_pct: float = 0.0  # Estimated slippage for $1k trade

    # Flags
    is_healthy: bool = False
    has_slippage_warning: bool = False


class LiquidityQualityLayer:
    """
    Evaluates liquidity quality beyond simple amount checks.

    Considers depth, stability, lock/burn status, and slippage risk.
    """

    # Liquidity amount tiers
    MIN_LIQUIDITY = 100_000
    PREFERRED_LIQUIDITY = 500_000
    EXCELLENT_LIQUIDITY = 2_000_000

    # Slippage thresholds
    MAX_SLIPPAGE_1K = 2.0  # Max 2% slippage for $1k trade

    # Component weights
    WEIGHT_AMOUNT = 0.30
    WEIGHT_STABILITY = 0.30
    WEIGHT_LOCK = 0.25
    WEIGHT_SLIPPAGE = 0.15

    async def score(self, token_data: dict) -> LiquidityQualityScore:
        """
        Calculate liquidity quality score.

        Args:
            token_data: Token data with liquidity metrics
        """
        result = LiquidityQualityScore()

        # Extract metrics
        result.liquidity_usd = float(token_data.get("liquidity_usd", 0))
        result.liquidity_trend = token_data.get("liquidity_trend", "stable") or "stable"
        result.is_locked = bool(token_data.get("is_liquidity_locked", False))
        result.is_burned = bool(token_data.get("is_liquidity_burned", False))
        result.slippage_pct = float(token_data.get("slippage_pct_1k", 0))

        # 9.1 Liquidity Amount
        self._score_amount(result)

        # 9.2 Liquidity Stability
        self._score_stability(result)

        # 9.3 Liquidity Lock / Ownership
        self._score_lock(result)

        # 9.4 Slippage Risk
        self._score_slippage(result)

        # Total score
        result.total_score = (
            result.amount_score * self.WEIGHT_AMOUNT +
            result.stability_score * self.WEIGHT_STABILITY +
            result.lock_score * self.WEIGHT_LOCK +
            result.slippage_score * self.WEIGHT_SLIPPAGE
        )

        result.is_healthy = result.total_score >= 50

        return result

    def _score_amount(self, result: LiquidityQualityScore):
        """
        9.1 Liquidity Amount.

        - Minimum: $100k
        - Preferred: $500k+
        """
        liq = result.liquidity_usd

        if liq >= self.EXCELLENT_LIQUIDITY:
            result.amount_score = 100.0
        elif liq >= self.PREFERRED_LIQUIDITY:
            # $500k-$2M: 70-100
            result.amount_score = 70.0 + (liq - self.PREFERRED_LIQUIDITY) / \
                (self.EXCELLENT_LIQUIDITY - self.PREFERRED_LIQUIDITY) * 30
        elif liq >= self.MIN_LIQUIDITY:
            # $100k-$500k: 30-70
            result.amount_score = 30.0 + (liq - self.MIN_LIQUIDITY) / \
                (self.PREFERRED_LIQUIDITY - self.MIN_LIQUIDITY) * 40
        elif liq > 0:
            # Below $100k: 0-30
            result.amount_score = (liq / self.MIN_LIQUIDITY) * 30
        else:
            result.amount_score = 0.0

        result.amount_score = min(result.amount_score, 100.0)

    def _score_stability(self, result: LiquidityQualityScore):
        """
        9.2 Liquidity Stability.

        Good: liquidity stable or increasing.
        Bad: liquidity dropping during volume spike.
        """
        trend = result.liquidity_trend

        if trend == "increasing":
            result.stability_score = 100.0
        elif trend == "stable":
            result.stability_score = 75.0
        elif trend == "falling":
            result.stability_score = 20.0
        elif trend == "falling_fast":
            result.stability_score = 0.0
        else:
            result.stability_score = 50.0

    def _score_lock(self, result: LiquidityQualityScore):
        """
        9.3 Liquidity Lock / Ownership.

        Good: LP locked or burned.
        Bad: unlocked LP with anonymous team.
        """
        if result.is_burned:
            result.lock_score = 100.0  # Burned LP is best
        elif result.is_locked:
            result.lock_score = 80.0   # Locked LP is good
        else:
            result.lock_score = 10.0   # Unlocked LP — high risk

    def _score_slippage(self, result: LiquidityQualityScore):
        """
        9.4 Slippage Risk.

        Penalize tokens where reasonable trade sizes cause large slippage.
        """
        slippage = result.slippage_pct

        if slippage <= 0.5:
            result.slippage_score = 100.0
        elif slippage <= self.MAX_SLIPPAGE_1K:
            result.slippage_score = 50.0 + (self.MAX_SLIPPAGE_1K - slippage) / \
                (self.MAX_SLIPPAGE_1K - 0.5) * 50
        elif slippage <= 5.0:
            result.slippage_score = 10.0 + (5.0 - slippage) / (5.0 - self.MAX_SLIPPAGE_1K) * 40
            result.has_slippage_warning = True
        elif slippage <= 10.0:
            result.slippage_score = (10.0 - slippage) / 5.0 * 10
            result.has_slippage_warning = True
        else:
            result.slippage_score = 0.0
            result.has_slippage_warning = True

        result.slippage_score = min(result.slippage_score, 100.0)
