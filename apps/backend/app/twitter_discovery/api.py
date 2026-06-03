"""
Twitter Discovery API Routes.

Endpoints:
    GET  /twitter/discovery?window=24h&limit=50
    GET  /twitter/discovery/{chain}/{token_address}
    GET  /twitter/sources
    POST /twitter/sources
    DELETE /twitter/sources/{source_id}
    PUT  /twitter/sources/{source_id}/toggle
    GET  /twitter/discovery/stats
    POST /twitter/collect
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.config import settings
from app.twitter_discovery.aggregator import TwitterDiscoveryAggregator
from app.twitter_discovery.config import seed_twitter_sources
from app.twitter_discovery.models import (
    TwitterSource, TwitterTweet, TwitterCandidateToken,
    TwitterTokenMention, TwitterSourceType,
)
from app.twitter_discovery.schemas import (
    TwitterDiscoveryRankingResponse,
    TwitterSourceResponse,
    TwitterTokenMentionDetail,
    TwitterStatsResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/twitter", tags=["twitter-discovery"])

_COLLECT_LOCK = asyncio.Lock()


# Status

@router.get("/discovery/status")
async def get_twitter_status():
    configured = bool(settings.TWITTER_USERNAME and settings.TWITTER_PASSWORD)
    if not configured:
        return {
            "configured": False,
            "message": "Set TWITTER_USERNAME and TWITTER_PASSWORD in apps/backend/.env",
        }

    # Check if cookies file exists (fast, no network call)
    import os as _os
    cookies_path = "/app/twitter_cookies.json"
    if _os.path.exists(cookies_path):
        return {
            "configured": True,
            "message": "Twitter cookies found — ready for discovery",
        }
    return {
        "configured": False,
        "message": "No cookies file — export from browser (EditThisCookie → x.com → Export JSON → save to apps/backend/twitter_cookies.json)",
    }


# ── Discovery Rankings ─────────────────────────────────────────────────

@router.get("/discovery", response_model=TwitterDiscoveryRankingResponse)
async def get_twitter_discovery(
    window: str = Query("24h", description="Time window: 6h, 12h, 24h, 7d"),
    limit: int = Query(50, ge=1, le=500, description="Max tokens to return"),
    min_mentions: int = Query(1, ge=1, description="Minimum mention count"),
    min_users: int = Query(1, ge=1, description="Minimum unique users"),
    session: AsyncSession = Depends(get_session),
):
    """Get top discovered tokens from Twitter for a time window."""
    aggregator = TwitterDiscoveryAggregator(
        min_mention_count=min_mentions,
        min_unique_users=min_users,
    )
    return await aggregator.rank(session, window=window, limit=limit)


@router.get("/discovery/{chain}/{token_address}", response_model=TwitterTokenMentionDetail)
async def get_twitter_token_detail(
    chain: str,
    token_address: str,
    session: AsyncSession = Depends(get_session),
):
    """Get detailed Twitter discovery data for a specific token."""
    aggregator = TwitterDiscoveryAggregator()
    detail = await aggregator.get_token_detail(session, chain, token_address)
    if not detail:
        raise HTTPException(status_code=404, detail="Token not found in Twitter discovery")
    return TwitterTokenMentionDetail(**detail)


# ── Sources ────────────────────────────────────────────────────────────

@router.get("/sources", response_model=list[TwitterSourceResponse])
async def get_twitter_sources(
    enabled_only: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    """List configured Twitter discovery sources (search queries)."""
    q = select(TwitterSource)
    if enabled_only:
        q = q.where(TwitterSource.enabled == True)
    q = q.order_by(TwitterSource.source_type, TwitterSource.name)

    result = await session.execute(q)
    sources = result.scalars().all()
    return [TwitterSourceResponse.model_validate(s) for s in sources]


@router.post("/sources", response_model=TwitterSourceResponse, status_code=201)
async def add_twitter_source(
    query: str = Query(..., description="Search query (e.g., $TOKEN, keyword, @handle)"),
    name: str = Query("", description="Display name"),
    source_type: str = Query("cashtag_search", description="cashtag_search, keyword_search, address_search, account_monitor"),
    session: AsyncSession = Depends(get_session),
):
    """Add a new Twitter search query source."""
    source_id = f"twitter_{source_type}_{query.lower().replace(' ', '_').replace('@', '').replace('$', '')[:60]}"
    display_name = name or query

    existing = (await session.execute(
        select(TwitterSource).where(TwitterSource.source_id == source_id)
    )).scalar_one_or_none()

    if existing:
        existing.enabled = True
        existing.query = query
        existing.name = display_name
        existing.source_type = TwitterSourceType(source_type)
        await session.commit()
        await session.refresh(existing)
        return TwitterSourceResponse.model_validate(existing)

    src = TwitterSource(
        source_id=source_id,
        name=display_name,
        query=query,
        source_type=TwitterSourceType(source_type),
        enabled=True,
    )
    session.add(src)
    await session.commit()
    await session.refresh(src)
    return TwitterSourceResponse.model_validate(src)


@router.delete("/sources/{source_id}")
async def remove_twitter_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove a Twitter source."""
    src = (await session.execute(
        select(TwitterSource).where(TwitterSource.source_id == source_id)
    )).scalar_one_or_none()

    if not src:
        src = (await session.execute(
            select(TwitterSource).where(TwitterSource.id == source_id)
        )).scalar_one_or_none()

    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    await session.delete(src)
    await session.commit()
    return {"status": "deleted", "source_id": src.source_id}


@router.put("/sources/{source_id}/toggle")
async def toggle_twitter_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Toggle a Twitter source enabled/disabled."""
    src = (await session.execute(
        select(TwitterSource).where(TwitterSource.source_id == source_id)
    )).scalar_one_or_none()

    if not src:
        src = (await session.execute(
            select(TwitterSource).where(TwitterSource.id == source_id)
        )).scalar_one_or_none()

    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    src.enabled = not src.enabled
    await session.commit()
    return {"status": "ok", "source_id": src.source_id, "enabled": src.enabled}


# ── Stats ──────────────────────────────────────────────────────────────

@router.get("/discovery/stats", response_model=TwitterStatsResponse)
async def get_twitter_stats(
    session: AsyncSession = Depends(get_session),
):
    """Get Twitter discovery statistics."""
    token_count = (await session.execute(select(func.count(TwitterCandidateToken.id)))).scalar() or 0
    mention_count = (await session.execute(select(func.count(TwitterTokenMention.id)))).scalar() or 0
    tweet_count = (await session.execute(select(func.count(TwitterTweet.id)))).scalar() or 0
    src_count = (await session.execute(
        select(func.count(TwitterSource.id)).where(TwitterSource.enabled == True)
    )).scalar() or 0

    latest = (await session.execute(
        select(TwitterTokenMention.tweet_timestamp)
        .order_by(desc(TwitterTokenMention.tweet_timestamp))
        .limit(1)
    )).scalar_one_or_none()

    return TwitterStatsResponse(
        candidate_tokens=token_count,
        total_mentions=mention_count,
        tweets_stored=tweet_count,
        enabled_sources=src_count,
        latest_mention_at=latest,
        generated_at=datetime.now(timezone.utc),
    )


# ── Collect ────────────────────────────────────────────────────────────

@router.post("/collect")
async def trigger_twitter_collect(
    window: str = Query("24h", description="Time window: 6h, 12h, 24h, 7d"),
):
    """Run Twitter discovery collection as a foreground SSE stream."""
    if _COLLECT_LOCK.locked():
        return {"status": "busy", "message": "Collection already in progress"}

    async def event_stream():
        import asyncio as aio
        from app.twitter_discovery.client import TwitterClientService
        from app.core.database import async_session_factory

        logger = logging.getLogger("twitter.collect.sse")
        event_queue: aio.Queue = aio.Queue()

        def fmt(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

        async with _COLLECT_LOCK:
            try:
                async def run_collection():
                    """Background task: runs collection, pushes events to queue."""
                    try:
                        async with async_session_factory() as session:
                            await seed_twitter_sources(session)

                            async def progress_callback(data: dict):
                                await event_queue.put(fmt("progress", data))

                            service = TwitterClientService()
                            stats = await service.collect(session, progress_callback=progress_callback)

                            await event_queue.put(fmt("done", {
                                "status": "completed",
                                "tweets_stored": stats["tweets_stored"],
                                "mentions_stored": stats["mentions_stored"],
                                "tokens_discovered": stats["tokens_discovered"],
                                "errors": stats["errors"],
                            }))
                    except Exception as e:
                        logger.error("Twitter collection failed: %s", e, exc_info=True)
                        await event_queue.put(fmt("error", {"error": str(e)}))
                    finally:
                        await event_queue.put(None)  # sentinel

                # Start collection in background
                collection_task = aio.ensure_future(run_collection())

                # Yield events as they arrive in real-time
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
                yield fmt("error", {"error": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
