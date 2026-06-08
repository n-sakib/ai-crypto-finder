"""
Telegram Discovery API Routes.

Endpoints:
    GET /telegram/discovery?window=1h&limit=100
    GET /telegram/discovery/{chain}/{token_address}
    GET /telegram/sources
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.telegram_discovery.aggregator import TelegramDiscoveryAggregator
from app.telegram_discovery.models import TelegramSource
from app.telegram_discovery.schemas import (
    DiscoveryRankingResponse,
    TelegramSourceResponse,
    TokenMentionDetail,
)
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram-discovery"])

# Prevent concurrent collection runs
_COLLECT_LOCK = asyncio.Lock()


# ── Discovery Rankings ─────────────────────────────────────────────────

@router.get("/discovery", response_model=DiscoveryRankingResponse)
async def get_telegram_discovery(
    window: str = Query(
        default_factory=lambda: f"{settings.DISCOVERY_WINDOW_MINUTES}m",
        description="Time window: 30m, 1h, 6h, 24h"
    ),
    limit: int = Query(
        default_factory=lambda: settings.TOP_DISCOVERY_LIMIT,
        ge=1, le=500, description="Max tokens to return"
    ),
    min_mentions: int = Query(
        default=1, ge=1, description="Minimum mention count"
    ),
    min_groups: int = Query(
        default=1, ge=1, le=100, description="Minimum distinct groups"
    ),
    min_unique_users: int = Query(
        default=1, ge=1, le=1000, description="Minimum distinct users"
    ),
    session: AsyncSession = Depends(get_session),
):
    """
    Get top discovered tokens from Telegram for a time window.

    Tokens are ranked by group_count DESC, then mention_count DESC,
    then unique_user_count DESC, then most recent mention DESC.
    """
    aggregator = TelegramDiscoveryAggregator(
        min_mention_count=min_mentions,
        min_group_count=min_groups,
        min_unique_user_count=min_unique_users,
    )
    return await aggregator.rank(session, window=window, limit=limit)


@router.get("/discovery/{chain}/{token_address}", response_model=TokenMentionDetail)
async def get_token_discovery_detail(
    chain: str,
    token_address: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Get detailed Telegram discovery data for a specific token.
    """
    aggregator = TelegramDiscoveryAggregator()
    detail = await aggregator.get_token_detail(session, chain, token_address)
    if not detail:
        raise HTTPException(status_code=404, detail="Token not found in Telegram discovery")
    return TokenMentionDetail(**detail)


# ── Sources ────────────────────────────────────────────────────────────

@router.get("/sources", response_model=list[TelegramSourceResponse])
async def get_telegram_sources(
    enabled_only: bool = Query(False, description="Only show enabled sources"),
    session: AsyncSession = Depends(get_session),
):
    """
    List configured Telegram discovery sources.
    """
    q = select(TelegramSource)
    if enabled_only:
        q = q.where(TelegramSource.enabled == True)
    q = q.order_by(TelegramSource.source_type, TelegramSource.name)

    result = await session.execute(q)
    sources = result.scalars().all()
    return [TelegramSourceResponse.model_validate(s) for s in sources]


@router.post("/sources", response_model=TelegramSourceResponse, status_code=201)
async def add_telegram_source(
    telegram_identifier: str = Query(..., description="@username or numeric chat ID"),
    name: str = Query("", description="Display name (optional, defaults to identifier)"),
    source_type: str = Query("", description="alpha_group, trend_group, meme_group, trading_group, chain_group (auto-inferred if empty)"),
    session: AsyncSession = Depends(get_session),
):
    """Add a new Telegram source."""
    from app.telegram_discovery.models import SourceType
    from app.telegram_discovery.config import _identifier_to_source_id, _infer_source_type

    source_id = _identifier_to_source_id(telegram_identifier)
    display_name = name or telegram_identifier

    # Auto-infer source type if not explicitly provided
    if not source_type:
        source_type = _infer_source_type(source_id)

    existing = (await session.execute(
        select(TelegramSource).where(TelegramSource.source_id == source_id)
    )).scalar_one_or_none()

    if existing:
        existing.enabled = True
        existing.telegram_identifier = telegram_identifier
        existing.name = display_name
        existing.source_type = SourceType(source_type)
        await session.commit()
        await session.refresh(existing)
        return TelegramSourceResponse.model_validate(existing)

    src = TelegramSource(
        source_id=source_id,
        name=display_name,
        telegram_identifier=telegram_identifier,
        source_type=SourceType(source_type),
        enabled=True,
    )
    session.add(src)
    await session.commit()
    await session.refresh(src)
    return TelegramSourceResponse.model_validate(src)


@router.delete("/sources/{source_id}")
async def remove_telegram_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove a Telegram source."""
    src = (await session.execute(
        select(TelegramSource).where(TelegramSource.source_id == source_id)
    )).scalar_one_or_none()

    if not src:
        # Try by DB id
        src = (await session.execute(
            select(TelegramSource).where(TelegramSource.id == source_id)
        )).scalar_one_or_none()

    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    await session.delete(src)
    await session.commit()
    return {"status": "deleted", "source_id": src.source_id}


@router.put("/sources/{source_id}/toggle")
async def toggle_telegram_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Toggle a Telegram source enabled/disabled."""
    src = (await session.execute(
        select(TelegramSource).where(TelegramSource.source_id == source_id)
    )).scalar_one_or_none()

    if not src:
        src = (await session.execute(
            select(TelegramSource).where(TelegramSource.id == source_id)
        )).scalar_one_or_none()

    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    src.enabled = not src.enabled
    await session.commit()
    return {"status": "ok", "source_id": src.source_id, "enabled": src.enabled}


# ── Collect ────────────────────────────────────────────────────────────

@router.post("/collect")
async def trigger_collect(
    window: str = Query("24h", description="Time window for collection: 30m, 60m, 6h, 24h"),
):
    """
    Run Telegram discovery collection as SSE stream.

    Pipeline steps:
    1. Collect messages from all enabled sources with social indicators
    2. Extract token references (CAs, Cashtags, DEX links)
    3. Store ALL messages with metadata (group, reactions, views, forwards)
    4. Per-group dedup: same coin in same group = 1 mention
    5. Enrich tokens with Dexscreener + GMGN data
    6. Remove duplicate tokens (merge cashtag→CA resolutions)
    7. DeepSeek AI evaluation: keep/discard each token
    """
    if _COLLECT_LOCK.locked():
        return {"status": "busy", "message": "Collection already in progress"}

    async def event_stream():
        import json
        import asyncio as aio
        from datetime import datetime as dt, timezone as tz, timedelta
        from app.telegram_discovery.aggregator import parse_window
        logger = logging.getLogger("telegram.collect.sse")

        window_delta = parse_window(window)
        offset_date = dt.now(tz.utc) - window_delta

        event_queue: aio.Queue = aio.Queue()

        def fmt(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

        async with _COLLECT_LOCK:
            try:
                from app.core.database import async_session_factory
                from app.telegram_discovery.client import TelegramClientService
                from app.telegram_discovery.config import load_telegram_sources_async
                from app.telegram_discovery.extractor import TokenExtractor
                from app.telegram_discovery.resolver import TokenResolver
                from app.telegram_discovery.enricher import TokenEnricher
                from app.telegram_discovery.evaluator import DeepSeekEvaluator
                from app.telegram_discovery.models import (
                    TelegramSource, TelegramMessage, TelegramTokenMention,
                    CandidateToken, TelegramDiscoveryRanking, DiscoveryMethod,
                )
                from sqlalchemy import delete, update, func, or_ as sa_or
                from sqlalchemy import select as sa_select

                configs = await load_telegram_sources_async()
                enabled = [c for c in configs if c.enabled]
                if not enabled:
                    await event_queue.put(fmt("error", {"message": "No enabled sources"}))
                    await event_queue.put(None)
                    return

                await event_queue.put(fmt("progress", {
                    "step": "reset", "status": "Clearing previous data...",
                    "progress_pct": 0,
                }))

                async def run_pipeline():
                    client_service = TelegramClientService()
                    extractor = TokenExtractor()
                    resolver = TokenResolver()
                    enricher = TokenEnricher()
                    evaluator = DeepSeekEvaluator()

                    try:
                        async with async_session_factory() as session:
                            # ── Step 0: Reset ──────────────────────────────
                            await session.execute(delete(TelegramTokenMention))
                            await session.execute(delete(TelegramDiscoveryRanking))
                            await session.execute(delete(CandidateToken))
                            await session.execute(delete(TelegramMessage))
                            await session.execute(update(TelegramSource).values(
                                last_message_id=0, last_collected_at=None
                            ))
                            await session.commit()

                            sources = await client_service.sync_sources(session, enabled)
                            if not sources:
                                await event_queue.put(fmt("error", {"message": "No sources synced"}))
                                return

                            # ── Step 1: Collect Messages ───────────────────
                            await event_queue.put(fmt("progress", {
                                "step": "collect", "status": f"Scanning {len(sources)} groups...",
                                "progress_pct": 5,
                            }))

                            total_messages = 0
                            sources_done = 0

                            async def on_progress(source, source_stats):
                                nonlocal total_messages, sources_done
                                total_messages += source_stats["processed"]
                                sources_done += 1
                                await event_queue.put(fmt("progress", {
                                    "step": "collect",
                                    "status": f"Group: {source.name} ({source_stats['processed']} msgs)",
                                    "group": source.name or source.telegram_identifier,
                                    "total_messages": total_messages,
                                    "sources_done": sources_done,
                                    "sources_total": len(sources),
                                    "progress_pct": 5 + int(20 * sources_done / len(sources)),
                                }))

                            stats, collected = await client_service.collect_messages(
                                session, sources,
                                progress_callback=on_progress,
                                offset_date=offset_date,
                            )
                            await session.commit()

                            await event_queue.put(fmt("progress", {
                                "step": "collect",
                                "status": f"Collected {total_messages} messages with social indicators",
                                "total_messages": total_messages,
                                "progress_pct": 25,
                            }))

                            # ── Step 2: Extract & Store Token Refs ─────────
                            await event_queue.put(fmt("progress", {
                                "step": "extract",
                                "status": f"Extracting tokens from {len(collected)} messages...",
                                "progress_pct": 28,
                            }))

                            total_items = len(collected)
                            for i, (db_msg, src, text) in enumerate(collected):
                                refs = extractor.extract(text)
                                if refs:
                                    fast_refs = [r for r in refs if r.discovery_method.value in ('CONTRACT_ADDRESS', 'DEX_LINK')]
                                    cashtag_refs = [r for r in refs if r.discovery_method.value == 'CASHTAG']

                                    if fast_refs:
                                        await resolver.resolve_and_store_mentions(session, src, db_msg, fast_refs)

                                    for ref in cashtag_refs:
                                        candidate = await resolver._upsert_candidate(
                                            session=session,
                                            chain=ref.chain or 'ethereum',
                                            token_address=ref.token_address or f"cashtag:{ref.symbol or 'unknown'}",
                                            symbol=ref.symbol or 'UNKNOWN',
                                            name=ref.symbol,
                                            source=src,
                                            discovery_method=ref.discovery_method,
                                            pair_address=None, dex_url=None,
                                            now=dt.now(tz.utc),
                                        )
                                        if candidate:
                                            await resolver._store_mention(
                                                session=session,
                                                candidate=candidate,
                                                source=src,
                                                message=db_msg,
                                                ref=ref,
                                            )

                                if (i + 1) % 20 == 0:
                                    await session.commit()
                                    await event_queue.put(fmt("progress", {
                                        "step": "extract",
                                        "status": f"Extracting {i + 1}/{total_items}",
                                        "progress_pct": 28 + int(12 * (i + 1) / total_items),
                                    }))

                            await session.commit()
                            token_count = (await session.execute(sa_select(func.count(CandidateToken.id)))).scalar() or 0
                            mention_count = (await session.execute(sa_select(func.count(TelegramTokenMention.id)))).scalar() or 0

                            await event_queue.put(fmt("progress", {
                                "step": "extract",
                                "status": f"Found {token_count} unique tokens, {mention_count} mentions",
                                "total_tokens": token_count,
                                "total_mentions": mention_count,
                                "progress_pct": 40,
                            }))

                            # ── Step 3: Enrich with Dexscreener + GMGN ─────
                            await event_queue.put(fmt("progress", {
                                "step": "enrich", "status": "Enriching tokens with Dexscreener + GMGN...",
                                "progress_pct": 42,
                            }))

                            tokens_to_enrich = (await session.execute(
                                sa_select(CandidateToken).where(
                                    CandidateToken.id.in_(
                                        sa_select(TelegramTokenMention.candidate_token_id)
                                        .where(TelegramTokenMention.message_timestamp >= offset_date)
                                        .distinct()
                                    )
                                )
                            )).scalars().all()

                            async def on_enrich_progress(done, total, enriched, failed):
                                token_count = (await session.execute(sa_select(func.count(CandidateToken.id)))).scalar() or 0
                                mention_count = (await session.execute(sa_select(func.count(TelegramTokenMention.id)))).scalar() or 0
                                msg_count = (await session.execute(sa_select(func.count(TelegramMessage.id)))).scalar() or 0
                                await event_queue.put(fmt("progress", {
                                    "step": "enrich",
                                    "status": f"Enriching {done}/{total} (✓{enriched} ✗{failed})",
                                    "enriched": enriched, "failed": failed,
                                    "total_tokens": token_count,
                                    "total_mentions": mention_count,
                                    "total_messages": msg_count,
                                    "progress_pct": 42 + int(18 * done / max(total, 1)),
                                }))

                            enriched_count, _ = await enricher.enrich_tokens_batch(
                                session, tokens_to_enrich,
                                progress_callback=on_enrich_progress,
                            )
                            await session.commit()

                            # Signal frontend to refetch with updated enriched data
                            token_count = (await session.execute(sa_select(func.count(CandidateToken.id)))).scalar() or 0
                            mention_count = (await session.execute(sa_select(func.count(TelegramTokenMention.id)))).scalar() or 0
                            msg_count = (await session.execute(sa_select(func.count(TelegramMessage.id)))).scalar() or 0
                            await event_queue.put(fmt("progress", {
                                "step": "enrich",
                                "status": f"Enriched {enriched_count} tokens",
                                "total_tokens": token_count,
                                "total_mentions": mention_count,
                                "total_messages": msg_count,
                                "refetch": True,
                                "progress_pct": 60,
                            }))

                            # ── Step 4: Remove Duplicates ──────────────────
                            await event_queue.put(fmt("progress", {
                                "step": "dedup", "status": "Removing duplicate tokens...",
                                "progress_pct": 62,
                            }))

                            # Merge tokens that were resolved from cashtags to real addresses
                            dup_fixed = 0
                            with session.no_autoflush:
                                all_tokens = (await session.execute(
                                    sa_select(CandidateToken).order_by(CandidateToken.token_address)
                                )).scalars().all()

                                seen: dict = {}
                                for token in all_tokens:
                                    key = f"{token.chain}:{token.token_address}"
                                    if token.token_address.startswith("cashtag:"):
                                        continue  # Keep unresolved cashtags
                                    if key in seen:
                                        # Duplicate → merge mentions to first token
                                        existing = seen[key]
                                        await session.execute(
                                            update(TelegramTokenMention)
                                            .where(TelegramTokenMention.candidate_token_id == token.id)
                                            .values(candidate_token_id=existing.id)
                                        )
                                        await session.delete(token)
                                        dup_fixed += 1
                                    else:
                                        seen[key] = token
                                await session.flush()
                            await session.commit()

                            # Clean up unresolved cashtags (no real contract address)
                            cashtag_deleted = 0
                            unresolved = (await session.execute(
                                sa_select(CandidateToken).where(
                                    CandidateToken.token_address.startswith("cashtag:")
                                )
                            )).scalars().all()
                            for ct in unresolved:
                                await session.execute(
                                    delete(TelegramTokenMention).where(
                                        TelegramTokenMention.candidate_token_id == ct.id
                                    )
                                )
                                await session.delete(ct)
                                cashtag_deleted += 1
                            if cashtag_deleted:
                                await session.commit()

                            final_token_count = (await session.execute(
                                sa_select(func.count(CandidateToken.id))
                            )).scalar() or 0

                            await event_queue.put(fmt("progress", {
                                "step": "dedup",
                                "status": f"Dedup done: merged {dup_fixed} duplicates, removed {cashtag_deleted} unresolved → {final_token_count} unique",
                                "refetch": True,
                                "total_tokens": final_token_count,
                                "progress_pct": 66,
                            }))

                            # ── Step 5: DeepSeek AI Evaluation ─────────────
                            if settings.DEEPSEEK_API_KEY:
                                await event_queue.put(fmt("progress", {
                                    "step": "ai", "status": "DeepSeek AI evaluating tokens...",
                                    "progress_pct": 68,
                                }))

                                tokens_to_eval = (await session.execute(
                                    sa_select(CandidateToken).where(
                                        CandidateToken.id.in_(
                                            sa_select(TelegramTokenMention.candidate_token_id)
                                            .where(TelegramTokenMention.message_timestamp >= offset_date)
                                            .distinct()
                                        )
                                    )
                                )).scalars().all()

                                async def on_eval_progress(done, total, kept, discarded, pending):
                                    await event_queue.put(fmt("progress", {
                                        "step": "ai",
                                        "status": f"AI: {done}/{total} (✓keep:{kept} ✗discard:{discarded} ?:{pending})",
                                        "ai_kept": kept, "ai_discarded": discarded, "ai_pending": pending,
                                        "progress_pct": 68 + int(25 * done / max(total, 1)),
                                    }))

                                kept, discarded, pending = await evaluator.evaluate_tokens_batch(
                                    session, tokens_to_eval,
                                    progress_callback=on_eval_progress,
                                )
                                await session.commit()

                                await event_queue.put(fmt("progress", {
                                    "step": "ai",
                                    "status": f"AI done: {kept} keep, {discarded} discard, {pending} pending",
                                    "ai_kept": kept, "ai_discarded": discarded, "ai_pending": pending,
                                    "progress_pct": 93,
                                }))
                            else:
                                await event_queue.put(fmt("progress", {
                                    "step": "ai",
                                    "status": "DeepSeek API key not configured — skipping AI evaluation",
                                    "progress_pct": 93,
                                }))

                            # ── Step 6: Final Stats ────────────────────────
                            final_msgs = (await session.execute(
                                sa_select(func.count(TelegramMessage.id))
                            )).scalar() or 0
                            final_tokens = (await session.execute(
                                sa_select(func.count(CandidateToken.id))
                            )).scalar() or 0
                            final_mentions = (await session.execute(
                                sa_select(func.count(TelegramTokenMention.id))
                            )).scalar() or 0
                            ai_kept = (await session.execute(
                                sa_select(func.count(CandidateToken.id)).where(
                                    CandidateToken.ai_decision == 'keep'
                                )
                            )).scalar() or 0

                            await event_queue.put(fmt("done", {
                                "step": "done",
                                "total_messages": final_msgs,
                                "total_tokens": final_tokens,
                                "total_mentions": final_mentions,
                                "ai_kept": ai_kept,
                                "sources_done": sources_done,
                                "sources_total": len(sources),
                                "progress_pct": 100,
                            }))
                            logger.info("Pipeline done: %d msgs, %d tokens, %d mentions, %d ai-kept",
                                        final_msgs, final_tokens, final_mentions, ai_kept)

                    except Exception as e:
                        logger.error("Pipeline failed: %s", e, exc_info=True)
                        await event_queue.put(fmt("error", {"message": str(e)}))
                    finally:
                        await client_service.disconnect()
                        await resolver.close()
                        await enricher.close()
                        await evaluator.close()
                        await event_queue.put(None)

                collection_task = aio.ensure_future(run_pipeline())

                while True:
                    try:
                        msg = await aio.wait_for(event_queue.get(), timeout=30.0)
                    except aio.TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    if msg is None:
                        break
                    yield msg
                await collection_task

            except Exception as e:
                logger.error("SSE event stream failed: %s", e, exc_info=True)
                yield fmt("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/reset")
async def reset_discovery():
    """
    Reset everything: stop any running collection, clear all discovery data,
    reset source checkpoints. Call this before running a fresh discovery.
    """
    if _COLLECT_LOCK.locked():
        return {"status": "busy", "message": "Collection in progress — wait for it to finish or restart the server"}

    from app.core.database import async_session_factory
    from app.telegram_discovery.models import (
        TelegramMessage, TelegramTokenMention, CandidateToken,
        TelegramDiscoveryRanking, TelegramSource,
    )
    from sqlalchemy import delete, update

    async with async_session_factory() as session:
        # Delete all discovery data
        await session.execute(delete(TelegramTokenMention))
        await session.execute(delete(TelegramDiscoveryRanking))
        await session.execute(delete(CandidateToken))
        await session.execute(delete(TelegramMessage))

        # Reset source checkpoints
        await session.execute(
            update(TelegramSource).values(last_message_id=None, last_collected_at=None)
        )

        await session.commit()

    # Get counts
    from sqlalchemy import select as sa_select, func
    async with async_session_factory() as session:
        remaining_msgs = (await session.execute(sa_select(func.count(TelegramMessage.id)))).scalar() or 0
        remaining_tokens = (await session.execute(sa_select(func.count(CandidateToken.id)))).scalar() or 0
        remaining_mentions = (await session.execute(sa_select(func.count(TelegramTokenMention.id)))).scalar() or 0
        source_count = (await session.execute(
            sa_select(func.count(TelegramSource.id)).where(TelegramSource.enabled == True)
        )).scalar() or 0

    return {
        "status": "reset",
        "message": "All discovery data cleared, source checkpoints reset",
        "remaining": {
            "messages": remaining_msgs,
            "tokens": remaining_tokens,
            "mentions": remaining_mentions,
            "enabled_sources": source_count,
        }
    }


@router.get("/collect/status")
async def get_collect_status():
    """Get current collection progress."""
    # Check if a collection lock is held (pipeline running)
    if _COLLECT_LOCK.locked():
        return {"status": "collecting", "step": "running", "group": "", "total_messages": 0,
                "total_tokens": 0, "total_mentions": 0, "sources_done": 0, "sources_total": 0}
    return {"status": "idle", "step": "idle", "group": "", "total_messages": 0,
            "total_tokens": 0, "total_mentions": 0, "sources_done": 0, "sources_total": 0}


# ── Stats ──────────────────────────────────────────────────────────────

@router.get("/discovery/stats")
async def get_telegram_stats(session: AsyncSession = Depends(get_session)):
    """
    Get statistics about Telegram discovery data.
    """
    from sqlalchemy import func
    from app.telegram_discovery.models import (
        CandidateToken, TelegramTokenMention, TelegramMessage,
    )

    candidate_count = await session.execute(
        select(func.count(CandidateToken.id)).where(CandidateToken.pair_address.isnot(None))
    )
    mention_count = await session.execute(select(func.count(TelegramTokenMention.id)))
    message_count = await session.execute(select(func.count(TelegramMessage.id)))
    source_count = await session.execute(
        select(func.count(TelegramSource.id)).where(TelegramSource.enabled == True)
    )

    latest_mention = await session.execute(
        select(TelegramTokenMention.message_timestamp)
        .order_by(desc(TelegramTokenMention.message_timestamp))
        .limit(1)
    )
    latest = latest_mention.scalar_one_or_none()

    return {
        "candidate_tokens": candidate_count.scalar() or 0,
        "total_mentions": mention_count.scalar() or 0,
        "messages_stored": message_count.scalar() or 0,
        "enabled_sources": source_count.scalar() or 0,
        "latest_mention_at": latest.isoformat() if latest else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
