"""
Reddit Discovery API Routes.

Endpoints:
    GET /reddit/discovery?window=24h&limit=100
    GET /reddit/discovery/{chain}/{token_address}
    GET /reddit/sources
    POST /reddit/collect
    GET /reddit/discovery/stats
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc, and_, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.reddit_discovery.aggregator import RedditDiscoveryAggregator
from app.reddit_discovery.models import (
    RedditSource, RedditPost, RedditCandidateToken,
    RedditTokenMention, RedditDiscoveryRanking,
    RedditSourceType, RedditDiscoveryMethod,
)
from app.reddit_discovery.schemas import (
    RedditDiscoveryRankingResponse,
    RedditSourceResponse,
    RedditTokenMentionDetail,
    RedditStatsResponse,
)
from app.reddit_discovery.config import load_reddit_sources_async

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reddit", tags=["reddit-discovery"])

_COLLECT_LOCK = asyncio.Lock()


# ── Discovery Rankings ─────────────────────────────────────────────────

@router.get("/discovery", response_model=RedditDiscoveryRankingResponse)
async def get_reddit_discovery(
    window: str = Query("24h", description="Time window: 6h, 12h, 24h, 7d"),
    limit: int = Query(50, ge=1, le=500, description="Max tokens to return"),
    min_mentions: int = Query(1, ge=1, description="Minimum mention count"),
    min_users: int = Query(1, ge=1, description="Minimum unique users"),
    session: AsyncSession = Depends(get_session),
):
    """Get top discovered tokens from Reddit for a time window."""
    aggregator = RedditDiscoveryAggregator(
        min_mention_count=min_mentions,
        min_unique_users=min_users,
    )
    return await aggregator.rank(session, window=window, limit=limit)


@router.get("/discovery/{chain}/{token_address}", response_model=RedditTokenMentionDetail)
async def get_reddit_token_detail(
    chain: str,
    token_address: str,
    session: AsyncSession = Depends(get_session),
):
    """Get detailed Reddit discovery data for a specific token."""
    aggregator = RedditDiscoveryAggregator()
    detail = await aggregator.get_token_detail(session, chain, token_address)
    if not detail:
        raise HTTPException(status_code=404, detail="Token not found in Reddit discovery")
    return RedditTokenMentionDetail(**detail)


# ── Sources ────────────────────────────────────────────────────────────

@router.get("/sources", response_model=list[RedditSourceResponse])
async def get_reddit_sources(
    enabled_only: bool = Query(False, description="Only show enabled sources"),
    session: AsyncSession = Depends(get_session),
):
    """List configured Reddit discovery sources (subreddits)."""
    q = select(RedditSource)
    if enabled_only:
        q = q.where(RedditSource.enabled == True)
    q = q.order_by(RedditSource.source_type, RedditSource.name)

    result = await session.execute(q)
    sources = result.scalars().all()
    return [RedditSourceResponse.model_validate(s) for s in sources]


@router.post("/sources", response_model=RedditSourceResponse, status_code=201)
async def add_reddit_source(
    subreddit_name: str = Query(..., description="Subreddit name (without r/ prefix)"),
    name: str = Query("", description="Display name (optional, defaults to r/subreddit)"),
    source_type: str = Query("general_crypto", description="general_crypto, meme_coins, trading, defi, chain_specific"),
    session: AsyncSession = Depends(get_session),
):
    """Add a new Reddit subreddit source."""
    from app.reddit_discovery.config import _infer_source_type

    subreddit_name = subreddit_name.strip().lstrip("r/").lstrip("/")
    source_id = f"reddit_r_{subreddit_name.lower()}"
    display_name = name or f"r/{subreddit_name}"

    existing = (await session.execute(
        select(RedditSource).where(RedditSource.source_id == source_id)
    )).scalar_one_or_none()

    if existing:
        existing.enabled = True
        existing.subreddit_name = subreddit_name
        existing.name = display_name
        existing.source_type = RedditSourceType(source_type)
        await session.commit()
        await session.refresh(existing)
        return RedditSourceResponse.model_validate(existing)

    src = RedditSource(
        source_id=source_id,
        name=display_name,
        subreddit_name=subreddit_name,
        source_type=RedditSourceType(source_type),
        enabled=True,
    )
    session.add(src)
    await session.commit()
    await session.refresh(src)
    return RedditSourceResponse.model_validate(src)


@router.delete("/sources/{source_id}")
async def remove_reddit_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove a Reddit source."""
    src = (await session.execute(
        select(RedditSource).where(RedditSource.source_id == source_id)
    )).scalar_one_or_none()

    if not src:
        src = (await session.execute(
            select(RedditSource).where(RedditSource.id == source_id)
        )).scalar_one_or_none()

    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    await session.delete(src)
    await session.commit()
    return {"status": "deleted", "source_id": src.source_id}


@router.put("/sources/{source_id}/toggle")
async def toggle_reddit_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Toggle a Reddit source enabled/disabled."""
    src = (await session.execute(
        select(RedditSource).where(RedditSource.source_id == source_id)
    )).scalar_one_or_none()

    if not src:
        src = (await session.execute(
            select(RedditSource).where(RedditSource.id == source_id)
        )).scalar_one_or_none()

    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    src.enabled = not src.enabled
    await session.commit()
    return {"status": "ok", "source_id": src.source_id, "enabled": src.enabled}


# ── Stats ──────────────────────────────────────────────────────────────

@router.get("/discovery/stats", response_model=RedditStatsResponse)
async def get_reddit_stats(
    session: AsyncSession = Depends(get_session),
):
    """Get Reddit discovery statistics."""
    token_count = (await session.execute(select(func.count(RedditCandidateToken.id)))).scalar() or 0
    mention_count = (await session.execute(select(func.count(RedditTokenMention.id)))).scalar() or 0
    post_count = (await session.execute(select(func.count(RedditPost.id)))).scalar() or 0
    src_count = (await session.execute(
        select(func.count(RedditSource.id)).where(RedditSource.enabled == True)
    )).scalar() or 0

    latest = (await session.execute(
        select(RedditTokenMention.post_timestamp)
        .order_by(desc(RedditTokenMention.post_timestamp))
        .limit(1)
    )).scalar_one_or_none()

    return RedditStatsResponse(
        candidate_tokens=token_count,
        total_mentions=mention_count,
        posts_stored=post_count,
        enabled_sources=src_count,
        latest_mention_at=latest,
        generated_at=datetime.now(timezone.utc),
    )


# ── Collect ────────────────────────────────────────────────────────────

@router.post("/collect")
async def trigger_reddit_collect(
    window: str = Query("24h", description="Time window for collection: 6h, 12h, 24h, 7d"),
):
    """
    Run Reddit discovery collection as a foreground SSE stream.
    Sends real-time progress events.
    """
    if _COLLECT_LOCK.locked():
        return {"status": "busy", "message": "Collection already in progress"}

    async def event_stream():
        import asyncio as aio
        from app.reddit_discovery.aggregator import parse_window
        from app.reddit_discovery.client import RedditClientService
        from app.reddit_discovery.extractor import RedditTokenExtractor
        from app.reddit_discovery.resolver import RedditTokenResolver

        logger = logging.getLogger("reddit.collect.sse")

        window_delta = parse_window(window)
        offset_date = datetime.now(timezone.utc) - window_delta

        event_queue: aio.Queue = aio.Queue()

        def fmt(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

        async with _COLLECT_LOCK:
            try:
                from app.core.database import async_session_factory

                configs = await load_reddit_sources_async()
                enabled = [c for c in configs if c.enabled]
                if not enabled:
                    await event_queue.put(fmt("error", {"message": "No enabled sources"}))
                    yield await event_queue.get()
                    return

                await event_queue.put(fmt("progress", {
                    "status": "resetting", "subreddit": "", "total_posts": 0,
                    "total_tokens": 0, "total_mentions": 0,
                    "sources_done": 0, "sources_total": len(enabled),
                }))

                async def run_collection():
                    client_service = RedditClientService()
                    extractor = RedditTokenExtractor()
                    resolver = RedditTokenResolver()

                    try:
                        async with async_session_factory() as session:
                            # Reset existing data
                            await session.execute(delete(RedditTokenMention))
                            await session.execute(delete(RedditDiscoveryRanking))
                            await session.execute(delete(RedditCandidateToken))
                            await session.execute(delete(RedditPost))
                            await session.execute(update(RedditSource).values(last_post_id=None, last_collected_at=None))
                            await session.commit()

                            sources = await client_service.sync_sources(session, enabled)
                            if not sources:
                                await event_queue.put(fmt("error", {"message": "No sources synced"}))
                                return

                            total_posts = 0
                            total_tokens = 0
                            total_mentions = 0
                            sources_done = 0

                            async def on_source(source, source_stats):
                                nonlocal total_posts, total_tokens, total_mentions, sources_done
                                total_posts += source_stats["processed"]
                                sources_done += 1
                                token_count = (await session.execute(
                                    select(func.count(RedditCandidateToken.id))
                                )).scalar() or 0
                                mention_count = (await session.execute(
                                    select(func.count(RedditTokenMention.id))
                                )).scalar() or 0
                                await event_queue.put(fmt("progress", {
                                    "status": "collecting",
                                    "subreddit": source.subreddit_name,
                                    "total_posts": total_posts,
                                    "total_tokens": token_count,
                                    "total_mentions": mention_count,
                                    "sources_done": sources_done,
                                    "sources_total": len(sources),
                                }))

                            stats, posts = await client_service.collect_posts(
                                session, sources,
                                progress_callback=on_source,
                                offset_date=offset_date,
                            )

                            # Extract and resolve tokens
                            for post in posts:
                                text = post.selftext or ""
                                extractions = extractor.extract(text, post.title)
                                if extractions:
                                    mentions = await resolver.resolve(session, extractions, post)
                                    total_mentions += mentions
                                    total_tokens += len(extractions)

                            token_count = (await session.execute(
                                select(func.count(RedditCandidateToken.id))
                            )).scalar() or 0
                            mention_count = (await session.execute(
                                select(func.count(RedditTokenMention.id))
                            )).scalar() or 0

                            await event_queue.put(fmt("done", {
                                "status": "done",
                                "subreddit": "",
                                "total_posts": total_posts,
                                "total_tokens": token_count,
                                "total_mentions": mention_count,
                                "sources_done": sources_done,
                                "sources_total": len(sources),
                            }))
                    except Exception as e:
                        logger.exception("Collection failed")
                        await event_queue.put(fmt("error", {"message": str(e)}))

                task = aio.ensure_future(run_collection())

                while True:
                    try:
                        msg = await aio.wait_for(event_queue.get(), timeout=30)
                        if msg is None:
                            break
                        yield msg
                    except aio.TimeoutError:
                        if task.done():
                            # Drain remaining
                            while not event_queue.empty():
                                try:
                                    msg = event_queue.get_nowait()
                                    if msg:
                                        yield msg
                                except aio.QueueEmpty:
                                    break
                            break

                if task.done() and task.exception():
                    logger.error(f"Collection task failed: {task.exception()}")

            except Exception as e:
                logger.exception("SSE stream failed")
                yield fmt("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
