"""
Narrative Layer — Adds market context via sector classification.

Layer 11: Tags tokens with narrative categories and scores narrative strength.

Narratives: AI, RWA, DePIN, Gaming, Privacy, Memes, Prediction Markets, L1/L2

Strengths:
- Cold: 0% boost
- Warm: 10% boost
- Hot: 20% boost
- Dominant: 30% boost

Issue fixed: narrative only adds context, not automatic conviction.
Must be based on sector-wide activity, not just one token claiming a narrative.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.core.models import NarrativeType, NarrativeStrength


# Boost multipliers for each narrative strength
NARRATIVE_BOOST: dict[NarrativeStrength, float] = {
    NarrativeStrength.COLD: 0.0,
    NarrativeStrength.WARM: 10.0,
    NarrativeStrength.HOT: 20.0,
    NarrativeStrength.DOMINANT: 30.0,
}


@dataclass
class NarrativeScore:
    """Narrative scoring result."""
    total_score: float = 0.0  # 0-100 base score
    boost_pct: float = 0.0    # Additional boost percentage (0-30)

    # Active narratives for this token
    narratives: list[dict] = field(default_factory=list)

    # Sector-wide metrics
    sector_volume_24h: float = 0.0
    sector_volume_change_24h: float = 0.0
    sector_market_cap: float = 0.0

    @property
    def final_score(self) -> float:
        """Score with narrative boost applied (capped at 100)."""
        return min(self.total_score + self.boost_pct, 100.0)

    @property
    def dominant_narrative(self) -> Optional[str]:
        """Return the strongest narrative, if any."""
        if not self.narratives:
            return None
        return max(self.narratives, key=lambda n: NARRATIVE_BOOST.get(
            NarrativeStrength(n.get("strength", "cold")), 0
        )).get("narrative")


class NarrativeLayer:
    """
    Scores narrative relevance and strength.

    Narrative adds context and a configurable boost — never automatic conviction.
    Narrative strength must be validated by sector-wide data.
    """

    # Minimum sector volume to consider a narrative "active"
    MIN_SECTOR_VOLUME = 1_000_000  # $1M daily

    async def score(
        self,
        token_narratives: list[dict],
        sector_data: Optional[dict] = None,
    ) -> NarrativeScore:
        """
        Calculate narrative score.

        Args:
            token_narratives: List of {narrative, strength} for this token
            sector_data: Sector-wide metrics for validation
        """
        result = NarrativeScore()
        sector_data = sector_data or {}

        # Validate each narrative against sector data
        validated_narratives = []
        for n in token_narratives:
            narrative = n.get("narrative", "")
            strength = n.get("strength", NarrativeStrength.COLD.value)

            # 11.3 Narrative Validation — must be sector-wide
            if self._validate_narrative(narrative, sector_data):
                validated_narratives.append({
                    "narrative": narrative,
                    "strength": strength,
                })

        result.narratives = validated_narratives

        # Calculate base score from narrative strength
        result.total_score = self._calculate_base_score(validated_narratives)

        # Calculate boost
        result.boost_pct = self._calculate_boost(validated_narratives)

        # Sector metrics
        result.sector_volume_24h = float(sector_data.get("volume_24h", 0))
        result.sector_volume_change_24h = float(sector_data.get("volume_change_24h", 0))
        result.sector_market_cap = float(sector_data.get("market_cap", 0))

        return result

    def _validate_narrative(self, narrative: str, sector_data: dict) -> bool:
        """
        11.3 Narrative Validation.

        Must be based on sector-wide activity, not just one token claiming it.
        """
        if not narrative:
            return False

        # Check sector has meaningful volume
        sector_volume = float(sector_data.get("volume_24h", 0))
        if sector_volume < self.MIN_SECTOR_VOLUME:
            return False

        return True

    def _calculate_base_score(self, narratives: list[dict]) -> float:
        """
        Calculate base score from narrative presence.

        Multiple narratives = stronger diversification signal.
        Strong narratives contribute more.
        """
        if not narratives:
            return 0.0

        # Base: 20 points for having any narrative
        base = 20.0

        # Additional: up to 80 points based on narrative count and strength
        strength_values = {
            "cold": 0,
            "warm": 1,
            "hot": 2,
            "dominant": 3,
        }

        narrative_points = sum(
            strength_values.get(n.get("strength", "cold"), 0)
            for n in narratives
        )

        # Max from strength = 3 narratives * dominant(3) = 9
        # Scale 0-9 to 0-80
        extra = min(narrative_points / 9 * 80, 80.0)

        return base + extra

    def _calculate_boost(self, narratives: list[dict]) -> float:
        """
        Calculate narrative boost percentage (0-30%).

        Uses the strongest narrative to determine boost.
        """
        if not narratives:
            return 0.0

        max_boost = 0.0
        for n in narratives:
            strength = NarrativeStrength(n.get("strength", "cold"))
            boost = NARRATIVE_BOOST.get(strength, 0.0)
            max_boost = max(max_boost, boost)

        return max_boost

    async def classify_token(
        self,
        token_symbol: str,
        token_name: str,
        token_description: str = "",
    ) -> list[dict]:
        """
        Classify a token into narratives based on symbol, name, and description.

        In production: use NLP/embedding similarity, CoinGecko categories,
        or curated mapping tables.
        """
        text = f"{token_symbol} {token_name} {token_description}".lower()
        matches: list[dict] = []

        for narrative_type, keywords in NARRATIVE_KEYWORD_MAP.items():
            score = 0
            for keyword in keywords:
                if keyword.lower() in text:
                    score += 1

            if score > 0:
                # Determine strength based on keyword match count
                if score >= 4:
                    strength = NarrativeStrength.HOT.value
                elif score >= 2:
                    strength = NarrativeStrength.WARM.value
                else:
                    strength = NarrativeStrength.COLD.value

                matches.append({
                    "narrative": narrative_type.value,
                    "strength": strength,
                    "match_score": score,
                })

        return matches


# Narrative keyword map for classification
NARRATIVE_KEYWORD_MAP: dict[NarrativeType, list[str]] = {
    NarrativeType.AI: ["ai", "agent", "artificial", "intelligence", "neural", "llm", "gpt",
                        "autonomous", "machine learning", "deep learning", "chatbot"],
    NarrativeType.RWA: ["rwa", "real world", "tokenized", "treasury", "real estate",
                         "commodity", "gold", "t-bill", "private credit"],
    NarrativeType.DEPIN: ["depin", "physical", "infrastructure", "network", "node",
                           "decentralized infrastructure", "iot", "sensor", "wireless"],
    NarrativeType.GAMING: ["game", "gaming", "gamefi", "play-to-earn", "p2e", "metaverse",
                            "nft game", "esports", "mmorpg"],
    NarrativeType.PRIVACY: ["privacy", "zk", "zero knowledge", "anonymous", "private",
                             "mixer", "shielded", "confidential", "stealth"],
    NarrativeType.MEMES: ["meme", "dog", "cat", "pepe", "wojak", "chad", "based",
                           "moon", "inu", "shib", "bonk", "floki"],
    NarrativeType.PREDICTION_MARKETS: ["prediction", "polymarket", "betting", "forecast",
                                        "oracle market", "outcome", "event market"],
    NarrativeType.L1_L2: ["l1", "l2", "layer 1", "layer 2", "blockchain", "rollup",
                           "scaling", "zk rollup", "optimistic", "modular"],
}
