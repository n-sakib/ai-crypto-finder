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
        default_factory=lambda: settings.MIN_MENTIONS,
        ge=1, description="Minimum mention count"
    ),
    min_users: int = Query(
        default_factory=lambda: settings.MIN_UNIQUE_USERS,
        ge=1, description="Minimum unique users"
    ),
    session: AsyncSession = Depends(get_session),
):
    """
    Get top discovered tokens from Telegram for a time window.

    Tokens are ranked by mention_count DESC, then unique_user_count DESC,
    then group_count DESC, then most recent mention DESC.
    """
    aggregator = TelegramDiscoveryAggregator(
        min_mention_count=min_mentions,
        min_unique_users=min_users,
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
    Run Telegram discovery collection as a foreground SSE stream.
    Sends real-time progress events: group, messages, tokens, mentions.
    Only one collection runs at a time.
    """
    if _COLLECT_LOCK.locked():
        return {"status": "busy", "message": "Collection already in progress"}

    async def event_stream():
        import json
        import asyncio as aio
        from datetime import datetime as dt, timezone as tz, timedelta
        from app.telegram_discovery.aggregator import parse_window
        logger = logging.getLogger("telegram.collect.sse")

        # Parse window to calculate offset_date for Telegram collection
        window_delta = parse_window(window)
        offset_date = dt.now(tz.utc) - window_delta

        event_queue: aio.Queue = aio.Queue()

        def fmt(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        async with _COLLECT_LOCK:
            try:
                from app.core.database import async_session_factory
                from app.telegram_discovery.client import TelegramClientService
                from app.telegram_discovery.config import load_telegram_sources_async
                from app.telegram_discovery.extractor import TokenExtractor
                from app.telegram_discovery.resolver import TokenResolver
                from app.telegram_discovery.models import (
                    TelegramSource, TelegramMessage, TelegramTokenMention,
                    CandidateToken, TelegramDiscoveryRanking,
                    DiscoveryMethod,
                )
                from sqlalchemy import delete, update, func, or_ as sa_or
                from sqlalchemy import select as sa_select

                configs = await load_telegram_sources_async()
                enabled = [c for c in configs if c.enabled]
                if not enabled:
                    await event_queue.put(fmt("error", {"message": "No enabled sources"}))
                    await event_queue.put(None)
                    # drain
                    while not event_queue.empty():
                        try:
                            msg = await aio.wait_for(event_queue.get(), timeout=0.1)
                            if msg:
                                yield msg
                        except aio.TimeoutError:
                            break
                    return

                await event_queue.put(fmt("progress", {
                    "status": "resetting", "group": "", "total_messages": 0,
                    "total_tokens": 0, "total_mentions": 0,
                    "sources_done": 0, "sources_total": len(enabled),
                }))

                async def run_collection():
                    """Background task: runs collection, pushes events to queue."""
                    client_service = TelegramClientService()
                    extractor = TokenExtractor()
                    resolver = TokenResolver()
                    try:
                        async with async_session_factory() as session:
                            await session.execute(delete(TelegramTokenMention))
                            await session.execute(delete(TelegramDiscoveryRanking))
                            await session.execute(delete(CandidateToken))
                            await session.execute(delete(TelegramMessage))
                            await session.execute(update(TelegramSource).values(last_message_id=0, last_collected_at=None))
                            await session.commit()

                            sources = await client_service.sync_sources(session, enabled)
                            if not sources:
                                await event_queue.put(fmt("error", {"message": "No sources synced"}))
                                return

                            total_messages = 0
                            sources_done = 0

                            async def on_source(source, source_stats):
                                nonlocal total_messages, sources_done
                                total_messages += source_stats["processed"]
                                sources_done += 1
                                token_count = (await session.execute(sa_select(func.count(CandidateToken.id)))).scalar() or 0
                                mention_count = (await session.execute(sa_select(func.count(TelegramTokenMention.id)))).scalar() or 0
                                await event_queue.put(fmt("progress", {
                                    "status": "collecting",
                                    "group": source.name or source.telegram_identifier,
                                    "group_id": source.source_id,
                                    "total_messages": total_messages,
                                    "total_tokens": token_count,
                                    "total_mentions": mention_count,
                                    "sources_done": sources_done,
                                    "sources_total": len(sources),
                                }))

                            stats, collected = await client_service.collect_messages(
                                session, sources, progress_callback=on_source,
                                offset_date=offset_date,
                            )
                            # Commit messages immediately so they persist
                            await session.commit()

                            # Extract + resolve tokens with progress
                            # Contract addresses + DEX links: full resolution
                            # Cashtags: store directly without DEX Screener lookups (too slow)
                            total_items = len(collected)
                            extracted = 0
                            for db_msg, src, text in collected:
                                refs = extractor.extract(text)
                                if refs:
                                    # Separate fast refs (addresses/links) from slow (cashtags)
                                    fast_refs = [r for r in refs if r.discovery_method.value in ('CONTRACT_ADDRESS', 'DEX_LINK')]
                                    cashtag_refs = [r for r in refs if r.discovery_method.value == 'CASHTAG']
                                    if fast_refs:
                                        await resolver.resolve_and_store_mentions(session, src, db_msg, fast_refs)
                                    # Store cashtags directly (no DEX lookup) + create mention
                                    for ref in cashtag_refs:
                                        candidate = await resolver._upsert_candidate(
                                            session=session,
                                            chain=ref.chain or 'ethereum',
                                            token_address=ref.token_address or f'cashtag:{ref.symbol or "unknown"}',
                                            symbol=ref.symbol or 'UNKNOWN',
                                            name=ref.symbol,
                                            source=src,
                                            discovery_method=ref.discovery_method,
                                            pair_address=None,
                                            dex_url=None,
                                            now=datetime.now(timezone.utc),
                                        )
                                        if candidate:
                                            await resolver._store_mention(
                                                session=session,
                                                candidate=candidate,
                                                source=src,
                                                message=db_msg,
                                                ref=ref,
                                            )
                                extracted += 1
                                if extracted % 10 == 0 or extracted == total_items:
                                    await session.commit()
                                    token_count = (await session.execute(sa_select(func.count(CandidateToken.id)))).scalar() or 0
                                    mention_count = (await session.execute(sa_select(func.count(TelegramTokenMention.id)))).scalar() or 0
                                    await event_queue.put(fmt("progress", {
                                        "status": "extracting",
                                        "group": f"Processing {extracted}/{total_items}",
                                        "total_messages": total_messages,
                                        "total_tokens": token_count,
                                        "total_mentions": mention_count,
                                        "sources_done": sources_done,
                                        "sources_total": len(sources),
                                    }))

                            # ── Enrich tokens from THIS window only ──
                            # Only enrich tokens that have mentions WITHIN the selected window.
                            # This ensures 15m window only enriches tokens mentioned in last 15 min.
                            contract_tokens = (await session.execute(
                                sa_select(CandidateToken).where(
                                    sa_or(
                                        CandidateToken.first_discovery_method.in_([DiscoveryMethod.CONTRACT_ADDRESS, DiscoveryMethod.DEX_LINK]),
                                        CandidateToken.token_address.startswith("cashtag:"),
                                    ),
                                    CandidateToken.id.in_(
                                        sa_select(TelegramTokenMention.candidate_token_id)
                                        .where(TelegramTokenMention.message_timestamp >= offset_date)
                                        .distinct()
                                    ),
                                )
                            )).scalars().all()
                            enriched = 0
                            total_contract = len(contract_tokens)
                            if contract_tokens:
                                await event_queue.put(fmt("progress", {
                                    "status": "enriching",
                                    "group": f"0/{total_contract}",
                                    "total_messages": total_messages,
                                    "total_tokens": 0,
                                    "total_mentions": 0,
                                    "sources_done": 0,
                                    "sources_total": total_contract,
                                }))
                                import httpx
                                from app.config import settings as app_settings
                                from sqlalchemy.exc import IntegrityError
                                async with httpx.AsyncClient(timeout=10) as http:
                                    for i, token in enumerate(contract_tokens):
                                        try:
                                            if token.first_discovery_method == DiscoveryMethod.CASHTAG:
                                                resp = await http.get(
                                                    f"{app_settings.DEXSCREENER_API_URL}/latest/dex/search?q={token.symbol}"
                                                )
                                            else:
                                                resp = await http.get(
                                                    f"{app_settings.DEXSCREENER_API_URL}/latest/dex/tokens/{token.token_address}"
                                                )
                                            if resp.status_code == 200:
                                                data = resp.json()
                                                pairs = data.get("pairs")
                                                if pairs and len(pairs) > 0:
                                                    base = pairs[0].get("baseToken", {})
                                                    if base.get("symbol") and base.get("address"):
                                                        new_addr = base["address"]
                                                        new_chain = pairs[0].get("chainId", token.chain)
                                                        # Check if another token already has this address
                                                        existing = (await session.execute(
                                                            sa_select(CandidateToken.id).where(
                                                                CandidateToken.chain == new_chain,
                                                                CandidateToken.token_address == new_addr,
                                                            )
                                                        )).scalar_one_or_none()
                                                        if not existing or existing == token.id:
                                                            token.symbol = base["symbol"]
                                                            token.name = base.get("name") or base["symbol"]
                                                            token.token_address = new_addr
                                                            token.chain = new_chain
                                                            enriched += 1
                                                            # Use savepoint to isolate failures
                                                            try:
                                                                await session.flush()
                                                            except IntegrityError:
                                                                await session.rollback()
                                                                await session.refresh(token)
                                                                enriched -= 1
                                                            except Exception:
                                                                await session.rollback()
                                                                await session.refresh(token)
                                                                enriched -= 1
                                                        elif token.token_address.startswith("cashtag:"):
                                                            # Cashtag placeholder resolves to existing token → merge
                                                            await session.execute(
                                                                update(TelegramTokenMention)
                                                                .where(TelegramTokenMention.candidate_token_id == token.id)
                                                                .values(candidate_token_id=existing)
                                                            )
                                                            await session.delete(token)
                                                            enriched += 1
                                                            try:
                                                                await session.flush()
                                                            except Exception:
                                                                await session.rollback()
                                                                await session.refresh(token)
                                                                enriched -= 1
                                            await aio.sleep(0.35)
                                        except Exception as e:
                                            logger.warning(f"Enrichment failed for {token.symbol}: {e}")
                                        if (i + 1) % 5 == 0 or i == total_contract - 1:
                                            await event_queue.put(fmt("progress", {
                                                "status": "enriching",
                                                "group": f"{i + 1}/{total_contract}",
                                                "total_messages": total_messages,
                                                "total_tokens": enriched,
                                                "total_mentions": 0,
                                                "sources_done": i + 1,
                                                "sources_total": total_contract,
                                            }))
                            if enriched:
                                await session.commit()
                                await event_queue.put(fmt("progress", {
                                    "status": "enriching",
                                    "group": f"Enriched {enriched} tokens with DEX symbols",
                                    "total_messages": total_messages,
                                    "total_tokens": enriched,
                                    "total_mentions": 0,
                                    "sources_done": sources_done,
                                    "sources_total": len(sources),
                                }))
                            await session.commit()

                            final_messages = (await session.execute(sa_select(func.count(TelegramMessage.id)))).scalar() or 0
                            final_tokens = (await session.execute(sa_select(func.count(CandidateToken.id)))).scalar() or 0
                            final_mentions = (await session.execute(sa_select(func.count(TelegramTokenMention.id)))).scalar() or 0

                            await event_queue.put(fmt("done", {
                                "status": "done",
                                "total_messages": final_messages,
                                "total_tokens": final_tokens,
                                "total_mentions": final_mentions,
                                "sources_done": sources_done,
                                "sources_total": len(sources),
                            }))
                            logger.info("SSE collection done: %d msgs, %d tokens", final_messages, final_tokens)
                    except Exception as e:
                        logger.error("SSE collection failed: %s", e, exc_info=True)
                        await event_queue.put(fmt("error", {"message": str(e)}))
                    finally:
                        await client_service.disconnect()
                        await resolver.close()
                        await event_queue.put(None)  # sentinel

                # Start collection in background
                collection_task = aio.ensure_future(run_collection())

                # Yield events as they arrive
                while True:
                    try:
                        msg = await aio.wait_for(event_queue.get(), timeout=30.0)
                    except aio.TimeoutError:
                        # send heartbeat
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


@router.get("/collect/status")
async def get_collect_status():
    """Get current collection progress."""
    import json
    try:
        from app.core.redis import get_redis
        redis = await get_redis()
        raw = await redis.get("telegram:collect:progress")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"status": "idle", "group": "", "total_messages": 0, "total_tokens": 0,
            "sources_done": 0, "sources_total": 0}


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

    candidate_count = await session.execute(select(func.count(CandidateToken.id)))
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
