"""
Pydantic schemas for API request/response validation.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

from models import QueryStatus, PlanType, SubscriptionStatus


# ===========================================
# Health Check
# ===========================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "0.1.0"
    timestamp: datetime


# ===========================================
# Query Schemas
# ===========================================

class QueryCreate(BaseModel):
    """Request to create a new query."""
    text: Optional[str] = Field(None, description="User's text input")
    photo_keys: Optional[List[str]] = Field(
        default_factory=list, 
        description="List of MinIO photo keys"
    )


class QueryResponse(BaseModel):
    """Query response model."""
    id: int
    user_id: int
    input_text: Optional[str]
    status: QueryStatus
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class QueryDetailResponse(QueryResponse):
    """Detailed query response with response content."""
    extracted_text: Optional[str]
    error_message: Optional[str]
    response: Optional["ResponseModel"]


class ResponseModel(BaseModel):
    """Response content model."""
    id: int
    content_markdown: str
    citations: List[dict]
    confidence_score: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True


# ===========================================
# User Schemas  
# ===========================================

class UserResponse(BaseModel):
    """User response model."""
    id: int
    tg_uid: int
    username: Optional[str]
    display_name: Optional[str]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# ===========================================
# Plan Schemas
# ===========================================

class PlanResponse(BaseModel):
    """Plan response model."""
    id: int
    name: str
    type: PlanType
    daily_queries: int
    monthly_queries: int
    price_monthly: int
    price_yearly: int
    features: dict
    
    class Config:
        from_attributes = True


# Update forward refs
QueryDetailResponse.model_rebuild()
