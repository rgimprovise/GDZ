"""Initial schema - users, plans, subscriptions, queries, responses

Revision ID: 001
Revises: 
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tg_uid', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(255), nullable=True),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('language_code', sa.String(10), server_default='ru'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('accepted_terms_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_privacy_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_tg_uid', 'users', ['tg_uid'], unique=True)
    
    # Create plans table
    op.create_table(
        'plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('type', sa.String(20), server_default='free'),
        sa.Column('daily_queries', sa.Integer(), server_default='5'),
        sa.Column('monthly_queries', sa.Integer(), server_default='50'),
        sa.Column('price_monthly', sa.Integer(), server_default='0'),
        sa.Column('price_yearly', sa.Integer(), server_default='0'),
        sa.Column('features', sa.JSON(), server_default='{}'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('ix_plans_id', 'plans', ['id'])
    
    # Create subscriptions table
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), server_default='active'),
        sa.Column('queries_used_today', sa.Integer(), server_default='0'),
        sa.Column('queries_used_month', sa.Integer(), server_default='0'),
        sa.Column('last_query_date', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id'])
    )
    op.create_index('ix_subscriptions_id', 'subscriptions', ['id'])
    
    # Create queries table
    op.create_table(
        'queries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('input_text', sa.Text(), nullable=True),
        sa.Column('input_photo_keys', sa.JSON(), server_default='[]'),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('ocr_confidence', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), server_default='queued'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('tokens_used', sa.Integer(), server_default='0'),
        sa.Column('processing_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'])
    )
    op.create_index('ix_queries_id', 'queries', ['id'])
    
    # Create responses table
    op.create_table(
        'responses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query_id', sa.Integer(), nullable=False),
        sa.Column('content_markdown', sa.Text(), nullable=False),
        sa.Column('citations', sa.JSON(), server_default='[]'),
        sa.Column('model_used', sa.String(50), nullable=True),
        sa.Column('confidence_score', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['query_id'], ['queries.id']),
        sa.UniqueConstraint('query_id')
    )
    op.create_index('ix_responses_id', 'responses', ['id'])
    
    # Insert default free plan
    op.execute("""
        INSERT INTO plans (name, type, daily_queries, monthly_queries, price_monthly, price_yearly, features)
        VALUES ('Free', 'free', 5, 50, 0, 0, '{"hints_only": false}')
    """)


def downgrade() -> None:
    op.drop_table('responses')
    op.drop_table('queries')
    op.drop_table('subscriptions')
    op.drop_table('plans')
    op.drop_table('users')
    
    pass  # No enums to drop
