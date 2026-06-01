"""
Base class and shared types for discovery sources.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CandidateToken:
    """Raw candidate token from any discovery source."""
    chain: str
    contract_address: str
    pair_address: str
    symbol: str
    name: Optional[str] = None
    dex_id: Optional[str] = None
    liquidity_usd: float = 0.0
    volume_24h: float = 0.0
    volume_1h: float = 0.0
    price_usd: float = 0.0
    price_change_24h: float = 0.0
    holder_count: int = 0
    launched_at: Optional[datetime] = None
    extra: dict = field(default_factory=dict)


class BaseDiscoverySource(ABC):
    """Abstract base for all discovery sources."""

    @abstractmethod
    async def discover(self) -> list[dict]:
        """Run discovery and return list of candidate dicts."""
        ...

    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source name."""
        ...
