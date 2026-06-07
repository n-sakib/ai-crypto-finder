"""
API Routes — REST endpoints for the AI Crypto Finder.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.models import Token, DiscoveryEvent, DiscoverySource, RankingTier
from app.core.schemas import (
    TokenSummary, TokenDetail, RankingResponse,
    PipelineStatusResponse, TokenDiscoveredRequest,
)
from app.telegram_discovery.api import router as telegram_discovery_router
from app.reddit_discovery.api import router as reddit_discovery_router
from app.twitter_discovery.api import router as twitter_discovery_router
from app.gmgn_discovery.api import router as gmgn_discovery_router
from app.dexscreener_discovery.api import router as dexscreener_discovery_router

router = APIRouter()

# Include Telegram discovery sub-router
router.include_router(telegram_discovery_router)

# Include Reddit discovery sub-router
router.include_router(reddit_discovery_router)

# Include Twitter discovery sub-router
router.include_router(twitter_discovery_router)

# Include GMGN discovery sub-router
router.include_router(gmgn_discovery_router)

# Include DexScreener discovery sub-router
router.include_router(dexscreener_discovery_router)

# Include Unified Pipeline sub-router
from app.api.unified_pipeline import router as unified_pipeline_router
router.include_router(unified_pipeline_router)

# ── Token Endpoints ────────────────────────────────────────────────────

@router.get("/tokens", response_model=list[TokenSummary])
async def list_tokens(
    tier: Optional[str] = Query(None, description="Filter by tier (tier_a, tier_b, tier_c, excluded)"),
    chain: Optional[str] = Query(None, description="Filter by chain"),
    min_momentum: Optional[float] = Query(None, description="Minimum momentum score"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    q = select(Token)
    if tier:
        try:
            q = q.where(Token.tier == RankingTier(tier))
        except ValueError:
            pass
    if chain:
        q = q.where(Token.chain == chain.lower())
    if min_momentum is not None:
        q = q.where(Token.early_momentum_score >= min_momentum)
    q = q.order_by(desc(Token.early_momentum_score)).offset(offset).limit(limit)
    result = await session.execute(q)
    tokens = result.scalars().all()
    return [TokenSummary.model_validate(t) for t in tokens]


@router.get("/tokens/{token_id}", response_model=TokenDetail)
async def get_token(token_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Token).where(Token.id == token_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    return TokenDetail.model_validate(token)


# ── Ranking Endpoints ──────────────────────────────────────────────────

@router.get("/rankings", response_model=RankingResponse)
async def get_rankings(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Token).where(Token.tier.isnot(None)).order_by(desc(Token.early_momentum_score))
    )
    tokens = result.scalars().all()

    tier_a = [TokenSummary.model_validate(t) for t in tokens if t.tier == RankingTier.TIER_A]
    tier_b = [TokenSummary.model_validate(t) for t in tokens if t.tier == RankingTier.TIER_B]
    tier_c = [TokenSummary.model_validate(t) for t in tokens if t.tier == RankingTier.TIER_C]
    excluded = [TokenSummary.model_validate(t) for t in tokens if t.tier == RankingTier.EXCLUDED]

    return RankingResponse(
        tier_a=tier_a, tier_b=tier_b, tier_c=tier_c, excluded=excluded,
        total_candidates=len(tokens), generated_at=datetime.now(timezone.utc),
    )


# ── Discovery Endpoints ────────────────────────────────────────────────

@router.post("/discover", response_model=TokenSummary, status_code=201)
async def ingest_discovery(
    payload: TokenDiscoveredRequest,
    session: AsyncSession = Depends(get_session),
):
    existing = await session.execute(
        select(Token).where(
            Token.chain == payload.chain,
            Token.contract_address == payload.contract_address,
        )
    )
    token = existing.scalar_one_or_none()

    if not token:
        token = Token(
            chain=payload.chain,
            contract_address=payload.contract_address,
            pair_address=payload.pair_address,
            symbol=payload.symbol,
            name=payload.name,
            dex_id=payload.dex_id,
        )
        session.add(token)
        await session.flush()

    evt = DiscoveryEvent(
        token_id=token.id,
        source=payload.source,
        raw_data=payload.raw_data,
    )
    session.add(evt)
    await session.commit()
    await session.refresh(token)
    return TokenSummary.model_validate(token)


# ── Pipeline Endpoints ─────────────────────────────────────────────────

PIPELINE_RUNNING = False

@router.post("/pipeline/run")
async def trigger_pipeline(background_tasks: BackgroundTasks):
    global PIPELINE_RUNNING
    if PIPELINE_RUNNING:
        return {"status": "already_running", "message": "Pipeline is already running"}
    PIPELINE_RUNNING = True

    async def run():
        global PIPELINE_RUNNING
        try:
            from app.core.database import async_session_factory
            from app.services.pipeline import PipelineOrchestrator
            async with async_session_factory() as session:
                orch = PipelineOrchestrator()
                stats = await orch.run_full_pipeline(session)
                await session.commit()
                print(f"Pipeline complete: {stats}")
        except Exception as e:
            print(f"Pipeline error: {e}")
        finally:
            PIPELINE_RUNNING = False

    background_tasks.add_task(run)
    return {"status": "started", "message": "Pipeline run triggered"}


@router.get("/pipeline/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(session: AsyncSession = Depends(get_session)):
    from app.core.models import PipelineRun
    from app.services.pipeline import get_pipeline_progress

    result = await session.execute(
        select(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(10)
    )
    runs = result.scalars().all()

    count_result = await session.execute(select(func.count(Token.id)))
    total = count_result.scalar() or 0

    progress = await get_pipeline_progress()

    return PipelineStatusResponse(
        latest_runs=[
            {
                "layer_name": r.layer_name,
                "tokens_processed": r.tokens_processed,
                "tokens_passed": r.tokens_passed,
                "tokens_rejected": r.tokens_rejected,
            }
            for r in runs
        ],
        tokens_in_pipeline=total,
        tokens_by_status={},
        last_full_run=runs[0].started_at if runs else None,
        progress=progress,
    )


# ── Health ─────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    total_r = await session.execute(select(func.count(Token.id)))
    a_r = await session.execute(select(func.count(Token.id)).where(Token.tier == RankingTier.TIER_A))
    b_r = await session.execute(select(func.count(Token.id)).where(Token.tier == RankingTier.TIER_B))
    c_r = await session.execute(select(func.count(Token.id)).where(Token.tier == RankingTier.TIER_C))
    x_r = await session.execute(select(func.count(Token.id)).where(Token.tier == RankingTier.EXCLUDED))

    total = total_r.scalar() or 0
    a = a_r.scalar() or 0
    b = b_r.scalar() or 0
    c = c_r.scalar() or 0
    x = x_r.scalar() or 0

    return {
        "total_tokens_tracked": total,
        "tokens_in_pipeline": total,
        "tokens_ranked": a + b + c,
        "tier_a_count": a,
        "tier_b_count": b,
        "tier_c_count": c,
        "excluded_count": x,
    }

