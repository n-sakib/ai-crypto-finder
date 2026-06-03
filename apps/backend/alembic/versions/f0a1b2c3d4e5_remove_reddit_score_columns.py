"""remove_reddit_score_columns

Revision ID: f0a1b2c3d4e5
Revises: e7f8a9b0c1d2
Create Date: 2026-06-03 13:30:00.000000

Remove score, num_comments, upvote_ratio from reddit_posts and
comment_count from reddit_discovery_rankings.
RSS feeds don't provide these metrics.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop columns from reddit_posts
    op.drop_column('reddit_posts', 'score')
    op.drop_column('reddit_posts', 'num_comments')
    op.drop_column('reddit_posts', 'upvote_ratio')

    # Drop comment_count from reddit_discovery_rankings
    op.drop_column('reddit_discovery_rankings', 'comment_count')


def downgrade() -> None:
    # Restore columns to reddit_posts
    op.add_column('reddit_posts', sa.Column('score', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('reddit_posts', sa.Column('num_comments', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('reddit_posts', sa.Column('upvote_ratio', sa.Integer(), nullable=True))

    # Restore comment_count to reddit_discovery_rankings
    op.add_column('reddit_discovery_rankings', sa.Column('comment_count', sa.Integer(), nullable=False, server_default=sa.text('0')))
