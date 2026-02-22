"""
LLM module for generating grounded explanations.

Uses OpenAI GPT to explain solutions based on:
1. The problem text
2. The answer from the database
3. The theoretical material from the section
"""
import os
import re
from typing import Optional

from openai import OpenAI

# Get API key from environment
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL_TEXT", "gpt-4o-mini")


SYSTEM_PROMPT = """Ты — репетитор по математике и геометрии. Твоя задача — объяснить решение задачи ученику.

ПРАВИЛА:
1. По условию задачи однозначно определи, ЧТО требуется найти (величина, объект, отношение — что угодно из формулировки). В своём объяснении решай строго эту задачу и не подменяй её другой: не меняй искомую величину на другую и не отвечай на другой вопрос.
2. Используй обозначения из условия (буквы, символы из текста задачи) и не вводи лишние переменные без необходимости.
3. Опирайся на теорию из предоставленного МАТЕРИАЛА РАЗДЕЛА, если он подходит по смыслу.
4. Объясняй пошагово и понятно.
5. Если дан ответ — покажи, как к нему прийти; если нет — выведи формулу или результат из условия.
6. Используй обычные математические обозначения: °, ², √ и т.д.
7. Объём: до 300 слов. Формат: краткое объяснение и шаги решения.

Если материала раздела нет или он не по теме — объясни на общих принципах, но искомое в твоём ответе должно совпадать с тем, что просят в условии."""


def _extract_requested_quantity(problem_text: str) -> Optional[str]:
    """Из условия извлекает формулировку «что найти» (по шаблонам «Найдите …», «Найти …», «Чему равна …»)."""
    if not problem_text or len(problem_text.strip()) < 10:
        return None
    patterns = [
        r"найдите\s+([^.,]+?)(?:\.|,|$)",
        r"найти\s+([^.,]+?)(?:\.|,|$)",
        r"чему\s+равн[аоы]\s+([^.?]+)",
    ]
    text_lower = problem_text.strip().lower()
    for pattern in patterns:
        m = re.search(pattern, text_lower, re.IGNORECASE)
        if m:
            phrase = m.group(1).strip()
            if 3 < len(phrase) < 80:
                return phrase
    return None


def get_section_theory(db, book_id: int, section: str) -> str:
    """
    Получить теоретический материал параграфа для LLM (ответы на контрольные вопросы,
    обоснование решений). Сначала берётся сохранённый при ingestion section_theory,
    иначе — эвристика по pdf_pages.ocr_text.
    """
    from sqlalchemy import text
    from models import SectionTheory

    if not section:
        return ""

    section_match = re.search(r"(\d+)", section)
    section_num = section_match.group(1) if section_match else None
    section_label = section if (section and section.strip().startswith("§")) else (f"§{section_num}" if section_num else "")

    # 1. Сохранённый при ingestion теоретический материал
    if section_label:
        row = db.query(SectionTheory).filter(
            SectionTheory.book_id == book_id,
            SectionTheory.section == section_label,
        ).first()
        if row and (row.theory_text or "").strip():
            return (row.theory_text or "").strip()[:8000]

    # 2. Fallback: эвристика по страницам (до появления section_theory в БД)
    if not section_num:
        return ""

    result = db.execute(text("""
        SELECT pp.page_num, pp.ocr_text
        FROM pdf_pages pp
        JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
        WHERE ps.book_id = :book_id
        ORDER BY pp.page_num
    """), {"book_id": book_id})

    theory_texts = []
    in_section = False
    pages_collected = 0
    max_pages = 3

    for row in result:
        ocr_text = row.ocr_text or ""
        section_header = re.search(rf"[§$]\s*{section_num}[.,\s]", ocr_text[:500])
        if section_header:
            in_section = True
        elif in_section:
            new_section = re.search(r"[§$]\s*(\d{1,2})[.,\s]", ocr_text[:300])
            if new_section and new_section.group(1) != section_num:
                break
        if in_section and pages_collected < max_pages:
            text_content = ocr_text
            exercises_start = len(text_content)
            for marker in ["Задачи", "Упражнения", "ЗАДАЧИ", "УПРАЖНЕНИЯ", "Вопросы для"]:
                pos = text_content.find(marker)
                if pos > 0 and pos < exercises_start:
                    exercises_start = pos
            theory_part = text_content[: min(exercises_start, 2500)]
            if len(theory_part) > 100:
                theory_texts.append(theory_part)
                pages_collected += 1

    return "\n\n".join(theory_texts)[:6000]


def generate_solution_explanation(
    problem_text: str,
    answer_text: Optional[str],
    section_theory: Optional[str],
    book_title: str = "",
    section: str = "",
) -> Optional[str]:
    """
    Generate an explanation of the solution using LLM.
    
    Args:
        problem_text: The problem/question text
        answer_text: The answer from the database (if available)
        section_theory: Theoretical material from the section
        book_title: Name of the textbook
        section: Section/paragraph number
        
    Returns:
        Explanation text or None if LLM call fails
    """
    if not OPENAI_API_KEY:
        print("⚠️ OPENAI_API_KEY not set, skipping LLM generation")
        return None
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Build the user prompt; optionally highlight what is asked
        requested = _extract_requested_quantity(problem_text)
        user_prompt = f"""ЗАДАЧА:
{problem_text}

"""
        if requested:
            user_prompt += f"""В УСЛОВИИ ПРОСЯТ НАЙТИ: {requested}. Решай именно эту величину.

"""
        
        if answer_text:
            user_prompt += f"""ИЗВЕСТНЫЙ ОТВЕТ:
{answer_text}

"""
        
        if section_theory and len(section_theory) > 50:
            # Truncate if too long
            theory_truncated = section_theory[:4000]
            user_prompt += f"""МАТЕРИАЛ РАЗДЕЛА {section}:
{theory_truncated}

"""
        
        user_prompt += """ЗАДАНИЕ:
По условию определи, что именно просят найти. Дай объяснение и решение только для этой цели, используя обозначения из задачи. Искомое в твоём ответе должно совпадать с формулировкой условия."""
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=800,
        )
        
        explanation = response.choices[0].message.content
        
        # Track tokens used
        tokens_used = response.usage.total_tokens if response.usage else 0
        print(f"   🤖 LLM generated explanation ({tokens_used} tokens)")
        
        return explanation
        
    except Exception as e:
        print(f"⚠️ LLM generation failed: {e}")
        return None


def generate_quick_explanation(
    problem_text: str,
    answer_text: Optional[str],
) -> Optional[str]:
    """
    Generate a quick explanation without section theory (fallback).
    """
    if not OPENAI_API_KEY:
        return None
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        prompt = f"""Задача: {problem_text[:500]}
Ответ: {answer_text or 'не известен'}

Кратко объясни решение (2-3 предложения)."""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use cheaper model for quick explanations
            messages=[
                {"role": "system", "content": "Ты — репетитор. Кратко объясняй решения задач."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=300,
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"⚠️ Quick explanation failed: {e}")
        return None
