"""
SQLAlchemy models for TutorBot.
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, DateTime, 
    ForeignKey, Enum, Boolean, JSON
)
from sqlalchemy.orm import relationship

from database import Base


class PlanType(str, enum.Enum):
    """Subscription plan types."""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"


class SubscriptionStatus(str, enum.Enum):
    """Subscription status."""
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class QueryStatus(str, enum.Enum):
    """Query processing status."""
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_CHOICE = "needs_choice"
    DONE = "done"
    FAILED = "failed"


# ===========================================
# User Models
# ===========================================

class User(Base):
    """Telegram user."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    tg_uid = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    language_code = Column(String(10), default="ru")
    is_active = Column(Boolean, default=True)
    
    # Consent tracking
    accepted_terms_at = Column(DateTime, nullable=True)
    accepted_privacy_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")
    queries = relationship("Query", back_populates="user")


# ===========================================
# Subscription Models
# ===========================================

class Plan(Base):
    """Subscription plan definition."""
    __tablename__ = "plans"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    type = Column(String(20), default="free")
    
    # Limits
    daily_queries = Column(Integer, default=5)
    monthly_queries = Column(Integer, default=50)
    
    # Pricing (in smallest currency unit, e.g., kopecks)
    price_monthly = Column(Integer, default=0)
    price_yearly = Column(Integer, default=0)
    
    # Features (JSON for flexibility)
    features = Column(JSON, default=dict)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="plan")


class Subscription(Base):
    """User subscription."""
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    
    status = Column(String(20), default="active")
    
    # Usage tracking
    queries_used_today = Column(Integer, default=0)
    queries_used_month = Column(Integer, default=0)
    last_query_date = Column(DateTime, nullable=True)
    
    # Dates
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")


# ===========================================
# Query & Response Models
# ===========================================

class Query(Base):
    """User homework query."""
    __tablename__ = "queries"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Input
    input_text = Column(Text, nullable=True)
    input_photo_keys = Column(JSON, default=list)  # MinIO keys
    
    # OCR results (filled by worker)
    extracted_text = Column(Text, nullable=True)
    ocr_confidence = Column(Integer, nullable=True)  # 0-100
    
    # Processing
    status = Column(String(20), default="queued")
    error_message = Column(Text, nullable=True)
    
    # Costs tracking
    tokens_used = Column(Integer, default=0)
    processing_time_ms = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="queries")
    response = relationship("Response", back_populates="query", uselist=False)


class Response(Base):
    """Generated response for a query."""
    __tablename__ = "responses"
    
    id = Column(Integer, primary_key=True, index=True)
    query_id = Column(Integer, ForeignKey("queries.id"), unique=True, nullable=False)
    
    # Content
    content_markdown = Column(Text, nullable=False)
    
    # Citations (JSON array of {page, bbox, text})
    citations = Column(JSON, default=list)
    
    # Metadata
    model_used = Column(String(50), nullable=True)
    confidence_score = Column(Integer, nullable=True)  # 0-100
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    query = relationship("Query", back_populates="response")


# ===========================================
# Ingestion Models (Books, Problems)
# ===========================================

class IngestionStatus(str, enum.Enum):
    """PDF ingestion status."""
    PENDING = "pending"
    RENDERING = "rendering"
    OCR = "ocr"
    SEGMENTING = "segmenting"
    EMBEDDING = "embedding"
    DONE = "done"
    FAILED = "failed"


class ProblemType(str, enum.Enum):
    """Type of problem/question."""
    QUESTION = "question"    # Control question (theoretical, needs proof/definition)
    EXERCISE = "exercise"    # Numerical exercise (needs answer from answers section)
    UNKNOWN = "unknown"      # Not yet classified


class Book(Base):
    """Textbook / solution book."""
    __tablename__ = "books"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Classification
    subject = Column(String(50), nullable=False, index=True)  # math, physics, etc.
    grade = Column(String(20), nullable=True, index=True)     # "8" or "7-9"
    
    # Metadata
    title = Column(String(255), nullable=False)
    authors = Column(String(255), nullable=True)
    publisher = Column(String(255), nullable=True)
    edition_year = Column(Integer, nullable=True)
    part = Column(String(10), nullable=True)  # "1", "2"
    is_gdz = Column(Boolean, default=False)   # Is this a solutions book?
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    pdf_sources = relationship("PdfSource", back_populates="book")
    problems = relationship("Problem", back_populates="book")
    section_theory = relationship("SectionTheory", back_populates="book", cascade="all, delete-orphan")


class SectionTheory(Base):
    """Теоретический материал параграфа (для ответов на контрольные вопросы и обоснования решений)."""
    __tablename__ = "section_theory"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    section = Column(String(50), nullable=False)   # "§7", "7"
    theory_text = Column(Text, nullable=False)
    page_ref = Column(String(100), nullable=True)  # "стр. 45–48"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    book = relationship("Book", back_populates="section_theory")


class PdfSource(Base):
    """Uploaded PDF file."""
    __tablename__ = "pdf_sources"
    
    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    
    # Storage
    minio_key = Column(String(255), unique=True, nullable=False)
    original_filename = Column(String(255), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    
    # Ingestion status
    status = Column(String(30), default="pending")
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    book = relationship("Book", back_populates="pdf_sources")
    pages = relationship("PdfPage", back_populates="pdf_source")


class PdfPage(Base):
    """Single page from a PDF."""
    __tablename__ = "pdf_pages"
    
    id = Column(Integer, primary_key=True, index=True)
    pdf_source_id = Column(Integer, ForeignKey("pdf_sources.id"), nullable=False)
    
    page_num = Column(Integer, nullable=False)
    
    # Rendered image
    image_minio_key = Column(String(255), nullable=True)
    
    # OCR results
    ocr_text = Column(Text, nullable=True)
    ocr_confidence = Column(Integer, nullable=True)  # 0-100
    
    # Review flags
    needs_review = Column(Boolean, default=False)
    reviewed_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    pdf_source = relationship("PdfSource", back_populates="pages")
    problems = relationship("Problem", back_populates="source_page")


class Problem(Base):
    """Extracted problem/exercise from a textbook."""
    __tablename__ = "problems"
    
    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    source_page_id = Column(Integer, ForeignKey("pdf_pages.id"), nullable=True)
    
    # Problem identification
    number = Column(String(50), nullable=True, index=True)  # "№123", "Упр. 45"
    section = Column(String(100), nullable=True)            # "Глава 3", "§15"
    
    # Content (raw OCR)
    problem_text = Column(Text, nullable=False)
    problem_text_clean = Column(Text, nullable=True)  # After OCR post-processing
    solution_text = Column(Text, nullable=True)
    answer_text = Column(Text, nullable=True)
    
    # Location in PDF
    page_ref = Column(String(50), nullable=True)  # "стр. 45"
    bbox = Column(JSON, nullable=True)            # [x0, y0, x1, y1] on page
    
    # Search / Embeddings (pgvector will be added later)
    # embedding = Column(Vector(1536), nullable=True)
    
    # Classification
    problem_type = Column(String(20), default="unknown")  # question, exercise, unknown
    
    # Multi-part problems (e.g., "4. Найдите... 1) ... 2) ... 3) ...")
    has_parts = Column(Boolean, default=False)
    
    # Quality
    confidence = Column(Integer, nullable=True)   # 0-100
    needs_review = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    book = relationship("Book", back_populates="problems")
    source_page = relationship("PdfPage", back_populates="problems")
    parts = relationship("ProblemPart", back_populates="problem", cascade="all, delete-orphan")


class ProblemPart(Base):
    """
    Sub-item of a multi-part problem.
    
    Example: "4. Найдите смежные углы, если: 1) ... 2) ... 3) ... 4) ..."
    Each "1)", "2)", etc. is a separate ProblemPart.
    """
    __tablename__ = "problem_parts"
    
    id = Column(Integer, primary_key=True, index=True)
    problem_id = Column(Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    
    # Part identification
    part_number = Column(String(10), nullable=False)  # "1", "2", "а", "б"
    
    # Content
    part_text = Column(Text, nullable=True)  # Text of this sub-item
    answer_text = Column(Text, nullable=True)  # Answer for this sub-item
    solution_text = Column(Text, nullable=True)  # Solution (if available)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    problem = relationship("Problem", back_populates="parts")
