"""Add ingestion tables: books, pdf_sources, pdf_pages, problems

Revision ID: 002
Revises: 001
Create Date: 2026-02-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Books table
    op.create_table('books',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subject', sa.String(length=50), nullable=False),
        sa.Column('grade', sa.String(length=20), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('authors', sa.String(length=255), nullable=True),
        sa.Column('publisher', sa.String(length=255), nullable=True),
        sa.Column('edition_year', sa.Integer(), nullable=True),
        sa.Column('part', sa.String(length=10), nullable=True),
        sa.Column('is_gdz', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_books_id', 'books', ['id'], unique=False)
    op.create_index('ix_books_subject', 'books', ['subject'], unique=False)
    op.create_index('ix_books_grade', 'books', ['grade'], unique=False)
    
    # PDF Sources table
    op.create_table('pdf_sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('minio_key', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=True, default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('minio_key')
    )
    op.create_index('ix_pdf_sources_id', 'pdf_sources', ['id'], unique=False)
    
    # PDF Pages table
    op.create_table('pdf_pages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pdf_source_id', sa.Integer(), nullable=False),
        sa.Column('page_num', sa.Integer(), nullable=False),
        sa.Column('image_minio_key', sa.String(length=255), nullable=True),
        sa.Column('ocr_text', sa.Text(), nullable=True),
        sa.Column('ocr_confidence', sa.Integer(), nullable=True),
        sa.Column('needs_review', sa.Boolean(), nullable=True, default=False),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['pdf_source_id'], ['pdf_sources.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_pdf_pages_id', 'pdf_pages', ['id'], unique=False)
    
    # Problems table
    op.create_table('problems',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('source_page_id', sa.Integer(), nullable=True),
        sa.Column('number', sa.String(length=50), nullable=True),
        sa.Column('section', sa.String(length=100), nullable=True),
        sa.Column('problem_text', sa.Text(), nullable=False),
        sa.Column('solution_text', sa.Text(), nullable=True),
        sa.Column('answer_text', sa.Text(), nullable=True),
        sa.Column('page_ref', sa.String(length=50), nullable=True),
        sa.Column('bbox', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('needs_review', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ),
        sa.ForeignKeyConstraint(['source_page_id'], ['pdf_pages.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_problems_id', 'problems', ['id'], unique=False)
    op.create_index('ix_problems_number', 'problems', ['number'], unique=False)
    
    # Full-text search index on problems
    op.execute("""
        CREATE INDEX ix_problems_fts ON problems 
        USING gin(to_tsvector('russian', problem_text))
    """)


def downgrade() -> None:
    op.drop_index('ix_problems_fts', table_name='problems')
    op.drop_index('ix_problems_number', table_name='problems')
    op.drop_index('ix_problems_id', table_name='problems')
    op.drop_table('problems')
    
    op.drop_index('ix_pdf_pages_id', table_name='pdf_pages')
    op.drop_table('pdf_pages')
    
    op.drop_index('ix_pdf_sources_id', table_name='pdf_sources')
    op.drop_table('pdf_sources')
    
    op.drop_index('ix_books_grade', table_name='books')
    op.drop_index('ix_books_subject', table_name='books')
    op.drop_index('ix_books_id', table_name='books')
    op.drop_table('books')
