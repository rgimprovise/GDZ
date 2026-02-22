#!/usr/bin/env python3
"""
Исправление учебников геометрии в БД: subject и title.

Учебники, которые по названию/содержанию являются геометрией, но при первичном
seed были записаны как subject=math и title="Математика ...", приводятся к
subject=geometry и title="Геометрия ...".

Использование:
    python scripts/fix_geometry_books.py           # сухой прогон
    python scripts/fix_geometry_books.py --apply   # применить изменения
"""

import argparse
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps", "worker"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "infra", ".env"))

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


def build_geometry_title(grade: Optional[str], authors: Optional[str], part: Optional[str]) -> str:
    parts = ["Геометрия"]
    if grade:
        parts.append(f"{grade} класс")
    if authors:
        parts.append(authors)
    if part:
        parts.append(f"часть {part}")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Fix geometry books: subject and title")
    ap.add_argument("--apply", action="store_true", help="Apply updates to DB")
    ap.add_argument("--book-id", type=int, help="Fix only this book ID (e.g. 1)")
    args = ap.parse_args()
    dry = not args.apply

    db = Session()
    try:
        if args.book_id:
            r = db.execute(text("""
                SELECT id, title, subject, grade, authors, part
                FROM books WHERE id = :id
            """), {"id": args.book_id})
            rows = list(r)
            if not rows:
                print(f"Книга с ID={args.book_id} не найдена.")
                return
        else:
            # Найти книги subject=math, у которых в title есть геометрия, или все math для ручного --book-id
            r = db.execute(text("""
                SELECT id, title, subject, grade, authors, part
                FROM books
                WHERE subject = 'math'
                  AND (LOWER(title) LIKE '%геометр%' OR LOWER(title) LIKE '%geometry%')
            """))
            rows = list(r)
        if not rows:
            print("Книг «математика» с геометрией в названии не найдено. Используйте --book-id 1 для конкретной книги.")
            return
        print(f"Найдено книг для исправления: {len(rows)}")
        for row in rows:
            new_title = build_geometry_title(row.grade, row.authors, row.part)
            print(f"  ID={row.id}: {row.title!r} (subject={row.subject})")
            print(f"       -> subject=geometry, title={new_title!r}")
            if not dry:
                db.execute(
                    text("UPDATE books SET subject = 'geometry', title = :title WHERE id = :id"),
                    {"title": new_title, "id": row.id},
                )
        if not dry and rows:
            db.commit()
            print("Изменения применены.")
        elif dry and rows:
            print("Запустите с --apply, чтобы применить изменения.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
