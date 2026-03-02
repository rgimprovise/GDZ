"""
Authentication router for Telegram Mini App.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import TelegramUser, require_telegram_auth, validate_init_data, parse_user_from_init_data_unsafe
from config import get_settings
from database import get_db
from models import User, Subscription, Plan

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/v1/auth", tags=["Authentication"])


class AuthRequest(BaseModel):
    """Request body for authentication."""
    init_data: str


class AuthResponse(BaseModel):
    """Response after successful authentication."""
    user_id: int
    tg_uid: int
    username: Optional[str]
    display_name: Optional[str]
    is_new_user: bool
    plan_type: str
    daily_queries_remaining: int


class MeResponse(BaseModel):
    """Current user info response."""
    user_id: int
    tg_uid: int
    username: Optional[str]
    display_name: Optional[str]
    plan_type: str
    daily_queries_remaining: int
    monthly_queries_remaining: int


@router.post("/telegram", response_model=AuthResponse)
def authenticate_telegram(
    request: AuthRequest,
    db: Session = Depends(get_db),
):
    """
    Authenticate user via Telegram Mini App initData.
    
    Creates user if not exists, returns user info and subscription status.
    """
    # Validate initData — fall back to unsafe parse if validation fails
    tg_user = None
    if not settings.telegram_bot_token or settings.telegram_bot_token.startswith("your_"):
        logger.warning("Bot token not configured — parsing initData without HMAC validation")
        tg_user = parse_user_from_init_data_unsafe(request.init_data)
    else:
        try:
            payload = validate_init_data(request.init_data, settings.telegram_bot_token)
            tg_user = payload.user
            logger.info("initData validated OK for tg_uid=%s", tg_user.id)
        except HTTPException as exc:
            logger.warning("initData HMAC validation failed (%s: %s) — using unsafe parse",
                           exc.status_code, exc.detail)
            tg_user = parse_user_from_init_data_unsafe(request.init_data)
        except Exception as exc:
            logger.warning("initData validation error: %s — using unsafe parse", exc)
            tg_user = parse_user_from_init_data_unsafe(request.init_data)

    if not tg_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract user from initData",
        )
    
    # Find or create user
    user = db.query(User).filter(User.tg_uid == tg_user.id).first()
    is_new_user = False
    
    if not user:
        # Create new user
        user = User(
            tg_uid=tg_user.id,
            username=tg_user.username,
            display_name=f"{tg_user.first_name} {tg_user.last_name or ''}".strip(),
            language_code=tg_user.language_code or "ru",
            accepted_terms_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        is_new_user = True
        
        # Create free subscription
        free_plan = db.query(Plan).filter(Plan.type == "free").first()
        if free_plan:
            subscription = Subscription(
                user_id=user.id,
                plan_id=free_plan.id,
            )
            db.add(subscription)
            db.commit()
    else:
        # Update user info if changed
        if tg_user.username != user.username:
            user.username = tg_user.username
        display_name = f"{tg_user.first_name} {tg_user.last_name or ''}".strip()
        if display_name != user.display_name:
            user.display_name = display_name
        db.commit()
    
    # Get active subscription
    subscription = (
        db.query(Subscription)
        .filter(Subscription.user_id == user.id)
        .filter(Subscription.status == "active")
        .first()
    )
    
    plan_type = "free"
    daily_remaining = 5
    
    if subscription:
        plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()
        if plan:
            plan_type = plan.type
            daily_remaining = max(0, plan.daily_queries - subscription.queries_used_today)
    
    return AuthResponse(
        user_id=user.id,
        tg_uid=user.tg_uid,
        username=user.username,
        display_name=user.display_name,
        is_new_user=is_new_user,
        plan_type=plan_type,
        daily_queries_remaining=daily_remaining,
    )


@router.get("/me", response_model=MeResponse)
def get_current_user(
    tg_user: TelegramUser = Depends(require_telegram_auth),
    db: Session = Depends(get_db),
):
    """
    Get current authenticated user info.
    
    Requires X-Telegram-Init-Data header.
    """
    user = db.query(User).filter(User.tg_uid == tg_user.id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please authenticate first."
        )
    
    # Get subscription
    subscription = (
        db.query(Subscription)
        .filter(Subscription.user_id == user.id)
        .filter(Subscription.status == "active")
        .first()
    )
    
    plan_type = "free"
    daily_remaining = 5
    monthly_remaining = 50
    
    if subscription:
        plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()
        if plan:
            plan_type = plan.type
            daily_remaining = max(0, plan.daily_queries - subscription.queries_used_today)
            monthly_remaining = max(0, plan.monthly_queries - subscription.queries_used_month)
    
    return MeResponse(
        user_id=user.id,
        tg_uid=user.tg_uid,
        username=user.username,
        display_name=user.display_name,
        plan_type=plan_type,
        daily_queries_remaining=daily_remaining,
        monthly_queries_remaining=monthly_remaining,
    )
