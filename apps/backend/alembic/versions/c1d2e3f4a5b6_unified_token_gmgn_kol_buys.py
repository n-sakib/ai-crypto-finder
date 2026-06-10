"""unified token gmgn kol buys

Revision ID: c1d2e3f4a5b6
Revises: b7c9d1e2f3a4
Create Date: 2026-06-10 19:05:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b7c9d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS gmgn_kol_count integer DEFAULT 0")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS gmgn_kol_buy_count integer DEFAULT 0")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS gmgn_kol_total_amount_usd double precision DEFAULT 0")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS gmgn_kol_last_buy_at timestamp with time zone")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS gmgn_kol_wallets json DEFAULT '[]'::json")


def downgrade() -> None:
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS gmgn_kol_wallets")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS gmgn_kol_last_buy_at")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS gmgn_kol_total_amount_usd")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS gmgn_kol_buy_count")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS gmgn_kol_count")
