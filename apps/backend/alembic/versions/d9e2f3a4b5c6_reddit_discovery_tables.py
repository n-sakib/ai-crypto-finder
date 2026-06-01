"""reddit_discovery_tables

Revision ID: d9e2f3a4b5c6
Revises: c8a1b2d3e4f5
Create Date: 2026-05-31 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd9e2f3a4b5c6'
down_revision: Union[str, None] = 'c8a1b2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── reddit_sources ────────────────────────────────────────────────
    op.create_table('reddit_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('subreddit_name', sa.String(length=256), nullable=False),
        sa.Column('source_type', sa.Enum('GENERAL_CRYPTO', 'MEME_COINS', 'TRADING', 'DEFI', 'CHAIN_SPECIFIC', name='redditsourcetype'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_post_id', sa.String(length=64), nullable=True),
        sa.Column('last_collected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id'),
    )
    op.create_index('ix_reddit_sources_enabled', 'reddit_sources', ['enabled'])
    op.create_index(op.f('ix_reddit_sources_source_id'), 'reddit_sources', ['source_id'])

    # ── reddit_posts ──────────────────────────────────────────────────
    op.create_table('reddit_posts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reddit_post_id', sa.String(length=64), nullable=False),
        sa.Column('post_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('author', sa.String(length=128), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('text_hash', sa.String(length=128), nullable=False),
        sa.Column('selftext', sa.Text(), nullable=True),
        sa.Column('score', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('num_comments', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('upvote_ratio', sa.Integer(), nullable=True),
        sa.Column('post_url', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['reddit_sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'reddit_post_id', name='uq_reddit_post_source_postid'),
    )
    op.create_index('ix_reddit_posts_text_hash', 'reddit_posts', ['text_hash'])
    op.create_index('ix_reddit_posts_timestamp', 'reddit_posts', ['post_timestamp'])
    op.create_index(op.f('ix_reddit_posts_source_id'), 'reddit_posts', ['source_id'])

    # ── reddit_candidate_tokens ───────────────────────────────────────
    op.create_table('reddit_candidate_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('chain', sa.String(length=32), nullable=False),
        sa.Column('token_address', sa.String(length=128), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=True),
        sa.Column('first_discovered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('first_discovered_source_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('first_discovery_method', sa.Enum('CONTRACT_ADDRESS', 'DEX_LINK', 'CASHTAG', 'TOKEN_NAME', name='redditdiscoverymethod'), nullable=False),
        sa.Column('pair_address', sa.String(length=128), nullable=True),
        sa.Column('dex_url', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['first_discovered_source_id'], ['reddit_sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chain', 'token_address', name='uq_reddit_candidate_token_chain_address'),
    )
    op.create_index('ix_reddit_candidate_tokens_chain', 'reddit_candidate_tokens', ['chain'])
    op.create_index(op.f('ix_reddit_candidate_tokens_token_address'), 'reddit_candidate_tokens', ['token_address'])

    # ── reddit_token_mentions ─────────────────────────────────────────
    op.create_table('reddit_token_mentions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_token_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reddit_post_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('post_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('author', sa.String(length=128), nullable=False),
        sa.Column('discovery_method', sa.Enum('CONTRACT_ADDRESS', 'DEX_LINK', 'CASHTAG', 'TOKEN_NAME', name='redditdiscoverymethod'), nullable=False),
        sa.Column('confidence', sa.Enum('very_high', 'high', 'medium', 'low', name='redditdiscoveryconfidence'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_token_id'], ['reddit_candidate_tokens.id']),
        sa.ForeignKeyConstraint(['source_id'], ['reddit_sources.id']),
        sa.ForeignKeyConstraint(['reddit_post_id'], ['reddit_posts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('candidate_token_id', 'reddit_post_id', 'discovery_method', name='uq_reddit_mention_token_post_method'),
    )
    op.create_index('ix_reddit_mentions_timestamp', 'reddit_token_mentions', ['post_timestamp'])
    op.create_index('ix_reddit_mentions_token_window', 'reddit_token_mentions', ['candidate_token_id', 'post_timestamp'])
    op.create_index(op.f('ix_reddit_token_mentions_candidate_token_id'), 'reddit_token_mentions', ['candidate_token_id'])
    op.create_index(op.f('ix_reddit_token_mentions_source_id'), 'reddit_token_mentions', ['source_id'])
    op.create_index(op.f('ix_reddit_token_mentions_reddit_post_id'), 'reddit_token_mentions', ['reddit_post_id'])

    # ── reddit_discovery_rankings ─────────────────────────────────────
    op.create_table('reddit_discovery_rankings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_token_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('mention_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('unique_user_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('subreddit_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('total_score', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_token_id'], ['reddit_candidate_tokens.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reddit_rankings_window', 'reddit_discovery_rankings', ['window_start', 'window_end'])
    op.create_index('ix_reddit_rankings_token_window', 'reddit_discovery_rankings', ['candidate_token_id', 'window_start'])
    op.create_index(op.f('ix_reddit_discovery_rankings_candidate_token_id'), 'reddit_discovery_rankings', ['candidate_token_id'])


def downgrade() -> None:
    op.drop_table('reddit_discovery_rankings')
    op.drop_table('reddit_token_mentions')
    op.execute("DROP TYPE IF EXISTS redditdiscoveryconfidence")
    op.execute("DROP TYPE IF EXISTS redditdiscoverymethod")
    op.drop_table('reddit_candidate_tokens')
    op.drop_table('reddit_posts')
    op.drop_table('reddit_sources')
    op.execute("DROP TYPE IF EXISTS redditsourcetype")
