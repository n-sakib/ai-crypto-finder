"""telegram_discovery_tables

Revision ID: c8a1b2d3e4f5
Revises: 5fda02050404
Create Date: 2026-05-31 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c8a1b2d3e4f5'
down_revision: Union[str, None] = '5fda02050404'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── telegram_sources ──────────────────────────────────────────────
    op.create_table('telegram_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('telegram_identifier', sa.String(length=256), nullable=False),
        sa.Column('source_type', sa.Enum('ALPHA_GROUP', 'TREND_GROUP', 'MEME_GROUP', 'TRADING_GROUP', 'CHAIN_GROUP', name='sourcetype'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_message_id', sa.BigInteger(), nullable=True),
        sa.Column('last_collected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id'),
    )
    op.create_index('ix_telegram_sources_enabled', 'telegram_sources', ['enabled'])
    op.create_index(op.f('ix_telegram_sources_source_id'), 'telegram_sources', ['source_id'])

    # ── telegram_messages ─────────────────────────────────────────────
    op.create_table('telegram_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=False),
        sa.Column('message_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sender_id_hash', sa.String(length=128), nullable=False),
        sa.Column('text_hash', sa.String(length=128), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['telegram_sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'telegram_message_id', name='uq_telegram_msg_source_msgid'),
    )
    op.create_index('ix_telegram_messages_text_hash', 'telegram_messages', ['text_hash'])
    op.create_index('ix_telegram_messages_timestamp', 'telegram_messages', ['message_timestamp'])
    op.create_index(op.f('ix_telegram_messages_source_id'), 'telegram_messages', ['source_id'])

    # ── candidate_tokens ──────────────────────────────────────────────
    op.create_table('candidate_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('chain', sa.String(length=32), nullable=False),
        sa.Column('token_address', sa.String(length=128), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=True),
        sa.Column('first_discovered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('first_discovered_source_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('first_discovery_method', sa.Enum('CONTRACT_ADDRESS', 'DEX_LINK', 'CASHTAG', 'TOKEN_NAME', name='discoverymethod'), nullable=False),
        sa.Column('pair_address', sa.String(length=128), nullable=True),
        sa.Column('dex_url', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['first_discovered_source_id'], ['telegram_sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chain', 'token_address', name='uq_candidate_token_chain_address'),
    )
    op.create_index('ix_candidate_tokens_chain', 'candidate_tokens', ['chain'])
    op.create_index(op.f('ix_candidate_tokens_token_address'), 'candidate_tokens', ['token_address'])

    # ── telegram_token_mentions ───────────────────────────────────────
    op.create_table('telegram_token_mentions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_token_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('telegram_message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sender_id_hash', sa.String(length=128), nullable=False),
        sa.Column('discovery_method', sa.Enum('CONTRACT_ADDRESS', 'DEX_LINK', 'CASHTAG', 'TOKEN_NAME', name='discoverymethod'), nullable=False),
        sa.Column('confidence', sa.Enum('very_high', 'high', 'medium', 'low', name='discoveryconfidence'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_token_id'], ['candidate_tokens.id']),
        sa.ForeignKeyConstraint(['source_id'], ['telegram_sources.id']),
        sa.ForeignKeyConstraint(['telegram_message_id'], ['telegram_messages.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('candidate_token_id', 'telegram_message_id', 'discovery_method', name='uq_mention_token_msg_method'),
    )
    op.create_index('ix_mentions_timestamp', 'telegram_token_mentions', ['message_timestamp'])
    op.create_index('ix_mentions_token_window', 'telegram_token_mentions', ['candidate_token_id', 'message_timestamp'])
    op.create_index(op.f('ix_telegram_token_mentions_candidate_token_id'), 'telegram_token_mentions', ['candidate_token_id'])
    op.create_index(op.f('ix_telegram_token_mentions_source_id'), 'telegram_token_mentions', ['source_id'])
    op.create_index(op.f('ix_telegram_token_mentions_telegram_message_id'), 'telegram_token_mentions', ['telegram_message_id'])

    # ── telegram_discovery_rankings ───────────────────────────────────
    op.create_table('telegram_discovery_rankings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_token_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('mention_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('unique_user_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('group_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('first_seen_in_window', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_in_window', sa.DateTime(timezone=True), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_token_id'], ['candidate_tokens.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('candidate_token_id', 'window_start', 'window_end', name='uq_ranking_token_window'),
    )
    op.create_index('ix_rankings_window', 'telegram_discovery_rankings', ['window_start', 'window_end'])
    op.create_index('ix_rankings_rank', 'telegram_discovery_rankings', ['rank'])
    op.create_index(op.f('ix_telegram_discovery_rankings_candidate_token_id'), 'telegram_discovery_rankings', ['candidate_token_id'])


def downgrade() -> None:
    op.drop_table('telegram_discovery_rankings')
    op.drop_table('telegram_token_mentions')
    op.drop_table('candidate_tokens')
    op.drop_table('telegram_messages')
    op.drop_table('telegram_sources')
    op.execute('DROP TYPE IF EXISTS discoveryconfidence')
    op.execute('DROP TYPE IF EXISTS discoverymethod')
    op.execute('DROP TYPE IF EXISTS sourcetype')
