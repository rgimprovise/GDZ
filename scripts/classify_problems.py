#!/usr/bin/env python3
"""
Classify problems into types: question (теоретические) vs exercise (числовые).

Usage:
    python scripts/classify_problems.py --book-id 1
    python scripts/classify_problems.py --book-id 1 --dry-run
"""

import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "worker"))

from sqlalchemy import text
from database import SessionLocal


# Patterns for theoretical questions (контрольные вопросы)
QUESTION_PATTERNS = [
    r'^докажите',
    r'^что\s+(такое|называется|означает)',
    r'^какой\s+(угол|отрезок|треугольник|вектор)',
    r'^какая\s+(фигура|прямая|точка)',
    r'^какие\s+(углы|отрезки|точки|прямые|фигуры|векторы)',
    r'^как\s+(называ|обознача|доказ|определ)',
    r'^сформулируйте',
    r'^объясните',
    r'^в\s+чём\s+состоит',
    r'^чему\s+равен',  # Could be both, but often theoretical
    r'^когда\s+говорят',
    r'^при\s+каком\s+условии',
    r'^верно\s+ли',
]

# Patterns for exercises (задачи с числовым ответом)
EXERCISE_PATTERNS = [
    r'^найдите',
    r'^вычислите',
    r'^решите',
    r'^постройте',
    r'^определите',
    r'^даны?\s+',
    r'^дан[оа]?\s+',
    r'^\d+[\.\)]\s*\d',  # Starts with number then another number (sub-problem)
    r'^отрезки?\s+',
    r'^треугольник',
    r'^в\s+треугольнике',
    r'^в\s+параллелограмме',
    r'^на\s+(прямой|отрезке|плоскости)',
    r'^через\s+точк',
    r'^из\s+точки',
    r'^стороны?\s+',
    r'^угол\s+',
    r'^диагонал',
    r'^радиус',
    r'^основани[ея]',
    r'^высота',
    r'^медиана',
    r'^биссектриса',
    r'^окружност',
    r'^могут\s+ли',  # Often exercise-style
]


def classify_problem(problem_text: str) -> str:
    """
    Classify problem as 'question' or 'exercise'.
    """
    # Get first 200 chars, lowercase, remove number prefix
    text_lower = problem_text[:200].lower().strip()
    text_lower = re.sub(r'^\d+[\.\)]\s*', '', text_lower)  # Remove "1. " or "1) "
    
    # Check question patterns first (they're more specific)
    for pattern in QUESTION_PATTERNS:
        if re.search(pattern, text_lower):
            return 'question'
    
    # Check exercise patterns
    for pattern in EXERCISE_PATTERNS:
        if re.search(pattern, text_lower):
            return 'exercise'
    
    # Default: if contains numbers/measurements, likely exercise
    if re.search(r'\d+\s*(см|м|°|градус|мм|км)', text_lower):
        return 'exercise'
    
    # If contains "?" - likely question
    if '?' in problem_text[:100]:
        return 'question'
    
    return 'unknown'


def classify_all_problems(db, book_id: int, dry_run: bool = False) -> dict:
    """Classify all problems in a book."""
    
    result = db.execute(text("""
        SELECT id, problem_text FROM problems WHERE book_id = :book_id
    """), {"book_id": book_id})
    
    stats = {'question': 0, 'exercise': 0, 'unknown': 0}
    updates = []
    
    for row in result:
        problem_type = classify_problem(row.problem_text)
        stats[problem_type] += 1
        updates.append((row.id, problem_type))
    
    if not dry_run:
        for problem_id, problem_type in updates:
            db.execute(text("""
                UPDATE problems SET problem_type = :ptype WHERE id = :id
            """), {"ptype": problem_type, "id": problem_id})
    
    return stats, updates


def main():
    parser = argparse.ArgumentParser(description="Classify problems by type")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID")
    parser.add_argument("--dry-run", action="store_true", help="Don't update DB")
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        print(f"📚 Classifying problems for book {args.book_id}...")
        
        stats, updates = classify_all_problems(db, args.book_id, args.dry_run)
        
        print(f"\n📊 Classification results:")
        print(f"   📝 Questions (теоретические): {stats['question']}")
        print(f"   🔢 Exercises (с ответом): {stats['exercise']}")
        print(f"   ❓ Unknown: {stats['unknown']}")
        
        # Show examples
        print(f"\n📋 Examples:")
        questions = [(id, classify_problem(text)) for id, text in 
                     [(u[0], db.execute(text("SELECT problem_text FROM problems WHERE id = :id"), 
                      {"id": u[0]}).scalar()) for u in updates[:100]] 
                     if classify_problem(text) == 'question'][:3]
        
        exercises = [(id, classify_problem(text)) for id, text in 
                     [(u[0], db.execute(text("SELECT problem_text FROM problems WHERE id = :id"), 
                      {"id": u[0]}).scalar()) for u in updates[:100]] 
                     if classify_problem(text) == 'exercise'][:3]
        
        if not args.dry_run:
            db.commit()
            print(f"\n✅ Updated {len(updates)} problems")
        else:
            print(f"\n🔍 Dry run - would update {len(updates)} problems")
            
    finally:
        db.close()


if __name__ == "__main__":
    main()
