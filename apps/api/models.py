"""
SQLAlchemy models for TutorBot.

Simplified schema: users, plans, subscriptions, conversations, messages.
All content retrieval is handled by OpenAI Assistants API + Vector Store.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, DateTime,
    ForeignKey, Boolean, JSON,
)
from sqlalchemy.orm import relationship

from database import Base


class PlanType(str, enum.Enum):
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class InputType(str, enum.Enum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"


# ── User ─────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tg_uid = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    language_code = Column(String(10), default="ru")
    is_active = Column(Boolean, default=True)

    accepted_terms_at = Column(DateTime, nullable=True)
    accepted_privacy_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subscriptions = relationship("Subscription", back_populates="user")
    conversations = relationship("Conversation", back_populates="user")


# ── Plan & Subscription ─────────────────────────────

class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    type = Column(String(20), default="free")

    daily_queries = Column(Integer, default=5)
    monthly_queries = Column(Integer, default=50)

    price_monthly = Column(Integer, default=0)
    price_yearly = Column(Integer, default=0)

    features = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    subscriptions = relationship("Subscription", back_populates="plan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)

    status = Column(String(20), default="active")

    queries_used_today = Column(Integer, default=0)
    queries_used_month = Column(Integer, default=0)
    last_query_date = Column(DateTime, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")


# ── Conversation & Message ──────────────────────────

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    openai_thread_id = Column(String(255), unique=True, nullable=False)
    title = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="conversations")
    messages = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False,
    )

    role = Column(String(20), nullable=False)       # user | assistant
    content = Column(Text, nullable=False)
    input_type = Column(String(20), default="text")  # text | audio | image
    tokens_used = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
