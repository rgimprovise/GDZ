"""
Pydantic schemas for API request/response validation.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ── Health ──────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.2.0"
    timestamp: datetime


# ── Conversation ────────────────────────────────────

class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)


class ConversationResponse(BaseModel):
    id: int
    openai_thread_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationListItem(BaseModel):
    id: int
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_message: Optional[str] = None

    class Config:
        from_attributes = True


# ── Message ─────────────────────────────────────────

class MessageSend(BaseModel):
    """Text message input. Audio/image are sent as multipart form."""
    text: str = Field(..., min_length=1, max_length=4000)


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    input_type: str
    tokens_used: int
    created_at: datetime

    class Config:
        from_attributes = True


class AssistantReply(BaseModel):
    """Pair: saved user message + assistant reply."""
    user_message: MessageResponse
    assistant_message: MessageResponse


# ── User ────────────────────────────────────────────

class UserResponse(BaseModel):
    id: int
    tg_uid: int
    username: Optional[str]
    display_name: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Plan ────────────────────────────────────────────

class PlanResponse(BaseModel):
    id: int
    name: str
    type: str
    daily_queries: int
    monthly_queries: int
    price_monthly: int
    price_yearly: int
    features: dict

    class Config:
        from_attributes = True
