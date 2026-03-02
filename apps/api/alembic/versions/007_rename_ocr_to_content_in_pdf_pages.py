"""Rename ocr_text -> page_text, ocr_confidence -> confidence in pdf_pages

Revision ID: 007
Revises: 006
Create Date: 2025-02-28

Удаление упоминаний OCR из схемы БД: текст страницы и уверенность переименованы.
"""
from alembic import op


revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'pdf_pages',
        'ocr_text',
        new_column_name='page_text',
    )
    op.alter_column(
        'pdf_pages',
        'ocr_confidence',
        new_column_name='confidence',
    )


def downgrade():
    op.alter_column(
        'pdf_pages',
        'page_text',
        new_column_name='ocr_text',
    )
    op.alter_column(
        'pdf_pages',
        'confidence',
        new_column_name='ocr_confidence',
    )
