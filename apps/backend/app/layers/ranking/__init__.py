"""
Ranking Layer — Creates actionable tiered rankings.

Layer 15: Sorts tokens into tiers based on momentum and risk.

Tiers:
- Tier A: High momentum + low/medium risk — Review immediately
- Tier B: Strong momentum + acceptable risk — Watch closely
- Tier C: Early signs — Needs more confirmation
- Excluded: High momentum + critical risk — Visible in "Rejected / Dangerous" list

Output: Top 20 opportunities + rejected high-risk list.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.models import RankingTier, RiskLevel


@dataclass
class RankedToken:
    """Token with ranking tier and position."""
    token_id: str
    symbol: str
    chain: str
    contract_address: str

    # Scores
    early_momentum_score: float = 0.0
    risk_level: Optional[RiskLevel] = None
    risk_score: float = 0.0

    # Tier
    tier: RankingTier = RankingTier.TIER_C
    position: int = 0

    # Sub-scores for transparency
    attention_score: float = 0.0
    market_flow_score: float = 0.0
    adoption_score: float = 0.0

    # Flags
    has_divergence: bool = False  # High momentum + high risk

    # Metadata
    liquidity_usd: float = 0.0
    volume_24h: float = 0.0
    price_change_24h: float = 0.0
    market_cap: float = 0.0


@dataclass
class RankingResult:
    """Complete ranking output."""
    tier_a: list[RankedToken] = field(default_factory=list)
    tier_b: list[RankedToken] = field(default_factory=list)
    tier_c: list[RankedToken] = field(default_factory=list)
    excluded: list[RankedToken] = field(default_factory=list)

    total_candidates: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def top_20(self) -> list[RankedToken]:
        """Top 20 opportunities (Tier A + Tier B, sorted)."""
        all_opportunities = self.tier_a + self.tier_b
        all_opportunities.sort(key=lambda t: t.early_momentum_score, reverse=True)
        return all_opportunities[:20]


class RankingLayer:
    """
    Assigns tokens to tiers based on momentum and risk.

    Ranking logic:
    - Tier A: momentum >= 65 AND risk in (LOW, MEDIUM)
    - Tier B: momentum >= 45 AND risk in (LOW, MEDIUM)
    - Tier C: momentum >= 20
    - Excluded: risk == CRITICAL (even with high momentum)
    """

    # Momentum thresholds
    TIER_A_MOMENTUM = 21.0
    TIER_B_MOMENTUM = 14.0
    TIER_C_MOMENTUM = 7.0

    async def rank(self, tokens: list[dict]) -> RankingResult:
        """
        Rank tokens into tiers.

        Args:
            tokens: List of token dicts with momentum and risk scores
        """
        result = RankingResult()
        ranked: list[RankedToken] = []

        for t in tokens:
            momentum = float(t.get("early_momentum_score", 0))
            risk_level_str = t.get("risk_level", "low")
            risk_score = float(t.get("risk_score", 0))

            try:
                risk_level = RiskLevel(risk_level_str)
            except (ValueError, TypeError):
                risk_level = RiskLevel.LOW

            ranked_token = RankedToken(
                token_id=str(t.get("id", "")),
                symbol=t.get("symbol", ""),
                chain=t.get("chain", ""),
                contract_address=t.get("contract_address", ""),
                early_momentum_score=momentum,
                risk_level=risk_level,
                risk_score=risk_score,
                attention_score=float(t.get("attention_score", 0)),
                market_flow_score=float(t.get("market_flow_score", 0)),
                adoption_score=float(t.get("adoption_score", 0)),
                has_divergence=bool(t.get("has_divergence_warning", False)),
                liquidity_usd=float(t.get("liquidity_usd", 0)),
                volume_24h=float(t.get("volume_24h", 0)),
                price_change_24h=float(t.get("price_change_24h", 0)),
                market_cap=float(t.get("market_cap", 0)),
            )

            # 15.4 Excluded: High momentum but critical risk
            if risk_level == RiskLevel.CRITICAL:
                ranked_token.tier = RankingTier.EXCLUDED
                ranked.append(ranked_token)
                continue

            # 15.1 Tier A: High momentum + low/medium risk
            if momentum >= self.TIER_A_MOMENTUM and risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
                ranked_token.tier = RankingTier.TIER_A
            # 15.2 Tier B: Strong momentum + acceptable risk
            elif momentum >= self.TIER_B_MOMENTUM and risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
                ranked_token.tier = RankingTier.TIER_B
            # 15.3 Tier C: Early signs
            elif momentum >= self.TIER_C_MOMENTUM:
                ranked_token.tier = RankingTier.TIER_C
            else:
                # Below threshold — not ranked
                continue

            ranked.append(ranked_token)

        # Sort each tier by momentum descending
        result.tier_a = self._sort_and_position(
            [t for t in ranked if t.tier == RankingTier.TIER_A]
        )
        result.tier_b = self._sort_and_position(
            [t for t in ranked if t.tier == RankingTier.TIER_B]
        )
        result.tier_c = self._sort_and_position(
            [t for t in ranked if t.tier == RankingTier.TIER_C]
        )
        result.excluded = self._sort_and_position(
            [t for t in ranked if t.tier == RankingTier.EXCLUDED]
        )
        result.total_candidates = len(ranked)

        return result

    def _sort_and_position(self, tokens: list[RankedToken]) -> list[RankedToken]:
        """Sort tokens by momentum and assign positions."""
        tokens.sort(key=lambda t: t.early_momentum_score, reverse=True)
        for i, token in enumerate(tokens):
            token.position = i + 1
        return tokens
