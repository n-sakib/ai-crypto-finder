"""
Unified Pipeline — Telegram → DexScreener → GMGN → Dedup → Windowed Aggregation → Ranking.

Steps:
  1. Telegram Scan  — collect messages, extract tokens
  2. DexScreener     — enrich each token with pair data (price/volume/txns)
  3. GMGN            — enrich with GMGN metrics (score, hot_level)
  4. Dedup           — merge same token across sources
  5. Windowed Agg    — bucket metrics into 5m/1h/6h/24h windows
  6. Ranking         — composite score, assign rank
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy import select, func, desc, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import get_session
from app.core.models import UnifiedToken
from app.config import settings

logger = logging.getLogger(__name__)

DEXSCREENER_PAIRS_URL = "https://api.dexscreener.com/tokens/v1"
DEXSCREENER_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
GMGN_TRENDING_URL = "https://gmgn.ai/defi/router/v1/sol/txns/trending"


class UnifiedPipeline:
    """Orchestrates the full discovery → enrichment → ranking pipeline."""

    def __init__(self):
        self._dex_client: Optional[httpx.AsyncClient] = None
        self._gmgn_client: Optional[httpx.AsyncClient] = None
        self._telegram_client = None

    async def run(self, session: AsyncSession, window: str = "24h", status_callback=None, should_stop=None) -> list[dict]:
        """Run the pipeline for a specific time window (5m, 1h, 6h, 24h)."""
        logger.info("=== Unified Pipeline Start (window=%s) ===", window)
        now = datetime.now(timezone.utc)

        def _stop() -> bool:
            return should_stop and should_stop()

        # ── Cleanup: remove old unenriched tokens from DB ─────────────
        from sqlalchemy import delete as sqla_delete
        result = await session.execute(
            sqla_delete(UnifiedToken).where(UnifiedToken.pair_address.is_(None))
        )
        if result.rowcount:
            logger.info("  Cleaned up %d unenriched tokens from previous runs", result.rowcount)
            await session.commit()

        windows = (window,)  # single window

        # ── Step 1: Telegram Scan ─────────────────────────────────────
        logger.info("Step 1: Telegram scan...")
        if status_callback:
            status_callback("telegram", "Scanning Telegram groups...")
        tg_tokens = await self._scan_telegram(session, now, window=window, status_callback=status_callback)
        if _stop():
            return []
        logger.info("  Found %d unique tokens from Telegram", len(tg_tokens))
        if status_callback:
            status_callback("telegram", f"Found {len(tg_tokens)} tokens", len(tg_tokens))

        if not tg_tokens:
            logger.warning("  No tokens found. Pipeline stopping.")
            return []

        total = len(tg_tokens)

        # ── Step 2+3: Parallel enrichment (DexScreener + GMGN) ────────
        logger.info("Step 2+3: Parallel enrichment (DexScreener + GMGN)...")
        if status_callback:
            status_callback("dexscreener", f"0/{total} enriched", 0, total)

        # Progress-tracking wrapper — tracks both DexScreener matches & GMGN enrichment
        def enrichment_progress(label: str):
            dex = sum(1 for t in tg_tokens if t.get("pair_address"))
            gmgn = sum(1 for t in tg_tokens if t.get("gmgn_score") is not None)
            if status_callback:
                status_callback("dexscreener",
                    f"Dex:{dex}/{total}  GMGN:{gmgn}",
                    max(dex, gmgn), total)

        await asyncio.gather(
            self._enrich_dexscreener(tg_tokens, enrichment_progress),
            self._enrich_gmgn(tg_tokens, enrichment_progress),
        )

        dex_matched = sum(1 for t in tg_tokens if t.get("pair_address"))
        gmgn_scored = sum(1 for t in tg_tokens if t.get("gmgn_score") is not None)
        logger.info("  Enrichment complete: Dex:%d/%d GMGN:%d", dex_matched, total, gmgn_scored)
        if status_callback:
            status_callback("dexscreener",
                f"Dex:{dex_matched}/{total}  GMGN:{gmgn_scored} ✓",
                max(dex_matched, gmgn_scored), total)

        # ── Step 3: Dedup ──────────────────────────────────────────────
        logger.info("Step 3: Dedup...")
        if status_callback:
            status_callback("dedup", f"Deduplicating {total} tokens...", total, total)
        deduped = self._dedup(tg_tokens)
        logger.info("  %d tokens after dedup", len(deduped))

        # ── Cleanup: remove unenriched tokens (no DexScreener pair found) ──
        before_clean = len(deduped)
        deduped = [t for t in deduped if t.get("pair_address")]
        logger.info("  %d tokens after removing unenriched (removed %d)", len(deduped), before_clean - len(deduped))
        if status_callback:
            status_callback("dedup", f"{len(deduped)} tokens (removed {before_clean - len(deduped)} unenriched)", len(deduped), total)

        # ── Step 4: Windowed Aggregation ───────────────────────────────
        logger.info("Step 4: Windowed aggregation (%s)...", window)
        if status_callback:
            status_callback("aggregate", f"Computing {window} window metrics for {len(deduped)} tokens...", len(deduped), total)
        for token in deduped:
            await self._aggregate_window(session, token, window, now)
        if status_callback:
            status_callback("aggregate", f"Windowed aggregation complete ({window})", len(deduped), total)

        # ── Step 5: Persist ────────────────────────────────────────────
        logger.info("Step 5: Persisting...")
        if status_callback:
            status_callback("persist", f"Saving {len(deduped)} tokens to database...", len(deduped), total)
        count = await self._persist(session, deduped, now)
        logger.info("  Saved %d tokens", count)
        if status_callback:
            status_callback("persist", f"Saved {count} tokens ✓", count, total)

        logger.info("Pipeline Complete: %d tokens persisted", count)
        return deduped

    # ── Step 1: Telegram ───────────────────────────────────────────────

    async def _scan_telegram(self, session: AsyncSession, now: datetime, window: str = "24h", status_callback=None) -> list[dict]:
        """Scan all Telegram groups in parallel and extract tokens with per-window social stats."""
        from telethon import TelegramClient
        from telethon.tl.types import Message, MessageEntityTextUrl
        from app.telegram_discovery.extractor import TokenExtractor
        from app.telegram_discovery.models import TelegramSource

        result = await session.execute(
            select(TelegramSource).where(TelegramSource.enabled == True)
        )
        sources = result.scalars().all()
        if not sources:
            return []

        telethon = TelegramClient(
            settings.TELEGRAM_SESSION_NAME or "telegram_discovery",
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
        )
        await telethon.start()
        extractor = TokenExtractor()

        # Window deltas
        deltas = {"5m": timedelta(minutes=5), "1h": timedelta(hours=1),
                   "6h": timedelta(hours=6), "24h": timedelta(hours=24)}
        cutoff = now - deltas[window]

        # Shared token map (built by merging per-source results)
        merged_map: dict[str, dict] = {}
        sources_done = 0

        async def scan_one(source) -> dict[str, dict]:
            """Scan a single source, return local token_map."""
            nonlocal sources_done
            local_map: dict[str, dict] = {}
            try:
                entity = await telethon.get_entity(source.source_id)

                # Fetch messages within the time window
                all_messages: list = []
                max_id = 0
                while True:
                    batch = await telethon.get_messages(
                        entity, limit=500, offset_id=max_id
                    )
                    if not batch:
                        break

                    in_window: list = []
                    for m in batch:
                        if not m.date:
                            continue
                        msg_ts = m.date.replace(tzinfo=timezone.utc)
                        if msg_ts < cutoff:
                            break
                        in_window.append(m)

                    all_messages.extend(in_window)

                    if len(in_window) < len(batch):
                        break
                    max_id = batch[-1].id

                messages = all_messages
            except Exception:
                messages = []

            # Extract tokens from messages
            for msg in messages:
                if not isinstance(msg, Message) or not msg.message:
                    continue
                msg_ts = msg.date.replace(tzinfo=timezone.utc) if msg.date else now
                sender_id = str(msg.sender_id) if msg.sender_id else "unknown"
                text = self._get_full_text(msg)
                refs = extractor.extract(text)
                if not refs:
                    continue

                for ref in refs:
                    addr = ref.token_address
                    if not addr:
                        continue
                    chain = ref.chain or "solana"
                    if chain in ("sol",):
                        chain = "solana"
                    if chain in ("eth",):
                        chain = "ethereum"
                    key = f"{chain}:{addr}"

                    if key not in local_map:
                        local_map[key] = {
                            "chain": chain,
                            "token_address": addr,
                            "symbol": ref.symbol,
                            "name": None,
                            "group_count": 0,
                            "all_groups": set(),
                            "tg_mentions": 0,
                        }
                        for w in deltas:
                            local_map[key][f"_w_{w}_mentions"] = 0
                            local_map[key][f"_w_{w}_users"] = set()
                            local_map[key][f"_w_{w}_groups"] = set()
                            local_map[key][f"_w_{w}_reactions"] = 0
                            local_map[key][f"_w_{w}_replies"] = 0

                    t = local_map[key]
                    t["all_groups"].add(source.name)
                    t["tg_mentions"] += 1

                    # Per-message social stats
                    reactions = getattr(msg, 'reactions', None)
                    reactions_count = 0
                    if reactions and hasattr(reactions, 'results') and reactions.results:
                        reactions_count = sum(r.count for r in reactions.results)
                    replies_count = getattr(msg, 'replies', None)
                    replies_count = replies_count.replies if replies_count and hasattr(replies_count, 'replies') else 0

                    for w, delta in deltas.items():
                        if msg_ts >= now - delta:
                            t[f"_w_{w}_mentions"] += 1
                            t[f"_w_{w}_users"].add(sender_id)
                            t[f"_w_{w}_groups"].add(source.name)
                            t[f"_w_{w}_reactions"] += reactions_count
                            t[f"_w_{w}_replies"] += replies_count

            # Merge local map into shared merged_map
            for key, local_t in local_map.items():
                if key in merged_map:
                    mt = merged_map[key]
                    mt["tg_mentions"] += local_t["tg_mentions"]
                    mt["all_groups"] |= local_t["all_groups"]
                    for w in deltas:
                        mt[f"_w_{w}_mentions"] += local_t[f"_w_{w}_mentions"]
                        mt[f"_w_{w}_users"] |= local_t[f"_w_{w}_users"]
                        mt[f"_w_{w}_groups"] |= local_t[f"_w_{w}_groups"]
                        mt[f"_w_{w}_reactions"] += local_t[f"_w_{w}_reactions"]
                        mt[f"_w_{w}_replies"] += local_t[f"_w_{w}_replies"]
                else:
                    merged_map[key] = local_t

            sources_done += 1
            if status_callback:
                status_callback("telegram",
                    f"{source.name}: {len(messages)} msgs, {len(merged_map)} tokens total",
                    len(merged_map))
            return local_map

        # Scan all sources in parallel (up to 5 concurrent)
        await asyncio.gather(*[scan_one(s) for s in sources])

        await telethon.disconnect()

        # Finalize: collapse sets to counts
        result_list = []
        for t in merged_map.values():
            t["group_count"] = len(t.pop("all_groups"))
            for w in deltas:
                t[f"tg_mentions_{w}"] = t.pop(f"_w_{w}_mentions")
                t[f"tg_users_{w}"] = len(t.pop(f"_w_{w}_users"))
                t[f"tg_groups_{w}"] = len(t.pop(f"_w_{w}_groups"))
                t[f"tg_reactions_{w}"] = t.pop(f"_w_{w}_reactions")
                t[f"tg_replies_{w}"] = t.pop(f"_w_{w}_replies")
            result_list.append(t)

        return result_list

    @staticmethod
    def _get_full_text(msg) -> str:
        from telethon.tl.types import MessageEntityTextUrl
        text = (msg.message or "").strip()
        if not text or not msg.entities:
            return text
        urls = []
        for ent in msg.entities:
            if isinstance(ent, MessageEntityTextUrl):
                urls.append(ent.url)
        if urls:
            text = text + "\n" + "\n".join(urls)
        return text.strip()

    # ── Step 2: DexScreener (batch, rate-limited) ──────────────────

    async def _enrich_dexscreener(self, tokens: list[dict], progress_cb=None):
        """Enrich tokens using DexScreener batch endpoint with rate limiting.

        Supports all chains DexScreener covers: solana, ethereum, bsc, base,
        polygon, arbitrum, optimism, avalanche, fantom, etc.
        """
        if not tokens:
            return
        if not self._dex_client:
            self._dex_client = httpx.AsyncClient(timeout=30.0)

        # Group tokens by chain (map our chain names to DexScreener's)
        CHAIN_MAP = {
            "solana": "solana", "sol": "solana",
            "ethereum": "ethereum", "eth": "ethereum",
            "bsc": "bsc", "bnb": "bsc",
            "base": "base",
            "polygon": "polygon", "matic": "polygon",
            "arbitrum": "arbitrum", "arb": "arbitrum",
            "optimism": "optimism", "op": "optimism",
            "avalanche": "avalanche", "avax": "avalanche",
            "fantom": "fantom", "ftm": "fantom",
        }

        chain_groups: dict[str, list[dict]] = {}
        for t in tokens:
            chain = t.get("chain", "solana")
            ds_chain = CHAIN_MAP.get(chain, chain)
            chain_groups.setdefault(ds_chain, []).append(t)

        BATCH_SIZE = 30
        RATE_LIMIT_DELAY = 1.2
        MAX_RETRIES = 3

        for ds_chain, chain_tokens in chain_groups.items():
            addrs = [t["token_address"] for t in chain_tokens]
            addr_to_idx = {addr: i for i, addr in enumerate(addrs)}

            for i in range(0, len(addrs), BATCH_SIZE):
                batch = addrs[i : i + BATCH_SIZE]
                addr_list = ",".join(batch)

                for attempt in range(MAX_RETRIES):
                    try:
                        resp = await self._dex_client.get(
                            f"{DEXSCREENER_PAIRS_URL}/{ds_chain}/{addr_list}"
                        )
                        if resp.status_code == 429:
                            wait = (2 ** attempt) * 2
                            logger.debug("DexScreener 429, retry %d/%d in %ds",
                                         attempt + 1, MAX_RETRIES, wait)
                            await asyncio.sleep(wait)
                            continue
                        resp.raise_for_status()
                        pairs = resp.json() if isinstance(resp.json(), list) else []

                        for p in pairs:
                            base = p.get("baseToken", {})
                            addr = base.get("address")
                            if not addr:
                                continue

                            idx = addr_to_idx.get(addr)
                            if idx is None:
                                continue
                            token = chain_tokens[idx]

                            token["symbol"] = token.get("symbol") or base.get("symbol")
                            token["name"] = base.get("name")
                            token["dex_url"] = p.get("url")
                            token["pair_address"] = p.get("pairAddress")
                            token["dex_id"] = p.get("dexId")

                            # Price
                            price = float(p.get("priceUsd", 0) or 0)
                            for w in ("5m", "1h", "6h", "24h"):
                                token[f"price_{w}"] = price

                            # Time-windowed metrics
                            pc = p.get("priceChange", {})
                            vol = p.get("volume", {})
                            for w, wk in [("5m", "m5"), ("1h", "h1"), ("6h", "h6"), ("24h", "h24")]:
                                txns = p.get("txns", {}).get(wk, {})
                                token[f"price_change_{w}"] = pc.get(wk)
                                token[f"volume_{w}"] = vol.get(wk)
                                token[f"buys_{w}"] = txns.get("buys")
                                token[f"sells_{w}"] = txns.get("sells")
                                token[f"trades_{w}"] = (txns.get("buys") or 0) + (txns.get("sells") or 0)

                            liq = p.get("liquidity", {})
                            for w in ("5m", "1h", "6h", "24h"):
                                token[f"liquidity_{w}"] = liq.get("usd")
                            for w in ("5m", "1h", "6h", "24h"):
                                token[f"market_cap_{w}"] = p.get("marketCap")

                        break  # success

                    except Exception as e:
                        logger.debug("DexScreener batch error (try %d): %s", attempt + 1, e)
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(2)
                        else:
                            logger.warning("DexScreener batch failed after %d retries", MAX_RETRIES)

                await asyncio.sleep(RATE_LIMIT_DELAY)
                # Report progress after each batch
                if progress_cb:
                    progress_cb("DexScreener")

            # Fallback: search API for tokens not found via batch endpoint
            unmatched = [t for t in chain_tokens if not t.get("pair_address")]
            if unmatched:
                logger.debug("  Search-fallback for %d unmatched tokens on %s", len(unmatched), ds_chain)
            for token in unmatched[:50]:  # limit search fallback to 50 per chain
                addr = token.get("token_address")
                if not addr:
                    continue
                try:
                    resp = await self._dex_client.get(
                        f"{DEXSCREENER_SEARCH_URL}", params={"q": addr}
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    search_pairs = data.get("pairs", [])
                    for p in search_pairs:
                        base = p.get("baseToken", {})
                        # Match: token address OR pair address (Telegram may catch pair URLs)
                        matched = base.get("address") == addr
                        is_pair_addr = p.get("pairAddress") == addr
                        if not matched and not is_pair_addr:
                            continue
                        if is_pair_addr and not matched:
                            # Our "token" is actually a pair address — use real token
                            token["token_address"] = base.get("address")
                            token["symbol"] = token.get("symbol") or base.get("symbol")
                        else:
                            token["symbol"] = token.get("symbol") or base.get("symbol")
                        token["name"] = base.get("name")
                        token["dex_url"] = p.get("url")
                        token["pair_address"] = p.get("pairAddress")
                        token["dex_id"] = p.get("dexId")
                        price = float(p.get("priceUsd", 0) or 0)
                        for w in ("5m", "1h", "6h", "24h"):
                            token[f"price_{w}"] = price
                        pc = p.get("priceChange", {})
                        vol = p.get("volume", {})
                        for w, wk in [("5m", "m5"), ("1h", "h1"), ("6h", "h6"), ("24h", "h24")]:
                            txns = p.get("txns", {}).get(wk, {})
                            token[f"price_change_{w}"] = pc.get(wk)
                            token[f"volume_{w}"] = vol.get(wk)
                            token[f"buys_{w}"] = txns.get("buys")
                            token[f"sells_{w}"] = txns.get("sells")
                            token[f"trades_{w}"] = (txns.get("buys") or 0) + (txns.get("sells") or 0)
                        liq = p.get("liquidity", {})
                        for w in ("5m", "1h", "6h", "24h"):
                            token[f"liquidity_{w}"] = liq.get("usd")
                        for w in ("5m", "1h", "6h", "24h"):
                            token[f"market_cap_{w}"] = p.get("marketCap")
                        if progress_cb:
                            progress_cb("DexScreener")
                        break  # first matching pair
                    await asyncio.sleep(0.3)  # rate limit for search API
                except Exception:
                    pass

    # ── Step 3: GMGN ───────────────────────────────────────────────────

    async def _enrich_gmgn(self, tokens: list[dict], progress_cb=None):
        """Enrich via GMGN OpenAPI. Uses X-APIKEY header + timestamp + client_id.
        Skips if API key missing. Only processes Solana tokens."""
        api_key = settings.GMGN_API_KEY
        if not api_key:
            logger.info("  GMGN skipped: no API key")
            return

        import uuid as _uuid

        if not self._gmgn_client:
            self._gmgn_client = httpx.AsyncClient(
                timeout=10.0,
                headers={
                    "X-APIKEY": api_key,
                    "Accept": "application/json",
                },
                base_url="https://openapi.gmgn.ai",
            )

        # Only process Solana tokens sent to GMGN
        solana_tokens = [t for t in tokens if t.get("chain", "solana") in ("solana", "sol")]
        if not solana_tokens:
            return

        # Rate limit: 1 req/s (GMGN default)
        for i, token in enumerate(solana_tokens):
            addr = token.get("token_address")
            chain = token.get("chain", "solana")
            if not addr:
                continue
            try:
                ts = int(__import__("time").time())
                cid = str(_uuid.uuid4())
                resp = await self._gmgn_client.get(
                    "/v1/token/info",
                    params={
                        "chain": "sol" if chain in ("solana", "sol") else chain,
                        "address": addr,
                        "timestamp": ts,
                        "client_id": cid,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        info = data.get("data", {})
                        token["gmgn_score"] = info.get("score")
                        token["gmgn_hot_level"] = info.get("hot_level")
                elif resp.status_code == 429:
                    await asyncio.sleep(2)  # rate limit backoff
            except Exception as e:
                logger.debug("GMGN enrich failed for %s: %s", addr[:12], e)
            await asyncio.sleep(0.2)  # gentle rate limiting
            if progress_cb and i % 5 == 0:
                progress_cb(f"GMGN {i+1}/{len(solana_tokens)}")

    # ── Step 4: Dedup ──────────────────────────────────────────────────

    def _dedup(self, tokens: list[dict]) -> list[dict]:
        seen: set[str] = set()
        result = []
        for t in tokens:
            key = f"{t.get('chain')}:{t.get('token_address')}"
            if key in seen:
                for existing in result:
                    ek = f"{existing.get('chain')}:{existing.get('token_address')}"
                    if ek == key:
                        existing["tg_mentions"] = (existing.get("tg_mentions", 0) + t.get("tg_mentions", 0))
                        for w in ("5m", "1h", "6h", "24h"):
                            existing[f"tg_mentions_{w}"] = (existing.get(f"tg_mentions_{w}", 0) + t.get(f"tg_mentions_{w}", 0))
                            existing[f"tg_users_{w}"] = max(existing.get(f"tg_users_{w}", 0), t.get(f"tg_users_{w}", 0))
                            existing[f"tg_groups_{w}"] = max(existing.get(f"tg_groups_{w}", 0), t.get(f"tg_groups_{w}", 0))
                            existing[f"tg_reactions_{w}"] = (existing.get(f"tg_reactions_{w}", 0) + t.get(f"tg_reactions_{w}", 0))
                            existing[f"tg_replies_{w}"] = (existing.get(f"tg_replies_{w}", 0) + t.get(f"tg_replies_{w}", 0))
                        existing["group_count"] = max(existing.get("group_count", 0), t.get("group_count", 0))
                        break
                continue
            seen.add(key)
            result.append(t)
        return result

    # ── Step 5: Windowed Aggregation (TG stats already in token dicts) ─

    async def _aggregate_window(self, session: AsyncSession, token: dict, window: str, now: datetime):
        """No-op: TG window stats already captured during Telegram scan."""
        pass

    # ── Step 6: Persist ────────────────────────────────────────────────

    async def _persist(self, session: AsyncSession, tokens: list[dict], now: datetime) -> int:
        saved = 0
        with session.no_autoflush:
            for t in tokens:
                addr = t.get("token_address")
                chain = t.get("chain", "solana")
                if not addr:
                    continue

                data = {
                    "chain": chain, "token_address": addr,
                    "symbol": t.get("symbol"), "name": t.get("name"),
                    "dex_url": t.get("dex_url"), "pair_address": t.get("pair_address"),
                    "dex_id": t.get("dex_id"),
                    "gmgn_score": t.get("gmgn_score"), "gmgn_hot_level": t.get("gmgn_hot_level"),
                    "group_count": t.get("group_count", 0),
                    "last_seen_at": now,
                }
                for w in ("5m", "1h", "6h", "24h"):
                    for field in ("price", "price_change", "volume", "buys", "sells", "trades",
                                  "liquidity", "market_cap"):
                        key = f"{field}_{w}"
                        if key in t:
                            data[key] = t[key]
                    for field in ("tg_mentions", "tg_users", "tg_groups", "tg_reactions", "tg_replies"):
                        key = f"{field}_{w}"
                        if key in t:
                            data[key] = t[key]

                # Upsert — only overwrite fields that have actual values
                stmt = pg_insert(UnifiedToken).values(**data)
                update_cols = {
                    k: stmt.excluded[k]
                    for k in data
                    if k not in ("chain", "token_address") and data[k] is not None
                }
                stmt = stmt.on_conflict_do_update(
                    index_elements=["chain", "token_address"],
                    set_=update_cols,
                )
                await session.execute(stmt)
                saved += 1

        await session.commit()
        return saved


# Singleton
pipeline = UnifiedPipeline()
