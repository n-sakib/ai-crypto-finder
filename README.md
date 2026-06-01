# AI Crypto Finder

A multi-layered AI-powered crypto trading signal system that discovers, validates, and ranks early-stage token opportunities across 17 analytical layers.

## Architecture

```
Discovery (7 sources)
  → Token Identity Resolver
    → Coin Age Classification
      → Safety Layer
        → Manipulation / Spam Filter
          → Attention Layer (Twitter, Telegram, Reddit)
            → Market Flow Layer
              → Adoption Layer
                → Liquidity Quality Layer
                  → Smart Money Layer
                    → Narrative Layer
                      → Price Compression Layer
                        → Risk Score Layer
                          → Early Momentum Score
                            → Ranking (Tier A/B/C/Excluded)
                              → Human Review
                                → Validation
```

## Layers

| # | Layer | Purpose | Update |
|---|-------|---------|--------|
| 1 | Discovery | Find candidates from 7 sources | 15m–daily |
| 2 | Token Identity | Prevent wrong/duplicate tokens | On discovery |
| 3 | Coin Age | Choose correct baseline by age | On discovery |
| 4 | Safety | Remove dangerous tokens | 6h |
| 5 | Manipulation Filter | Detect fake attention/volume | On demand |
| 6 | Attention | Measure real attention velocity | Hourly |
| 7 | Market Flow | Confirm real money entering | 15m |
| 8 | Adoption | Confirm real user growth | 6h |
| 9 | Liquidity Quality | Healthy trading conditions | On demand |
| 10 | Smart Money | Conviction from proven wallets | 15m |
| 11 | Narrative | Market context & sector boost | Daily |
| 12 | Price Compression | Entry timing optimization | 15m |
| 13 | Risk Score | Opportunity vs danger separation | On demand |
| 14 | Early Momentum | Combined opportunity score | 15m |
| 15 | Ranking | Tier A/B/C/Excluded | 15m |
| 16 | Human Review | Due diligence checklist | Manual |
| 17 | Validation | External confirmation | On demand |

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (for PostgreSQL + Redis)
- API keys for external services (optional — layers work independently)

### Setup

```bash
# Clone and navigate
cd ai-crypto-finder

# Copy environment config
cp .env.example .env
# Edit .env with your API keys

# Start infrastructure
docker-compose up -d postgres redis

# Install dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start the API server
uvicorn app.main:app --reload

# Start Celery worker (in another terminal)
celery -A app.tasks.celery_app worker --loglevel=info

# Start Celery beat scheduler (in another terminal)
celery -A app.tasks.celery_app beat --loglevel=info
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/tokens` | List ranked tokens |
| GET | `/api/v1/tokens/{id}` | Token detail |
| GET | `/api/v1/rankings` | Current tier rankings |
| POST | `/api/v1/pipeline/run` | Trigger full pipeline |
| GET | `/api/v1/pipeline/status` | Pipeline run history |
| POST | `/api/v1/discover` | Ingest external discovery |
| GET | `/api/v1/stats` | System statistics |

### Scoring Weights

| Component | Weight |
|-----------|--------|
| Market Flow | 25% |
| Attention | 25% |
| Adoption | 15% |
| Liquidity Quality | 10% |
| Smart Money | 10% |
| Narrative | 5% |
| Price Compression | Multiplier |
| Risk Score | Penalty |

## Configuration

All configuration is in `.env` and `app/config.py`. Key settings:

- `MIN_LIQUIDITY_NEW` — Minimum liquidity for new launches ($25k default)
- `MIN_LIQUIDITY_GROWING` — Minimum for growing coins ($100k default)
- `MIN_LIQUIDITY_MATURE` — Minimum for mature coins ($500k default)
- `WEIGHT_*` — Scoring weight adjustments

## Development

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```
