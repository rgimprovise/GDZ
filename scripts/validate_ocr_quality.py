#!/usr/bin/env python3
"""
OCR Quality Validation Script

Анализирует качество OCR для книги и создаёт отчёт:
- Выявляет проблемные страницы/задачи
- Предлагает исправления
- Показывает статистику

Использование:
    python scripts/validate_ocr_quality.py --book-id 1
    python scripts/validate_ocr_quality.py --book-id 1 --fix  # автоисправление
    python scripts/validate_ocr_quality.py --book-id 1 --export report.json
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Optional

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'apps', 'api'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'apps', 'worker'))

from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.orm import sessionmaker

# Load environment
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'infra', '.env'))

# Import cleaner
from ocr_cleaner import clean_ocr_text, calculate_quality_score

# Database connection - use localhost for local scripts
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'postgres')
# Override Docker hostname to localhost for local execution
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


def analyze_problem(problem_id: int, text: str) -> dict:
    """
    Analyze a single problem's OCR quality.
    """
    quality = calculate_quality_score(text)
    cleaned = clean_ocr_text(text)
    quality_after = calculate_quality_score(cleaned)
    
    return {
        "problem_id": problem_id,
        "original_length": len(text),
        "score_before": quality['score'],
        "score_after": quality_after['score'],
        "issues": quality['issues'],
        "needs_cleaning": cleaned != text,
        "improvement": quality_after['score'] - quality['score'],
    }


def validate_book_problems(book_id: int, verbose: bool = True) -> dict:
    """
    Validate all problems in a book.
    """
    db = Session()
    
    try:
        # Get book info
        book_result = db.execute(sql_text("""
            SELECT title, subject, grade FROM books WHERE id = :book_id
        """), {"book_id": book_id}).first()
        
        if not book_result:
            print(f"❌ Книга {book_id} не найдена")
            return {}
        
        print(f"\n📚 {book_result.title}")
        print(f"   Предмет: {book_result.subject}, Класс: {book_result.grade}")
        
        # Get all problems
        problems = db.execute(sql_text("""
            SELECT id, number, problem_text, problem_text_clean, answer_text
            FROM problems
            WHERE book_id = :book_id
            ORDER BY id
        """), {"book_id": book_id}).fetchall()
        
        print(f"   Всего задач: {len(problems)}\n")
        
        # Analyze each problem
        report = {
            "book_id": book_id,
            "book_title": book_result.title,
            "total_problems": len(problems),
            "problems_with_issues": 0,
            "problems_need_cleaning": 0,
            "avg_score_before": 0,
            "avg_score_after": 0,
            "issue_types": defaultdict(int),
            "worst_problems": [],
            "details": [],
        }
        
        total_score_before = 0
        total_score_after = 0
        
        for row in problems:
            text = row.problem_text or ""
            
            analysis = analyze_problem(row.id, text)
            report["details"].append(analysis)
            
            total_score_before += analysis["score_before"]
            total_score_after += analysis["score_after"]
            
            if analysis["issues"]:
                report["problems_with_issues"] += 1
                for issue in analysis["issues"]:
                    report["issue_types"][issue["type"]] += 1
            
            if analysis["needs_cleaning"]:
                report["problems_need_cleaning"] += 1
            
            # Track worst problems
            if analysis["score_before"] < 70:
                report["worst_problems"].append({
                    "id": row.id,
                    "number": row.number,
                    "score": analysis["score_before"],
                    "text_preview": text[:100] + "..." if len(text) > 100 else text,
                })
        
        # Calculate averages
        if problems:
            report["avg_score_before"] = total_score_before / len(problems)
            report["avg_score_after"] = total_score_after / len(problems)
        
        # Sort worst problems
        report["worst_problems"] = sorted(
            report["worst_problems"], 
            key=lambda x: x["score"]
        )[:10]  # Top 10 worst
        
        # Print summary
        print("=" * 60)
        print("📊 ОТЧЁТ О КАЧЕСТВЕ OCR")
        print("=" * 60)
        print(f"\n📈 Общая статистика:")
        print(f"   Всего задач:          {report['total_problems']}")
        print(f"   С проблемами OCR:     {report['problems_with_issues']}")
        print(f"   Требуют очистки:      {report['problems_need_cleaning']}")
        print(f"\n   Средний скор ДО:      {report['avg_score_before']:.1f}/100")
        print(f"   Средний скор ПОСЛЕ:   {report['avg_score_after']:.1f}/100")
        print(f"   Улучшение:            +{report['avg_score_after'] - report['avg_score_before']:.1f}")
        
        if report["issue_types"]:
            print(f"\n🔍 Типы проблем:")
            for issue_type, count in sorted(report["issue_types"].items(), key=lambda x: -x[1]):
                label = {
                    "mixed_script": "Смешение латиницы/кириллицы",
                    "unusual_chars": "Необычные символы",
                    "numbering_error": "Ошибки нумерации",
                    "digits_in_words": "Цифры внутри слов",
                }.get(issue_type, issue_type)
                print(f"   {label}: {count}")
        
        if report["worst_problems"]:
            print(f"\n⚠️ Проблемные задачи (скор < 70):")
            for p in report["worst_problems"][:5]:
                print(f"   #{p['number'] or p['id']} (скор {p['score']}): {p['text_preview'][:60]}...")
        
        return report
        
    finally:
        db.close()


def validate_book_pages(book_id: int) -> dict:
    """
    Validate OCR quality of PDF pages.
    """
    db = Session()
    
    try:
        pages = db.execute(sql_text("""
            SELECT pp.id, pp.page_num, pp.ocr_text, pp.ocr_confidence
            FROM pdf_pages pp
            JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
            WHERE ps.book_id = :book_id
            ORDER BY pp.page_num
        """), {"book_id": book_id}).fetchall()
        
        print(f"\n📄 Анализ {len(pages)} страниц...")
        
        page_report = {
            "total_pages": len(pages),
            "pages_with_issues": 0,
            "low_confidence_pages": [],
            "page_scores": [],
        }
        
        for page in pages:
            text = page.ocr_text or ""
            if not text:
                continue
            
            quality = calculate_quality_score(text)
            
            page_report["page_scores"].append({
                "page_num": page.page_num,
                "score": quality["score"],
                "db_confidence": page.ocr_confidence,
            })
            
            if quality["score"] < 70:
                page_report["pages_with_issues"] += 1
                page_report["low_confidence_pages"].append({
                    "page_num": page.page_num,
                    "score": quality["score"],
                    "issues": quality["issues"],
                })
        
        if page_report["low_confidence_pages"]:
            print(f"\n⚠️ Страницы с низким качеством OCR:")
            for p in sorted(page_report["low_confidence_pages"], key=lambda x: x["score"])[:10]:
                issues = ", ".join(i["type"] for i in p["issues"])
                print(f"   Стр. {p['page_num']}: скор {p['score']}, проблемы: {issues}")
        
        return page_report
        
    finally:
        db.close()


def apply_cleaning(book_id: int, dry_run: bool = False):
    """
    Apply OCR cleaning to all problems in a book.
    """
    db = Session()
    
    try:
        problems = db.execute(sql_text("""
            SELECT id, problem_text
            FROM problems
            WHERE book_id = :book_id
              AND (problem_text_clean IS NULL OR problem_text_clean = '')
        """), {"book_id": book_id}).fetchall()
        
        print(f"\n🧹 Применение очистки OCR к {len(problems)} задачам...")
        
        cleaned_count = 0
        
        for row in problems:
            original = row.problem_text or ""
            cleaned = clean_ocr_text(original)
            
            if cleaned != original:
                cleaned_count += 1
                
                if not dry_run:
                    db.execute(sql_text("""
                        UPDATE problems 
                        SET problem_text_clean = :cleaned,
                            updated_at = NOW()
                        WHERE id = :problem_id
                    """), {"cleaned": cleaned, "problem_id": row.id})
        
        if not dry_run:
            db.commit()
            print(f"✅ Очищено: {cleaned_count} задач")
        else:
            print(f"⚠️ Dry run: было бы очищено {cleaned_count} задач")
        
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Validate OCR quality")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID")
    parser.add_argument("--fix", action="store_true", help="Apply OCR cleaning")
    parser.add_argument("--dry-run", action="store_true", help="Don't save changes")
    parser.add_argument("--pages", action="store_true", help="Also analyze page-level OCR")
    parser.add_argument("--export", type=str, help="Export report to JSON file")
    
    args = parser.parse_args()
    
    # Validate problems
    report = validate_book_problems(args.book_id)
    
    # Optionally validate pages
    if args.pages:
        page_report = validate_book_pages(args.book_id)
        report["pages"] = page_report
    
    # Export report
    if args.export:
        # Convert defaultdict to dict for JSON
        report["issue_types"] = dict(report.get("issue_types", {}))
        
        with open(args.export, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Отчёт сохранён: {args.export}")
    
    # Apply cleaning
    if args.fix:
        apply_cleaning(args.book_id, args.dry_run)
    
    print("\n" + "=" * 60)
    print("✅ Валидация завершена")


if __name__ == "__main__":
    main()
