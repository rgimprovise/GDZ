"""
SQLAlchemy models for Worker (mirrored from API).
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, JSON, Boolean, ForeignKey
)
from sqlalchemy.orm import relationship

from database import Base


class Query(Base):
    """User homework query."""
    __tablename__ = "queries"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)  # FK to users table
    
    # Input
    input_text = Column(Text, nullable=True)
    input_photo_keys = Column(JSON, default=list)
    
    # OCR results
    extracted_text = Column(Text, nullable=True)
    ocr_confidence = Column(Integer, nullable=True)
    
    # Processing
    status = Column(String(20), default="queued")
    error_message = Column(Text, nullable=True)
    
    # Costs
    tokens_used = Column(Integer, default=0)
    processing_time_ms = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Response(Base):
    """Generated response for a query."""
    __tablename__ = "responses"
    
    id = Column(Integer, primary_key=True, index=True)
    query_id = Column(Integer, unique=True, nullable=False)  # FK to queries table
    
    content_markdown = Column(Text, nullable=False)
    citations = Column(JSON, default=list)
    model_used = Column(String(50), nullable=True)
    confidence_score = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


# ===========================================
# Ingestion Models
# ===========================================

class Book(Base):
    """Textbook / solution book."""
    __tablename__ = "books"
    
    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(50), nullable=False)
    grade = Column(String(20), nullable=True)
    title = Column(String(255), nullable=False)
    authors = Column(String(255), nullable=True)
    publisher = Column(String(255), nullable=True)
    edition_year = Column(Integer, nullable=True)
    part = Column(String(10), nullable=True)
    is_gdz = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SectionTheory(Base):
    """Теоретический материал параграфа (для ответов на контрольные вопросы и обоснования решений)."""
    __tablename__ = "section_theory"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, nullable=False)
    section = Column(String(50), nullable=False)   # "§7", "7"
    theory_text = Column(Text, nullable=False)
    page_ref = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PdfSource(Base):
    """Uploaded PDF file."""
    __tablename__ = "pdf_sources"
    
    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, nullable=False)
    minio_key = Column(String(255), unique=True, nullable=False)
    original_filename = Column(String(255), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    status = Column(String(30), default="pending")
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PdfPage(Base):
    """Single page from a PDF."""
    __tablename__ = "pdf_pages"
    
    id = Column(Integer, primary_key=True, index=True)
    pdf_source_id = Column(Integer, nullable=False)
    page_num = Column(Integer, nullable=False)
    image_minio_key = Column(String(255), nullable=True)
    ocr_text = Column(Text, nullable=True)
    ocr_confidence = Column(Integer, nullable=True)
    needs_review = Column(Boolean, default=False)
    reviewed_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class Problem(Base):
    """Extracted problem/exercise from a textbook."""
    __tablename__ = "problems"
    
    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, nullable=False)
    source_page_id = Column(Integer, nullable=True)
    number = Column(String(50), nullable=True)
    section = Column(String(100), nullable=True)
    problem_text = Column(Text, nullable=False)
    problem_text_clean = Column(Text, nullable=True)  # After OCR post-processing
    solution_text = Column(Text, nullable=True)
    answer_text = Column(Text, nullable=True)
    page_ref = Column(String(50), nullable=True)
    bbox = Column(JSON, nullable=True)
    problem_type = Column(String(20), default="unknown")  # question, exercise, unknown
    has_parts = Column(Boolean, default=False)  # Multi-part problem
    confidence = Column(Integer, nullable=True)
    needs_review = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProblemPart(Base):
    """
    Sub-item of a multi-part problem.
    
    Example: "4. Найдите смежные углы, если: 1) ... 2) ... 3) ... 4) ..."
    Each "1)", "2)", etc. is a separate ProblemPart.
    """
    __tablename__ = "problem_parts"
    
    id = Column(Integer, primary_key=True, index=True)
    problem_id = Column(Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    
    part_number = Column(String(10), nullable=False)  # "1", "2", "а", "б"
    part_text = Column(Text, nullable=True)
    answer_text = Column(Text, nullable=True)
    solution_text = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
