#!/usr/bin/env python3
"""
Скрипт для исправления формул в уже распознанном тексте.

Применяет пост-обработку ко всем страницам и задачам в БД.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../apps/worker')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../apps/api')))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from formula_processor import post_process_ocr, calculate_formula_confidence

# Config
POSTGRES_HOST = os.environ.get('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.environ.get('POSTGRES_PORT', '5432')
POSTGRES_DB = os.environ.get('POSTGRES_DB', 'tutorbot')
POSTGRES_USER = os.environ.get('POSTGRES_USER', 'tutorbot')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', 'tutorbot')

DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


def fix_pdf_pages(dry_run: bool = True, limit: int = None):
    """Исправляет OCR текст в pdf_pages."""
    session = Session()
    
    print("\n" + "="*60)
    print("📄 Исправление OCR текста в pdf_pages")
    print("="*60)
    
    # Получаем страницы
    query = "SELECT id, ocr_text FROM pdf_pages WHERE ocr_text IS NOT NULL"
    if limit:
        query += f" LIMIT {limit}"
    
    pages = session.execute(text(query)).fetchall()
    print(f"\n📊 Найдено страниц: {len(pages)}")
    
    fixed_count = 0
    changed_pages = []
    
    for page in pages:
        page_id, original = page.id, page.ocr_text
        
        if not original:
            continue
            
        processed = post_process_ocr(original)
        
        if processed != original:
            fixed_count += 1
            changes = len(original) - len(processed)
            changed_pages.append({
                'id': page_id,
                'original_sample': original[:100],
                'processed_sample': processed[:100],
                'char_diff': changes
            })
            
            if not dry_run:
                session.execute(
                    text("UPDATE pdf_pages SET ocr_text = :text WHERE id = :id"),
                    {"text": processed, "id": page_id}
                )
    
    if not dry_run:
        session.commit()
    
    print(f"\n✅ Страниц с изменениями: {fixed_count} / {len(pages)}")
    
    # Показать примеры
    if changed_pages:
        print(f"\n📝 Примеры изменений (первые 5):")
        for p in changed_pages[:5]:
            print(f"\n  Page #{p['id']}:")
            print(f"    До:    {p['original_sample']}...")
            print(f"    После: {p['processed_sample']}...")
    
    session.close()
    return fixed_count


def fix_problems(dry_run: bool = True, limit: int = None):
    """Исправляет текст задач в problems."""
    session = Session()
    
    print("\n" + "="*60)
    print("🎯 Исправление текста задач в problems")
    print("="*60)
    
    # Получаем задачи
    query = "SELECT id, problem_text, solution_text, answer_text FROM problems"
    if limit:
        query += f" LIMIT {limit}"
    
    problems = session.execute(text(query)).fetchall()
    print(f"\n📊 Найдено задач: {len(problems)}")
    
    fixed_count = 0
    
    for problem in problems:
        problem_id = problem.id
        updates = {}
        
        # Обрабатываем каждое поле
        for field in ['problem_text', 'solution_text', 'answer_text']:
            original = getattr(problem, field)
            if original:
                processed = post_process_ocr(original)
                if processed != original:
                    updates[field] = processed
        
        if updates:
            fixed_count += 1
            
            if not dry_run:
                # Строим UPDATE запрос
                set_clause = ", ".join([f"{k} = :{k}" for k in updates.keys()])
                updates['id'] = problem_id
                session.execute(
                    text(f"UPDATE problems SET {set_clause} WHERE id = :id"),
                    updates
                )
    
    if not dry_run:
        session.commit()
    
    print(f"\n✅ Задач с изменениями: {fixed_count} / {len(problems)}")
    
    session.close()
    return fixed_count


def show_before_after_examples():
    """Показывает примеры до/после для конкретных проблемных паттернов."""
    session = Session()
    
    print("\n" + "="*60)
    print("🔍 Примеры проблемных паттернов в БД")
    print("="*60)
    
    patterns = [
        ('@', 'Q (теплота)'),
        ('м?', 'м³ (кубические метры)'),
        ('kak', 'как'),
        ('He ', 'не '),
        ('t, —', 't₂ - t₁'),
    ]
    
    for pattern, description in patterns:
        result = session.execute(
            text(f"""
                SELECT id, left(problem_text, 150) as sample
                FROM problems 
                WHERE problem_text LIKE :pattern
                LIMIT 3
            """),
            {"pattern": f"%{pattern}%"}
        ).fetchall()
        
        if result:
            print(f"\n🔸 Паттерн: '{pattern}' ({description})")
            print(f"   Найдено примеров: {len(result)}")
            for r in result:
                print(f"   ID {r.id}: {r.sample}...")
        else:
            print(f"\n✅ Паттерн '{pattern}' не найден в БД")
    
    session.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Fix formulas in OCR text")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Only show what would be changed (default)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually apply changes to DB")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of records to process")
    parser.add_argument("--examples", action="store_true",
                        help="Show examples of problematic patterns")
    
    args = parser.parse_args()
    
    dry_run = not args.apply
    
    if dry_run:
        print("\n⚠️  DRY RUN MODE - изменения НЕ будут применены")
        print("   Используйте --apply для применения изменений")
    else:
        print("\n🚀 APPLYING CHANGES to database!")
    
    if args.examples:
        show_before_after_examples()
    else:
        fix_pdf_pages(dry_run=dry_run, limit=args.limit)
        fix_problems(dry_run=dry_run, limit=args.limit)
    
    print("\n✅ Готово!")


if __name__ == "__main__":
    main()
