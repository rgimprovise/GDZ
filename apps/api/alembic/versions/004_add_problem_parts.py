"""Add problem_parts table for multi-variant problems

Revision ID: 004_problem_parts
Revises: 003_add_problem_type
Create Date: 2024-02-14

Задачи в учебниках часто имеют несколько подпунктов:
"4. Найдите смежные углы, если: 1) ... 2) ... 3) ... 4) ..."

Каждый подпункт имеет свой ответ.
"""
from alembic import op
import sqlalchemy as sa


revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    # Таблица подпунктов задач
    op.create_table(
        'problem_parts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('problem_id', sa.Integer(), sa.ForeignKey('problems.id', ondelete='CASCADE'), nullable=False),
        sa.Column('part_number', sa.String(10), nullable=False),  # "1", "2", "а", "б"
        sa.Column('part_text', sa.Text(), nullable=True),  # Текст подпункта
        sa.Column('answer_text', sa.Text(), nullable=True),  # Ответ для этого подпункта
        sa.Column('solution_text', sa.Text(), nullable=True),  # Решение (если есть)
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Индекс для быстрого поиска подпунктов задачи
    op.create_index('ix_problem_parts_problem_id', 'problem_parts', ['problem_id'])
    
    # Уникальный индекс: один номер подпункта на задачу
    op.create_index('ix_problem_parts_unique', 'problem_parts', ['problem_id', 'part_number'], unique=True)
    
    # Добавим флаг в problems - есть ли подпункты
    op.add_column('problems', sa.Column('has_parts', sa.Boolean(), server_default='false'))
    
    # Добавим очищенный текст (после OCR постобработки)
    op.add_column('problems', sa.Column('problem_text_clean', sa.Text(), nullable=True))
    
    # FTS индекс для очищенного текста
    op.execute("""
        CREATE INDEX IF NOT EXISTS problems_clean_fts 
        ON problems 
        USING gin(to_tsvector('russian', COALESCE(problem_text_clean, problem_text)))
    """)


def downgrade():
    op.drop_index('problems_clean_fts', table_name='problems')
    op.drop_column('problems', 'problem_text_clean')
    op.drop_column('problems', 'has_parts')
    op.drop_index('ix_problem_parts_unique', table_name='problem_parts')
    op.drop_index('ix_problem_parts_problem_id', table_name='problem_parts')
    op.drop_table('problem_parts')
