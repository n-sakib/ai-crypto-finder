"""
Centralized configuration loaded from environment variables.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────
    APP_NAME: str = "AI Crypto Finder"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # ── Database ─────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_crypto_finder"

    # ── Redis ────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Celery ───────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── External APIs ────────────────────────────────────
    DEXSCREENER_API_URL: str = "https://api.dexscreener.com"
    # Twikit (free Twitter scraping) — needs a Twitter account
    TWITTER_USERNAME: Optional[str] = None
    TWITTER_EMAIL: Optional[str] = None
    TWITTER_PASSWORD: Optional[str] = None
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_SESSION_NAME: str = "telegram_discovery"
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    COINGECKO_API_URL: str = "https://api.coingecko.com/api/v3"
    COINMARKETCAP_API_KEY: Optional[str] = None

    # ── Telegram Discovery ───────────────────────────────
    # Comma-separated list of group names to monitor
    TELEGRAM_GROUPS: str = ""
    # Comma-separated discovery keywords for extraction prioritization
    TELEGRAM_DISCOVERY_TERMS: str = "alpha,gems,lowcap,microcap,degen,moonshot,100x,1000x,calls,signals,onchain,smartmoney,whale,pumpfun,dexscreener,birdeye,gmgn,newlaunch,fairlaunch,stealthlaunch"
    # Comma-separated narrative keywords
    TELEGRAM_NARRATIVE_TERMS: str = "ai,agent,rwa,depin,gaming,privacy,prediction,memecoin,meme,l2,base,solana"
    # Comma-separated DEX link domains to detect
    TELEGRAM_DEX_DOMAINS: str = "dexscreener.com,birdeye.so,gmgn.ai,geckoterminal.com"
    # Chain focus filter
    TELEGRAM_CHAIN_FOCUS: str = "solana,base,ethereum,bsc"
    # Discovery thresholds
    MIN_MENTIONS: int = 5
    MIN_UNIQUE_USERS: int = 3
    TOP_DISCOVERY_LIMIT: int = 100
    DISCOVERY_WINDOW_MINUTES: int = 60
    # Store raw message text (off by default for privacy)
    TELEGRAM_STORE_RAW_TEXT: bool = False
    # Reddit Discovery subreddits (comma-separated)
    REDDIT_SUBREDDITS: str = "CryptoMarkets,CryptoMoonShots,SatoshiStreetBets,ethtrader,ethfinance,ethereum,EthereumClassic,solana,SolanaMemeCoins,BaseChain,base,defi,DeFiLlama,Bitcoin,BitcoinMarkets,altcoin"
    # Store raw Reddit post text
    REDDIT_STORE_RAW_TEXT: bool = False

    # ── Web3 ─────────────────────────────────────────────
    RPC_URLS: str = "ethereum:https://eth.llamarpc.com,bsc:https://bsc-dataseed.binance.org,solana:https://api.mainnet-beta.solana.com"

    # ── On-chain data ─────────────────────────────────
    # Free API key from https://gmgn.ai/ai — sol, eth, bsc, base
    GMGN_API_KEY: Optional[str] = None

    # ── Scoring Defaults ─────────────────────────────────
    MIN_LIQUIDITY_NEW: float = 25_000       # Minimum for new launches
    MIN_LIQUIDITY_GROWING: float = 100_000
    MIN_LIQUIDITY_MATURE: float = 500_000
    MIN_VOLUME_24H: float = 50_000
    MAX_TOP_HOLDER_PCT: float = 25.0
    MAX_TOP_HOLDER_CRITICAL: float = 40.0

    # ── Momentum Score Weights ───────────────────────────
    WEIGHT_MARKET_FLOW: float = 0.40
    WEIGHT_ATTENTION: float = 0.15
    WEIGHT_ADOPTION: float = 0.15
    WEIGHT_LIQUIDITY_QUALITY: float = 0.15
    WEIGHT_SMART_MONEY: float = 0.10
    WEIGHT_NARRATIVE: float = 0.10

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # Ignore extra env vars not in the model
    }


settings = Settings()
