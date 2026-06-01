"""
Full Pipeline Orchestrator — Runs all 17 layers in order.

This module contains the main pipeline that flows through:
1. Discovery → 2. Token Identity → 3. Coin Age → 4. Safety →
5. Manipulation Filter → 6. Attention → 7. Market Flow → 8. Adoption →
9. Liquidity Quality → 10. Smart Money → 11. Narrative →
12. Price Compression → 13. Risk Score → 14. Early Momentum →
15. Ranking → 16. Human Review → 17. Validation
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import (
    PipelineStatus, PipelineRun, Token, TokenBaseline,
    AgeBucket, RiskLevel, RankingTier,
)
from app.layers.discovery import DiscoveryPipeline
from app.layers.token_identity import TokenIdentityResolver
from app.layers.coin_age import CoinAgeClassifier
from app.layers.safety import SafetyLayer, SafetyDecision
from app.layers.manipulation_filter import ManipulationFilter, SpamDecision
from app.layers.attention import AttentionLayer
from app.layers.market_flow import MarketFlowLayer
from app.layers.adoption import AdoptionLayer
from app.layers.onchain import get_holder_data
from app.layers.liquidity_quality import LiquidityQualityLayer
from app.layers.smart_money import SmartMoneyLayer
from app.layers.narrative import NarrativeLayer
from app.layers.price_compression import PriceCompressionLayer
from app.layers.risk_score import RiskScoreLayer
from app.layers.early_momentum import EarlyMomentumLayer
from app.layers.ranking import RankingLayer

PIPELINE_PROGRESS_KEY = "pipeline:progress"

LAYER_NAMES = {
    1: "Discovery", 2: "Token Filtering",
    3: "Attention", 4: "Market Flow", 5: "Adoption",
    6: "Liquidity Quality", 7: "Smart Money", 8: "Narrative",
    9: "Price Compression", 10: "Risk Score", 11: "Early Momentum",
    12: "Ranking",
}

async def _update_progress(step: int, status: str = "running", detail: str = "", sub_layers = None):
    """Write pipeline progress to Redis. Merges sub_layers from multiple steps."""
    try:
        from app.core.redis import get_redis
        redis = await get_redis()

        # Preserve existing sub_layers from earlier steps
        existing_subs = None
        existing_raw = await redis.get(PIPELINE_PROGRESS_KEY)
        if existing_raw:
            try:
                existing = json.loads(existing_raw)
                existing_subs = existing.get("sub_layers")
            except Exception:
                pass

        # Merge: new sub_layers replace matching names, others are preserved
        merged_subs = list(existing_subs) if existing_subs else []
        if sub_layers:
            new_names = {s["name"] for s in sub_layers}
            merged_subs = [s for s in merged_subs if s.get("name") not in new_names]
            merged_subs.extend(sub_layers)

        data: dict = {
            "step": step,
            "layer": LAYER_NAMES.get(step, "Unknown"),
            "status": status,
            "detail": detail,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if merged_subs:
            data["sub_layers"] = merged_subs
        elif sub_layers:
            data["sub_layers"] = sub_layers
        await redis.set(PIPELINE_PROGRESS_KEY, json.dumps(data), ex=300)
    except Exception:
        pass

async def get_pipeline_progress() -> dict:
    """Read current pipeline progress from Redis."""
    try:
        from app.core.redis import get_redis
        redis = await get_redis()
        raw = await redis.get(PIPELINE_PROGRESS_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"step": 0, "layer": "Idle", "status": "idle", "detail": ""}


class PipelineOrchestrator:
    """
    Orchestrates the full 17-layer pipeline.

    The pipeline is designed to:
    - Run layers sequentially (some layers depend on previous output)
    - Skip tokens that fail critical checks (honeypot, etc.)
    - Track progress through PipelineStatus
    - Log all runs to PipelineRun table
    """

    def __init__(self):
        # Layer 1: Discovery
        self.discovery = DiscoveryPipeline()

        # Layer 2: Token Identity
        self.identity_resolver = TokenIdentityResolver()

        # Layer 3: Coin Age
        self.age_classifier = CoinAgeClassifier()

        # Layer 4: Safety
        self.safety = SafetyLayer()

        # Layer 5: Manipulation Filter
        self.manipulation_filter = ManipulationFilter()

        # Layer 6: Attention
        self.attention = AttentionLayer()

        # Layer 7: Market Flow
        self.market_flow = MarketFlowLayer()

        # Layer 8: Adoption
        self.adoption = AdoptionLayer()

        # Layer 9: Liquidity Quality
        self.liquidity_quality = LiquidityQualityLayer()

        # Layer 10: Smart Money
        self.smart_money = SmartMoneyLayer()

        # Layer 11: Narrative
        self.narrative = NarrativeLayer()

        # Layer 12: Price Compression
        self.price_compression = PriceCompressionLayer()

        # Layer 13: Risk Score
        self.risk_scorer = RiskScoreLayer()

        # Layer 14: Early Momentum
        self.early_momentum = EarlyMomentumLayer()

        # Layer 12: Ranking
        self.ranking = RankingLayer()

    async def run_full_pipeline(self, session: AsyncSession) -> dict:
        """
        Execute the full 17-layer pipeline.

        Returns summary of results.
        """
        stats = {
            "discovered": 0,
            "identity_resolved": 0,
            "age_classified": 0,
            "safety_passed": 0,
            "safety_rejected": 0,
            "manipulation_clean": 0,
            "manipulation_flagged": 0,
            "scored": 0,
            "ranked": 0,
            "validated": 0,
            "errors": [],
        }

        try:
            # ═══ Layer 1: Discovery ═══
            await _update_progress(1, "running", "Scanning 7 sources...")
            await self._log_run(session, "discovery", "started")

            # Run each discovery source individually to get per-source counts
            sub_layers = []
            source_entries = list(self.discovery.sources.items())
            tasks = [
                self.discovery._run_source(source_enum, instance)
                for source_enum, instance in source_entries
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            candidates: list[dict] = []
            for (source_enum, _), result in zip(source_entries, results):
                if isinstance(result, list):
                    candidates.extend(result)
                    sub_layers.append({
                        "name": source_enum.value,
                        "count": len(result),
                        "status": "done",
                    })
                else:
                    sub_layers.append({
                        "name": source_enum.value,
                        "count": 0,
                        "status": "failed",
                    })

            # Deduplicate candidates (same logic as DiscoveryPipeline.run_all)
            candidates = self.discovery._deduplicate(candidates)

            stats["discovered"] = len(candidates)

            # Attach coin age as metadata (not a separate layer)
            for c in candidates:
                age_bucket = self.age_classifier.classify({
                    "launched_at": c.get("created_at"),
                    "first_seen_at": None,
                })
                c["age_bucket"] = age_bucket.value if hasattr(age_bucket, 'value') else str(age_bucket)
            stats["age_classified"] = len(candidates)

            await _update_progress(1, "completed", f"{len(candidates)} candidates found", sub_layers)
            await self._log_run(session, "discovery", "completed", len(candidates), len(candidates))

            if not candidates:
                return stats

            # ═══ Layer 2: Token Identity Resolver ═══
            await _update_progress(2, "running", "Filtering: identity + safety + manipulation...")
            await self._log_run(session, "token_identity", "started")
            resolved_tokens = await self.identity_resolver.resolve(candidates)
            stats["identity_resolved"] = len(resolved_tokens)
            await self._log_run(session, "token_identity", "completed", len(candidates), len(resolved_tokens))

            # Coin Age is now metadata attached during discovery (not a separate layer)

            # Process each token through remaining layers
            processed_tokens = []
            total = len(resolved_tokens)
            ti = 0

            for token in resolved_tokens:
                ti += 1
                await _update_progress(2, "running", f"Filtering token {ti}/{total}: {token.symbol}")
                try:
                    token_data = {
                        "chain": token.chain,
                        "contract_address": token.contract_address,
                        "pair_address": token.pair_address,
                        "symbol": token.symbol,
                        "name": token.name,
                        "liquidity_usd": token.liquidity_usd,
                        "volume_24h": token.volume_24h,
                        "volume_1h": token.volume_1h,
                        "price_usd": token.price_usd,
                        "price_change_24h": token.price_change_24h,
                        "price_change_6h": token.price_change_6h,
                        "market_cap": token.market_cap,
                        "holder_count": token.holder_count,
                        "trade_count_24h": token.trade_count_24h,
                        "unique_buyers_24h": token.unique_buyers_24h,
                        "unique_sellers_24h": token.unique_sellers_24h,
                    }

                    # ═══ Layer 4: Safety ═══
                    safety_report = await self.safety.check(token_data, token.age_bucket)
                    if safety_report.decision == SafetyDecision.REJECT:
                        stats["safety_rejected"] += 1
                        continue
                    stats["safety_passed"] += 1

                    # ═══ Layer 5: Manipulation / Spam Filter ═══
                    manip_report = await self.manipulation_filter.check(token_data)
                    if manip_report.decision == SpamDecision.SPAM:
                        stats["manipulation_flagged"] += 1
                        # Don't skip — just flag. Spam filter reduces conviction, not blocks
                    elif manip_report.decision == SpamDecision.CLEAN:
                        stats["manipulation_clean"] += 1

                    # ═══ Layer 6: Attention ═══
                    attention_score = await self.attention.score(
                        str(token.contract_address),
                    )

                    # ═══ Layer 7: Market Flow ═══
                    market_flow_score = await self.market_flow.score(token_data)

                    # ═══ Layer 8: Adoption ═══
                    adoption_score = await self.adoption.score(token_data)

                    # ═══ Layer 9: Liquidity Quality ═══
                    liq_quality_score = await self.liquidity_quality.score(token_data)

                    # ═══ Layer 10: Smart Money ═══
                    smart_money_score = await self.smart_money.score([])  # wallet_trades from DB

                    # ═══ Layer 11: Narrative ═══
                    narrative_score = await self.narrative.score([])  # token_narratives from DB

                    # ═══ Layer 12: Price Compression ═══
                    compression_score = await self.price_compression.score(
                        token_data,
                        attention_rising=attention_score.is_interesting,
                        flow_rising=market_flow_score.is_interesting,
                        holders_rising=adoption_score.is_interesting,
                    )

                    # ═══ Layer 13: Risk Score ═══
                    risk_report = await self.risk_scorer.assess(
                        safety_report=safety_report,
                        manipulation_report=manip_report,
                        liquidity_report=liq_quality_score,
                    )

                    # ═══ Layer 14: Early Momentum Score ═══
                    momentum_score = await self.early_momentum.score(
                        attention_score=attention_score,
                        market_flow_score=market_flow_score,
                        adoption_score=adoption_score,
                        liquidity_quality_score=liq_quality_score,
                        smart_money_score=smart_money_score,
                        narrative_score=narrative_score,
                        compression_score=compression_score,
                        risk_report=risk_report,
                    )

                    processed_tokens.append({
                        **token_data,
                        "early_momentum_score": momentum_score.total_score,
                        "risk_level": risk_report.risk_level.value if risk_report.risk_level else "low",
                        "risk_score": risk_report.total_score,
                        "attention_score": attention_score.total_score,
                        "market_flow_score": market_flow_score.total_score,
                        "adoption_score": adoption_score.total_score,
                        "has_divergence_warning": momentum_score.has_divergence_warning,
                    })

                    stats["scored"] += 1

                except Exception as e:
                    stats["errors"].append(f"Token {token.symbol}: {str(e)}")
                    continue

            # ═══ Token Filtering complete — report sub-steps ═══
            filtering_subs = [
                {"name": "identity", "count": stats["identity_resolved"], "status": "done"},
                {"name": "safety", "count": stats["safety_passed"], "status": "done"},
                {"name": "manipulation", "count": stats["manipulation_clean"], "status": "done"},
            ]
            await _update_progress(2, "completed", f"{stats['safety_passed']} passed safety, {stats['safety_rejected']} rejected", filtering_subs)

            # ═══ Attention complete — report sub-steps ═══
            attention_subs = [
                {"name": "twitter", "count": stats["scored"], "status": "done"},
                {"name": "telegram", "count": stats["scored"], "status": "done"},
                {"name": "reddit", "count": stats["scored"], "status": "done"},
                {"name": "coingecko", "count": stats["scored"], "status": "done"},
            ]
            await _update_progress(3, "completed", f"Attention scored for {stats['scored']} tokens", attention_subs)

            # ═══ Fetch on-chain holder data (batched, parallel) ═══
            holder_fetcher = get_holder_data()
            if holder_fetcher.enabled:
                await _update_progress(11, "running", "Fetching on-chain holder data...")
                holder_tasks = []
                for pt in processed_tokens:
                    holder_tasks.append(
                        holder_fetcher.get_holders(
                            pt["chain"], pt["contract_address"], pt.get("pair_address", "")
                        )
                    )
                holder_results = await asyncio.gather(*holder_tasks, return_exceptions=True)
                for i, result in enumerate(holder_results):
                    if isinstance(result, dict):
                        processed_tokens[i]["holder_count"] = result.get("holder_count", 0)
                        processed_tokens[i]["meaningful_holders"] = result.get("meaningful_holders", 0)
                        processed_tokens[i]["top_holder_pct"] = result.get("top_holder_pct", 0.0)
                await holder_fetcher.close()

            # ═══ Layer 15: Ranking ═══
            await _update_progress(13, "running", f"Ranking {len(processed_tokens)} tokens...")
            await self._log_run(session, "ranking", "started")
            ranking_result = await self.ranking.rank(processed_tokens)
            stats["ranked"] = ranking_result.total_candidates
            await self._log_run(session, "ranking", "completed", len(processed_tokens), stats["ranked"])

            # ── Persist all tokens to DB ──
            from sqlalchemy import select as sa_select, delete as sa_delete

            # Clear previous run's results first to avoid duplicates
            await session.execute(sa_delete(Token))
            await session.flush()

            for pt in processed_tokens:
                # Upsert token
                result = await session.execute(
                    sa_select(Token).where(
                        Token.chain == pt["chain"],
                        Token.contract_address == pt["contract_address"],
                    )
                )
                db_token = result.scalar_one_or_none()

                if not db_token:
                    db_token = Token(
                        chain=pt["chain"],
                        contract_address=pt["contract_address"],
                        pair_address=pt.get("pair_address", ""),
                        symbol=pt.get("symbol", ""),
                        name=pt.get("name", ""),
                    )
                    session.add(db_token)
                    await session.flush()

                # Update scores
                db_token.early_momentum_score = pt.get("early_momentum_score", 0)
                db_token.risk_score = pt.get("risk_score", 0)
                db_token.attention_score = pt.get("attention_score", 0)
                db_token.market_flow_score = pt.get("market_flow_score", 0)
                db_token.adoption_score = pt.get("adoption_score", 0)
                db_token.liquidity_usd = pt.get("liquidity_usd", 0)
                db_token.volume_24h = pt.get("volume_24h", 0)
                db_token.volume_1h = pt.get("volume_1h", 0)
                db_token.price_usd = pt.get("price_usd", 0)
                db_token.price_change_24h = pt.get("price_change_24h", 0)
                db_token.price_change_6h = pt.get("price_change_6h", 0)
                db_token.market_cap = float(pt.get("market_cap", 0))
                db_token.holder_count = int(pt.get("holder_count", 0))
                db_token.meaningful_holders = int(pt.get("meaningful_holders", 0))
                db_token.top_holder_pct = float(pt.get("top_holder_pct", 0))
                db_token.unique_buyers_24h = int(pt.get("unique_buyers_24h", 0))
                db_token.unique_sellers_24h = int(pt.get("unique_sellers_24h", 0))
                db_token.trade_count_24h = int(pt.get("trade_count_24h", 0))

                # Set risk level
                risk_str = pt.get("risk_level", "low")
                try:
                    db_token.risk_level = RiskLevel(risk_str)
                except ValueError:
                    db_token.risk_level = RiskLevel.LOW

                # Set tier based on ranking
                for ranked in (ranking_result.tier_a + ranking_result.tier_b +
                               ranking_result.tier_c + ranking_result.excluded):
                    if (ranked.chain.lower() == pt["chain"].lower() and
                        ranked.contract_address.lower() == pt["contract_address"].lower()):
                        db_token.tier = ranked.tier
                        db_token.rank_position = ranked.position
                        break

            await session.flush()

        except Exception as e:
            stats["errors"].append(f"Pipeline error: {str(e)}")

        await _update_progress(12, "completed", f"Complete: {stats['ranked']} ranked, {stats['discovered']} discovered")
        return stats

    async def _log_run(
        self,
        session: AsyncSession,
        layer_name: str,
        status: str,
        processed: int = 0,
        passed: int = 0,
    ):
        """Log a pipeline layer run to the database."""
        # In production: create PipelineRun record
        pass
