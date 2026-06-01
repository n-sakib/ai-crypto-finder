"""
Narrative Discovery — Finds tokens inside hot sectors.

Source: 1.8 Narrative Discovery
Update: daily
Narratives: AI, RWA, DePIN, Gaming, Privacy, Memes, Prediction Markets, L1/L2

Issue fixed: narrative only adds context, not automatic conviction.
"""

import asyncio
from typing import Optional

from app.core.models import NarrativeType
from app.layers.discovery.base import BaseDiscoverySource


class NarrativeDiscovery(BaseDiscoverySource):
    """
    Discovers tokens belonging to currently hot narratives.

    Each narrative is mapped to keywords and known tokens.
    Daily scan checks if narrative is active and finds related tokens.
    """

    # Narrative keyword mappings for discovery
    NARRATIVE_KEYWORDS: dict[NarrativeType, list[str]] = {
        NarrativeType.AI: ["AI", "artificial intelligence", "agent", "autonomous", "neural", "LLM", "GPT"],
        NarrativeType.RWA: ["RWA", "real world asset", "tokenized", "treasury", "real estate token"],
        NarrativeType.DEPIN: ["DePIN", "physical infrastructure", "network", "node", "decentralized infrastructure"],
        NarrativeType.GAMING: ["gaming", "gamefi", "play-to-earn", "P2E", "metaverse", "NFT game"],
        NarrativeType.PRIVACY: ["privacy", "zk", "zero knowledge", "anonymous", "private", "mixer"],
        NarrativeType.MEMES: ["meme", "dog", "cat", "pepe", "wojak", "chad", "based"],
        NarrativeType.PREDICTION_MARKETS: ["prediction market", "polymarket", "betting", "forecast", "oracle"],
        NarrativeType.L1_L2: ["L1", "L2", "layer 1", "layer 2", "blockchain", "rollup", "scaling"],
    }

    # Known tokens per narrative (production: load from DB/CoinGecko categories)
    NARRATIVE_TOKENS: dict[NarrativeType, list[dict]] = {
        NarrativeType.AI: [],
        NarrativeType.RWA: [],
        NarrativeType.DEPIN: [],
        NarrativeType.GAMING: [],
        NarrativeType.PRIVACY: [],
        NarrativeType.MEMES: [],
        NarrativeType.PREDICTION_MARKETS: [],
        NarrativeType.L1_L2: [],
    }

    def __init__(self):
        self._narrative_activity: dict[NarrativeType, float] = {}  # narrative -> activity score

    def source_name(self) -> str:
        return "Narrative"

    async def discover(self) -> list[dict]:
        """
        Find tokens in currently active narratives.

        In production:
        1. Check CoinGecko categories / sector performance
        2. Identify which narratives are "hot" based on sector-wide volume/price
        3. Return tokens tagged with those narratives
        """
        candidates: list[dict] = []

        # Score each narrative's current activity
        active_narratives = await self._score_narrative_activity()

        # Only return tokens from warm+ narratives
        for narrative, strength in active_narratives.items():
            if strength <= 0:  # cold narratives get 0% boost, skip discovery
                continue

            tokens = self.NARRATIVE_TOKENS.get(narrative, [])
            for token in tokens:
                token["narrative"] = narrative.value
                token["narrative_strength"] = strength
                candidates.append(token)

        return candidates

    async def _score_narrative_activity(self) -> dict[NarrativeType, float]:
        """
        Score how active each narrative is based on sector-wide data.

        Returns dict of narrative -> activity score (0-1).

        In production: use CoinGecko categories API, sector volume/price changes,
        social discussion volume per narrative.
        """
        scores: dict[NarrativeType, float] = {}

        for narrative in NarrativeType:
            # In production: check sector performance, social volume, etc.
            scores[narrative] = 0.0  # Default: cold

        return scores

    async def update_narrative_tokens(self, narrative: NarrativeType, tokens: list[dict]):
        """Update the token list for a narrative (from external sources)."""
        self.NARRATIVE_TOKENS[narrative] = tokens
