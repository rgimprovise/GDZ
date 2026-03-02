"""
Conversations & messages router.

Replaces the old /v1/queries endpoints.  All LLM work is done via
OpenAI Assistants API; audio and images are pre-processed into text
before being sent to the assistant.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, Header
from sqlalchemy.orm import Session

from config import get_settings
from auth import TelegramUser, get_current_user_from_init_data
from database import get_db
from models import Conversation, Message, User, Subscription, Plan
from schemas import (
    AssistantReply,
    ConversationCreate,
    ConversationListItem,
    ConversationResponse,
    MessageResponse,
    MessageSend,
)
import openai_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/conversations", tags=["Conversations"])


# ── helpers ─────────────────────────────────────────

def _get_or_create_free_plan(db: Session) -> Plan:
    """Return the free plan, creating it if needed."""
    plan = db.query(Plan).filter(Plan.type == "free").first()
    if plan:
        return plan
    plan = Plan(
        name="Free", type="free",
        daily_queries=20, monthly_queries=500,
        price_monthly=0, price_yearly=0,
        features={"hints_only": False},
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def _create_user_and_subscription(
    db: Session,
    tg_uid: int,
    username: Optional[str] = None,
    display_name: Optional[str] = None,
    language_code: str = "ru",
) -> User:
    """Create a new user and their free subscription."""
    free_plan = _get_or_create_free_plan(db)
    user = User(
        tg_uid=tg_uid,
        username=username or f"user_{tg_uid}",
        display_name=display_name or f"User {tg_uid}",
        language_code=language_code,
    )
    db.add(user)
    db.flush()
    sub = Subscription(user_id=user.id, plan_id=free_plan.id)
    db.add(sub)
    db.commit()
    db.refresh(user)
    logger.info("Created user tg_uid=%s (id=%s) with free subscription", tg_uid, user.id)
    return user


def _resolve_user(
    db: Session,
    tg_user: Optional[TelegramUser],
    tg_user_id_header: Optional[str],
) -> User:
    """Find or create DB user from Telegram auth; without auth use or create guest."""
    if tg_user:
        user = db.query(User).filter(User.tg_uid == tg_user.id).first()
        if user:
            return user
        display_name = f"{tg_user.first_name} {tg_user.last_name or ''}".strip() or f"User {tg_user.id}"
        return _create_user_and_subscription(
            db,
            tg_uid=tg_user.id,
            username=tg_user.username,
            display_name=display_name,
            language_code=tg_user.language_code or "ru",
        )

    if tg_user_id_header:
        try:
            tg_uid = int(tg_user_id_header)
            user = db.query(User).filter(User.tg_uid == tg_uid).first()
            if user:
                return user
            return _create_user_and_subscription(db, tg_uid=tg_uid)
        except ValueError:
            pass

    user = db.query(User).filter(User.tg_uid == 0).first()
    if user:
        return user

    free_plan = _get_or_create_free_plan(db)
    user = User(tg_uid=0, username="guest", display_name="Гость", language_code="ru")
    db.add(user)
    db.flush()
    sub = Subscription(user_id=user.id, plan_id=free_plan.id)
    db.add(sub)
    db.commit()
    db.refresh(user)
    return user


def _unlimited_tg_ids() -> set[int]:
    s = get_settings()
    if not s.unlimited_tg_ids:
        return set()
    out: set[int] = set()
    for x in s.unlimited_tg_ids.split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.add(int(x))
        except ValueError:
            logger.warning("Invalid unlimited_tg_ids entry: %r", x)
    return out


def _check_limits(
    db: Session,
    user: User,
    x_telegram_user_id: Optional[str] = None,
) -> None:
    """Enforce daily query limits; raises 429 on exceed."""
    unlimited = _unlimited_tg_ids()
    if user.tg_uid in unlimited:
        return
    if x_telegram_user_id:
        try:
            if int(x_telegram_user_id) in unlimited:
                return
        except ValueError:
            pass
    subscription = (
        db.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == "active")
        .first()
    )
    if not subscription:
        return

    plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()
    if plan and subscription.queries_used_today >= plan.daily_queries:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Daily limit reached ({plan.daily_queries}). Upgrade or try tomorrow.",
        )


def _bump_usage(db: Session, user: User) -> None:
    subscription = (
        db.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == "active")
        .first()
    )
    if subscription:
        subscription.queries_used_today += 1
        subscription.queries_used_month += 1
        subscription.last_query_date = datetime.utcnow()
        db.commit()


# ── CRUD ────────────────────────────────────────────

@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
):
    user = _resolve_user(db, tg_user, x_telegram_user_id)

    try:
        thread_id = openai_service.create_thread()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI not configured (missing API key)",
        ) from e
    except Exception as e:
        logger.exception("create_thread failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant temporarily unavailable. Check OPENAI_API_KEY and network.",
        ) from e

    conv = Conversation(
        user_id=user.id,
        openai_thread_id=thread_id,
        title=body.title,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.get("", response_model=list[ConversationListItem])
def list_conversations(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
):
    user = _resolve_user(db, tg_user, x_telegram_user_id)
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    result = []
    for c in convs:
        last_msg = None
        if c.messages:
            last_msg = c.messages[-1].content[:120]
        result.append(ConversationListItem(
            id=c.id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
            last_message=last_msg,
        ))
    return result


@router.get("/{conversation_id}", response_model=list[MessageResponse])
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
):
    user = _resolve_user(db, tg_user, x_telegram_user_id)
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv.messages


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
):
    user = _resolve_user(db, tg_user, x_telegram_user_id)
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    openai_service.delete_thread(conv.openai_thread_id)
    db.delete(conv)
    db.commit()


# ── Send message (text) ────────────────────────────

@router.post("/{conversation_id}/messages", response_model=AssistantReply)
def send_text_message(
    conversation_id: int,
    body: MessageSend,
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
):
    user = _resolve_user(db, tg_user, x_telegram_user_id)
    conv = _get_conv(db, conversation_id, user)
    _check_limits(db, user, x_telegram_user_id)

    return _process_text(db, conv, body.text, "text", user)


# ── Send audio ──────────────────────────────────────

@router.post("/{conversation_id}/audio", response_model=AssistantReply)
def send_audio_message(
    conversation_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
):
    user = _resolve_user(db, tg_user, x_telegram_user_id)
    conv = _get_conv(db, conversation_id, user)
    _check_limits(db, user, x_telegram_user_id)

    audio_bytes = file.file.read()
    text = openai_service.transcribe_audio(audio_bytes, filename=file.filename or "audio.webm")
    if not text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not transcribe audio")

    return _process_text(db, conv, text, "audio", user)


# ── Send image ──────────────────────────────────────

@router.post("/{conversation_id}/image", response_model=AssistantReply)
def send_image_message(
    conversation_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tg_user: Optional[TelegramUser] = Depends(get_current_user_from_init_data),
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
):
    user = _resolve_user(db, tg_user, x_telegram_user_id)
    conv = _get_conv(db, conversation_id, user)
    _check_limits(db, user, x_telegram_user_id)

    image_bytes = file.file.read()
    mime = file.content_type or "image/jpeg"
    text = openai_service.recognise_image(image_bytes, mime_type=mime)
    if not text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not recognise image")

    return _process_text(db, conv, text, "image", user)


# ── internal ────────────────────────────────────────

def _get_conv(db: Session, conversation_id: int, user: User) -> Conversation:
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


def _process_text(
    db: Session,
    conv: Conversation,
    user_text: str,
    input_type: str,
    user: User,
) -> AssistantReply:
    """Save user msg, call assistant, save reply, return both."""
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        content=user_text,
        input_type=input_type,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    reply_text, tokens = openai_service.send_message_and_run(
        conv.openai_thread_id, user_text,
    )

    assistant_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=reply_text,
        input_type="text",
        tokens_used=tokens,
    )
    db.add(assistant_msg)

    if not conv.title and len(user_text) > 0:
        conv.title = user_text[:80]
    conv.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(assistant_msg)

    _bump_usage(db, user)

    return AssistantReply(
        user_message=MessageResponse.model_validate(user_msg),
        assistant_message=MessageResponse.model_validate(assistant_msg),
    )
