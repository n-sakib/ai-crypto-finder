# Telegram Token Discovery Service

## Overview

Monitors a curated list of Telegram alpha/trend groups and discovers crypto tokens being mentioned. Ranks discovered tokens by mention count, with unique users and group count as tie-breakers.

## Architecture

```
telegram_sources.yaml          ── Configuration file
    │
    ▼
TelegramClientService          ── Connects to Telegram via Telethon
    │
    ▼
TokenExtractor                 ── Extracts token identifiers from messages
    │
    ▼
TokenResolver                  ── Resolves identifiers to canonical tokens
    │
    ▼
TelegramDiscoveryAggregator    ── Aggregates mentions, produces rankings
    │
    ▼
API / CLI                      ── Exposes results
```

## Components

### 1. TelegramClientService
- Connects to Telegram using Telethon.
- Reads only new messages since last checkpoint (per source).
- Handles rate limits conservatively.
- Stores minimal message metadata (hashes, not raw text by default).
- Respects private group access controls.

### 2. TokenExtractor
Extracts from every message:
- **EVM contract addresses** (`0x` + 40 hex chars) — confidence: very_high
- **Solana addresses** (base58, 32-44 chars) — confidence: very_high
- **DEX links** (dexscreener, birdeye, gmgn, geckoterminal) — confidence: very_high
- **Cashtags** (`$SYMBOL`, 2-15 chars) — confidence: medium

### 3. TokenResolver
Converts extracted references into canonical `candidate_tokens` records:
- Contract addresses → immediate candidate creation
- DEX links → parsed for token/pair data
- Cashtags → only resolved if DEX API confirms match
- Token names → low priority, skipped

### 4. TelegramDiscoveryAggregator
For a configurable time window (default: 1 hour):
- Counts `mention_count` per token
- Counts `unique_user_count` (distinct sender hashes)
- Counts `group_count` (distinct sources)
- Ranks by mention_count DESC → unique_user_count DESC → group_count DESC → recency DESC
- Minimum filters: mention_count ≥ 5, unique_user_count ≥ 3

## Configuration

### Telegram API Credentials

Set in your `.env` file:
```bash
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
```

Get these from https://my.telegram.org/apps

### Source Configuration

Edit `apps/backend/telegram_sources.yaml` to add your groups:

```yaml
sources:
  - source_id: "my_alpha_group"
    name: "My Alpha Group"
    telegram_identifier: "@my_group_username"  # or numeric chat ID
    source_type: "alpha_group"
    enabled: true
```

Source types:
- `alpha_group` — Alpha call groups
- `trend_group` — Trend alert groups
- `meme_group` — Memecoin groups
- `trading_group` — Trading communities
- `chain_group` — Chain-specific groups (Solana, Base, etc.)

For private groups, use the numeric chat ID (e.g., `-1001234567890`) instead of @username.

## Data Stored

| Table | Purpose |
|-------|---------|
| `telegram_sources` | Configured groups/channels |
| `telegram_messages` | Message metadata (hashes, no raw text by default) |
| `candidate_tokens` | Canonical tokens (chain + address) |
| `telegram_token_mentions` | Individual mention events |
| `telegram_discovery_rankings` | Aggregated rankings per time window |

## What Gets Stored vs. What Does NOT

**Stored:**
- SHA-256 hash of message text (for deduplication)
- SHA-256 hash of sender ID (for unique user counting)
- Extracted token identifiers
- Token metadata (chain, address, symbol, name)
- Mention counts and rankings

**NOT stored by default:**
- Raw message text (configurable but off by default)
- Actual Telegram user IDs (only hashes)
- Private group invite links
- Message content beyond token identifiers

## API Endpoints

Run the backend server, then access at `/api/v1/telegram/`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/telegram/discovery` | GET | Top discovered tokens for a time window |
| `/api/v1/telegram/discovery/{chain}/{address}` | GET | Detail for a specific token |
| `/api/v1/telegram/sources` | GET | List configured sources |
| `/api/v1/telegram/discovery/stats` | GET | Discovery statistics |

### Query Parameters for `/discovery`

- `window` — Time window (default: `1h`, supports `30m`, `6h`, `24h`)
- `limit` — Max tokens (default: 100, max: 500)
- `min_mentions` — Minimum mention count (default: 5)
- `min_users` — Minimum unique users (default: 3)

## CLI Usage

### Collect Messages
```bash
cd apps/backend
python -m app.telegram_discovery.collect
```

### Rank Discovered Tokens
```bash
python -m app.telegram_discovery.rank --window 1h --limit 100
python -m app.telegram_discovery.rank --window 6h --limit 50 --json
```

Options:
- `--window`, `-w` — Time window (default: 1h)
- `--limit`, `-l` — Max tokens (default: 100)
- `--min-mentions` — Min mention count (default: 5)
- `--min-users` — Min unique users (default: 3)
- `--json` — Output as JSON

## Running Tests
```bash
cd apps/backend
pytest tests/test_telegram_discovery.py -v
```

## Database Migrations
```bash
cd apps/backend
alembic upgrade head
```

The migration `c8a1b2d3e4f5_telegram_discovery_tables.py` creates all required tables.

## What Is NOT Implemented

This service is **discovery only**. The following are explicitly not in scope:
- Velocity scoring or baselines
- Price data or DEX volume
- Holder growth tracking
- Smart wallet analysis
- Trading or buy/sell signals
- Complex spam scoring (only basic deduplication)
- Token names resolution (low confidence, skipped)
- Automated trading

## Spam Handling

Simple safeguards only:
- Ignore duplicate messages with same text_hash from same source in 10-minute window
- Ignore messages with no token identifiers
- Ignore unresolved cashtags
- Ignore token names (not resolved)

## Privacy & Compliance

- Only groups the user has authorized access to
- No bypass of private access controls
- Hashed sender IDs for privacy
- Configurable raw text storage (off by default)
- Telegram API usage respects Telegram's terms of service
