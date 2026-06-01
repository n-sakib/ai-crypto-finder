"""
Coin Age Classification Layer — Chooses correct baseline by token age.

Layer 3: Classifies every token into an age bucket.

Buckets:
- New Launch:   0–24 hours   (baseline: 15m, 1h)
- Young Coin:   1–7 days     (baseline: 6h, 24h)
- Growing Coin: 7–30 days    (baseline: 7d)
- Mature Coin:  30+ days     (baseline: 30d, dormant: 90d)
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.models import AgeBucket


class CoinAgeClassifier:
    """
    Classifies tokens by age to select the correct comparison baseline.

    Each age bucket uses different lookback windows:
    - New tokens can't use 7d or 30d baselines
    - Mature tokens use longer baselines to detect dormant awakenings
    """

    # Age bucket definitions
    AGE_BUCKETS = {
        AgeBucket.NEW_LAUNCH: {
            "max_hours": 24,
            "baseline_windows": ["15m", "1h"],
            "description": "0–24 hours since launch",
        },
        AgeBucket.YOUNG: {
            "max_days": 7,
            "baseline_windows": ["6h", "24h"],
            "description": "1–7 days since launch",
        },
        AgeBucket.GROWING: {
            "max_days": 30,
            "baseline_windows": ["7d"],
            "description": "7–30 days since launch",
        },
        AgeBucket.MATURE: {
            "min_days": 30,
            "baseline_windows": ["30d"],
            "dormant_baseline": "90d",
            "description": "30+ days since launch",
        },
    }

    def classify(self, token: dict) -> AgeBucket:
        """
        Determine age bucket for a token.

        Args:
            token: dict with optional 'launched_at' (datetime) or 'created_at'

        Returns:
            AgeBucket for the token
        """
        launched_at = token.get("launched_at")

        if launched_at is None:
            # If no launch time known, check if we have pair creation time
            launched_at = token.get("first_seen_at") or token.get("created_at")

        if launched_at is None:
            # Unknown age — assume new launch (most conservative baseline)
            return AgeBucket.NEW_LAUNCH

        if isinstance(launched_at, str):
            launched_at = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))

        age = datetime.now(timezone.utc) - launched_at.replace(tzinfo=timezone.utc)
        hours = age.total_seconds() / 3600

        if hours <= 24:
            return AgeBucket.NEW_LAUNCH
        elif hours <= 24 * 7:  # 7 days
            return AgeBucket.YOUNG
        elif hours <= 24 * 30:  # 30 days
            return AgeBucket.GROWING
        else:
            return AgeBucket.MATURE

    def get_baseline_windows(self, bucket: AgeBucket) -> list[str]:
        """Get the appropriate baseline time windows for an age bucket."""
        info = self.AGE_BUCKETS.get(bucket, {})
        return info.get("baseline_windows", ["15m", "1h"])

    def get_dormant_baseline(self, bucket: AgeBucket) -> Optional[str]:
        """Get dormant baseline window (only for mature coins)."""
        info = self.AGE_BUCKETS.get(bucket, {})
        return info.get("dormant_baseline")

    def get_age_hours(self, launched_at: Optional[datetime]) -> Optional[float]:
        """Calculate age in hours from launch time."""
        if launched_at is None:
            return None
        if isinstance(launched_at, str):
            launched_at = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - launched_at.replace(tzinfo=timezone.utc)
        return age.total_seconds() / 3600

    def is_dormant_candidate(self, bucket: AgeBucket, current_volume: float,
                              baseline_30d: float = 0.0, baseline_90d: float = 0.0) -> bool:
        """
        Check if a mature coin qualifies as dormant awakening.
        Current volume must exceed dormant baseline by 5x.
        """
        if bucket != AgeBucket.MATURE:
            return False

        if baseline_30d > 0 and current_volume / baseline_30d >= 5.0:
            return True
        if baseline_90d > 0 and current_volume / baseline_90d >= 5.0:
            return True

        return False
