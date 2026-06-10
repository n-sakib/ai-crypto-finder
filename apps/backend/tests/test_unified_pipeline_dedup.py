from datetime import datetime, timezone

from app.services.unified_pipeline import UnifiedPipeline


def test_dedup_merges_chain_aliases_and_canonicalizes_chain():
    pipeline = UnifiedPipeline()

    deduped = pipeline._dedup([
        {
            "chain": "sol",
            "token_address": "ABC123",
            "tg_mentions": 1,
            "source_groups": ["gmgn_trending"],
            "discovery_methods": ["gmgn_trending"],
            "is_gmgn_trending": True,
        },
        {
            "chain": "solana",
            "token_address": "ABC123",
            "tg_mentions": 2,
            "source_groups": ["telegram"],
            "discovery_methods": [],
            "pair_address": "PAIR1",
        },
    ])

    assert len(deduped) == 1
    assert deduped[0]["chain"] == "solana"
    assert deduped[0]["token_address"] == "ABC123"
    assert deduped[0]["tg_mentions"] == 3
    assert deduped[0]["is_gmgn_trending"] is True
    assert deduped[0]["pair_address"] == "PAIR1"
    assert deduped[0]["source_groups"] == ["gmgn_trending", "telegram"]


def test_dedup_merges_evm_addresses_case_insensitively():
    pipeline = UnifiedPipeline()

    deduped = pipeline._dedup([
        {
            "chain": "eth",
            "token_address": "0xABCDEF1234567890ABCDEF1234567890ABCDEF12",
            "tg_mentions": 1,
            "source_groups": ["a"],
            "discovery_methods": [],
        },
        {
            "chain": "ethereum",
            "token_address": "0xabcdef1234567890abcdef1234567890abcdef12",
            "tg_mentions": 2,
            "source_groups": ["b"],
            "discovery_methods": [],
        },
    ])

    assert len(deduped) == 1
    assert deduped[0]["chain"] == "ethereum"
    assert deduped[0]["token_address"] == "0xabcdef1234567890abcdef1234567890abcdef12"
    assert deduped[0]["tg_mentions"] == 3
    assert deduped[0]["source_groups"] == ["a", "b"]


def test_dedup_does_not_merge_missing_addresses():
    pipeline = UnifiedPipeline()

    deduped = pipeline._dedup([
        {"chain": "solana", "tg_mentions": 1, "source_groups": ["a"], "discovery_methods": []},
        {"chain": "solana", "tg_mentions": 2, "source_groups": ["b"], "discovery_methods": []},
    ])

    assert len(deduped) == 2


def test_dedup_preserves_best_source_flags_and_wallet_matches():
    pipeline = UnifiedPipeline()
    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 1, 2, tzinfo=timezone.utc)

    deduped = pipeline._dedup([
        {
            "chain": "solana",
            "token_address": "ABC123",
            "tg_mentions": 1,
            "source_groups": ["dexscreener_trending"],
            "discovery_methods": ["dexscreener_trending"],
            "is_dexscreener_trending": True,
            "dexscreener_trending_rank": 10,
            "gmgn_kol_count": 1,
            "gmgn_kol_buy_count": 1,
            "gmgn_kol_total_amount_usd": 100.0,
            "gmgn_kol_last_buy_at": older,
            "gmgn_kol_wallets": [{"maker": "wallet-a", "source": "kol"}],
        },
        {
            "chain": "solana",
            "token_address": "ABC123",
            "tg_mentions": 2,
            "source_groups": ["gmgn_smartmoney_buy"],
            "discovery_methods": ["gmgn_smartmoney_buy"],
            "dexscreener_trending_rank": 3,
            "gmgn_kol_count": 1,
            "gmgn_kol_buy_count": 2,
            "gmgn_kol_total_amount_usd": 250.0,
            "gmgn_kol_last_buy_at": newer,
            "gmgn_kol_wallets": [{"maker": "wallet-b", "source": "smartmoney"}],
        },
    ])

    assert len(deduped) == 1
    token = deduped[0]
    assert token["is_dexscreener_trending"] is True
    assert token["dexscreener_trending_rank"] == 3
    assert token["gmgn_kol_count"] == 1
    assert token["gmgn_kol_buy_count"] == 3
    assert token["gmgn_kol_total_amount_usd"] == 350.0
    assert token["gmgn_kol_last_buy_at"] == newer
    assert token["gmgn_kol_wallets"] == [
        {"maker": "wallet-a", "source": "kol"},
        {"maker": "wallet-b", "source": "smartmoney"},
    ]
