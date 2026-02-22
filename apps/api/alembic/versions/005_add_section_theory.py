"""Add section_theory table for stored theoretical material per paragraph

Revision ID: 005
Revises: 004
Create Date: 2025-02-14

Теоретический материал параграфа сохраняется при ingestion:
OCR → нормализация → сегментация (задачи + теория по §) → БД.
Используется LLM для ответов на контрольные вопросы и обоснования решений.
"""
from alembic import op
import sqlalchemy as sa


revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'section_theory',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('book_id', sa.Integer(), sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=False),
        sa.Column('section', sa.String(50), nullable=False),   # "§7", "7", "Глава 3"
        sa.Column('theory_text', sa.Text(), nullable=False),  # Текст параграфа (определения, теоремы, доказательства)
        sa.Column('page_ref', sa.String(100), nullable=True), # "стр. 45–48" для отображения
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_section_theory_book_id', 'section_theory', ['book_id'], unique=False)
    op.create_index('ix_section_theory_book_section', 'section_theory', ['book_id', 'section'], unique=True)


def downgrade():
    op.drop_index('ix_section_theory_book_section', table_name='section_theory')
    op.drop_index('ix_section_theory_book_id', table_name='section_theory')
    op.drop_table('section_theory')
