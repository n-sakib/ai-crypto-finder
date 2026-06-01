"""reddit_ranking_kpi_columns

Revision ID: e7f8a9b0c1d2
Revises: d9e2f3a4b5c6
Create Date: 2026-05-31 00:30:00.000000

Adds post_count and comment_count columns to reddit_discovery_rankings
to track additional KPIs: post_count, comment_count, upvotes.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'd9e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reddit_discovery_rankings',
        sa.Column('post_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'reddit_discovery_rankings',
        sa.Column('comment_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )


def downgrade() -> None:
    op.drop_column('reddit_discovery_rankings', 'comment_count')
    op.drop_column('reddit_discovery_rankings', 'post_count')
