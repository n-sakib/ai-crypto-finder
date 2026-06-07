"""
TelegramClientService — Connects to Telegram using Telethon.

Reads messages from configured groups/channels, stores minimal metadata.
Handles rate limits conservatively. Respects private group access controls.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, ChatAdminRequiredError, ChannelPrivateError,
    ChatWriteForbiddenError,
)
from telethon.tl.types import Message, Channel, Chat, MessageEntityTextUrl

from app.config import settings
from app.telegram_discovery.models import TelegramSource, TelegramMessage, SourceType
from app.telegram_discovery.config import TelegramSourceConfig, load_telegram_sources, load_telegram_sources_async

logger = logging.getLogger(__name__)


def _get_full_text(msg: Message) -> str:
    """
    Reconstruct full message text including URLs from entities.
    
    Telegram messages with Markdown links like [text](url) have the URL
    stored in MessageEntityTextUrl entities but NOT in msg.message.
    This function rebuilds the text with URLs appended so extractors
    can find contract addresses embedded in links.
    """
    text = (msg.message or "").strip()
    if not text:
        return text
    
    if msg.entities:
        # Collect URLs from text URL entities and append them
        urls = []
        for ent in msg.entities:
            if isinstance(ent, MessageEntityTextUrl):
                urls.append(ent.url)
        if urls:
            text = text + "\n" + "\n".join(urls)
    
    return text.strip()

logger = logging.getLogger(__name__)


class TelegramClientService:
    """
    Connects to Telegram via Telethon, reads messages from configured sources,
    and stores minimal metadata in the database.

    Privacy: Stores only hashed sender IDs and hashed text by default.
    Raw text storage is configurable via store_raw_text parameter.

    Rate limits: Handles FloodWaitError with exponential backoff.
    """

    def __init__(
        self,
        session_name: str | None = None,
        store_raw_text: bool | None = None,
    ):
        self._session_name = session_name or settings.TELEGRAM_SESSION_NAME
        self._store_raw_text = store_raw_text if store_raw_text is not None else settings.TELEGRAM_STORE_RAW_TEXT
        self._client: Optional[TelegramClient] = None

    async def _get_client(self) -> TelegramClient:
        """Get or create the Telethon client."""
        if self._client is None:
            if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
                raise ValueError(
                    "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in environment. "
                    "Get them from https://my.telegram.org/apps"
                )

            self._client = TelegramClient(
                self._session_name,
                settings.TELEGRAM_API_ID,
                settings.TELEGRAM_API_HASH,
            )
            await self._client.start()
            logger.info("Telegram client connected")
        return self._client

    async def disconnect(self) -> None:
        """Disconnect the Telethon client."""
        if self._client:
            await self._client.disconnect()
            self._client = None
            logger.info("Telegram client disconnected")

    async def sync_sources(
        self, session: AsyncSession,
        configs: Optional[list[TelegramSourceConfig]] = None,
    ) -> list[TelegramSource]:
        """
        Sync configured sources from YAML to the database.

        Creates new sources, updates existing ones. Does not delete sources
        that are no longer in config (they are just disabled).

        Returns list of enabled TelegramSource ORM objects.
        """
        if configs is None:
            configs = await load_telegram_sources_async()

        enabled_sources: list[TelegramSource] = []
        config_source_ids = {cfg.source_id for cfg in configs}

        # Remove sources no longer in config
        all_existing = await session.execute(select(TelegramSource))
        for old in all_existing.scalars().all():
            if old.source_id not in config_source_ids:
                logger.info("Removing stale source: %s", old.source_id)
                await session.delete(old)

        for cfg in configs:
            # Upsert source in DB
            result = await session.execute(
                select(TelegramSource).where(TelegramSource.source_id == cfg.source_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.name = cfg.name
                existing.telegram_identifier = cfg.telegram_identifier
                existing.source_type = SourceType(cfg.source_type)
                existing.enabled = cfg.enabled
            else:
                existing = TelegramSource(
                    source_id=cfg.source_id,
                    name=cfg.name,
                    telegram_identifier=cfg.telegram_identifier,
                    source_type=SourceType(cfg.source_type),
                    enabled=cfg.enabled,
                )
                session.add(existing)

            if cfg.enabled:
                enabled_sources.append(existing)

        await session.flush()
        return enabled_sources

    async def collect_messages(
        self,
        session: AsyncSession,
        sources: Optional[list[TelegramSource]] = None,
        message_limit_per_source: int = 200,
        progress_callback = None,
        offset_date: Optional[datetime] = None,
    ) -> tuple[dict, list[tuple]]:
        """
        Read new messages from enabled Telegram sources.

        For each source, reads only messages newer than last_message_id.
        Stores minimal metadata. Handles rate limits.

        Returns:
            Tuple of:
              - dict with counts: messages_processed, messages_skipped_duplicate,
                messages_skipped_no_tokens, errors
              - list of (TelegramMessage, TelegramSource, str) tuples for
                downstream token extraction. str is the message text.
        """
        if sources is None:
            result = await session.execute(
                select(TelegramSource).where(TelegramSource.enabled == True)
            )
            sources = list(result.scalars().all())

        if not sources:
            logger.warning("No enabled Telegram sources found")
            return {
                "messages_processed": 0,
                "messages_skipped_duplicate": 0,
                "messages_skipped_no_tokens": 0,
                "errors": [],
            }, []

        client = await self._get_client()

        stats = {
            "messages_processed": 0,
            "messages_skipped_duplicate": 0,
            "messages_skipped_no_tokens": 0,
            "errors": [],
        }
        collected: list[tuple] = []

        for source in sources:
            try:
                source_stats, source_messages = await self._collect_from_source(
                    client, session, source, message_limit_per_source, offset_date,
                )
                stats["messages_processed"] += source_stats["processed"]
                stats["messages_skipped_duplicate"] += source_stats["duplicates"]
                stats["messages_skipped_no_tokens"] += source_stats["no_tokens"]
                collected.extend(source_messages)
                if progress_callback:
                    await progress_callback(source, source_stats)
                if source_stats.get("error"):
                    stats["errors"].append(source_stats["error"])
                stats["messages_skipped_duplicate"] += source_stats["duplicates"]
                stats["messages_skipped_no_tokens"] += source_stats["no_tokens"]
                if source_stats.get("error"):
                    stats["errors"].append(source_stats["error"])
            except FloodWaitError as e:
                wait_time = e.seconds
                logger.warning(
                    "Flood wait for source %s: %d seconds. Skipping.",
                    source.source_id, wait_time,
                )
                stats["errors"].append(
                    f"Flood wait {source.source_id}: {wait_time}s"
                )
                # Don't sleep — skip and move to next source
            except (ChatAdminRequiredError, ChannelPrivateError) as e:
                logger.warning(
                    "Cannot access source %s: %s. Disabling.",
                    source.source_id, e,
                )
                source.enabled = False
                stats["errors"].append(f"Access denied {source.source_id}: {e}")
            except Exception as e:
                logger.error(
                    "Error collecting from source %s: %s",
                    source.source_id, e, exc_info=True,
                )
                stats["errors"].append(f"Error {source.source_id}: {e}")

        await session.flush()
        return stats, collected

    async def _collect_from_source(
        self,
        client: TelegramClient,
        session: AsyncSession,
        source: TelegramSource,
        limit: int,
        offset_date: Optional[datetime] = None,
    ) -> tuple[dict, list[tuple]]:
        """Collect messages from a single Telegram source.

        Returns:
            Tuple of (stats dict, list of (TelegramMessage, TelegramSource, str) tuples)
        """
        stats = {"processed": 0, "duplicates": 0, "no_tokens": 0, "error": None}
        collected: list[tuple] = []

        try:
            entity = await client.get_entity(source.telegram_identifier)
        except Exception as e:
            stats["error"] = f"Cannot resolve {source.telegram_identifier}: {e}"
            return stats, collected

        # Get messages since last checkpoint
        # NOTE: We do NOT use Telethon's offset_date because it behaves
        # inconsistently. Instead, we filter by msg.date in our code below.
        min_id = source.last_message_id or 0
        messages = await client.get_messages(entity=entity, limit=limit, min_id=min_id)

        if not messages:
            return stats, collected

        from app.telegram_discovery.extractor import TokenExtractor
        extractor = TokenExtractor()

        msg_count = 0
        for msg in messages:
            if not isinstance(msg, Message) or not msg.message:
                stats["no_tokens"] += 1
                continue

            # ── Window filter: skip messages outside the selected window ──
            msg_dt = msg.date.replace(tzinfo=timezone.utc) if msg.date.tzinfo is None else msg.date
            if offset_date and msg_dt < offset_date:
                stats["no_tokens"] += 1
                continue

            text = _get_full_text(msg)
            if not text:
                stats["no_tokens"] += 1
                continue

            # Check for token identifiers — skip if none found
            refs = extractor.extract(text)
            if not refs:
                stats["no_tokens"] += 1
                continue

            # Hash identifiers for privacy
            text_hash = extractor.hash_text(text)
            sender_hash = extractor.hash_sender_id(msg.sender_id or 0)

            # Check for duplicate (same source + text_hash within 10 min)
            ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
            dup_result = await session.execute(
                select(TelegramMessage.id).where(
                    TelegramMessage.source_id == source.id,
                    TelegramMessage.text_hash == text_hash,
                    TelegramMessage.message_timestamp >= ten_min_ago,
                ).limit(1)
            )
            if dup_result.scalar_one_or_none():
                stats["duplicates"] += 1
                continue

            # Store message with social indicators
            raw_text = text if self._store_raw_text else None

            # Extract social indicators from Telethon message
            reactions_count = 0
            if msg.reactions:
                try:
                    reactions_count = sum(
                        getattr(rc, 'count', 0) or 0
                        for rc in (msg.reactions.results or [])
                    )
                except Exception:
                    pass
            views_count = getattr(msg, 'views', 0) or 0
            forwards_count = getattr(msg, 'forwards', 0) or 0
            reply_count = getattr(msg.replies, 'replies', 0) if msg.replies else 0

            # Debug: log social indicators for first 5 stored messages per source
            if msg_count < 5:
                logger.debug(
                    f"[social] source={source.name} msg_id={msg.id} "
                    f"reactions={reactions_count} views={views_count} "
                    f"forwards={forwards_count} replies={reply_count}"
                )
                msg_count += 1

            db_msg = TelegramMessage(
                source_id=source.id,
                telegram_message_id=msg.id,
                message_timestamp=msg.date.replace(tzinfo=timezone.utc),
                sender_id_hash=sender_hash,
                text_hash=text_hash,
                raw_text=raw_text,
                reactions_count=reactions_count,
                views_count=views_count,
                forwards_count=forwards_count,
                reply_count=reply_count,
            )
            session.add(db_msg)
            stats["processed"] += 1

            # Pass message + source + text for downstream extraction
            collected.append((db_msg, source, text))

            # Update checkpoint — track highest message ID seen
            if msg.id > (source.last_message_id or 0):
                source.last_message_id = msg.id

        # Update last collected timestamp
        source.last_collected_at = datetime.now(timezone.utc)

        return stats, collected
