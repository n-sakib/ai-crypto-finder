"""
DeepSeekEvaluator — AI-powered evaluation of discovered tokens.

Uses DeepSeek API to evaluate tokens in 3 parallel partitions.
Each partition evaluates multiple tokens in a single API call.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.telegram_discovery.models import CandidateToken, TelegramTokenMention

logger = logging.getLogger(__name__)

# Prompt template for batch token evaluation
BATCH_EVALUATION_SYSTEM_PROMPT = """You are a crypto token analyst. Evaluate ALL the tokens listed below and decide KEEP or DISCARD for each one.

For EACH token, consider:
1. Social momentum: Many unique users across many groups = genuine. Low users + high mentions = spam.
2. Liquidity quality: >$50k is good. Low liquidity + high volume = risky.
3. Safety: Honeypot, mint risk, high taxes = DISCARD.
4. Holder concentration: Top holder >40% = risky.
5. Price action: >200% pump without liquidity = risky.

Decision rules:
- KEEP: Genuine social traction, adequate liquidity, no safety red flags.
- DISCARD: Scam indicators, bot activity, extreme holder concentration, no meaningful data.

Return ONLY a JSON array with one object per token. Do NOT include any other text:
[{"symbol":"TOKEN1","decision":"keep"|"discard","confidence":0.0-1.0,"reasoning":"brief","red_flags":[],"positive_signals":[]}]
"""


class DeepSeekEvaluator:
    """Evaluates tokens in 3 parallel partitions via DeepSeek API."""

    PARTITIONS = 3

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._api_url = "https://api.deepseek.com/v1/chat/completions"

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=60.0)
        return self._http

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    def _build_batch_context(
        self,
        batch: list[tuple[CandidateToken, dict, list[str]]],
    ) -> str:
        """Build a text context for a batch of tokens."""
        parts = []
        for idx, (token, stats, source_names) in enumerate(batch, 1):
            dex = token.dexscreener_data or {}
            gmgn = token.gmgn_data or {}

            # Quick pre-filters that auto-discard
            auto_decision = None
            auto_reason = ""
            if gmgn.get('is_honeypot'):
                auto_decision = "discard"
                auto_reason = "HONEYPOT"
            elif gmgn.get('buy_tax_pct', 0) > 50 or gmgn.get('sell_tax_pct', 0) > 50:
                auto_decision = "discard"
                auto_reason = "EXTREME TAX >50%"

            parts.append(f"--- Token {idx}: {token.symbol} ({token.chain}) ---")
            if auto_decision:
                parts.append(f"AUTO: {auto_decision} — {auto_reason}")
            parts.append(f"Address: {token.token_address}")
            parts.append(f"Mentions: {stats.get('mention_count', 0)} | Users: {stats.get('unique_user_count', 0)} | Groups: {stats.get('group_count', 0)}")
            parts.append(f"Reactions: {stats.get('total_reactions', 0)} | Views: {stats.get('total_views', 0)} | Forwards: {stats.get('total_forwards', 0)}")
            parts.append(f"Sources: {', '.join(source_names[:5])}" if source_names else "Sources: none")

            if dex:
                parts.append(f"Price: ${dex.get('price_usd', 0):.8f} | Vol24h: ${dex.get('volume_24h', 0):,.0f} | Liq: ${dex.get('liquidity_usd', 0):,.0f} | MCap: ${dex.get('market_cap', 0):,.0f} | 24hΔ: {dex.get('price_change_24h', 0):.1f}%")

            if gmgn:
                parts.append(f"Safety: HP={gmgn.get('is_honeypot', False)} Tax={gmgn.get('buy_tax_pct', 0)}%/{gmgn.get('sell_tax_pct', 0)}% Top10={gmgn.get('top_10_holder_pct', 0)}% LP={gmgn.get('lp_locked_pct', 0)}% Rug={gmgn.get('rugpull_risk', '?')}")
            parts.append("")

        return "\n".join(parts)

    async def _evaluate_partition(
        self,
        batch: list[tuple[CandidateToken, dict, list[str]]],
    ) -> list[dict]:
        """Evaluate one partition of tokens in a single DeepSeek API call."""
        if not settings.DEEPSEEK_API_KEY:
            return [{"symbol": t.symbol, "decision": "pending", "confidence": 0.0,
                     "reasoning": "No API key"} for t, _, _ in batch]

        # Check for auto-discards first
        results = []
        api_tokens = []
        for token, stats, names in batch:
            gmgn = token.gmgn_data or {}
            if gmgn.get('is_honeypot'):
                results.append({"symbol": token.symbol, "decision": "discard",
                                "confidence": 1.0, "reasoning": "Auto: honeypot",
                                "red_flags": ["honeypot"], "positive_signals": []})
            elif gmgn.get('buy_tax_pct', 0) > 50 or gmgn.get('sell_tax_pct', 0) > 50:
                results.append({"symbol": token.symbol, "decision": "discard",
                                "confidence": 0.95, "reasoning": "Auto: extreme tax",
                                "red_flags": ["extreme_tax"], "positive_signals": []})
            else:
                api_tokens.append((token, stats, names))

        if not api_tokens:
            return results

        context = self._build_batch_context(api_tokens)

        try:
            http = await self._get_http()
            resp = await http.post(
                self._api_url,
                headers={
                    "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": BATCH_EVALUATION_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Evaluate these {len(api_tokens)} tokens:\n\n{context}"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 600 * len(api_tokens),  # ~600 tokens per token
                },
            )

            if resp.status_code != 200:
                logger.warning(f"DeepSeek API error: {resp.status_code}")
                results.extend([
                    {"symbol": t.symbol, "decision": "pending", "confidence": 0.0,
                     "reasoning": f"API error: {resp.status_code}"}
                    for t, _, _ in api_tokens
                ])
                return results

            result = resp.json()
            content = result["choices"][0]["message"]["content"].strip()

            # Parse JSON array from response
            try:
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                evaluations = json.loads(content)
                if not isinstance(evaluations, list):
                    evaluations = [evaluations]
            except (json.JSONDecodeError, IndexError):
                # Fallback: create pending decisions
                logger.warning(f"Failed to parse AI response: {content[:200]}")
                evaluations = [
                    {"symbol": t.symbol, "decision": "pending", "confidence": 0.0,
                     "reasoning": "Parse error"}
                    for t, _, _ in api_tokens
                ]

            # Match evaluations to tokens by symbol
            eval_map = {e.get("symbol", "").upper(): e for e in evaluations}
            for token, _, _ in api_tokens:
                ev = eval_map.get(token.symbol.upper(), {})
                results.append({
                    "symbol": token.symbol,
                    "decision": ev.get("decision", "pending"),
                    "confidence": ev.get("confidence", 0.0),
                    "reasoning": ev.get("reasoning", "No response"),
                    "red_flags": ev.get("red_flags", []),
                    "positive_signals": ev.get("positive_signals", []),
                })

            return results

        except Exception as e:
            logger.error(f"Partition evaluation failed: {e}")
            results.extend([
                {"symbol": t.symbol, "decision": "pending", "confidence": 0.0,
                 "reasoning": f"Error: {str(e)[:80]}"}
                for t, _, _ in api_tokens
            ])
            return results

    async def evaluate_tokens_batch(
        self,
        session: AsyncSession,
        tokens: list[CandidateToken],
        progress_callback=None,
    ) -> tuple[int, int, int]:
        """
        Evaluate tokens in 3 parallel partitions using DeepSeek.

        All DB queries batched upfront, then tokens split into 3 groups.
        Each group is sent as one API call. All 3 run in parallel.

        Returns (kept, discarded, pending).
        """
        if not tokens:
            return 0, 0, 0

        if not settings.DEEPSEEK_API_KEY:
            return 0, 0, len(tokens)

        from sqlalchemy import func
        from app.telegram_discovery.models import TelegramSource, TelegramMessage

        token_ids = [t.id for t in tokens]

        # ── Batch 1: Mention stats for ALL tokens ───────────────────
        mention_rows = (await session.execute(
            sa_select(
                TelegramTokenMention.candidate_token_id,
                func.count(TelegramTokenMention.id).label("mention_count"),
                func.count(func.distinct(TelegramTokenMention.sender_id_hash)).label("unique_user_count"),
                func.count(func.distinct(TelegramTokenMention.source_id)).label("group_count"),
            )
            .where(TelegramTokenMention.candidate_token_id.in_(token_ids))
            .group_by(TelegramTokenMention.candidate_token_id)
        )).all()

        mention_stats = {}
        for row in mention_rows:
            mention_stats[str(row.candidate_token_id)] = {
                "mention_count": row.mention_count,
                "unique_user_count": row.unique_user_count,
                "group_count": row.group_count,
            }

        # ── Batch 2: Source names for ALL tokens ────────────────────
        src_rows = (await session.execute(
            sa_select(
                TelegramTokenMention.candidate_token_id,
                TelegramSource.name,
            )
            .join(TelegramSource, TelegramTokenMention.source_id == TelegramSource.id)
            .where(TelegramTokenMention.candidate_token_id.in_(token_ids))
            .distinct()
        )).all()

        source_names: dict[str, list[str]] = {}
        for row in src_rows:
            tid = str(row.candidate_token_id)
            if tid not in source_names:
                source_names[tid] = []
            source_names[tid].append(row.name)

        # ── Batch 3: Social stats for ALL tokens ────────────────────
        msg_rows = (await session.execute(
            sa_select(
                TelegramTokenMention.candidate_token_id,
                func.sum(TelegramMessage.reactions_count).label("total_reactions"),
                func.sum(TelegramMessage.views_count).label("total_views"),
                func.sum(TelegramMessage.forwards_count).label("total_forwards"),
            )
            .join(TelegramMessage, TelegramTokenMention.telegram_message_id == TelegramMessage.id)
            .where(TelegramTokenMention.candidate_token_id.in_(token_ids))
            .group_by(TelegramTokenMention.candidate_token_id)
        )).all()

        msg_stats: dict[str, dict] = {}
        for row in msg_rows:
            msg_stats[str(row.candidate_token_id)] = {
                "total_reactions": row.total_reactions or 0,
                "total_views": row.total_views or 0,
                "total_forwards": row.total_forwards or 0,
            }

        # ── Build token tuples with pre-fetched data ────────────────
        token_tuples = []
        for token in tokens:
            tid = str(token.id)
            stats = mention_stats.get(tid, {"mention_count": 0, "unique_user_count": 0, "group_count": 0})
            stats["total_reactions"] = msg_stats.get(tid, {}).get("total_reactions", 0)
            stats["total_views"] = msg_stats.get(tid, {}).get("total_views", 0)
            stats["total_forwards"] = msg_stats.get(tid, {}).get("total_forwards", 0)
            names = source_names.get(tid, [])
            token_tuples.append((token, stats, names))

        # ── Partition into 3 groups ─────────────────────────────────
        n = len(token_tuples)
        partition_size = max(1, (n + self.PARTITIONS - 1) // self.PARTITIONS)
        partitions = [
            token_tuples[i:i + partition_size]
            for i in range(0, n, partition_size)
        ]

        if progress_callback:
            await progress_callback(0, n, 0, 0, 0)

        # ── 3 parallel API calls ────────────────────────────────────
        all_results: list[dict] = []
        tasks = [self._evaluate_partition(p) for p in partitions]
        partition_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(partition_results):
            if isinstance(result, Exception):
                logger.error(f"Partition {i} failed: {result}")
                for token, _, _ in partitions[i]:
                    all_results.append({"symbol": token.symbol, "decision": "pending",
                                        "confidence": 0.0, "reasoning": f"Partition error: {result}"})
            else:
                all_results.extend(result)

        # ── Apply results to tokens ─────────────────────────────────
        kept = discarded = pending = 0
        eval_map = {r.get("symbol", "").upper(): r for r in all_results}

        for token in token_tuples:
            ev = eval_map.get(token[0].symbol.upper(), {})
            tok = token[0]
            tok.ai_evaluation = ev
            tok.ai_decision = ev.get("decision", "pending")
            tok.ai_evaluated_at = datetime.now(timezone.utc)

            if ev.get("decision") == "keep":
                kept += 1
            elif ev.get("decision") == "discard":
                discarded += 1
            else:
                pending += 1

        if progress_callback:
            await progress_callback(n, n, kept, discarded, pending)

        await session.flush()
        return kept, discarded, pending
