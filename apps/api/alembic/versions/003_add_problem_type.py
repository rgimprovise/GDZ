"""Add problem_type column to problems table.

Revision ID: 003
Revises: 002
Create Date: 2026-02-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # Add problem_type column
    op.add_column('problems', sa.Column('problem_type', sa.String(20), nullable=True))
    
    # Set default value for existing rows
    op.execute("UPDATE problems SET problem_type = 'unknown' WHERE problem_type IS NULL")
    
    # Create index for filtering by type
    op.create_index('ix_problems_type', 'problems', ['problem_type'])


def downgrade():
    op.drop_index('ix_problems_type', table_name='problems')
    op.drop_column('problems', 'problem_type')
