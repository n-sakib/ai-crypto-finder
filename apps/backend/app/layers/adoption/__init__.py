"""
Adoption Layer — Confirms real user growth.

Layer 8: Tracks holder and wallet growth.

Metrics:
- 8.1 Holder Velocity: new meaningful holders vs baseline
- 8.2 Active Wallet Velocity: active wallets and transfers vs baseline
- 8.3 Meaningful Holder Growth: exclude dust, bots, near-zero balances
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AdoptionScore:
    """Adoption scoring result."""
    total_score: float = 0.0  # 0-100

    # Component scores
    holder_velocity_score: float = 0.0
    active_wallet_score: float = 0.0
    meaningful_growth_score: float = 0.0

    # Raw metrics
    total_holders: int = 0
    meaningful_holders: int = 0
    new_holders_6h: int = 0
    new_holders_24h: int = 0
    active_wallets: int = 0
    transfers_24h: int = 0
    dust_holders: int = 0
    suspected_bot_holders: int = 0

    # Velocity ratios
    holder_velocity: float = 0.0
    active_wallet_velocity: float = 0.0

    # Flags
    is_interesting: bool = False
    is_strong: bool = False

    @property
    def level(self) -> str:
        if self.is_strong:
            return "strong"
        if self.is_interesting:
            return "interesting"
        return "low"


class AdoptionLayer:
    """
    Measures real user adoption by tracking holder and wallet growth.

    Filters out dust wallets, suspected bots, and near-zero balances
    to focus on meaningful adoption.
    """

    # Velocity thresholds
    INTERESTING_HOLDERS = 2.0
    STRONG_HOLDERS = 4.0
    INTERESTING_WALLETS = 2.0
    STRONG_WALLETS = 4.0

    # Minimum balance for "meaningful" holder (USD)
    MIN_MEANINGFUL_BALANCE_USD = 10.0

    # Dust threshold (holders with less than this = dust)
    DUST_THRESHOLD_USD = 1.0

    # Component weights
    WEIGHT_HOLDERS = 0.40
    WEIGHT_WALLETS = 0.35
    WEIGHT_MEANINGFUL = 0.25

    async def score(
        self,
        token_data: dict,
        holder_snapshots: Optional[list[dict]] = None,
        baselines: Optional[dict] = None,
    ) -> AdoptionScore:
        """
        Calculate adoption score.

        Args:
            token_data: Current token metrics
            holder_snapshots: Recent holder snapshots for trend analysis
            baselines: Age-adjusted baselines
        """
        result = AdoptionScore()
        baselines = baselines or {}

        # Extract current data
        result.total_holders = int(token_data.get("holder_count", 0))
        result.meaningful_holders = int(token_data.get("meaningful_holders", 0))
        result.active_wallets = int(token_data.get("active_wallets_24h", 0))
        result.transfers_24h = int(token_data.get("transfers_24h", 0))

        # Calculate new holders from snapshots
        if holder_snapshots:
            result.new_holders_6h = self._calc_new_holders(holder_snapshots, hours=6)
            result.new_holders_24h = self._calc_new_holders(holder_snapshots, hours=24)

        # 8.1 Holder Velocity
        self._score_holder_velocity(result, baselines)

        # 8.2 Active Wallet Velocity
        self._score_active_wallet_velocity(result, baselines)

        # 8.3 Meaningful Holder Growth
        self._score_meaningful_growth(result, token_data)

        # Total score
        result.total_score = (
            result.holder_velocity_score * self.WEIGHT_HOLDERS +
            result.active_wallet_score * self.WEIGHT_WALLETS +
            result.meaningful_growth_score * self.WEIGHT_MEANINGFUL
        )

        # Determine level
        if result.total_score >= 70:
            result.is_strong = True
            result.is_interesting = True
        elif result.total_score >= 40:
            result.is_interesting = True

        return result

    def _score_holder_velocity(self, result: AdoptionScore, baselines: dict):
        """
        8.1 Holder Velocity.

        New meaningful holders vs baseline.
        Interesting: > 2x. Strong: > 4x.
        """
        baseline_new_holders = max(baselines.get("avg_new_holders_6h", 1.0), 1.0)
        new_holders = max(result.new_holders_6h, result.new_holders_24h / 4)  # Normalize to 6h

        if baseline_new_holders > 0:
            result.holder_velocity = new_holders / baseline_new_holders
        else:
            result.holder_velocity = float(new_holders) if new_holders > 0 else 0.0

        hv = result.holder_velocity

        if hv >= 8:
            result.holder_velocity_score = 100.0
        elif hv >= self.STRONG_HOLDERS:
            result.holder_velocity_score = 70.0 + (hv - 4) * 7.5
        elif hv >= self.INTERESTING_HOLDERS:
            result.holder_velocity_score = 40.0 + (hv - 2) * 15
        elif hv >= 1.2:
            result.holder_velocity_score = 20.0 + (hv - 1.2) * 25
        else:
            result.holder_velocity_score = hv * 16

        result.holder_velocity_score = min(result.holder_velocity_score, 100.0)

    def _score_active_wallet_velocity(self, result: AdoptionScore, baselines: dict):
        """
        8.2 Active Wallet Velocity.

        Active wallets and transfers vs baseline.
        Interesting: > 2x. Strong: > 4x.
        """
        baseline_active = max(baselines.get("avg_active_wallets", 1.0), 1.0)

        if baseline_active > 0:
            result.active_wallet_velocity = result.active_wallets / baseline_active
        else:
            result.active_wallet_velocity = float(result.active_wallets)

        wv = result.active_wallet_velocity

        if wv >= 8:
            result.active_wallet_score = 100.0
        elif wv >= self.STRONG_WALLETS:
            result.active_wallet_score = 70.0 + (wv - 4) * 7.5
        elif wv >= self.INTERESTING_WALLETS:
            result.active_wallet_score = 40.0 + (wv - 2) * 15
        elif wv >= 1.2:
            result.active_wallet_score = 20.0 + (wv - 1.2) * 25
        else:
            result.active_wallet_score = wv * 16

        result.active_wallet_score = min(result.active_wallet_score, 100.0)

    def _score_meaningful_growth(self, result: AdoptionScore, token_data: dict):
        """
        8.3 Meaningful Holder Growth.

        Excludes:
        - Dust wallets (balance < $1)
        - Suspected bot wallets
        - Wallets with near-zero balances
        """
        total = result.total_holders
        meaningful = result.meaningful_holders
        dust = int(token_data.get("dust_holders", 0))
        bots = int(token_data.get("suspected_bot_holders", 0))

        result.dust_holders = dust
        result.suspected_bot_holders = bots

        if total == 0:
            result.meaningful_growth_score = 0.0
            return

        # Meaningful ratio: what % of holders are meaningful
        meaningful_ratio = meaningful / total if total > 0 else 0.0

        # Penalty for dust/bot holders
        dust_bot_ratio = (dust + bots) / total if total > 0 else 0.0

        # Base score from meaningful ratio
        if meaningful_ratio > 0.8:
            base = 100.0
        elif meaningful_ratio > 0.5:
            base = 60.0 + (meaningful_ratio - 0.5) * 133
        elif meaningful_ratio > 0.3:
            base = 30.0 + (meaningful_ratio - 0.3) * 150
        elif meaningful_ratio > 0.1:
            base = 10.0 + (meaningful_ratio - 0.1) * 100
        else:
            base = meaningful_ratio * 100

        # Penalty for dust/bot concentration
        if dust_bot_ratio > 0.5:
            penalty = 0.5  # 50% reduction
        elif dust_bot_ratio > 0.3:
            penalty = 0.3
        elif dust_bot_ratio > 0.1:
            penalty = 0.1
        else:
            penalty = 0.0

        result.meaningful_growth_score = max(base * (1 - penalty), 0.0)

        # Bonus: meaningful holders growing while total also growing
        if meaningful > 100 and meaningful_ratio > 0.7:
            result.meaningful_growth_score = min(result.meaningful_growth_score * 1.15, 100.0)

    def _calc_new_holders(self, snapshots: list[dict], hours: int = 6) -> int:
        """
        Calculate new holders over a period from snapshots.
        """
        from datetime import datetime, timedelta, timezone

        if not snapshots:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Find closest snapshot to cutoff
        snapshots_sorted = sorted(snapshots, key=lambda s: s.get("snapshot_at", datetime.min))
        earlier = None
        latest = snapshots_sorted[-1] if snapshots_sorted else None

        for s in snapshots_sorted:
            if s.get("snapshot_at", datetime.min) < cutoff:
                earlier = s
            else:
                break

        if earlier and latest:
            return int(latest.get("total_holders", 0)) - int(earlier.get("total_holders", 0))

        return 0
