"""
TutorBot Telegram Bot — minimal launcher for the TMA.

Features:
- /start — register user in DB + welcome message + WebApp button
- /help  — brief instructions
"""
import asyncio
import logging

import httpx
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from config import get_settings

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

settings = get_settings()

TMA_URL = settings.tma_url
API_URL = settings.api_internal_url.rstrip("/")


async def _register_user(user) -> None:
    """Call API to register / update the Telegram user in the DB."""
    payload = {
        "tg_uid": user.id,
        "username": user.username,
        "first_name": user.first_name or "",
        "last_name": user.last_name,
        "language_code": user.language_code or "ru",
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{API_URL}/v1/auth/register-tg", json=payload)
        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info(
                "Registered tg_uid=%s, db_id=%s, new=%s",
                user.id, data.get("user_id"), data.get("is_new_user"),
            )
        else:
            logger.warning("register-tg returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.error("Failed to register user %s: %s", user.id, exc)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info("User %s (%s) started the bot", user.id, user.username)

    await _register_user(user)

    sep = "&" if "?" in TMA_URL else "?"
    user_tma_url = f"{TMA_URL}{sep}tg_uid={user.id}"

    keyboard = ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    text="Открыть TutorBot",
                    web_app=WebAppInfo(url=user_tma_url),
                )
            ]
        ],
        resize_keyboard=True,
    )

    await update.message.reply_text(
        f"Привет, {user.first_name}!\n\n"
        "Я — TutorBot, образовательный помощник.\n"
        "Нажми кнопку ниже, чтобы открыть приложение.",
        reply_markup=keyboard,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "TutorBot помогает разобраться с домашними заданиями.\n\n"
        "Нажми кнопку «Открыть TutorBot» внизу экрана, "
        "чтобы задать вопрос текстом, голосом или фото.",
    )


def main() -> None:
    print(f"TutorBot Bot | env={settings.env} | TMA={TMA_URL}")

    if not settings.telegram_bot_token or settings.telegram_bot_token.startswith("your_"):
        logger.warning("TELEGRAM_BOT_TOKEN not set — standby mode")
        while True:
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(60))

    application = Application.builder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    logger.info("Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
