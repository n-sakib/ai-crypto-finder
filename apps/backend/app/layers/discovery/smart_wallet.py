"""
Smart Wallet Discovery — Tracks tokens bought by proven profitable wallets.

Source: 1.6 Smart Wallet Discovery
Update: every 15 minutes
Criteria: 3+ proven wallets buying

Issue fixed: smart wallets are a booster, not the only source.
"""

from typing import Optional

from app.layers.discovery.base import BaseDiscoverySource


class SmartWalletDiscovery(BaseDiscoverySource):
    """
    Discovers tokens by tracking purchases from proven profitable wallets.

    Wallet criteria:
    - 10+ completed trades
    - Win rate > 60%
    - Average ROI > 100%
    - Median hold time > 24h
    - Not exchange, deployer, bridge, or MEV wallet
    """

    def __init__(self):
        self._tracked_wallets: set[str] = set()
        self._wallet_stats: dict[str, dict] = {}  # wallet -> stats

    def source_name(self) -> str:
        return "Smart Wallets"

    async def discover(self) -> list[dict]:
        """
        Find tokens where 3+ proven wallets are buying.

        In production: monitor on-chain transactions from tracked wallets.
        Use Web3/RPC to watch for token purchases.
        """
        candidates: list[dict] = []

        # In production:
        # 1. Watch mempool/transactions for tracked wallet addresses
        # 2. Decode swap/buy transactions
        # 3. Group by token address
        # 4. Return tokens with 3+ unique buyers

        return self._filter_by_wallet_threshold(candidates)

    async def load_tracked_wallets(self, wallets: list[str]):
        """Load tracked wallet addresses (from DB)."""
        self._tracked_wallets = set(wallets)

    async def add_wallet(self, address: str, stats: dict):
        """Add a proven wallet to tracking."""
        self._tracked_wallets.add(address)
        self._wallet_stats[address] = stats

    def _is_proven_wallet(self, stats: dict) -> bool:
        """Check if wallet meets proven criteria."""
        return (
            stats.get("completed_trades", 0) >= 10
            and stats.get("win_rate", 0) > 0.60
            and stats.get("avg_roi", 0) > 1.0  # 100%
            and stats.get("median_hold_hours", 0) > 24
            and not stats.get("is_exchange", False)
            and not stats.get("is_deployer", False)
            and not stats.get("is_bridge", False)
            and not stats.get("is_mev", False)
        )

    def _filter_by_wallet_threshold(self, candidates: list[dict]) -> list[dict]:
        """
        Filter: 3+ proven wallets buying.
        Smart wallets are a booster, never the only source.
        """
        return [c for c in candidates if c.get("unique_buyers", 0) >= 3]
