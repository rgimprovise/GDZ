#!/usr/bin/env python3
"""
Находит в БД задачу про наклонную призму (22) и её решение, выводит расположение.

Использование:
    python scripts/find_problem_in_db.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "worker"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / "infra" / ".env")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
if POSTGRES_HOST == "postgres":
    POSTGRES_HOST = "localhost"

DATABASE_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'tutorbot')}:"
    f"{os.getenv('POSTGRES_PASSWORD', 'tutorbot')}@"
    f"{POSTGRES_HOST}:{os.getenv('POSTGRES_PORT', '5432')}/"
    f"{os.getenv('POSTGRES_DB', 'tutorbot')}"
)
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


def main():
    db = Session()
    try:
        print("=" * 70)
        print("1. ПОИСК ЗАДАЧИ (условие: наклонная призма, боковая поверхность, №22)")
        print("=" * 70)

        # Ищем в problems по номеру 22 и/или по ключевым словам
        r = db.execute(text("""
            SELECT p.id, p.book_id, p.number, p.section, p.page_ref, p.source_page_id,
                   LENGTH(p.problem_text) AS len_text,
                   LENGTH(p.problem_text_clean) AS len_clean,
                   LEFT(p.problem_text, 600) AS problem_snippet,
                   LEFT(p.solution_text, 400) AS solution_snippet,
                   p.answer_text,
                   b.title AS book_title
            FROM problems p
            JOIN books b ON b.id = p.book_id
            WHERE p.number = '22'
               OR LOWER(p.problem_text) LIKE '%наклонной призме%'
               OR LOWER(COALESCE(p.problem_text_clean, p.problem_text)) LIKE '%наклонной призме%'
               OR LOWER(p.problem_text) LIKE '%боковую поверхность призмы%'
            ORDER BY p.book_id, p.id
        """))
        rows = list(r)
        if not rows:
            print("Записей не найдено.")
        else:
            for row in rows:
                print(f"\n  Таблица: problems")
                print(f"  id: {row.id}, book_id: {row.book_id}, number: {row.number}, section: {row.section}")
                print(f"  page_ref: {row.page_ref}, source_page_id: {row.source_page_id}")
                print(f"  book_title: {row.book_title}")
                print(f"  problem_text: длина {row.len_text} символов" + (f", problem_text_clean: {row.len_clean}" if row.len_clean else ""))
                print(f"  answer_text: {repr(row.answer_text)[:120]}")
                print(f"  solution_text (в problems): {repr(row.solution_snippet)[:200] if row.solution_snippet else 'NULL'}...")
                print(f"  --- начало problem_text ---")
                print((row.problem_snippet or "")[:550])
                print("  --- конец snippet ---")

        print("\n" + "=" * 70)
        print("2. ПОИСК РЕШЕНИЯ (текст: «Плоскость проведенного сечения», «боковая поверхность ... равна р»)")
        print("=" * 70)

        # Решение в problems.solution_text
        r2 = db.execute(text("""
            SELECT p.id, p.book_id, p.number, p.section,
                   LEFT(p.solution_text, 800) AS solution_snippet,
                   LENGTH(p.solution_text) AS len_sol
            FROM problems p
            WHERE p.solution_text IS NOT NULL
              AND (LOWER(p.solution_text) LIKE '%плоскость проведенного сечения%'
                   OR LOWER(p.solution_text) LIKE '%боковая поверхность%исходной призмы%'
                   OR LOWER(p.solution_text) LIKE '%боковая поверхность%равна%')
            ORDER BY p.book_id, p.id
        """))
        rows2 = list(r2)
        if rows2:
            print("\n  Найдено в таблице: problems (поле solution_text)")
            for row in rows2:
                print(f"  id: {row.id}, book_id: {row.book_id}, number: {row.number}, section: {row.section}, длина solution_text: {row.len_sol}")
                print("  --- snippet solution_text ---")
                print((row.solution_snippet or "")[:600])
                print("  ---")
        else:
            print("  В problems.solution_text такого решения не найдено.")

        # Решение в pdf_pages.ocr_text (страницы учебника)
        r3 = db.execute(text("""
            SELECT pp.id AS page_id, pp.pdf_source_id, pp.page_num,
                   ps.book_id,
                   LENGTH(pp.ocr_text) AS len_ocr,
                   POSITION('плоскость проведенного сечения' IN LOWER(pp.ocr_text)) AS pos_solution,
                   POSITION('боковая поверхность' IN LOWER(pp.ocr_text)) AS pos_surface
            FROM pdf_pages pp
            JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
            WHERE pp.ocr_text IS NOT NULL
              AND (LOWER(pp.ocr_text) LIKE '%плоскость проведенного сечения%'
                   OR (LOWER(pp.ocr_text) LIKE '%боковая поверхность%' AND LOWER(pp.ocr_text) LIKE '%исходной призмы%равна%'))
            ORDER BY ps.book_id, pp.page_num
        """))
        rows3 = list(r3)
        if rows3:
            print("\n  Найдено в таблице: pdf_pages (поле ocr_text)")
            for row in rows3:
                print(f"  pdf_pages.id: {row.page_id}, pdf_source_id: {row.pdf_source_id}, page_num: {row.page_num}, book_id: {row.book_id}")
                print(f"  длина ocr_text: {row.len_ocr}, позиция «плоскость проведенного сечения»: {row.pos_solution}, «боковая поверхность»: {row.pos_surface}")
                # Вывести кусок страницы вокруг решения
                r4 = db.execute(text("SELECT ocr_text FROM pdf_pages WHERE id = :id"), {"id": row.page_id})
                page_row = r4.fetchone()
                if page_row and page_row.ocr_text:
                    start = max(0, (row.pos_solution or row.pos_surface or 0) - 100)
                    snippet = page_row.ocr_text[start:start + 700]
                    print("  --- фрагмент ocr_text вокруг решения ---")
                    print(snippet)
                    print("  ---")
        else:
            print("  В pdf_pages.ocr_text фрагмент решения с такими фразами не найден.")

        print("\n" + "=" * 70)
    finally:
        db.close()


if __name__ == "__main__":
    main()
