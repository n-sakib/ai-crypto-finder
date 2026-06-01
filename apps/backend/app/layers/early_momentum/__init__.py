"""
Early Momentum Score Layer — Combines all opportunity signals.

Layer 14: Aggregates all sub-scores into a single Early Momentum Score.

Inputs:
- Attention Score (Layer 6)
- Market Flow Score (Layer 7)
- Adoption Score (Layer 8)
- Liquidity Quality Score (Layer 9)
- Smart Money Score (Layer 10)
- Narrative Score (Layer 11)
- Price Compression Score (Layer 12) — used as multiplier
- Risk Score (Layer 13) — used as penalty

Weights (configurable via settings):
- Market Flow: 25%
- Attention: 25%
- Adoption: 15%
- Liquidity Quality: 10%
- Smart Money: 10%
- Narrative: 5%
- Price Compression: multiplier
- Risk Score: penalty

Important: High momentum + high risk should not be hidden. Show both separately.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.config import settings
from app.core.models import RiskLevel


@dataclass
class EarlyMomentumScore:
    """Combined early momentum score."""
    total_score: float = 0.0  # 0-100

    # Input scores (0-100)
    attention_score: float = 0.0
    market_flow_score: float = 0.0
    adoption_score: float = 0.0
    liquidity_quality_score: float = 0.0
    smart_money_score: float = 0.0
    narrative_score: float = 0.0
    narrative_boost: float = 0.0  # Additional boost from narrative (0-30)

    # Modifiers
    compression_multiplier: float = 1.0
    risk_penalty: float = 1.0  # 0-1, applied as multiplier
    risk_score: float = 0.0
    risk_level: Optional[RiskLevel] = None

    # Weighted contributions (for transparency)
    contributions: dict[str, float] = field(default_factory=dict)

    # Flags
    is_high_momentum: bool = False
    is_high_risk: bool = False
    has_divergence_warning: bool = False  # High momentum + high risk

    @property
    def adjusted_score(self) -> float:
        """Score after compression multiplier and risk penalty."""
        base = self._weighted_base()
        return base * self.compression_multiplier * self.risk_penalty

    def _weighted_base(self) -> float:
        """Calculate weighted base score before modifiers."""
        return (
            self.market_flow_score * settings.WEIGHT_MARKET_FLOW +
            self.attention_score * settings.WEIGHT_ATTENTION +
            self.adoption_score * settings.WEIGHT_ADOPTION +
            self.liquidity_quality_score * settings.WEIGHT_LIQUIDITY_QUALITY +
            self.smart_money_score * settings.WEIGHT_SMART_MONEY +
            self.narrative_score * settings.WEIGHT_NARRATIVE
        )


class EarlyMomentumLayer:
    """
    Aggregates all sub-scores into the final Early Momentum Score.

    The scoring follows the flow:
    1. Weighted average of all sub-scores
    2. Apply price compression multiplier (Layer 12)
    3. Apply risk penalty (Layer 13)
    4. Add narrative boost (max 30%)
    """

    async def score(
        self,
        attention_score,
        market_flow_score,
        adoption_score,
        liquidity_quality_score,
        smart_money_score,
        narrative_score,
        compression_score,
        risk_report,
    ) -> EarlyMomentumScore:
        """
        Aggregate all layers into a single momentum score.

        Args:
            attention_score: AttentionScore from Layer 6
            market_flow_score: MarketFlowScore from Layer 7
            adoption_score: AdoptionScore from Layer 8
            liquidity_quality_score: LiquidityQualityScore from Layer 9
            smart_money_score: SmartMoneyScore from Layer 10
            narrative_score: NarrativeScore from Layer 11
            compression_score: CompressionScore from Layer 12
            risk_report: RiskReport from Layer 13
        """
        result = EarlyMomentumScore()

        # Extract raw scores
        result.attention_score = getattr(attention_score, "total_score", 0)
        result.market_flow_score = getattr(market_flow_score, "total_score", 0)
        result.adoption_score = getattr(adoption_score, "total_score", 0)
        result.liquidity_quality_score = getattr(liquidity_quality_score, "total_score", 0)
        result.smart_money_score = getattr(smart_money_score, "total_score", 0)
        result.narrative_score = getattr(narrative_score, "total_score", 0)
        result.narrative_boost = getattr(narrative_score, "boost_pct", 0)

        # Get modifiers
        result.compression_multiplier = getattr(compression_score, "multiplier", 1.0)
        result.risk_score = getattr(risk_report, "total_score", 0)
        result.risk_level = getattr(risk_report, "risk_level", None)

        # Calculate risk penalty
        result.risk_penalty = self._calculate_risk_penalty(result.risk_level, result.risk_score)

        # Calculate contributions
        result.contributions = {
            "market_flow": result.market_flow_score * settings.WEIGHT_MARKET_FLOW,
            "attention": result.attention_score * settings.WEIGHT_ATTENTION,
            "adoption": result.adoption_score * settings.WEIGHT_ADOPTION,
            "liquidity_quality": result.liquidity_quality_score * settings.WEIGHT_LIQUIDITY_QUALITY,
            "smart_money": result.smart_money_score * settings.WEIGHT_SMART_MONEY,
            "narrative": result.narrative_score * settings.WEIGHT_NARRATIVE,
            "narrative_boost": result.narrative_boost,
            "compression_multiplier": result.compression_multiplier,
            "risk_penalty": result.risk_penalty,
        }

        # Calculate total score
        base_weighted = result._weighted_base() + result.narrative_boost
        result.total_score = base_weighted * result.compression_multiplier * result.risk_penalty
        result.total_score = min(max(result.total_score, 0.0), 100.0)

        # Set flags
        result.is_high_momentum = result.total_score >= 65
        result.is_high_risk = result.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

        # Divergence: high momentum + high risk should be visible
        result.has_divergence_warning = result.is_high_momentum and result.is_high_risk

        return result

    def _calculate_risk_penalty(self, risk_level, risk_score: float) -> float:
        """
        Calculate risk penalty multiplier.

        - Low risk: no penalty
        - Medium risk: slight penalty
        - High risk: significant penalty
        - Critical risk: maximum penalty

        Important: High momentum + high risk is NOT hidden — the flag
        remains visible and the token may go to 'Excluded' tier.
        """
        if risk_level is None:
            return 1.0

        if risk_level == RiskLevel.LOW:
            return 1.0
        elif risk_level == RiskLevel.MEDIUM:
            return 0.85
        elif risk_level == RiskLevel.HIGH:
            return 0.60
        elif risk_level == RiskLevel.CRITICAL:
            return 0.30
        return 1.0
