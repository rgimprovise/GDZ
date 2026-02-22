"""
Telegram authentication utilities.

Implements validation of Telegram Mini App initData according to:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qs, unquote

from fastapi import HTTPException, status, Depends, Header
from pydantic import BaseModel

from config import get_settings

settings = get_settings()


class TelegramUser(BaseModel):
    """Telegram user data from initData."""
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None
    is_premium: Optional[bool] = None
    photo_url: Optional[str] = None


class InitDataPayload(BaseModel):
    """Parsed and validated initData payload."""
    user: TelegramUser
    auth_date: int
    hash: str
    query_id: Optional[str] = None
    chat_instance: Optional[str] = None
    chat_type: Optional[str] = None
    start_param: Optional[str] = None


def validate_init_data(init_data: str, bot_token: str) -> InitDataPayload:
    """
    Validate Telegram Mini App initData.
    
    Args:
        init_data: Raw initData string from Telegram WebApp
        bot_token: Bot token for HMAC validation
        
    Returns:
        Parsed InitDataPayload
        
    Raises:
        HTTPException: If validation fails
    """
    if not init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing initData"
        )
    
    # Parse the query string
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        # Convert lists to single values
        data = {k: v[0] if v else "" for k, v in parsed.items()}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid initData format"
        )
    
    # Extract hash
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing hash in initData"
        )
    
    # Build data-check-string (sorted alphabetically)
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items())
    )
    
    # Compute secret key: HMAC-SHA256(bot_token, "WebAppData")
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256
    ).digest()
    
    # Compute hash: HMAC-SHA256(data_check_string, secret_key)
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Compare hashes
    if not hmac.compare_digest(computed_hash, received_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid initData signature"
        )
    
    # Check auth_date (not too old, e.g., 24 hours)
    auth_date = int(data.get("auth_date", 0))
    max_age_seconds = 24 * 60 * 60  # 24 hours
    
    if time.time() - auth_date > max_age_seconds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="initData expired"
        )
    
    # Parse user JSON
    user_json = data.get("user", "{}")
    try:
        user_data = json.loads(unquote(user_json))
        user = TelegramUser(**user_data)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user data in initData"
        )
    
    return InitDataPayload(
        user=user,
        auth_date=auth_date,
        hash=received_hash,
        query_id=data.get("query_id"),
        chat_instance=data.get("chat_instance"),
        chat_type=data.get("chat_type"),
        start_param=data.get("start_param"),
    )


def get_current_user_from_init_data(
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data")
) -> Optional[TelegramUser]:
    """
    FastAPI dependency to extract and validate Telegram user from initData header.
    
    Usage:
        @app.get("/protected")
        def protected_route(user: TelegramUser = Depends(get_current_user_from_init_data)):
            return {"user_id": user.id}
    """
    if not x_telegram_init_data:
        return None
    
    if not settings.telegram_bot_token:
        # Skip validation in development if no token configured
        return None
    
    payload = validate_init_data(x_telegram_init_data, settings.telegram_bot_token)
    return payload.user


def require_telegram_auth(
    user: Optional[TelegramUser] = Depends(get_current_user_from_init_data)
) -> TelegramUser:
    """
    FastAPI dependency that requires valid Telegram authentication.
    
    Raises HTTPException 401 if not authenticated.
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram authentication required"
        )
    return user
