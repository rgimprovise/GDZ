#!/usr/bin/env python3
"""
Parse Problem Parts Script

Находит задачи с несколькими подпунктами и разбивает их на части.

Примеры подпунктов:
- "1) ... 2) ... 3) ..."
- "а) ... б) ... в) ..."
- "a) ... b) ... c) ..."

Использование:
    python scripts/parse_problem_parts.py --book-id 1
    python scripts/parse_problem_parts.py --book-id 1 --dry-run
"""

import argparse
import re
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'apps', 'api'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'apps', 'worker'))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Load environment
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'infra', '.env'))

# Database connection - use localhost for local scripts
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'postgres')
if POSTGRES_HOST == 'postgres':
    POSTGRES_HOST = 'localhost'

DATABASE_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'tutorbot')}:"
    f"{os.getenv('POSTGRES_PASSWORD', 'tutorbot')}@"
    f"{POSTGRES_HOST}:"
    f"{os.getenv('POSTGRES_PORT', '5432')}/"
    f"{os.getenv('POSTGRES_DB', 'tutorbot')}"
)

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


# ===========================================
# Part Patterns
# ===========================================

# Паттерны для нумерации подпунктов
PART_PATTERNS = [
    # Цифры: 1) 2) 3)
    (r'\b([1-9])\)\s*', 'numeric'),
    # Буквы русские: а) б) в)
    (r'\b([а-гд])\)\s*', 'cyrillic'),
    # Буквы латинские: a) b) c)
    (r'\b([a-d])\)\s*', 'latin'),
]


def extract_problem_parts(problem_text: str) -> list[dict]:
    """
    Extract sub-parts from a multi-part problem.
    
    Args:
        problem_text: Full problem text
        
    Returns:
        List of {"part_number": "1", "part_text": "..."}
        Empty list if no parts found
    """
    parts = []
    
    # Определяем какой тип нумерации используется
    for pattern, ptype in PART_PATTERNS:
        matches = list(re.finditer(pattern, problem_text))
        
        if len(matches) >= 2:  # Минимум 2 подпункта
            # Проверяем что это последовательность
            nums = [m.group(1) for m in matches]
            
            if ptype == 'numeric':
                expected = [str(i) for i in range(1, len(nums) + 1)]
            elif ptype == 'cyrillic':
                cyrillic_seq = 'абвгд'
                expected = list(cyrillic_seq[:len(nums)])
            else:  # latin
                expected = list('abcd'[:len(nums)])
            
            # Если последовательность корректная (или почти)
            correct_count = sum(1 for a, b in zip(nums, expected) if a == b)
            if correct_count >= len(nums) * 0.7:  # 70% правильных
                # Разбиваем текст по маркерам
                for i, match in enumerate(matches):
                    start = match.end()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(problem_text)
                    
                    part_text = problem_text[start:end].strip()
                    # Убираем trailing punctuation before next number
                    part_text = re.sub(r'[;,]\s*$', '', part_text)
                    
                    parts.append({
                        "part_number": expected[i] if i < len(expected) else nums[i],
                        "part_text": part_text,
                    })
                
                break  # Используем первый подходящий паттерн
    
    return parts


def parse_answer_parts(answer_text: str) -> dict:
    """
    Parse answer text that contains multiple sub-answers.
    
    Example: "1) 130° и 50°; 2) 110° и 70°; 3) 135° и 45°; 4) 90°"
    
    Returns:
        {"1": "130° и 50°", "2": "110° и 70°", ...}
    """
    answers = {}
    
    if not answer_text:
        return answers
    
    # Пробуем найти нумерованные ответы
    for pattern, ptype in PART_PATTERNS:
        matches = list(re.finditer(pattern, answer_text))
        
        if len(matches) >= 2:
            for i, match in enumerate(matches):
                start = match.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(answer_text)
                
                ans = answer_text[start:end].strip()
                ans = re.sub(r'[;.]\s*$', '', ans)  # Remove trailing punctuation
                
                part_num = match.group(1)
                # Normalize to string
                if ptype == 'cyrillic':
                    cyrillic_map = {'а': '1', 'б': '2', 'в': '3', 'г': '4', 'д': '5'}
                    part_num = cyrillic_map.get(part_num, part_num)
                elif ptype == 'latin':
                    latin_map = {'a': '1', 'b': '2', 'c': '3', 'd': '4'}
                    part_num = latin_map.get(part_num, part_num)
                
                answers[part_num] = ans
            
            break
    
    return answers


def get_common_prefix(problem_text: str, parts: list[dict]) -> str:
    """
    Extract the common prefix (problem statement) before the parts.
    
    Example: "4. Найдите смежные углы, если: 1) ..." 
             → "Найдите смежные углы, если:"
    """
    if not parts:
        return problem_text
    
    # Найти позицию первого подпункта
    first_part_text = parts[0]["part_text"]
    part_num = parts[0]["part_number"]
    
    # Ищем маркер первого подпункта
    for pattern, _ in PART_PATTERNS:
        match = re.search(pattern, problem_text)
        if match and match.group(1) == part_num:
            prefix = problem_text[:match.start()].strip()
            # Убираем номер задачи в начале
            prefix = re.sub(r'^\d+\.\s*', '', prefix)
            return prefix
    
    return ""


# ===========================================
# Main Processing
# ===========================================

def process_book(book_id: int, dry_run: bool = False):
    """
    Process all problems in a book and extract parts.
    """
    db = Session()
    
    try:
        # Получаем задачи книги
        result = db.execute(text("""
            SELECT id, number, problem_text, answer_text
            FROM problems
            WHERE book_id = :book_id
            ORDER BY id
        """), {"book_id": book_id})
        
        problems = list(result)
        print(f"📚 Книга {book_id}: найдено {len(problems)} задач")
        
        stats = {
            "total": len(problems),
            "with_parts": 0,
            "parts_created": 0,
            "answers_linked": 0,
        }
        
        for row in problems:
            problem_id = row.id
            problem_text = row.problem_text or ""
            answer_text = row.answer_text or ""
            
            # Извлекаем подпункты
            parts = extract_problem_parts(problem_text)
            
            if len(parts) >= 2:
                stats["with_parts"] += 1
                common_prefix = get_common_prefix(problem_text, parts)
                
                print(f"\n  📝 Задача #{row.number or problem_id}")
                print(f"     Общая часть: {common_prefix[:80]}...")
                print(f"     Найдено {len(parts)} подпунктов")
                
                # Парсим ответы
                answer_parts = parse_answer_parts(answer_text)
                
                for part in parts:
                    part_num = part["part_number"]
                    part_text = part["part_text"]
                    part_answer = answer_parts.get(part_num, "")
                    
                    print(f"       {part_num}) {part_text[:50]}...")
                    if part_answer:
                        print(f"          ✅ Ответ: {part_answer}")
                        stats["answers_linked"] += 1
                    
                    if not dry_run:
                        # Сохраняем в БД
                        db.execute(text("""
                            INSERT INTO problem_parts (problem_id, part_number, part_text, answer_text)
                            VALUES (:problem_id, :part_number, :part_text, :answer_text)
                            ON CONFLICT (problem_id, part_number) 
                            DO UPDATE SET 
                                part_text = EXCLUDED.part_text,
                                answer_text = EXCLUDED.answer_text,
                                updated_at = NOW()
                        """), {
                            "problem_id": problem_id,
                            "part_number": part_num,
                            "part_text": part_text,
                            "answer_text": part_answer or None,
                        })
                    
                    stats["parts_created"] += 1
                
                # Обновляем флаг has_parts
                if not dry_run:
                    db.execute(text("""
                        UPDATE problems 
                        SET has_parts = true 
                        WHERE id = :problem_id
                    """), {"problem_id": problem_id})
        
        if not dry_run:
            db.commit()
            print("\n✅ Изменения сохранены")
        else:
            print("\n⚠️ Dry run - изменения НЕ сохранены")
        
        print(f"\n📊 Статистика:")
        print(f"   Всего задач: {stats['total']}")
        print(f"   С подпунктами: {stats['with_parts']}")
        print(f"   Создано частей: {stats['parts_created']}")
        print(f"   Ответов связано: {stats['answers_linked']}")
        
    finally:
        db.close()


def apply_ocr_cleaning(book_id: int, dry_run: bool = False):
    """
    Apply OCR cleaning to all problems in a book.
    """
    # Import the cleaner
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'apps', 'worker'))
    from ocr_cleaner import clean_ocr_text, calculate_quality_score
    
    db = Session()
    
    try:
        # Получаем задачи
        result = db.execute(text("""
            SELECT id, problem_text
            FROM problems
            WHERE book_id = :book_id
              AND (problem_text_clean IS NULL OR problem_text_clean = '')
        """), {"book_id": book_id})
        
        problems = list(result)
        print(f"🧹 Очистка OCR для {len(problems)} задач...")
        
        cleaned_count = 0
        quality_improved = 0
        
        for row in problems:
            original = row.problem_text or ""
            cleaned = clean_ocr_text(original)
            
            if cleaned != original:
                cleaned_count += 1
                
                # Проверяем улучшение качества
                score_before = calculate_quality_score(original)['score']
                score_after = calculate_quality_score(cleaned)['score']
                
                if score_after > score_before:
                    quality_improved += 1
                
                if not dry_run:
                    db.execute(text("""
                        UPDATE problems 
                        SET problem_text_clean = :cleaned
                        WHERE id = :problem_id
                    """), {"cleaned": cleaned, "problem_id": row.id})
        
        if not dry_run:
            db.commit()
        
        print(f"✅ Очищено: {cleaned_count}")
        print(f"📈 Качество улучшено: {quality_improved}")
        
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse problem parts")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't save changes")
    parser.add_argument("--clean-ocr", action="store_true", help="Also apply OCR cleaning")
    
    args = parser.parse_args()
    
    if args.clean_ocr:
        apply_ocr_cleaning(args.book_id, args.dry_run)
    
    process_book(args.book_id, args.dry_run)
