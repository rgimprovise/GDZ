"""
Постобработка нормализованного OCR через OpenAI: исправление ошибок распознавания
и приведение формул к единому формату, пригодному для БД, чата и скриптов.

Без шаблонных замен — модель исправляет по контексту (предмет, учебник).
"""

import os
import re
from typing import List, Optional

# Регулярка для разбора ответа по блокам ## Страница N
PAGE_HEADER = re.compile(r"^##\s+Страница\s+(\d+)\s*$", re.IGNORECASE)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL_TEXT", "gpt-4o")

SYSTEM_PROMPT = """Ты исправляешь текст после OCR учебника. Исходный текст содержит ошибки распознавания и неудобные обозначения формул.

ЗАДАЧИ:
1. Исправить ошибки OCR: латиница вместо кириллицы (TEOPEMA → ТЕОРЕМА, CHHYCOB → СИНУСОВ), перепутанные символы (6↔b, ?↔²), склеенные слова.
2. Привести математические формулы к единому формату:
   - Использовать ТОЛЬКО символы, которые корректно отображаются в обычном тексте, в мессенджерах и в БД: Unicode (², ³, √, ∠, °, ×, ÷, π, ≤, ≥, ≠, ∞, ±, ≈) и при необходимости ^ для степени (x^2).
   - НЕ использовать LaTeX с обратным слэшем (\\frac, \\sqrt и т.п.).
   - Дроби: записывать как a/b или в одну строку с ÷.
   - Формулы должны быть понятны и человеку, и скриптам/LLM при чтении текста.
3. Сохранить структуру: каждый блок должен начинаться с заголовка "## Страница N" и содержать только текст этой страницы. Порядок страниц не менять.
4. Контекст: учебник по указанному предмету — используй его для уточнения формул и терминов.

ФОРМАТ ОТВЕТА: верни исправленный текст в том же виде — блоки "## Страница 1", "## Страница 2", ... с пустой строкой после заголовка и текстом страницы. Никаких комментариев до или после блоков."""


def _parse_pages_from_response(content: str) -> List[tuple[int, str]]:
    """Разобрать ответ модели по блокам ## Страница N. Возвращает [(page_num, text), ...]."""
    result = []
    current_page = None
    current_lines = []
    for line in content.split("\n"):
        match = PAGE_HEADER.match(line.strip())
        if match:
            if current_page is not None:
                result.append((current_page, "\n".join(current_lines).strip()))
            current_page = int(match.group(1))
            current_lines = []
            continue
        if current_page is not None:
            current_lines.append(line)
    if current_page is not None:
        result.append((current_page, "\n".join(current_lines).strip()))
    return result


def _build_batch_chunk(page_texts: List[str], start_index: int) -> str:
    """Собрать один батч для отправки: ## Страница (start+1) ... ## Страница (start+len)."""
    lines = []
    for i, text in enumerate(page_texts):
        page_num = start_index + i + 1
        lines.append(f"## Страница {page_num}")
        lines.append("")
        lines.append((text or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip()


def correct_normalized_pages(
    page_texts: List[str],
    subject: str = "geometry",
    batch_size: int = 10,
    model: Optional[str] = None,
) -> List[str]:
    """
    Прогнать нормализованный постраничный текст через OpenAI для исправления OCR и формул.

    Ограничения на символы в формулах заданы в SYSTEM_PROMPT (Unicode + ^, без LaTeX).
    При отсутствии API ключа или ошибке возвращается исходный список без изменений.

    Args:
        page_texts: список текстов страниц (после ocr_cleaner).
        subject: предмет (geometry, math, physics, ...) для контекста.
        batch_size: сколько страниц отправлять в одном запросе.
        model: модель OpenAI (по умолчанию из env или gpt-4o).

    Returns:
        Список исправленных текстов той же длины.
    """
    if not page_texts:
        return page_texts
    if not OPENAI_API_KEY:
        print("   ⚠️  OPENAI_API_KEY не задан, пропуск LLM-коррекции формул")
        return page_texts

    try:
        from openai import OpenAI
    except ImportError:
        print("   ⚠️  openai не установлен, пропуск LLM-коррекции")
        return page_texts

    client = OpenAI(api_key=OPENAI_API_KEY)
    model_name = model or os.environ.get("OPENAI_MODEL_TEXT", OPENAI_MODEL)
    result: List[str] = [""] * len(page_texts)  # заполним по индексам
    total_batches = (len(page_texts) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(page_texts))
        batch = page_texts[start:end]
        chunk = _build_batch_chunk(batch, start)
        if not chunk.strip():
            for i in range(start, end):
                result[i] = page_texts[i]
            continue

        user_content = f"Предмет: {subject}.\n\nИсходный текст (блоки страниц):\n\n{chunk}"

        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
            )
            answer = (resp.choices[0].message.content or "").strip()
            parsed = _parse_pages_from_response(answer)
            for page_num, text in parsed:
                idx = page_num - 1
                if 0 <= idx < len(result):
                    result[idx] = text
            # Страницы, которых не оказалось в ответе, оставляем как были
            for i in range(start, end):
                if not result[i] and i < len(page_texts):
                    result[i] = page_texts[i]
        except Exception as e:
            print(f"   ⚠️  LLM-коррекция батча {batch_idx + 1}/{total_batches}: {e}")
            for i in range(start, end):
                result[i] = page_texts[i]

        if (batch_idx + 1) % 5 == 0 or batch_idx == total_batches - 1:
            print(f"   🤖 LLM-коррекция: {min(end, len(page_texts))}/{len(page_texts)} страниц")

    # Заполнить возможные пропуски
    for i in range(len(result)):
        if not result[i] and i < len(page_texts):
            result[i] = page_texts[i]
    return result
