"""
TutorBot Telegram Bot

Features:
- /start, /help commands
- Text messages → create query via API
- Photo messages → upload to MinIO and create query
- Push notifications when query is done
"""
import asyncio
import logging
import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import get_settings

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

settings = get_settings()

# API base URL (внутри Docker network)
API_URL = "http://api:8000"


# ===========================================
# Command Handlers
# ===========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot")
    
    # Check for deep link parameters
    if context.args:
        param = context.args[0]
        if param.startswith("query_"):
            query_id = param.replace("query_", "")
            await update.message.reply_text(
                f"📋 Открываю результат запроса #{query_id}...\n\n"
                f"Используй Mini App для просмотра полного ответа.",
                parse_mode="Markdown"
            )
            return
    
    welcome_message = f"""👋 Привет, {user.first_name}!

Я — **TutorBot**, твой образовательный помощник.

🎯 **Что я умею:**
• Помогаю разобраться с домашними заданиями
• Объясняю решения пошагово
• Ссылаюсь на проверенные источники

📝 **Как использовать:**
1. Отправь мне текст задания
2. Или сфотографируй задачу
3. Получи пошаговое объяснение!

⚡ **Команды:**
/start — Начать работу
/help — Справка
/status — Проверить статус последнего запроса

_Просто отправь задание и я помогу!_
"""
    
    await update.message.reply_text(welcome_message, parse_mode="Markdown")
    
    # Register user via API
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{API_URL}/v1/auth/telegram",
                json={
                    "init_data": f"user=%7B%22id%22%3A{user.id}%2C%22first_name%22%3A%22{user.first_name}%22%7D"
                },
                timeout=5.0
            )
    except Exception as e:
        logger.warning(f"Failed to register user {user.id}: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = """📚 **Справка по TutorBot**

**Как отправить задание:**
• Напиши текст задачи
• Или отправь фото задания
• Можно комбинировать!

**Формат запроса:**
_"Решите уравнение: 2x + 5 = 13"_
_"№123 из учебника алгебры 8 класс"_

**Что получишь:**
✅ Пошаговое объяснение
✅ Ссылки на источники
✅ Проверенное решение

**Команды:**
/start — Начать работу
/help — Эта справка
/status — Статус последнего запроса

🔒 Все ответы основаны на проверенных источниках.
Бот НЕ придумывает решения!
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - check last query status."""
    user = update.effective_user
    
    try:
        async with httpx.AsyncClient() as client:
            # Get user's queries
            response = await client.get(
                f"{API_URL}/v1/queries",
                params={"limit": 1},
                headers={"X-Telegram-User-Id": str(user.id)},
                timeout=5.0
            )
            
            if response.status_code == 200:
                queries = response.json()
                if queries:
                    q = queries[0]
                    status_emoji = {
                        "queued": "⏳",
                        "processing": "🔄",
                        "done": "✅",
                        "failed": "❌",
                        "needs_choice": "❓"
                    }.get(q["status"], "❔")
                    
                    text = f"""{status_emoji} **Последний запрос #{q['id']}**

📝 {q['input_text'][:100] if q['input_text'] else 'Фото'}...
📊 Статус: `{q['status']}`
🕐 Создан: {q['created_at'][:19]}
"""
                    if q["status"] == "done":
                        text += "\n✅ Ответ готов! Отправь /result для просмотра."
                    
                    await update.message.reply_text(text, parse_mode="Markdown")
                else:
                    await update.message.reply_text(
                        "У тебя пока нет запросов. Отправь мне задание!"
                    )
            else:
                await update.message.reply_text("Не удалось получить статус.")
                
    except Exception as e:
        logger.error(f"Error getting status for user {user.id}: {e}")
        await update.message.reply_text("❌ Ошибка при проверке статуса.")


# ===========================================
# Message Handlers
# ===========================================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages - create query."""
    user = update.effective_user
    text = update.message.text
    
    logger.info(f"User {user.id} sent text: {text[:50]}...")
    
    # Send "typing" action
    await update.message.chat.send_action("typing")
    
    try:
        async with httpx.AsyncClient() as client:
            # First, ensure user exists
            await client.post(
                f"{API_URL}/v1/auth/telegram",
                json={
                    "init_data": f"user=%7B%22id%22%3A{user.id}%2C%22first_name%22%3A%22{user.first_name}%22%2C%22username%22%3A%22{user.username or ''}%22%7D"
                },
                timeout=5.0
            )
            
            # Create query
            response = await client.post(
                f"{API_URL}/v1/queries",
                json={"text": text},
                headers={"X-Telegram-User-Id": str(user.id)},
                timeout=10.0
            )
            
            if response.status_code == 201:
                query_data = response.json()
                await update.message.reply_text(
                    f"✅ **Запрос #{query_data['id']} принят!**\n\n"
                    f"📝 _{text[:100]}{'...' if len(text) > 100 else ''}_\n\n"
                    f"⏳ Обрабатываю... Пришлю ответ когда будет готов!\n"
                    f"Используй /status для проверки.",
                    parse_mode="Markdown"
                )
                logger.info(f"Created query {query_data['id']} for user {user.id}")
            elif response.status_code == 429:
                await update.message.reply_text(
                    "⚠️ **Достигнут лимит запросов**\n\n"
                    "Попробуй завтра или обнови подписку.",
                    parse_mode="Markdown"
                )
            else:
                error_detail = response.json().get("detail", "Unknown error")
                await update.message.reply_text(
                    f"❌ Ошибка при создании запроса:\n{error_detail}"
                )
                logger.error(f"Failed to create query: {response.text}")
                
    except httpx.TimeoutException:
        await update.message.reply_text(
            "⏱️ Сервер не отвечает. Попробуй позже."
        )
    except Exception as e:
        logger.error(f"Error creating query for user {user.id}: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуй ещё раз."
        )


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages - create query with photo."""
    user = update.effective_user
    photo = update.message.photo[-1]  # Largest photo
    caption = update.message.caption or ""
    
    logger.info(f"User {user.id} sent photo (file_id: {photo.file_id})")
    
    await update.message.reply_text(
        "📷 Фото получено!\n\n"
        "⚠️ _Обработка фото пока в разработке._\n"
        "Пожалуйста, отправь текст задания.",
        parse_mode="Markdown"
    )
    
    # TODO: Implement photo handling
    # 1. Download photo via bot.get_file()
    # 2. Upload to MinIO
    # 3. Create query with photo_keys


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document messages."""
    await update.message.reply_text(
        "📎 Документы пока не поддерживаются.\n"
        "Отправь фото или текст задания."
    )


# ===========================================
# Notification Functions (called from worker)
# ===========================================

async def send_query_ready_notification(chat_id: int, query_id: int, preview: str):
    """Send notification when query is ready."""
    # This would be called from the worker via API
    # For now, worker sends directly via Telegram API
    pass


# ===========================================
# Main
# ===========================================

def main() -> None:
    """Start the bot."""
    print("🤖 TutorBot Telegram Bot starting...")
    print(f"🌍 Environment: {settings.env}")
    print(f"🔗 API URL: {API_URL}")
    
    # Check token
    if not settings.telegram_bot_token or settings.telegram_bot_token == "your_telegram_bot_token_here":
        logger.warning("⚠️  TELEGRAM_BOT_TOKEN not set! Bot will not work.")
        logger.info("Set TELEGRAM_BOT_TOKEN in .env file to enable the bot.")
        
        # Keep container running for docker-compose
        print("🔄 Running in standby mode (no token configured)...")
        while True:
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(60))
    
    # Create application
    application = Application.builder().token(settings.telegram_bot_token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    
    # Add message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Log startup
    logger.info("✅ Bot handlers registered")
    logger.info("🚀 Starting polling...")
    
    # Start polling (for development)
    # In production, switch to webhook mode
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
