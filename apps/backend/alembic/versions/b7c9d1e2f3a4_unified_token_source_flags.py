"""unified token source flags

Revision ID: b7c9d1e2f3a4
Revises: f46e205749d7
Create Date: 2026-06-08 18:59:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b7c9d1e2f3a4"
down_revision: Union[str, None] = "f46e205749d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS is_dexscreener_trending boolean DEFAULT false")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS is_dexscreener_boosted boolean DEFAULT false")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS is_gmgn_trending boolean DEFAULT false")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS dexscreener_trending_rank integer")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS dexscreener_boost_amount double precision")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS dexscreener_boost_total double precision")
    op.execute("ALTER TABLE unified_tokens ADD COLUMN IF NOT EXISTS gmgn_trending_rank integer")


def downgrade() -> None:
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS gmgn_trending_rank")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS dexscreener_boost_total")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS dexscreener_boost_amount")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS dexscreener_trending_rank")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS is_gmgn_trending")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS is_dexscreener_boosted")
    op.execute("ALTER TABLE unified_tokens DROP COLUMN IF EXISTS is_dexscreener_trending")
