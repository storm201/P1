"""Verification scheduler and release sync schema migration

Revision ID: 002_verification_scheduler_and_releases
Revises: 001_initial_schema
Create Date: 2026-10-11 18:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_verification_scheduler_and_releases'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. verification_schedules table
    if 'verification_schedules' not in tables:
        op.create_table(
            'verification_schedules',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('app_id', sa.Integer(), sa.ForeignKey('apps.id', ondelete='CASCADE'), nullable=False),
            sa.Column('check_type', sa.String(length=60), nullable=False),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='IDLE'),
            sa.Column('scheduled_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('last_run_at', sa.DateTime(), nullable=True),
            sa.Column('next_run_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('locked_by', sa.String(length=100), nullable=True),
            sa.Column('locked_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_verification_schedules_app_id', 'verification_schedules', ['app_id'])
        op.create_index('ix_verification_schedules_check_type', 'verification_schedules', ['check_type'])
        op.create_index('ix_verification_schedules_status', 'verification_schedules', ['status'])
        op.create_index('ix_verification_schedules_next_run_at', 'verification_schedules', ['next_run_at'])

    # 2. Add columns to app_releases
    rel_cols = [c['name'] for c in inspector.get_columns('app_releases')]
    with op.batch_alter_table('app_releases') as batch_op:
        if 'source_commit' not in rel_cols:
            batch_op.add_column(sa.Column('source_commit', sa.String(length=100), nullable=True))
        if 'last_synced_at' not in rel_cols:
            batch_op.add_column(sa.Column('last_synced_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
        if 'etag' not in rel_cols:
            batch_op.add_column(sa.Column('etag', sa.String(length=200), nullable=True))

    # 3. Add columns to release_assets
    asset_cols = [c['name'] for c in inspector.get_columns('release_assets')]
    with op.batch_alter_table('release_assets') as batch_op:
        if 'checksum_algorithm' not in asset_cols:
            batch_op.add_column(sa.Column('checksum_algorithm', sa.String(length=30), nullable=True))
        if 'platform' not in asset_cols:
            batch_op.add_column(sa.Column('platform', sa.String(length=50), nullable=True))
        if 'is_reachable' not in asset_cols:
            batch_op.add_column(sa.Column('is_reachable', sa.Boolean(), nullable=True))
        if 'last_checked_at' not in asset_cols:
            batch_op.add_column(sa.Column('last_checked_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('release_assets') as batch_op:
        batch_op.drop_column('last_checked_at')
        batch_op.drop_column('is_reachable')
        batch_op.drop_column('platform')
        batch_op.drop_column('checksum_algorithm')

    with op.batch_alter_table('app_releases') as batch_op:
        batch_op.drop_column('etag')
        batch_op.drop_column('last_synced_at')
        batch_op.drop_column('source_commit')

    op.drop_index('ix_verification_schedules_next_run_at', table_name='verification_schedules')
    op.drop_index('ix_verification_schedules_status', table_name='verification_schedules')
    op.drop_index('ix_verification_schedules_check_type', table_name='verification_schedules')
    op.drop_index('ix_verification_schedules_app_id', table_name='verification_schedules')
    op.drop_table('verification_schedules')
