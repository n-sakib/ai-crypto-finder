"""
Configuration loader for Reddit discovery sources.

Subreddits are defined as a comma-separated REDDIT_SUBREDDITS env var.
No YAML file required — fully dynamic.
"""

from __future__ import annotations

from typing import Optional

from app.config import settings


class RedditSourceConfig:
    """Parsed configuration for a single Reddit source (from env vars)."""

    __slots__ = (
        "source_id", "name", "subreddit_name",
        "source_type", "enabled",
    )

    def __init__(
        self,
        source_id: str,
        name: str = "",
        subreddit_name: str = "",
        source_type: str = "general_crypto",
        enabled: bool = True,
    ) -> None:
        self.source_id: str = source_id
        self.name: str = name or subreddit_name
        self.subreddit_name: str = subreddit_name
        self.source_type: str = source_type
        self.enabled: bool = enabled


def _infer_source_type(subreddit: str) -> str:
    """Infer subreddit type from name."""
    lower = subreddit.lower()
    if any(k in lower for k in ("meme", "moonshot", "shitcoin", "memecoin",
                                  "degencall", "gemhunter", "1000xcoin",
                                  "smallcrypto", "lowmarketcap", "cryptomars",
                                  "memeconomy", "cryptomeme", "shibarmy",
                                  "pepecryptocurrency", "dogecoin")):
        return "meme_coins"
    if any(k in lower for k in ("trading", "trader", "satoshistreetbets",
                                  "altstreetbets", "wallstreetbetscrypto",
                                  "cryptomarkets", "bitcoinmarkets")):
        return "trading"
    if any(k in lower for k in ("defi", "yield", "liquidity", "defillama")):
        return "defi"
    if any(k in lower for k in ("solana", "ethereum", "eth", "bsc", "polygon",
                                  "avalanche", "base", "arbitrum", "optimism",
                                  "nearprotocol", "injective", "cosmosnetwork",
                                  "osmosiszone", "polkadot", "cardano",
                                  "chainlink", "bittensor", "kaspa",
                                  "fantomfoundation", "rendernetwork")):
        return "chain_specific"
    if any(k in lower for k in ("bitcoin", "altcoin")):
        return "trading"
    if any(k in lower for k in ("technology", "general")):
        return "general_crypto"
    return "general_crypto"


def load_reddit_sources() -> list[RedditSourceConfig]:
    """
    Load Reddit source configurations from REDDIT_SUBREDDITS env var.

    Format: comma-separated list of subreddit names.
    Example: REDDIT_SUBREDDITS=CryptoCurrency,CryptoMoonShots,altcoin
    """
    subreddits_str = getattr(settings, "REDDIT_SUBREDDITS", "").strip()
    if not subreddits_str:
        # Default subreddits if none configured
        subreddits_str = "CryptoCurrency,CryptoMarkets,CryptoMoonShots,SatoshiStreetBets,ethtrader,ethfinance,ethereum,EthereumClassic,solana,SolanaMemeCoins,BaseChain,base,defi,DeFiLlama,Bitcoin,BitcoinMarkets,altcoin"

    names = [s.strip() for s in subreddits_str.split(",") if s.strip()]
    sources: list[RedditSourceConfig] = []
    seen_ids: set[str] = set()

    for name in names:
        source_id = f"reddit_r_{name.lower()}"
        if source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        sources.append(RedditSourceConfig(
            source_id=source_id,
            name=f"r/{name}",
            subreddit_name=name,
            source_type=_infer_source_type(name),
            enabled=True,
        ))

    return sources


async def load_reddit_sources_async() -> list[RedditSourceConfig]:
    """
    Load Reddit source configurations — DB-first, env var fallback.

    Priority:
    1. Database (if sources exist — managed via API/frontend)
    2. REDDIT_SUBREDDITS env var
    """
    # Try DB first
    try:
        from app.core.database import async_session_factory
        from sqlalchemy import select as sa_select
        from app.reddit_discovery.models import RedditSource as DBRedditSource

        async with async_session_factory() as session:
            result = await session.execute(
                sa_select(DBRedditSource).order_by(DBRedditSource.source_type, DBRedditSource.name)
            )
            db_sources = result.scalars().all()
            if db_sources:
                return [
                    RedditSourceConfig(
                        source_id=s.source_id,
                        name=s.name,
                        subreddit_name=s.subreddit_name,
                        source_type=s.source_type.value if hasattr(s.source_type, 'value') else str(s.source_type),
                        enabled=s.enabled,
                    )
                    for s in db_sources
                ]
    except Exception:
        pass

    # Fall back to env var
    return load_reddit_sources()
