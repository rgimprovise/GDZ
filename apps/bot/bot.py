"""
TutorBot Telegram Bot — minimal launcher for the TMA.

Features:
- /start — welcome message + WebApp button to open TMA
- /help  — brief instructions
"""
import asyncio
import logging

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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info("User %s (%s) started the bot", user.id, user.username)

    keyboard = ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    text="Открыть TutorBot",
                    web_app=WebAppInfo(url=TMA_URL),
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
