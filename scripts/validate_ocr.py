#!/usr/bin/env python3
"""
OCR Validation Script

Позволяет визуально проверить качество OCR, сравнивая:
1. Оригинальную страницу PDF
2. Распознанный текст

Использование:
    python validate_ocr.py                    # Случайная страница
    python validate_ocr.py --book_id 1        # Случайная страница из книги
    python validate_ocr.py --page_id 123      # Конкретная страница
    python validate_ocr.py --stats            # Показать статистику
"""

import sys
import os
import random
import argparse
from pathlib import Path

# Add parent paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../apps/api')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../apps/worker')))

# Database imports
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# PDF rendering
try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False
    print("⚠️  PyMuPDF not installed. Install with: pip install pymupdf")

# Config
POSTGRES_HOST = os.environ.get('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.environ.get('POSTGRES_PORT', '5432')
POSTGRES_DB = os.environ.get('POSTGRES_DB', 'tutorbot')
POSTGRES_USER = os.environ.get('POSTGRES_USER', 'tutorbot')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', 'tutorbot')

DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

DATA_DIR = Path(os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), '../data')))


def get_stats():
    """Показывает общую статистику по OCR"""
    session = Session()
    
    print("\n" + "="*70)
    print("📊 СТАТИСТИКА OCR")
    print("="*70)
    
    # Общая статистика
    result = session.execute(text("""
        SELECT 
            count(*) as total_pages,
            round(avg(length(coalesce(ocr_text, ''))), 0) as avg_text_len,
            count(CASE WHEN length(coalesce(ocr_text, '')) < 100 THEN 1 END) as short_pages,
            count(CASE WHEN length(coalesce(ocr_text, '')) = 0 THEN 1 END) as empty_pages
        FROM pdf_pages
    """)).fetchone()
    
    print(f"\n📄 Всего страниц: {result.total_pages}")
    print(f"📝 Средняя длина текста: {result.avg_text_len} символов")
    print(f"⚠️  Короткие страницы (<100 символов): {result.short_pages}")
    print(f"❌ Пустые страницы: {result.empty_pages}")
    
    # По книгам
    print("\n" + "-"*70)
    print("📚 По книгам:")
    print("-"*70)
    
    results = session.execute(text("""
        SELECT 
            b.title,
            count(pp.id) as pages,
            round(avg(length(coalesce(pp.ocr_text, ''))), 0) as avg_len,
            count(CASE WHEN length(coalesce(pp.ocr_text, '')) < 100 THEN 1 END) as short,
            (SELECT count(*) FROM problems p WHERE p.book_id = b.id) as problems
        FROM pdf_pages pp
        JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
        JOIN books b ON b.id = ps.book_id
        GROUP BY b.id, b.title
        ORDER BY b.title
    """)).fetchall()
    
    for r in results:
        print(f"\n  📖 {r.title}")
        print(f"     Страниц: {r.pages}, Avg длина: {r.avg_len}, Короткие: {r.short}, Задач: {r.problems}")
    
    # Качество задач
    print("\n" + "-"*70)
    print("🎯 Качество извлечения задач:")
    print("-"*70)
    
    results = session.execute(text("""
        SELECT 
            b.title,
            count(*) as total,
            count(CASE WHEN p.number ~ '^[0-9]+$' THEN 1 END) as numeric,
            count(CASE WHEN length(p.problem_text) > 200 THEN 1 END) as long_text
        FROM problems p
        JOIN books b ON b.id = p.book_id
        GROUP BY b.id, b.title
        ORDER BY b.title
    """)).fetchall()
    
    for r in results:
        pct_numeric = (r.numeric / r.total * 100) if r.total > 0 else 0
        pct_long = (r.long_text / r.total * 100) if r.total > 0 else 0
        print(f"\n  📖 {r.title[:40]}")
        print(f"     Всего: {r.total}, Числовые номера: {r.numeric} ({pct_numeric:.0f}%), Длинные: {r.long_text} ({pct_long:.0f}%)")
    
    session.close()


def get_random_page(book_id=None):
    """Получает случайную страницу для валидации"""
    session = Session()
    
    if book_id:
        result = session.execute(text("""
            SELECT pp.id
            FROM pdf_pages pp
            JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
            WHERE ps.book_id = :book_id
            ORDER BY random()
            LIMIT 1
        """), {"book_id": book_id}).fetchone()
    else:
        result = session.execute(text("""
            SELECT id FROM pdf_pages ORDER BY random() LIMIT 1
        """)).fetchone()
    
    session.close()
    return result.id if result else None


def validate_page(page_id):
    """Показывает детали страницы для валидации"""
    session = Session()
    
    result = session.execute(text("""
        SELECT 
            pp.id,
            pp.page_num,
            pp.ocr_text,
            pp.ocr_confidence,
            ps.original_filename,
            ps.minio_key,
            b.title as book_title
        FROM pdf_pages pp
        JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
        JOIN books b ON b.id = ps.book_id
        WHERE pp.id = :page_id
    """), {"page_id": page_id}).fetchone()
    
    if not result:
        print(f"❌ Страница {page_id} не найдена")
        session.close()
        return
    
    print("\n" + "="*70)
    print(f"📄 ВАЛИДАЦИЯ СТРАНИЦЫ #{result.id}")
    print("="*70)
    print(f"\n📖 Книга: {result.book_title}")
    print(f"📁 Файл: {result.original_filename}")
    print(f"📃 Страница: {result.page_num + 1}")
    print(f"🎯 Confidence: {result.ocr_confidence}")
    print(f"📝 Длина текста: {len(result.ocr_text or '')} символов")
    
    print("\n" + "-"*70)
    print("📜 РАСПОЗНАННЫЙ ТЕКСТ:")
    print("-"*70)
    
    ocr_content = result.ocr_text or "(пусто)"
    # Показываем первые 2000 символов
    if len(ocr_content) > 2000:
        print(ocr_content[:2000])
        print(f"\n... (ещё {len(ocr_content) - 2000} символов)")
    else:
        print(ocr_content)
    
    # Показываем задачи с этой страницы
    problems = session.execute(text("""
        SELECT number, left(problem_text, 100) as preview
        FROM problems
        WHERE source_page_id = :page_id
        ORDER BY number
        LIMIT 10
    """), {"page_id": page_id}).fetchall()
    
    if problems:
        print("\n" + "-"*70)
        print(f"🎯 ИЗВЛЕЧЁННЫЕ ЗАДАЧИ ({len(problems)}):")
        print("-"*70)
        for p in problems:
            print(f"\n  #{p.number}: {p.preview}...")
    
    # Путь к PDF для ручной проверки
    pdf_path = DATA_DIR / result.minio_key
    if not pdf_path.exists():
        pdf_path = DATA_DIR / "pdfs" / result.original_filename
    
    print("\n" + "-"*70)
    print("🔍 ДЛЯ РУЧНОЙ ПРОВЕРКИ:")
    print("-"*70)
    print(f"   Откройте PDF: {pdf_path}")
    print(f"   Перейдите на страницу: {result.page_num + 1}")
    
    # Если есть PyMuPDF, можем сохранить изображение страницы
    if HAS_FITZ and pdf_path.exists():
        try:
            doc = fitz.open(str(pdf_path))
            page = doc[result.page_num]
            
            # Сохраняем изображение
            output_path = Path(f"/tmp/ocr_validate_page_{page_id}.png")
            pix = page.get_pixmap(dpi=150)
            pix.save(str(output_path))
            doc.close()
            
            print(f"\n   📷 Изображение сохранено: {output_path}")
            print(f"      Откройте командой: open {output_path}")
        except Exception as e:
            print(f"\n   ⚠️  Не удалось сохранить изображение: {e}")
    
    session.close()


def compare_pages(count=5):
    """Сравнивает несколько случайных страниц"""
    print("\n" + "="*70)
    print(f"🔍 СРАВНЕНИЕ {count} СЛУЧАЙНЫХ СТРАНИЦ")
    print("="*70)
    
    session = Session()
    
    results = session.execute(text("""
        SELECT 
            pp.id,
            pp.page_num,
            length(coalesce(pp.ocr_text, '')) as text_len,
            pp.ocr_confidence,
            b.title
        FROM pdf_pages pp
        JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
        JOIN books b ON b.id = ps.book_id
        WHERE length(coalesce(pp.ocr_text, '')) > 500
        ORDER BY random()
        LIMIT :count
    """), {"count": count}).fetchall()
    
    for r in results:
        print(f"\n📄 ID: {r.id} | {r.title[:30]}... | Стр: {r.page_num + 1} | {r.text_len} символов")
        print(f"   Команда для просмотра: python validate_ocr.py --page_id {r.id}")
    
    session.close()


def main():
    parser = argparse.ArgumentParser(description="OCR Validation Tool")
    parser.add_argument("--stats", action="store_true", help="Показать статистику")
    parser.add_argument("--page_id", type=int, help="ID страницы для валидации")
    parser.add_argument("--book_id", type=int, help="ID книги (случайная страница)")
    parser.add_argument("--compare", type=int, default=0, help="Сравнить N случайных страниц")
    
    args = parser.parse_args()
    
    if args.stats:
        get_stats()
    elif args.page_id:
        validate_page(args.page_id)
    elif args.compare > 0:
        compare_pages(args.compare)
    elif args.book_id:
        page_id = get_random_page(args.book_id)
        if page_id:
            validate_page(page_id)
        else:
            print(f"❌ Не найдено страниц для книги {args.book_id}")
    else:
        # По умолчанию показываем статистику и случайную страницу
        get_stats()
        print("\n")
        page_id = get_random_page()
        if page_id:
            validate_page(page_id)


if __name__ == "__main__":
    main()
