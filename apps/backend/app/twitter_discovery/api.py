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

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException
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


# Status

@router.get("/discovery/status")
async def get_twitter_status():
    """Check if Playwright session is valid for authenticated scraping."""
    import json as _json
    import os as _os
    from datetime import datetime, timezone as _timezone

    session_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "x_session.json")
    session_path = _os.path.abspath(session_path)

    if not _os.path.exists(session_path):
        return {
            "configured": True,
            "mode": "playwright",
            "authenticated": False,
            "message": "No session file. Run collect_twitter_playwright.py --login on the host.",
        }

    try:
        with open(session_path) as f:
            data = _json.load(f)
        cookies = data.get("cookies", [])
        auth_token = next((c for c in cookies if c["name"] == "auth_token"), None)
        ct0 = next((c for c in cookies if c["name"] == "ct0"), None)

        if not auth_token or not ct0:
            return {
                "configured": True, "mode": "playwright",
                "authenticated": False,
                "message": "Session file exists but missing auth_token/ct0. Re-run --login.",
            }

        expires = auth_token.get("expires", 0)
        if expires > 0:
            expiry = datetime.fromtimestamp(expires, tz=_timezone.utc)
            now = datetime.now(_timezone.utc)
            if now > expiry:
                return {
                    "configured": True, "mode": "playwright",
                    "authenticated": False,
                    "message": f"Session expired {expiry.strftime('%Y-%m-%d')}. Re-run --login.",
                }
            days_left = (expiry - now).days
        else:
            days_left = None

        return {
            "configured": True, "mode": "playwright",
            "authenticated": True,
            "days_left": days_left,
            "message": "Authenticated — ready to collect.",
        }
    except Exception as e:
        return {
            "configured": True, "mode": "playwright",
            "authenticated": False,
            "message": f"Session file corrupt: {e}",
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


# ── Ingest (Playwright → Backend) ──────────────────────────────────────

from pydantic import BaseModel as PydanticBaseModel

class IngestPayload(PydanticBaseModel):
    candidates: list[dict]


@router.post("/ingest")
async def ingest_playwright_results(
    payload: IngestPayload,
    session: AsyncSession = Depends(get_session),
):
    """Ingest token candidates scraped by collect_twitter_playwright.py.

    The Playwright script runs on the host machine, scrapes public X profiles,
    and POSTs extracted candidates here for storage and ranking.
    """
    from app.twitter_discovery.client import TwitterClientService

    if not payload.candidates:
        return {"status": "ok", "stored": 0, "message": "No candidates to ingest"}

    service = TwitterClientService()
    stats = await service.ingest_playwright_candidates(session, payload.candidates)

    # Also cache in Redis for the discovery pipeline
    try:
        from app.core.redis import get_redis
        import json
        redis = await get_redis()
        await redis.set("twitter:pending_candidates", json.dumps(payload.candidates), ex=3600)
    except Exception:
        pass

    return {
        "status": "ok",
        "candidates_received": len(payload.candidates),
        "tweets_stored": stats["tweets_stored"],
        "mentions_stored": stats["mentions_stored"],
        "tokens_discovered": stats["tokens_discovered"],
        "errors": stats["errors"],
    }


# ── Collect ────────────────────────────────────────────────────────────

def _check_session() -> tuple[bool, str]:
    """Check if x_session.json exists and is valid. Returns (ok, message)."""
    import json as _json
    import os as _os
    from datetime import datetime, timezone as _timezone

    session_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "x_session.json")
    session_path = _os.path.abspath(session_path)

    if not _os.path.exists(session_path):
        return False, "Not logged in. Run: python collect_twitter_playwright.py --login"

    try:
        with open(session_path) as f:
            data = _json.load(f)
    except Exception:
        return False, "Session file corrupt. Re-run: python collect_twitter_playwright.py --login"

    cookies = data.get("cookies", [])
    auth_token = next((c for c in cookies if c["name"] == "auth_token"), None)
    ct0 = next((c for c in cookies if c["name"] == "ct0"), None)

    if not auth_token or not ct0:
        return False, "Session incomplete. Re-run: python collect_twitter_playwright.py --login"

    expires = auth_token.get("expires", 0)
    if expires > 0:
        expiry = datetime.fromtimestamp(expires, tz=_timezone.utc)
        if datetime.now(_timezone.utc) > expiry:
            return False, f"Session expired {expiry.strftime('%Y-%m-%d')}. Re-run: python collect_twitter_playwright.py --login"

    return True, "ok"


@router.post("/collect")
async def trigger_twitter_collect(
    query: str = Query("", description="Search term (e.g. token symbol) to discover accounts for"),
    accounts: str = Query("", description="Comma-separated @handles to scrape directly"),
):
    """Trigger Playwright-based Twitter scraping.

    Checks auth session first — returns error if not logged in.
    Spawns collect_twitter_playwright.py on the host machine.
    Results appear via /twitter/ingest → /twitter/discovery.
    """
    import subprocess
    import os as _os

    # ── Auth check ──────────────────────────────────────────────────
    ok, msg = _check_session()
    if not ok:
        raise HTTPException(status_code=401, detail=msg)

    # ── Find script ─────────────────────────────────────────────────
    script = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "collect_twitter_playwright.py")
    script = _os.path.abspath(script)

    if not _os.path.exists(script):
        raise HTTPException(
            status_code=500,
            detail=f"Script not found at {script}. Run collect_twitter_playwright.py on the host.",
        )

    args = ["python", script]
    if query:
        args += ["--search", query]
    elif accounts:
        args += ["--accounts", accounts]

    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {
            "status": "started",
            "query": query or None,
            "accounts": accounts or None,
            "message": "Scraper started. Results will appear via /twitter/ingest → /twitter/discovery",
        }
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Python not found on host.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
