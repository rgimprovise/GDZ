"""
TutorBot API - FastAPI Application
"""
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Header, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db, engine, Base
from models import Query, User, QueryStatus, Subscription, Plan, SubscriptionStatus
from schemas import (
    HealthResponse, 
    QueryCreate, 
    QueryResponse, 
    QueryDetailResponse
)
from job_queue import enqueue_query_job
from auth import TelegramUser, get_current_user_from_init_data
from routers import auth as auth_router
from routers import debug as debug_router

settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title="TutorBot API",
    description="Educational tutoring assistant API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware for TMA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to Telegram domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router.router)
app.include_router(debug_router.router)


# ===========================================
# Health Check
# ===========================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check():
    """
    Health check endpoint.
    Returns service status and version.
    """
    return HealthResponse(
        status="ok",
        version="0.1.0",
        timestamp=datetime.utcnow()
    )


# ===========================================
# Query Endpoints
# ===========================================

def get_user_id_from_auth(
    tg_user: Optional[TelegramUser],
    tg_user_id_header: Optional[str],
    db: Session,
    fallback_user_id: int = 1
) -> int:
    """Get user ID from Telegram auth, header, or fallback to test user."""
    # Try TMA initData first
    if tg_user:
        user = db.query(User).filter(User.tg_uid == tg_user.id).first()
        if user:
            return user.id
    
    # Try X-Telegram-User-Id header (from bot)
    if tg_user_id_header:
        try:
            tg_uid = int(tg_user_id_header)
            user = db.query(User).filter(User.tg_uid == tg_uid).first()
            if user:
                return user.id
        except ValueError:
            pass
    
    return fallback_user_id


@app.post(
    "/v1/queries", 
    response_model=QueryResponse, 
    status_code=status.HTTP_201_CREATED,
    tags=["Queries"]
)
def create_query(
    query_data: QueryCreate,
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
):
    """
    Create a new homework query.
    
    The query is queued for processing by a worker.
    Poll GET /v1/queries/{id} to check status.
    
    Authentication: 
    - X-Telegram-Init-Data header (TMA)
    - X-Telegram-User-Id header (Bot)
    - Falls back to test user (user_id=1)
    """
    # Validate input
    if not query_data.text and not query_data.photo_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either text or photo_keys must be provided"
        )
    
    # Get user ID
    user_id = get_user_id_from_auth(tg_user, x_telegram_user_id, db)
    
    # Check user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Create a test user or authenticate via Telegram."
        )
    
    # Check subscription limits
    subscription = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .filter(Subscription.status == "active")
        .first()
    )
    
    if subscription:
        plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()
        if plan and subscription.queries_used_today >= plan.daily_queries:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily query limit reached ({plan.daily_queries}). Upgrade your plan or try tomorrow."
            )
    
    # Create query record
    query = Query(
        user_id=user_id,
        input_text=query_data.text,
        input_photo_keys=query_data.photo_keys or [],
        status=QueryStatus.QUEUED,
    )
    db.add(query)
    db.commit()
    db.refresh(query)
    
    # Update usage counter
    if subscription:
        subscription.queries_used_today += 1
        subscription.queries_used_month += 1
        subscription.last_query_date = datetime.utcnow()
        db.commit()
    
    # Enqueue job for worker
    try:
        job_id = enqueue_query_job(query.id)
        print(f"📬 Enqueued job {job_id} for query {query.id}")
    except Exception as e:
        # Log error but don't fail the request
        print(f"⚠️ Failed to enqueue job for query {query.id}: {e}")
    
    return query


@app.get(
    "/v1/queries/{query_id}", 
    response_model=QueryDetailResponse,
    tags=["Queries"]
)
def get_query(
    query_id: int,
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
):
    """
    Get query by ID with its response if available.
    """
    query = db.query(Query).filter(Query.id == query_id).first()
    
    if not query:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query not found"
        )
    
    # Optional: check that user owns this query
    if tg_user:
        user = db.query(User).filter(User.tg_uid == tg_user.id).first()
        if user and query.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this query"
            )
    
    return query


@app.get(
    "/v1/queries",
    response_model=list[QueryResponse],
    tags=["Queries"]
)
def list_queries(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
):
    """
    List user's queries.
    
    Returns queries for authenticated user, or all queries in dev mode.
    """
    query = db.query(Query)
    
    if tg_user:
        user = db.query(User).filter(User.tg_uid == tg_user.id).first()
        if user:
            query = query.filter(Query.user_id == user.id)
    
    queries = (
        query
        .order_by(Query.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    return queries


# ===========================================
# Startup Events
# ===========================================

@app.on_event("startup")
async def startup_event():
    """Initialize resources on startup."""
    print(f"🚀 TutorBot API starting in {settings.env} mode")
    print(f"📦 Database: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    print(f"📮 Redis: {settings.redis_url}")
    print(f"📚 Docs: http://localhost:8000/docs")
    print(f"🔧 Debug Panel: http://localhost:8000/debug")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    print("👋 TutorBot API shutting down")
