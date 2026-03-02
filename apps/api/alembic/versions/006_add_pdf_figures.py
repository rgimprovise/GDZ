"""Add pdf_figures table for figures extracted from PDF pages

Revision ID: 006
Revises: 005
Create Date: 2025-02-28

Рисунки/фигуры из PDF (ebook) сохраняются с привязкой к странице и подписью.
"""
from alembic import op
import sqlalchemy as sa


revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pdf_figures',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('pdf_source_id', sa.Integer(), sa.ForeignKey('pdf_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page_num', sa.Integer(), nullable=False),
        sa.Column('figure_index', sa.Integer(), nullable=False),
        sa.Column('image_key', sa.String(512), nullable=False),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_pdf_figures_pdf_source_id', 'pdf_figures', ['pdf_source_id'], unique=False)
    op.create_index('ix_pdf_figures_pdf_source_page', 'pdf_figures', ['pdf_source_id', 'page_num'], unique=False)


def downgrade():
    op.drop_index('ix_pdf_figures_pdf_source_page', table_name='pdf_figures')
    op.drop_index('ix_pdf_figures_pdf_source_id', table_name='pdf_figures')
    op.drop_table('pdf_figures')
