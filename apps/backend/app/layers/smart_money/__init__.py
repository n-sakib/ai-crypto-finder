"""
Smart Money Layer — Adds conviction from proven wallets.

Layer 10: Tracks purchases by wallets with proven track records.

Metrics:
- 10.1 Wallet Participation: 3+ interesting, 10+ strong
- 10.2 Buy Size: normalized by wallet's historical average
- 10.3 Wallet Quality: proven criteria (10+ trades, >60% WR, >100% ROI, >24h hold)
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SmartMoneyScore:
    """Smart money scoring result."""
    total_score: float = 0.0  # 0-100

    # Component scores
    participation_score: float = 0.0
    buy_size_score: float = 0.0
    wallet_quality_score: float = 0.0

    # Raw metrics
    total_wallets_buying: int = 0
    proven_wallets_buying: int = 0
    total_buy_volume_usd: float = 0.0
    avg_normalized_buy_size: float = 0.0
    avg_wallet_win_rate: float = 0.0
    avg_wallet_roi: float = 0.0
    avg_wallet_trades: int = 0

    # Per-wallet details
    wallet_trades: list[dict] = field(default_factory=list)

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


class SmartMoneyLayer:
    """
    Tracks and scores smart money participation.

    Smart wallets are a booster, never the only source of conviction.
    """

    # Participation thresholds
    INTERESTING_WALLETS = 3
    STRONG_WALLETS = 10

    # Proven wallet criteria
    MIN_COMPLETED_TRADES = 10
    MIN_WIN_RATE = 0.60
    MIN_AVG_ROI = 1.0  # 100%
    MIN_MEDIAN_HOLD_HOURS = 24

    # Component weights
    WEIGHT_PARTICIPATION = 0.35
    WEIGHT_BUY_SIZE = 0.25
    WEIGHT_WALLET_QUALITY = 0.40

    async def score(self, wallet_trades: list[dict]) -> SmartMoneyScore:
        """
        Calculate smart money score.

        Args:
            wallet_trades: List of trades from tracked wallets for this token
        """
        result = SmartMoneyScore()
        result.wallet_trades = wallet_trades

        if not wallet_trades:
            return result

        # Separate proven vs non-proven wallets
        proven_trades = [t for t in wallet_trades if self._is_proven_wallet(t)]
        result.proven_wallets_buying = len(set(t.get("wallet_address", "") for t in proven_trades))
        result.total_wallets_buying = len(set(t.get("wallet_address", "") for t in wallet_trades))

        # Aggregate metrics
        if proven_trades:
            result.total_buy_volume_usd = sum(float(t.get("buy_amount_usd", 0)) for t in proven_trades)
            result.avg_normalized_buy_size = sum(
                float(t.get("normalized_buy_size", 0)) for t in proven_trades
            ) / len(proven_trades)
            result.avg_wallet_win_rate = sum(
                float(t.get("wallet_win_rate", 0)) for t in proven_trades
            ) / len(proven_trades)
            result.avg_wallet_roi = sum(
                float(t.get("wallet_avg_roi", 0)) for t in proven_trades
            ) / len(proven_trades)
            result.avg_wallet_trades = int(sum(
                int(t.get("wallet_completed_trades", 0)) for t in proven_trades
            ) / len(proven_trades))

        # 10.1 Wallet Participation
        self._score_participation(result)

        # 10.2 Buy Size
        self._score_buy_size(result)

        # 10.3 Wallet Quality
        self._score_wallet_quality(result)

        # Total score
        result.total_score = (
            result.participation_score * self.WEIGHT_PARTICIPATION +
            result.buy_size_score * self.WEIGHT_BUY_SIZE +
            result.wallet_quality_score * self.WEIGHT_WALLET_QUALITY
        )

        # Determine level
        if result.total_score >= 70:
            result.is_strong = True
            result.is_interesting = True
        elif result.total_score >= 40:
            result.is_interesting = True

        return result

    def _score_participation(self, result: SmartMoneyScore):
        """
        10.1 Wallet Participation.

        Interesting: 3+ proven wallets buying.
        Strong: 10+ proven wallets buying.
        """
        count = result.proven_wallets_buying

        if count >= self.STRONG_WALLETS:
            result.participation_score = 100.0
        elif count >= self.INTERESTING_WALLETS:
            # 3-10: score 40-100
            result.participation_score = 40.0 + (count - 3) / (10 - 3) * 60
        elif count > 0:
            result.participation_score = count / 3 * 40
        else:
            result.participation_score = 0.0

    def _score_buy_size(self, result: SmartMoneyScore):
        """
        10.2 Buy Size.

        Normalize by wallet's historical average buy size.
        >1.0 means buying larger than usual = higher conviction.
        """
        avg_size = result.avg_normalized_buy_size

        if avg_size >= 3.0:
            result.buy_size_score = 100.0  # 3x normal size = very high conviction
        elif avg_size >= 2.0:
            result.buy_size_score = 70.0 + (avg_size - 2.0) * 30
        elif avg_size >= 1.0:
            result.buy_size_score = 40.0 + (avg_size - 1.0) * 30
        elif avg_size >= 0.5:
            result.buy_size_score = 20.0 + (avg_size - 0.5) * 40
        else:
            result.buy_size_score = avg_size * 40  # Below average size

        result.buy_size_score = min(result.buy_size_score, 100.0)

    def _score_wallet_quality(self, result: SmartMoneyScore):
        """
        10.3 Wallet Quality.

        Aggregate quality of participating proven wallets.
        Based on: completed trades, win rate, ROI, hold time.
        """
        if result.proven_wallets_buying == 0:
            result.wallet_quality_score = 0.0
            return

        # Score each wallet quality dimension
        trades_score = min(result.avg_wallet_trades / 50 * 100, 100.0)  # 50 trades = max
        win_rate_score = min(result.avg_wallet_win_rate * 100, 100.0)    # 100% = max
        roi_score = min(result.avg_wallet_roi / 5 * 100, 100.0)         # 500% ROI = max

        result.wallet_quality_score = (
            trades_score * 0.25 +
            win_rate_score * 0.40 +
            roi_score * 0.35
        )

    def _is_proven_wallet(self, trade: dict) -> bool:
        """
        Check if a wallet meets proven criteria:

        - 10+ completed trades
        - Win rate > 60%
        - Average ROI > 100%
        - Median hold time > 24h
        - Not exchange, deployer, bridge, or MEV wallet
        """
        trades = int(trade.get("wallet_completed_trades", 0))
        win_rate = float(trade.get("wallet_win_rate", 0))
        avg_roi = float(trade.get("wallet_avg_roi", 0))

        # Exclude known non-trading wallets
        excluded_types = {"exchange", "deployer", "bridge", "mev", "contract"}
        wallet_type = trade.get("wallet_type", "")

        if wallet_type.lower() in excluded_types:
            return False

        return (
            trades >= self.MIN_COMPLETED_TRADES
            and win_rate > self.MIN_WIN_RATE
            and avg_roi > self.MIN_AVG_ROI
        )
