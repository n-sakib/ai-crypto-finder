"""telegram_social_indicators_and_ai_evaluation

Revision ID: 8e1bbd154960
Revises: a1b2c3d4e5f6
Create Date: 2026-06-06 11:47:31.889716
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '8e1bbd154960'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add social indicator columns to telegram_messages
    op.add_column('telegram_messages', sa.Column('reactions_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('telegram_messages', sa.Column('views_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('telegram_messages', sa.Column('forwards_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('telegram_messages', sa.Column('reply_count', sa.Integer(), nullable=False, server_default='0'))

    # Add enrichment + AI evaluation columns to candidate_tokens
    op.add_column('candidate_tokens', sa.Column('gmgn_data', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('candidate_tokens', sa.Column('dexscreener_data', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('candidate_tokens', sa.Column('ai_evaluation', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('candidate_tokens', sa.Column('ai_decision', sa.String(length=32), nullable=True))
    op.add_column('candidate_tokens', sa.Column('ai_evaluated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('telegram_messages', 'reply_count')
    op.drop_column('telegram_messages', 'forwards_count')
    op.drop_column('telegram_messages', 'views_count')
    op.drop_column('telegram_messages', 'reactions_count')

    op.drop_column('candidate_tokens', 'ai_evaluated_at')
    op.drop_column('candidate_tokens', 'ai_decision')
    op.drop_column('candidate_tokens', 'ai_evaluation')
    op.drop_column('candidate_tokens', 'dexscreener_data')
    op.drop_column('candidate_tokens', 'gmgn_data')
