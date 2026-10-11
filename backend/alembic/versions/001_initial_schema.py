"""Initial schema migration

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. categories
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('slug', sa.String(length=100), nullable=False, unique=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('categories.id'), nullable=True),
    )
    op.create_index('ix_categories_slug', 'categories', ['slug'])
    op.create_index('ix_categories_name', 'categories', ['name'])

    # 2. category_aliases
    op.create_table(
        'category_aliases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('categories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('alias', sa.String(length=100), nullable=False),
        sa.Column('match_type', sa.String(length=50), server_default='exact'),
    )
    op.create_index('ix_category_aliases_alias', 'category_aliases', ['alias'])

    # 3. apps
    op.create_table(
        'apps',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('slug', sa.String(length=120), nullable=False, unique=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('summary', sa.String(length=300), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('homepage_url', sa.String(length=500), nullable=False),
        sa.Column('repo_url', sa.String(length=500), nullable=True),
        sa.Column('license_state', sa.String(length=50), nullable=False, server_default='confirmed_open_source'),
        sa.Column('license_spdx', sa.String(length=100), nullable=True),
        sa.Column('primary_category_id', sa.Integer(), sa.ForeignKey('categories.id'), nullable=True),
        sa.Column('platforms', sa.JSON(), nullable=False),
        sa.Column('is_delisted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_apps_slug', 'apps', ['slug'])
    op.create_index('ix_apps_name', 'apps', ['name'])

    # 4. app_categories
    op.create_table(
        'app_categories',
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('apps.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('categories.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false')),
    )

    # 5. app_capabilities
    op.create_table(
        'app_capabilities',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('apps.id', ondelete='CASCADE'), nullable=False),
        sa.Column('capability', sa.String(length=120), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
    )
    op.create_index('ix_app_capabilities_capability', 'app_capabilities', ['capability'])

    # 6. app_releases
    op.create_table(
        'app_releases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('apps.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tag_name', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('release_url', sa.String(length=500), nullable=False),
        sa.Column('is_prerelease', sa.Boolean(), server_default=sa.text('false')),
    )

    # 7. release_assets
    op.create_table(
        'release_assets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('release_id', sa.Integer(), sa.ForeignKey('app_releases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=250), nullable=False),
        sa.Column('download_url', sa.String(length=500), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('checksum', sa.String(length=128), nullable=True),
        sa.Column('content_type', sa.String(length=100), nullable=True),
    )

    # 8. search_documents
    op.create_table(
        'search_documents',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('apps.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('document_text', sa.Text(), nullable=False),
        sa.Column('embedding', sa.JSON(), nullable=True),
        sa.Column('model_name', sa.String(length=100), nullable=True),
        sa.Column('embedding_dim', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # 9. verification_runs
    op.create_table(
        'verification_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('apps.id', ondelete='CASCADE'), nullable=True),
        sa.Column('run_type', sa.String(length=50), nullable=False, server_default='manual'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='SUCCESS'),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
    )

    # 10. verification_checks
    op.create_table(
        'verification_checks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('verification_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('apps.id', ondelete='CASCADE'), nullable=False),
        sa.Column('check_type', sa.String(length=60), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('final_url', sa.String(length=500), nullable=True),
        sa.Column('tls_valid', sa.Boolean(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
    )

    # 11. ingestion_jobs
    op.create_table(
        'ingestion_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('items_processed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('items_added', sa.Integer(), server_default='0', nullable=False),
        sa.Column('items_updated', sa.Integer(), server_default='0', nullable=False),
        sa.Column('requests_made', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
    )

    # 12. correction_requests
    op.create_table(
        'correction_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('apps.id', ondelete='SET NULL'), nullable=True),
        sa.Column('app_identifier', sa.String(length=200), nullable=True),
        sa.Column('request_type', sa.String(length=50), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('contact_email', sa.String(length=250), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('submitted_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('correction_requests')
    op.drop_table('ingestion_jobs')
    op.drop_table('verification_checks')
    op.drop_table('verification_runs')
    op.drop_table('search_documents')
    op.drop_table('release_assets')
    op.drop_table('app_releases')
    op.drop_table('app_capabilities')
    op.drop_table('app_categories')
    op.drop_table('apps')
    op.drop_table('category_aliases')
    op.drop_table('categories')
