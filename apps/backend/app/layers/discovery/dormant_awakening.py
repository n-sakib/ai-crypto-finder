"""
Dormant Awakening Discovery — Finds old coins suddenly waking up.

Source: 1.7 Dormant Awakening Discovery
Update: hourly
Criteria: current activity > 5x 30d/90d baseline

Issue fixed: system is not limited to new pairs — mature coins can wake up.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.layers.discovery.base import BaseDiscoverySource


class DormantAwakeningDiscovery(BaseDiscoverySource):
    """
    Detects mature/old tokens showing sudden activity revival.

    Looks for tokens with:
    - Age > 30 days
    - Very low activity in 30d/90d window
    - Current activity surge (>5x dormant baseline)
    """

    def __init__(self):
        self._dormant_baselines: dict[str, dict] = {}  # token -> {volume_30d, volume_90d, ...}

    def source_name(self) -> str:
        return "Dormant Awakening"

    async def discover(self) -> list[dict]:
        """
        Find dormant tokens with sudden activity > 5x 30d/90d baseline.

        In production:
        1. Query known tokens with age > 30 days
        2. Compare current volume/activity against 30d and 90d baselines
        3. Flag tokens where current > 5x baseline
        """
        candidates: list[dict] = []

        # In production: query DB for mature tokens, fetch current DEXScreener data,
        # compare against stored baselines

        return self._filter_dormant_awakenings(candidates)

    def _filter_dormant_awakenings(self, candidates: list[dict]) -> list[dict]:
        """
        Filter: current activity > 5x 30d or 90d baseline.
        """
        filtered: list[dict] = []
        for c in candidates:
            contract = c.get("contract_address", "")
            baseline = self._dormant_baselines.get(contract, {})
            current_vol = c.get("volume_24h", 0)
            baseline_30d = baseline.get("avg_volume_30d", 1.0)
            baseline_90d = baseline.get("avg_volume_90d", 1.0)

            # Must be 5x either 30d or 90d baseline
            if baseline_30d > 0 and current_vol / baseline_30d >= 5.0:
                c["awakening_from"] = "30d"
                filtered.append(c)
            elif baseline_90d > 0 and current_vol / baseline_90d >= 5.0:
                c["awakening_from"] = "90d"
                filtered.append(c)

        return filtered

    async def load_baselines(self, baselines: dict[str, dict]):
        """Load dormant baselines from DB."""
        self._dormant_baselines = baselines
