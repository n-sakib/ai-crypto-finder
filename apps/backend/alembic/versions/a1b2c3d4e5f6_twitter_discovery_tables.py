"""twitter_discovery_tables

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-06-03 14:00:00.000000

Create Twitter/X discovery tables for tracking token mentions from tweets.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── twitter_sources ────────────────────────────────────────────────
    op.create_table('twitter_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('query', sa.String(length=512), nullable=False),
        sa.Column('source_type', sa.Enum('CASHTAG_SEARCH', 'KEYWORD_SEARCH', 'ADDRESS_SEARCH', 'ACCOUNT_MONITOR', name='twittersourcetype'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_tweet_id', sa.String(length=64), nullable=True),
        sa.Column('last_collected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id'),
    )
    op.create_index('ix_twitter_sources_source_id', 'twitter_sources', ['source_id'])
    op.create_index('ix_twitter_sources_enabled', 'twitter_sources', ['enabled'])

    # ── twitter_tweets ─────────────────────────────────────────────────
    op.create_table('twitter_tweets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tweet_id', sa.String(length=64), nullable=False),
        sa.Column('tweet_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('author_name', sa.String(length=128), nullable=False),
        sa.Column('text_hash', sa.String(length=128), nullable=False),
        sa.Column('tweet_text', sa.Text(), nullable=True),
        sa.Column('retweet_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('like_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('reply_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('tweet_url', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['source_id'], ['twitter_sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'tweet_id', name='uq_twitter_tweet_source_tweetid'),
    )
    op.create_index('ix_twitter_tweets_text_hash', 'twitter_tweets', ['text_hash'])
    op.create_index('ix_twitter_tweets_timestamp', 'twitter_tweets', ['tweet_timestamp'])

    # ── twitter_candidate_tokens ───────────────────────────────────────
    op.create_table('twitter_candidate_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('chain', sa.String(length=32), nullable=False),
        sa.Column('token_address', sa.String(length=128), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=True),
        sa.Column('first_discovered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('first_discovered_source_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('first_discovery_method', sa.Enum('CASHTAG', 'CONTRACT_ADDRESS', 'TOKEN_NAME', name='twitterdiscoverymethod'), nullable=False),
        sa.Column('pair_address', sa.String(length=128), nullable=True),
        sa.Column('dex_url', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['first_discovered_source_id'], ['twitter_sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chain', 'token_address', name='uq_twitter_candidate_token_chain_address'),
    )
    op.create_index('ix_twitter_candidate_tokens_chain', 'twitter_candidate_tokens', ['chain'])
    op.create_index('ix_twitter_candidate_tokens_token_address', 'twitter_candidate_tokens', ['token_address'])

    # ── twitter_token_mentions ─────────────────────────────────────────
    op.create_table('twitter_token_mentions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_token_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tweet_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tweet_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('author_name', sa.String(length=128), nullable=False),
        sa.Column('discovery_method', sa.Enum('CASHTAG', 'CONTRACT_ADDRESS', 'TOKEN_NAME', name='twittermentiondiscoverymethod'), nullable=False),
        sa.Column('confidence', sa.Enum('very_high', 'high', 'medium', 'low', name='twitterdiscoveryconfidence'), nullable=False),
        sa.Column('is_reputable', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('engagement_score', sa.Float(), server_default=sa.text('0.0')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['candidate_token_id'], ['twitter_candidate_tokens.id']),
        sa.ForeignKeyConstraint(['source_id'], ['twitter_sources.id']),
        sa.ForeignKeyConstraint(['tweet_id'], ['twitter_tweets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('candidate_token_id', 'tweet_id', 'discovery_method', name='uq_twitter_mention_token_tweet_method'),
    )
    op.create_index('ix_twitter_mentions_candidate_token_id', 'twitter_token_mentions', ['candidate_token_id'])
    op.create_index('ix_twitter_mentions_source_id', 'twitter_token_mentions', ['source_id'])
    op.create_index('ix_twitter_mentions_tweet_id', 'twitter_token_mentions', ['tweet_id'])
    op.create_index('ix_twitter_mentions_timestamp', 'twitter_token_mentions', ['tweet_timestamp'])
    op.create_index('ix_twitter_mentions_token_window', 'twitter_token_mentions', ['candidate_token_id', 'tweet_timestamp'])

    # ── twitter_discovery_rankings ─────────────────────────────────────
    op.create_table('twitter_discovery_rankings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_token_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('mention_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('unique_user_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('total_engagement', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('authority_mentions', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('total_score', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['candidate_token_id'], ['twitter_candidate_tokens.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_twitter_rankings_candidate_token_id', 'twitter_discovery_rankings', ['candidate_token_id'])
    op.create_index('ix_twitter_rankings_window', 'twitter_discovery_rankings', ['window_start', 'window_end'])
    op.create_index('ix_twitter_rankings_token_window', 'twitter_discovery_rankings', ['candidate_token_id', 'window_start'])


def downgrade() -> None:
    op.drop_table('twitter_discovery_rankings')
    op.drop_table('twitter_token_mentions')
    op.drop_table('twitter_candidate_tokens')
    op.drop_table('twitter_tweets')
    op.drop_table('twitter_sources')
    op.execute('DROP TYPE IF EXISTS twittersourcetype')
    op.execute('DROP TYPE IF EXISTS twitterdiscoverymethod')
    op.execute('DROP TYPE IF EXISTS twittermentiondiscoverymethod')
    op.execute('DROP TYPE IF EXISTS twitterdiscoveryconfidence')
