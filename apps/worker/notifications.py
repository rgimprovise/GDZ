"""
Notification utilities for sending messages via Telegram bot.
"""
import httpx
from typing import Optional

from config import get_settings

settings = get_settings()


async def send_telegram_notification(
    chat_id: int,
    message: str,
    parse_mode: str = "Markdown",
) -> bool:
    """Send a notification message via Telegram bot."""
    if not settings.telegram_bot_token or settings.telegram_bot_token.startswith("your_"):
        print(f"⚠️ Telegram token not configured, skipping notification to {chat_id}")
        return False
    
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            
            if response.status_code == 200:
                print(f"✅ Notification sent to {chat_id}")
                return True
            else:
                print(f"❌ Failed to send notification: {response.text}")
                return False
                
    except Exception as e:
        print(f"❌ Error sending notification: {e}")
        return False


def send_telegram_notification_sync(
    chat_id: int,
    message: str,
    parse_mode: str = "Markdown",
) -> bool:
    """Synchronous version of send_telegram_notification."""
    import requests
    
    if not settings.telegram_bot_token or settings.telegram_bot_token.startswith("your_"):
        print(f"⚠️ Telegram token not configured, skipping notification to {chat_id}")
        return False
    
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            print(f"✅ Notification sent to {chat_id}")
            return True
        else:
            print(f"❌ Failed to send notification: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error sending notification: {e}")
        return False


def build_query_ready_message(
    query_id: int, 
    preview: str,
    answer_content: str = None,
    book_title: str = None,
    problem_number: str = None,
    confidence: int = None
) -> str:
    """Build notification message - shows answer directly in message."""
    
    # Short version if no answer
    if not answer_content:
        return f"""❌ Задача не найдена

Не удалось найти похожую задачу в базе.

Попробуйте:
• Переформулировать запрос
• Указать номер задачи из учебника
• Отправить фото условия"""
    
    # Truncate long answers for Telegram (max ~4000 chars)
    max_len = 3000
    if len(answer_content) > max_len:
        answer_content = answer_content[:max_len] + "\n\n... (сокращено)"
    
    # Build message - фокус на ответе
    msg = ""
    
    # Источник (компактно)
    if book_title and problem_number:
        msg += f"📚 {book_title}, №{problem_number}\n\n"
    elif book_title:
        msg += f"📚 {book_title}\n\n"
    
    # Сам ответ
    msg += answer_content
    
    return msg


def build_short_answer(
    problem_text: str, 
    solution_text: str = None, 
    answer_text: str = None,
    problem_type: str = 'unknown',
    llm_explanation: str = None,
    part_answer: str = None,
    requested_part: str = None,
    has_parts: bool = False,
) -> str:
    """
    Build answer format suitable for Telegram.
    
    ВАЖНО: НЕ показываем условие задачи - пользователь его уже знает.
    Показываем ТОЛЬКО ответ и/или решение.
    
    Args:
        problem_text: The problem text (not displayed, for context only)
        solution_text: Solution from DB
        answer_text: Answer from DB
        problem_type: 'exercise', 'question', or 'unknown'
        llm_explanation: AI-generated explanation (highest priority)
    
    For 'exercise' type: prioritize showing answer_text (numerical answer)
    For 'question' type: prioritize showing solution_text (theory/proof)
    """
    msg = ""
    
    # Проверяем есть ли вообще ответ или решение
    has_answer = bool(answer_text and answer_text.strip())
    has_solution = bool(solution_text and solution_text.strip())
    has_llm = bool(llm_explanation and llm_explanation.strip())
    has_part_answer = bool(part_answer and part_answer.strip())
    
    # Для задач с подпунктами - используем ответ на конкретный вариант
    if has_parts and has_part_answer:
        if requested_part:
            msg = f"✅ Ответ на вариант {requested_part}): {part_answer}"
        else:
            # Показываем все ответы
            msg = f"✅ Ответы:\n{part_answer}"
        
        # Добавляем LLM объяснение если есть
        if has_llm:
            explanation = llm_explanation
            if len(explanation) > 2000:
                explanation = explanation[:2000] + "..."
            msg += f"\n\n💡 Объяснение:\n\n{explanation}"
        
        return msg
    
    # LLM объяснение — приоритет (для обычных задач)
    if has_llm:
        # Начинаем с ответа если есть
        if has_answer:
            msg = f"✅ Ответ: {answer_text}\n\n"
        
        # LLM объяснение
        explanation = llm_explanation
        if len(explanation) > 2500:
            explanation = explanation[:2500] + "..."
        
        msg += f"💡 Объяснение:\n\n{explanation}"
        return msg
    
    # Без LLM — старая логика
    if problem_type == 'question':
        # Теоретический вопрос - показываем теорию/доказательство
        if has_solution:
            # Проверяем формат "[THEOREM]\n..." от link_theory.py
            if solution_text.startswith('['):
                parts = solution_text.split('\n', 1)
                theory_type = parts[0].strip('[]').lower()
                theory_content = parts[1] if len(parts) > 1 else solution_text
                
                type_labels = {
                    'definition': '📖 Определение',
                    'theorem': '📐 Теорема',
                    'proof': '📝 Доказательство',
                    'property': '📋 Свойство',
                }
                label = type_labels.get(theory_type, '💡 Ответ')
                
                if len(theory_content) > 2000:
                    msg = f"{label}:\n\n{theory_content[:2000]}..."
                else:
                    msg = f"{label}:\n\n{theory_content}"
            else:
                if len(solution_text) > 2000:
                    msg = f"💡 Ответ:\n\n{solution_text[:2000]}..."
                else:
                    msg = f"💡 Ответ:\n\n{solution_text}"
        elif has_answer:
            msg = f"💡 Ответ:\n\n{answer_text}"
        else:
            msg = "ℹ️ К сожалению, ответ на этот вопрос пока не добавлен в базу."
    
    elif problem_type == 'exercise':
        # Числовая задача - показываем ответ, потом решение
        if has_answer:
            msg = f"✅ Ответ: {answer_text}"
            
            if has_solution:
                if len(solution_text) > 1500:
                    msg += f"\n\n✏️ Решение:\n{solution_text[:1500]}..."
                else:
                    msg += f"\n\n✏️ Решение:\n{solution_text}"
        elif has_solution:
            if len(solution_text) > 2000:
                msg = f"✏️ Решение:\n\n{solution_text[:2000]}..."
            else:
                msg = f"✏️ Решение:\n\n{solution_text}"
        else:
            msg = "ℹ️ К сожалению, ответ на эту задачу пока не добавлен в базу."
    
    else:
        # Неизвестный тип - показываем что есть
        if has_answer:
            msg = f"✅ Ответ: {answer_text}"
            if has_solution:
                if len(solution_text) > 1500:
                    msg += f"\n\n✏️ Решение:\n{solution_text[:1500]}..."
                else:
                    msg += f"\n\n✏️ Решение:\n{solution_text}"
        elif has_solution:
            if len(solution_text) > 2000:
                msg = f"✏️ Решение:\n\n{solution_text[:2000]}..."
            else:
                msg = f"✏️ Решение:\n\n{solution_text}"
        else:
            msg = "ℹ️ Ответ пока не найден в базе."
    
    return msg
