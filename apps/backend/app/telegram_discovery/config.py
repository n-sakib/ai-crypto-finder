"""
Configuration loader for Telegram discovery sources.

Reads all configuration from environment variables (via app.config.settings).
Groups are defined as a comma-separated TELEGRAM_GROUPS env var.
No YAML file required — fully dynamic.
"""

from __future__ import annotations

from typing import Optional

from app.config import settings


class TelegramSourceConfig:
    """Parsed configuration for a single Telegram source (from env vars)."""

    __slots__ = (
        "source_id", "name", "telegram_identifier",
        "source_type", "enabled",
    )

    def __init__(
        self,
        source_id: str,
        name: str = "",
        telegram_identifier: str = "",
        source_type: str = "alpha_group",
        enabled: bool = True,
    ) -> None:
        self.source_id: str = source_id
        self.name: str = name or source_id.replace("_", " ").title()
        self.telegram_identifier: str = telegram_identifier
        self.source_type: str = source_type
        self.enabled: bool = enabled


def load_telegram_sources(config_path: Optional[str] = None) -> list[TelegramSourceConfig]:
    """
    Synchronous fallback: load from TELEGRAM_GROUPS env var or YAML.
    Call load_telegram_sources_async() instead when in an async context.
    """
    # Try env var
    groups_str = settings.TELEGRAM_GROUPS.strip()
    if groups_str:
        identifiers = [g.strip() for g in groups_str.split(",") if g.strip()]
        sources = []
        seen_ids: set[str] = set()
        for ident in identifiers:
            source_id = _identifier_to_source_id(ident)
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)
            sources.append(TelegramSourceConfig(
                source_id=source_id,
                name=ident,
                telegram_identifier=ident,
                source_type=_infer_source_type(source_id),
                enabled=True,
            ))
        return sources

    try:
        return _load_from_yaml(config_path)
    except Exception:
        return []


async def load_telegram_sources_async() -> list[TelegramSourceConfig]:
    """
    Load Telegram source configurations — DB-first, env var fallback.

    Priority:
    1. Database (if sources exist — managed via API/frontend)
    2. TELEGRAM_GROUPS env var
    3. YAML config fallback
    """
    # Try DB first
    try:
        from app.core.database import async_session_factory
        from sqlalchemy import select as sa_select
        from app.telegram_discovery.models import TelegramSource as DBTelegramSource

        async with async_session_factory() as session:
            result = await session.execute(
                sa_select(DBTelegramSource).order_by(DBTelegramSource.source_type, DBTelegramSource.name)
            )
            db_sources = result.scalars().all()
            if db_sources:
                return [
                    TelegramSourceConfig(
                        source_id=s.source_id,
                        name=s.name,
                        telegram_identifier=s.telegram_identifier,
                        source_type=s.source_type.value if hasattr(s.source_type, 'value') else str(s.source_type),
                        enabled=s.enabled,
                    )
                    for s in db_sources
                ]
    except Exception:
        pass

    # Fallback to env var / YAML
    return load_telegram_sources()


def _identifier_to_source_id(identifier: str) -> str:
    """Convert a Telegram identifier to a clean source_id."""
    ident = identifier.strip().lstrip("@").lower()

    # Numeric chat IDs (private groups): -1001234567890 → chat_1001234567890
    if ident.startswith("-"):
        return "chat_" + ident.lstrip("-")

    # @username → username
    # Replace any remaining special chars with underscore
    import re
    return re.sub(r"[^a-z0-9_]", "_", ident)


def _load_from_yaml(config_path: Optional[str] = None) -> list[TelegramSourceConfig]:
    """Fallback: load from telegram_sources.yaml."""
    import os
    from pathlib import Path
    import yaml

    default_path = Path(__file__).resolve().parent.parent.parent / "telegram_sources.yaml"
    path = Path(config_path) if config_path else default_path

    if not path.exists():
        env_path = os.getenv("TELEGRAM_SOURCES_CONFIG")
        if env_path:
            path = Path(env_path)
    if not path.exists():
        return []

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    if not data or "sources" not in data:
        return []

    return [
        TelegramSourceConfig(
            source_id=s["source_id"],
            name=s.get("name", s["source_id"]),
            telegram_identifier=s.get("telegram_identifier", ""),
            source_type=s.get("source_type", "alpha_group"),
            enabled=s.get("enabled", False),
        )
        for s in data["sources"]
    ]


def _infer_source_type(source_id: str) -> str:
    """Infer source_type from the source_id naming convention."""
    sid = source_id.lower()
    if "trading" in sid:
        return "trading_group"
    if any(t in sid for t in ("meme", "memecoin", "pumpfun", "moonshot")):
        return "meme_group"
    if any(t in sid for t in ("trend", "dexscreener", "gems")):
        return "trend_group"
    if any(t in sid for t in ("solana", "base", "ethereum", "bsc", "chain")):
        return "chain_group"
    return "alpha_group"


def get_discovery_terms() -> list[str]:
    """Get discovery search terms from env var."""
    return [t.strip().lower() for t in settings.TELEGRAM_DISCOVERY_TERMS.split(",") if t.strip()]


def get_narrative_terms() -> list[str]:
    """Get narrative keywords from env var."""
    return [t.strip().lower() for t in settings.TELEGRAM_NARRATIVE_TERMS.split(",") if t.strip()]


def get_dex_domains() -> list[str]:
    """Get DEX link domains from env var."""
    return [d.strip().lower() for d in settings.TELEGRAM_DEX_DOMAINS.split(",") if d.strip()]


def get_chain_focus() -> list[str]:
    """Get chain focus list from env var."""
    return [c.strip().lower() for c in settings.TELEGRAM_CHAIN_FOCUS.split(",") if c.strip()]
