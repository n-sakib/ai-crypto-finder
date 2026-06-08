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
import re
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
GMGN_TRENDING_URL = "https://gmgn.ai/defi/quotation/v1/rank/sol/swaps"
GMGN_ENRICHMENT_LIMITS = {
    "5m": 60,
    "1h": 80,
    "6h": 100,
    "24h": 150,
}


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
            status_callback("telegram", f"Found {len(tg_tokens)} unique tokens", len(tg_tokens), len(tg_tokens))

        total = len(tg_tokens)

        # ── Step 2: Discover trending tokens (DexScreener boosted + GMGN trending) ─
        logger.info("Step 2: Fetching trending tokens (DexScreener + GMGN)...")
        if status_callback:
            status_callback("trending", "Fetching DexScreener boosted & GMGN trending...")
        trending_tokens = await self._fetch_trending_tokens(now, window)
        logger.info("  Found %d trending tokens (DexScreener + GMGN)", len(trending_tokens))

        # Merge trending tokens into tg_tokens (update flags on existing, add new)
        tg_map: dict[str, dict] = {f"{t.get('chain')}:{t.get('token_address')}": t for t in tg_tokens}
        for tt in trending_tokens:
            key = f"{tt.get('chain')}:{tt.get('token_address')}"
            if key in tg_map:
                # Update flags on existing token
                existing = tg_map[key]
                if tt.get("is_dexscreener_trending"):
                    existing["is_dexscreener_trending"] = True
                if tt.get("is_dexscreener_boosted"):
                    existing["is_dexscreener_boosted"] = True
                if tt.get("is_gmgn_trending"):
                    existing["is_gmgn_trending"] = True
                self._merge_source_values(existing, tt)
                # Merge source groups
                for sg in tt.get("source_groups", []):
                    if sg not in existing.get("source_groups", []):
                        existing.setdefault("source_groups", []).append(sg)
                for dm in tt.get("discovery_methods", []):
                    if dm not in existing.get("discovery_methods", []):
                        existing.setdefault("discovery_methods", []).append(dm)
            else:
                tg_tokens.append(tt)
                tg_map[key] = tt
        logger.info("  Total tokens after merging trending: %d", len(tg_tokens))
        if status_callback:
            status_callback("trending", f"{len(trending_tokens)} trending + {len(tg_tokens)} total", len(tg_tokens), len(tg_tokens))

        total = len(tg_tokens)  # Update total after merging trending

        if not tg_tokens:
            logger.warning("  No Telegram or trending tokens found. Pipeline stopping.")
            return []

        # ── Step 3+4: Parallel enrichment (DexScreener + GMGN) ────────
        logger.info("Step 3+4: Parallel enrichment (DexScreener + GMGN)...")
        if status_callback:
            status_callback("dexscreener", f"0/{total} enriched", 0, total)

        gmgn_total = min(
            GMGN_ENRICHMENT_LIMITS.get(window, 100),
            sum(1 for t in tg_tokens if t.get("chain", "solana") in ("solana", "sol")),
        )
        dex_checked = 0
        gmgn_checked = 0

        # Progress-tracking wrapper — tracks both DexScreener matches & GMGN enrichment.
        def enrichment_progress(label: str):
            nonlocal dex_checked, gmgn_checked
            if label.startswith("DexScreener "):
                try:
                    dex_checked = int(label.split(" ", 1)[1].split("/", 1)[0])
                except (IndexError, ValueError):
                    pass
            if label.startswith("GMGN "):
                try:
                    gmgn_checked = int(label.split(" ", 1)[1].split("/", 1)[0])
                except (IndexError, ValueError):
                    pass
            dex = sum(1 for t in tg_tokens if t.get("pair_address"))
            gmgn = sum(1 for t in tg_tokens if t.get("gmgn_score") is not None)
            if status_callback:
                status_callback("dexscreener",
                    f"Dex matched:{dex} checked:{dex_checked}/{total}  GMGN scored:{gmgn} checked:{gmgn_checked}/{gmgn_total}",
                    max(dex_checked, gmgn_checked, dex, gmgn), total)

        await asyncio.gather(
            self._enrich_dexscreener(tg_tokens, enrichment_progress, should_stop=_stop),
            self._enrich_gmgn(tg_tokens, enrichment_progress, should_stop=_stop, window=window),
        )
        if _stop():
            return []

        dex_matched = sum(1 for t in tg_tokens if t.get("pair_address"))
        gmgn_scored = sum(1 for t in tg_tokens if t.get("gmgn_score") is not None)
        logger.info("  Enrichment complete: Dex:%d/%d GMGN:%d", dex_matched, total, gmgn_scored)
        if status_callback:
            status_callback("dexscreener",
                f"Dex matched:{dex_matched} checked:{total}/{total}  GMGN scored:{gmgn_scored} checked:{gmgn_checked}/{gmgn_total} ✓",
                max(dex_matched, gmgn_scored), total)

        # ── Step 3: Dedup ──────────────────────────────────────────────
        logger.info("Step 3: Dedup...")
        if status_callback:
            status_callback("dedup", f"Deduplicating {total} tokens...", total, total)
        deduped = self._dedup(tg_tokens)
        logger.info("  %d tokens after dedup", len(deduped))

        # ── Cleanup: remove unenriched tokens (no pair & not trending/boosted) ──
        before_clean = len(deduped)
        deduped = [t for t in deduped if t.get("pair_address") or t.get("is_dexscreener_trending") or t.get("is_dexscreener_boosted") or t.get("is_gmgn_trending")]
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
        source_total = len(sources)

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
        messages_scanned = 0

        async def scan_one(source) -> dict[str, dict]:
            """Scan a single source, return local token_map."""
            nonlocal sources_done, messages_scanned
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
            messages_scanned += len(messages)
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
                    f"Sources:{sources_done}/{source_total}  messages:{messages_scanned}  unique tokens:{len(merged_map)}  last:{source.name}",
                    sources_done, source_total)
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

    async def _enrich_dexscreener(self, tokens: list[dict], progress_cb=None, should_stop=None):
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
        dex_checked = 0
        dex_total = len(tokens)

        for ds_chain, chain_tokens in chain_groups.items():
            if should_stop and should_stop():
                return
            addrs = [t["token_address"] for t in chain_tokens]
            addr_to_idx = {addr: i for i, addr in enumerate(addrs)}

            for i in range(0, len(addrs), BATCH_SIZE):
                if should_stop and should_stop():
                    return
                batch = addrs[i : i + BATCH_SIZE]
                addr_list = ",".join(batch)

                for attempt in range(MAX_RETRIES):
                    if should_stop and should_stop():
                        return
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
                dex_checked += len(batch)
                if progress_cb:
                    progress_cb(f"DexScreener {dex_checked}/{dex_total}")

            # Fallback: search API for tokens not found via batch endpoint
            unmatched = [t for t in chain_tokens if not t.get("pair_address")]
            if unmatched:
                logger.debug("  Search-fallback for %d unmatched tokens on %s", len(unmatched), ds_chain)
            for token in unmatched[:50]:  # limit search fallback to 50 per chain
                if should_stop and should_stop():
                    return
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
                            progress_cb(f"DexScreener {dex_checked}/{dex_total}")
                        break  # first matching pair
                    await asyncio.sleep(0.3)  # rate limit for search API
                except Exception:
                    pass

    # ── Step 3: GMGN ───────────────────────────────────────────────────

    async def _enrich_gmgn(self, tokens: list[dict], progress_cb=None, should_stop=None, window: str = "24h"):
        """Enrich via GMGN OpenAPI. Uses X-APIKEY header + timestamp + client_id.
        Skips if API key missing. Only processes Solana tokens."""
        api_key = settings.GMGN_API_KEY
        if not api_key:
            logger.info("  GMGN skipped: no API key")
            return

        import uuid as _uuid

        # Use a dedicated OpenAPI client (separate from the trending client)
        gmgn_openapi = httpx.AsyncClient(
            timeout=10.0,
            headers={
                "X-APIKEY": api_key,
                "Accept": "application/json",
            },
            base_url="https://openapi.gmgn.ai",
        )

        # Only process Solana tokens sent to GMGN
        solana_tokens = [t for t in tokens if t.get("chain", "solana") in ("solana", "sol")]
        solana_tokens = self._prioritize_gmgn_tokens(solana_tokens, window)
        if not solana_tokens:
            return

        # Rate limit: 1 req/s (GMGN default)
        for i, token in enumerate(solana_tokens):
            if should_stop and should_stop():
                return
            addr = token.get("token_address")
            chain = token.get("chain", "solana")
            if not addr:
                continue
            try:
                ts = int(__import__("time").time())
                cid = str(_uuid.uuid4())
                resp = await gmgn_openapi.get(
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
            if progress_cb:
                progress_cb(f"GMGN {i+1}/{len(solana_tokens)}")

    # ── Step 4: Dedup ──────────────────────────────────────────────────

    @staticmethod
    def _prioritize_gmgn_tokens(tokens: list[dict], window: str) -> list[dict]:
        """Keep GMGN OpenAPI enrichment bounded so large windows can finish."""
        limit = GMGN_ENRICHMENT_LIMITS.get(window, 100)
        if len(tokens) <= limit:
            return tokens

        def score(token: dict) -> tuple:
            source_priority = int(bool(
                token.get("is_gmgn_trending")
                or token.get("is_dexscreener_trending")
                or token.get("is_dexscreener_boosted")
            ))
            return (
                source_priority,
                token.get(f"tg_mentions_{window}") or token.get("tg_mentions") or 0,
                token.get(f"tg_groups_{window}") or token.get("group_count") or 0,
                token.get(f"tg_users_{window}") or 0,
            )

        return sorted(tokens, key=score, reverse=True)[:limit]

    def _dedup(self, tokens: list[dict]) -> list[dict]:
        seen: set[str] = set()
        result = []
        for t in tokens:
            key = self._dedup_key(t)
            if key in seen:
                for existing in result:
                    ek = self._dedup_key(existing)
                    if ek == key:
                        self._merge_token(existing, t)
                        break
                continue
            seen.add(key)
            result.append(t)
        return result

    @staticmethod
    def _dedup_key(token: dict) -> str:
        chain = token.get("chain") or "solana"
        if chain == "sol":
            chain = "solana"
        elif chain == "eth":
            chain = "ethereum"
        return f"{chain}:{token.get('token_address') or ''}"

    @staticmethod
    def _merge_list_field(existing: dict, field: str, values: list) -> None:
        current = existing.setdefault(field, [])
        for value in values or []:
            if value not in current:
                current.append(value)

    def _merge_token(self, existing: dict, incoming: dict) -> None:
        """Merge duplicate token records without losing discovery flags or metrics."""
        for field in ("is_dexscreener_trending", "is_dexscreener_boosted", "is_gmgn_trending"):
            existing[field] = bool(existing.get(field) or incoming.get(field))

        self._merge_source_values(existing, incoming)
        self._merge_list_field(existing, "source_groups", incoming.get("source_groups", []))
        self._merge_list_field(existing, "discovery_methods", incoming.get("discovery_methods", []))

        for field in (
            "symbol", "name", "dex_url", "pair_address", "dex_id",
            "gmgn_score", "gmgn_hot_level",
        ):
            if incoming.get(field) is not None and existing.get(field) is None:
                existing[field] = incoming[field]

        existing["tg_mentions"] = existing.get("tg_mentions", 0) + incoming.get("tg_mentions", 0)
        existing["group_count"] = max(existing.get("group_count", 0), incoming.get("group_count", 0))

        for w in ("5m", "1h", "6h", "24h"):
            existing[f"tg_mentions_{w}"] = existing.get(f"tg_mentions_{w}", 0) + incoming.get(f"tg_mentions_{w}", 0)
            existing[f"tg_users_{w}"] = max(existing.get(f"tg_users_{w}", 0), incoming.get(f"tg_users_{w}", 0))
            existing[f"tg_groups_{w}"] = max(existing.get(f"tg_groups_{w}", 0), incoming.get(f"tg_groups_{w}", 0))
            existing[f"tg_reactions_{w}"] = existing.get(f"tg_reactions_{w}", 0) + incoming.get(f"tg_reactions_{w}", 0)
            existing[f"tg_replies_{w}"] = existing.get(f"tg_replies_{w}", 0) + incoming.get(f"tg_replies_{w}", 0)

            for field in ("price", "price_change", "volume", "buys", "sells", "trades", "liquidity", "market_cap"):
                key = f"{field}_{w}"
                if incoming.get(key) is not None and existing.get(key) is None:
                    existing[key] = incoming[key]

    @staticmethod
    def _merge_source_values(existing: dict, incoming: dict) -> None:
        for field in ("dexscreener_trending_rank", "gmgn_trending_rank"):
            incoming_value = incoming.get(field)
            if incoming_value is None:
                continue
            existing_value = existing.get(field)
            existing[field] = incoming_value if existing_value is None else min(existing_value, incoming_value)

        for field in ("dexscreener_boost_amount", "dexscreener_boost_total"):
            incoming_value = incoming.get(field)
            if incoming_value is None:
                continue
            existing_value = existing.get(field)
            existing[field] = incoming_value if existing_value is None else max(existing_value, incoming_value)

    # ── Step 2: Trending Discovery ────────────────────────────────────

    async def _fetch_trending_tokens(self, now: datetime, window: str) -> list[dict]:
        """Fetch DexScreener trending + boosted tokens and GMGN trending tokens.
        These come pre-enriched with price/volume/liquidity data."""
        trending: list[dict] = []
        seen: dict[str, dict] = {}  # key → token dict for dedup across sources

        if not self._dex_client:
            self._dex_client = httpx.AsyncClient(timeout=30.0)

        # ── DexScreener Trending Tokens (WebSocket io.dexscreener.com) ──
        try:
            ws_tokens = await self._fetch_trending_ws()
            logger.info("  DexScreener trending (WebSocket): %d tokens", len(ws_tokens))
            for token in ws_tokens:
                key = self._dedup_key(token)
                if key not in seen:
                    seen[key] = token
                    trending.append(token)
        except Exception as e:
            logger.warning("DexScreener trending WebSocket failed: %s", e)

        # ── DexScreener Boosted Tokens ──────────────────────────────────
        try:
            resp = await self._dex_client.get("https://api.dexscreener.com/token-boosts/latest/v1")
            resp.raise_for_status()
            boosts = resp.json() if isinstance(resp.json(), list) else []
            logger.info("  DexScreener boosted: %d tokens", len(boosts))

            for boost in boosts[:30]:
                chain = boost.get("chainId", "solana")
                addr = boost.get("tokenAddress", "")
                if not addr:
                    continue

                key = self._dedup_key({"chain": chain, "token_address": addr})
                if key in seen:
                    existing = seen[key]
                    existing["is_dexscreener_boosted"] = True
                    existing["dexscreener_boost_amount"] = boost.get("amount")
                    existing["dexscreener_boost_total"] = boost.get("totalAmount")
                    self._merge_list_field(existing, "source_groups", ["dexscreener_boosted"])
                    self._merge_list_field(existing, "discovery_methods", ["dexscreener_boosted"])
                    continue

                token = await self._build_dex_token(chain, addr, boost, {
                    "is_dexscreener_trending": False,
                    "is_dexscreener_boosted": True,
                    "dexscreener_boost_amount": boost.get("amount"),
                    "dexscreener_boost_total": boost.get("totalAmount"),
                    "source_groups": ["dexscreener_boosted"],
                    "discovery_methods": ["dexscreener_boosted"],
                })
                if token:
                    seen[key] = token
                    trending.append(token)
                await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning("DexScreener boosted fetch failed: %s", e)

        # ── GMGN Trending Tokens ───────────────────────────────────────
        try:
            data = await self._fetch_gmgn_trending_payload(window=window, limit=30)
            gmgn_trending = data.get("data", {}).get("rank", []) if data.get("code") == 0 else []
            logger.info("  GMGN trending: %d tokens", len(gmgn_trending))

            for idx, token_data in enumerate(gmgn_trending[:30], start=1):
                addr = token_data.get("address", "")
                if not addr:
                    continue
                chain = token_data.get("chain", "sol")
                chain = "solana" if chain in ("sol", "solana") else chain

                token = {
                    "chain": chain,
                    "token_address": addr,
                    "symbol": token_data.get("symbol"),
                    "name": token_data.get("name"),
                    "pair_address": None,
                    "dex_url": f"https://gmgn.ai/sol/token/{addr}" if chain == "solana" else None,
                    "dex_id": None,
                    "is_dexscreener_trending": False,
                    "is_dexscreener_boosted": False,
                    "is_gmgn_trending": True,
                    "gmgn_trending_rank": token_data.get("rank") or idx,
                    "gmgn_score": token_data.get("score"),
                    "gmgn_hot_level": token_data.get("hot_level"),
                    "group_count": 0,
                    "source_groups": ["gmgn_trending"],
                    "discovery_methods": ["gmgn_trending"],
                    "tg_mentions": 0,
                }
                # GMGN already has price/volume
                price = float(token_data.get("price", 0) or 0)
                for w in ("5m", "1h", "6h", "24h"):
                    token[f"price_{w}"] = price
                    token[f"tg_mentions_{w}"] = 0
                    token[f"tg_users_{w}"] = 0
                    token[f"tg_groups_{w}"] = 0
                    token[f"tg_reactions_{w}"] = 0
                    token[f"tg_replies_{w}"] = 0

                token["volume_24h"] = token_data.get("volume_24h")
                token["liquidity_24h"] = token_data.get("liquidity")
                token["market_cap_24h"] = token_data.get("market_cap")
                token["price_change_5m"] = token_data.get("price_change_5m") or token_data.get("price_change_percent5m")
                token["price_change_1h"] = token_data.get("price_change_1h") or token_data.get("price_change_percent1h")
                token["price_change_24h"] = token_data.get("price_change_24h")
                token[f"volume_{window}"] = token_data.get("volume_24h") or token_data.get("volume")
                token[f"buys_{window}"] = token_data.get("buys_24h") or token_data.get("buys")
                token[f"sells_{window}"] = token_data.get("sells_24h") or token_data.get("sells")
                token[f"trades_{window}"] = token_data.get("swaps_24h") or token_data.get("swaps")
                token[f"liquidity_{window}"] = token_data.get("liquidity")
                token[f"market_cap_{window}"] = token_data.get("market_cap")
                if token_data.get("price_change_percent") is not None:
                    token[f"price_change_{window}"] = token_data.get("price_change_percent")

                key = self._dedup_key(token)
                if key in seen:
                    existing = seen[key]
                    self._merge_token(existing, token)
                else:
                    seen[key] = token
                    trending.append(token)
        except Exception as e:
            logger.warning("GMGN trending fetch failed: %s", e)

        return trending

    async def _fetch_gmgn_trending_payload(self, window: str, limit: int = 30) -> dict:
        """Fetch GMGN public trending data with browser impersonation when available."""
        params = {"limit": limit, "orderby": "swaps", "direction": "desc"}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://gmgn.ai",
            "Referer": "https://gmgn.ai/",
        }
        url = f"{GMGN_TRENDING_URL}/{window}"
        try:
            from curl_cffi import requests as curl_requests

            header_variants = [
                {"Referer": "https://gmgn.ai/trend?chain=sol", "Accept": "application/json, text/plain, */*"},
                {**headers, "Referer": "https://gmgn.ai/trend?chain=sol"},
                {**headers, "Referer": "https://gmgn.ai/"},
            ]
            last_error = None
            for attempt, request_headers in enumerate(header_variants, start=1):
                try:
                    resp = curl_requests.get(
                        url,
                        params=params,
                        headers=request_headers,
                        impersonate="chrome131",
                        timeout=30,
                    )
                    resp.raise_for_status()
                    return resp.json()
                except Exception as e:
                    last_error = e
                    logger.debug("GMGN trending attempt %d failed: %s", attempt, e)
                    await asyncio.sleep(0.5 * attempt)
            raise last_error
        except ImportError:
            logger.warning("curl_cffi missing; GMGN public trending may be blocked by Cloudflare")

        if not self._gmgn_client:
            self._gmgn_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    **headers,
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                },
            )
        resp = await self._gmgn_client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _build_dex_token(self, chain: str, addr: str, raw: dict, flags: dict) -> dict | None:
        """Build a token dict from DexScreener profile/boost data with pair enrichment."""
        try:
            pr = await self._dex_client.get(
                f"https://api.dexscreener.com/tokens/v1/{chain}/{addr}"
            )
            pairs = pr.json() if isinstance(pr.json(), list) else []
        except Exception:
            pairs = []

        pair = pairs[0] if pairs else None
        base = pair.get("baseToken", {}) if pair else {}
        pc = pair.get("priceChange", {}) if pair else {}
        vol = pair.get("volume", {}) if pair else {}
        liq = pair.get("liquidity", {}) if pair else {}
        txns = pair.get("txns", {}) if pair else {}

        token: dict = {
            "chain": "solana" if chain in ("solana", "sol") else chain,
            "token_address": addr,
            "symbol": base.get("symbol") or raw.get("name"),
            "name": base.get("name"),
            "pair_address": pair.get("pairAddress") if pair else raw.get("pairAddress"),
            "dex_url": pair.get("url") if pair else raw.get("url"),
            "dex_id": pair.get("dexId") if pair else None,
            "is_gmgn_trending": False,
            "group_count": 0,
            "tg_mentions": 0,
        }
        token.update(flags)

        price = float(pair.get("priceUsd", 0) or 0) if pair else 0
        for w in ("5m", "1h", "6h", "24h"):
            token[f"price_{w}"] = price
            token[f"tg_mentions_{w}"] = 0
            token[f"tg_users_{w}"] = 0
            token[f"tg_groups_{w}"] = 0
            token[f"tg_reactions_{w}"] = 0
            token[f"tg_replies_{w}"] = 0

        for w, wk in [("5m", "m5"), ("1h", "h1"), ("6h", "h6"), ("24h", "h24")]:
            txn = txns.get(wk, {}) if pair else {}
            token[f"price_change_{w}"] = pc.get(wk) if pair else None
            token[f"volume_{w}"] = vol.get(wk) if pair else None
            token[f"buys_{w}"] = txn.get("buys") if pair else None
            token[f"sells_{w}"] = txn.get("sells") if pair else None
            token[f"trades_{w}"] = ((txn.get("buys") or 0) + (txn.get("sells") or 0)) if pair else 0
            token[f"liquidity_{w}"] = liq.get("usd") if pair else None
            token[f"market_cap_{w}"] = pair.get("marketCap") if pair else None

        return token

    async def _fetch_trending_ws(self) -> list[dict]:
        """Fetch trending tokens from DexScreener WebSocket + REST API using curl_cffi."""
        tokens: list[dict] = []
        try:
            from curl_cffi.requests import AsyncSession

            ws_url = "wss://io.dexscreener.com/dex/screener/v5/pairs/h24/1?rankBy[key]=trendingScoreH6&rankBy[order]=desc"
            session = AsyncSession(impersonate="chrome131")

            try:
                ws = await session.ws_connect(ws_url, headers={
                    "Origin": "https://dexscreener.com",
                })
                raw = b""
                # First message contains all trending data (no need to loop)
                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    # data is (bytes, int) tuple from curl_cffi
                    chunk = data[0] if isinstance(data, tuple) else data
                    if isinstance(chunk, bytes):
                        raw = chunk
                    elif isinstance(chunk, str):
                        raw = chunk.encode("utf-8", errors="replace")
                except asyncio.TimeoutError:
                    pass

                if raw:
                    # Decode binary stream
                    decoded = "".join(chr(b) if 32 <= b <= 126 else " " for b in raw)

                    # ETH addresses: 0x + 40 hex
                    eth_raw: list[str] = []
                    for m in re.finditer(r"0x[0-9a-fA-F]{40}", decoded):
                        eth_raw.append(m.group(0))

                    # Pump.fun: find "pump" then backtrack to get the full address
                    pump_raw: list[str] = []
                    for m in re.finditer(r"pump", decoded):
                        end = m.end()
                        start = end - 44
                        if start < 0:
                            start = 0
                        prefix = decoded[start:end]
                        addr_match = re.search(r"[a-zA-Z0-9]+pump$", prefix)
                        if addr_match:
                            addr = addr_match.group(0)
                            if 16 <= len(addr) <= 44:
                                pump_raw.append(addr)

                    # Standard Solana: 43-44 char base58
                    sol_raw: list[str] = []
                    for m in re.finditer(r"[1-9A-HJ-NP-Za-km-z]{42,44}", decoded):
                        addr = m.group(0)
                        if not addr.endswith("pump") and not addr.startswith("0x"):
                            sol_raw.append(addr)

                    # Take proportional slices from each type (max 50 total)
                    eth_addrs = list(dict.fromkeys(eth_raw))
                    pump_addrs = list(dict.fromkeys(pump_raw))
                    sol_addrs = list(dict.fromkeys(sol_raw))
                    # 20 ETH + 15 pump + 15 sol = 50 max
                    addresses = eth_addrs[:20] + pump_addrs[:15] + sol_addrs[:15]
                    logger.info("  WebSocket extracted %d ETH + %d pump + %d sol = %d total",
                                len(eth_addrs), len(pump_addrs), len(sol_addrs), len(addresses))

                    # Batch-fetch pair data via REST API
                    if not self._dex_client:
                        self._dex_client = httpx.AsyncClient(timeout=30.0)

                    BATCH = 30
                    for i in range(0, len(addresses), BATCH):
                        batch = addresses[i : i + BATCH]
                        try:
                            resp = await self._dex_client.get(
                                f"https://api.dexscreener.com/latest/dex/tokens/{','.join(batch)}"
                            )
                            resp.raise_for_status()
                            data = resp.json()
                            pairs_list = data.get("pairs", []) if isinstance(data, dict) else []

                            for rank_idx, pair in enumerate(pairs_list, start=i + 1):
                                if not pair or not isinstance(pair, dict):
                                    continue
                                base = pair.get("baseToken", {})
                                addr = base.get("address", "")
                                chain = pair.get("chainId", "solana")
                                if not addr:
                                    continue
                                pc = pair.get("priceChange", {})
                                vol = pair.get("volume", {})
                                liq = pair.get("liquidity", {})
                                txns = pair.get("txns", {})
                                price = float(pair.get("priceUsd", 0) or 0)

                                token = {
                                    "chain": chain, "token_address": addr,
                                    "symbol": base.get("symbol"), "name": base.get("name"),
                                    "pair_address": pair.get("pairAddress"),
                                    "dex_url": pair.get("url"), "dex_id": pair.get("dexId"),
                                    "is_dexscreener_trending": True,
                                    "is_dexscreener_boosted": False,
                                    "is_gmgn_trending": False,
                                    "dexscreener_trending_rank": rank_idx,
                                    "group_count": 0,
                                    "source_groups": ["dexscreener_trending"],
                                    "discovery_methods": ["dexscreener_trending"],
                                    "tg_mentions": 0,
                                }
                                for w in ("5m", "1h", "6h", "24h"):
                                    token[f"price_{w}"] = price
                                    token[f"tg_mentions_{w}"] = 0
                                    token[f"tg_users_{w}"] = 0
                                    token[f"tg_groups_{w}"] = 0
                                    token[f"tg_reactions_{w}"] = 0
                                    token[f"tg_replies_{w}"] = 0
                                for w, wk in [("5m", "m5"), ("1h", "h1"), ("6h", "h6"), ("24h", "h24")]:
                                    txn = txns.get(wk, {})
                                    token[f"price_change_{w}"] = pc.get(wk)
                                    token[f"volume_{w}"] = vol.get(wk)
                                    token[f"buys_{w}"] = txn.get("buys")
                                    token[f"sells_{w}"] = txn.get("sells")
                                    token[f"trades_{w}"] = (txn.get("buys") or 0) + (txn.get("sells") or 0)
                                    token[f"liquidity_{w}"] = liq.get("usd")
                                    token[f"market_cap_{w}"] = pair.get("marketCap")

                                tokens.append(token)
                        except Exception as e:
                            logger.warning("DexScreener batch tokens fetch failed: %s", e)
                        await asyncio.sleep(0.5)
            finally:
                await session.close()
        except Exception as e:
            logger.warning("DexScreener WebSocket failed: %s", e)
        return tokens

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
                    "is_dexscreener_trending": t.get("is_dexscreener_trending", False),
                    "is_dexscreener_boosted": t.get("is_dexscreener_boosted", False),
                    "is_gmgn_trending": t.get("is_gmgn_trending", False),
                    "dexscreener_trending_rank": t.get("dexscreener_trending_rank"),
                    "dexscreener_boost_amount": t.get("dexscreener_boost_amount"),
                    "dexscreener_boost_total": t.get("dexscreener_boost_total"),
                    "gmgn_trending_rank": t.get("gmgn_trending_rank"),
                    "group_count": t.get("group_count", 0),
                    "source_groups": t.get("source_groups", []),
                    "discovery_methods": t.get("discovery_methods", []),
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
