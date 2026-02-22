#!/usr/bin/env python3
"""
Перезапуск ingestion по всем книгам: очистка страниц и задач по каждому PDF-источнику,
установка статуса pending и постановка в очередь на переобработку (нормализация + сегментация + решение).

Использование:
    python scripts/reingest_all_books.py              # очистить и поставить в очередь
    python scripts/reingest_all_books.py --no-queue   # только очистить и установить pending (очередь вручную)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "worker"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / "infra" / ".env")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
# В контейнере оставляем postgres; на хосте подключаемся к localhost
if POSTGRES_HOST == "postgres" and not os.getenv("DOCKER"):
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
    import argparse
    ap = argparse.ArgumentParser(description="Re-ingest all PDF sources (clear pages/problems, enqueue)")
    ap.add_argument("--no-queue", action="store_true", help="Only clear data and set pending, do not enqueue")
    args = ap.parse_args()

    db = Session()
    try:
        # Все pdf_sources
        r = db.execute(text("""
            SELECT ps.id, ps.book_id, ps.original_filename, b.title
            FROM pdf_sources ps
            JOIN books b ON b.id = ps.book_id
            ORDER BY ps.book_id, ps.id
        """))
        sources = list(r)
        if not sources:
            print("Нет PDF-источников в БД.")
            return

        print(f"Найдено PDF-источников: {len(sources)}")
        for row in sources:
            print(f"  id={row.id}, book_id={row.book_id}, {row.original_filename!r} ({row.title})")

        # Очистка по каждому источнику
        deleted_problems = 0
        deleted_pages = 0
        for row in sources:
            pid = row.id
            # Задачи, привязанные к страницам этого источника
            rp = db.execute(text("""
                DELETE FROM problems
                WHERE source_page_id IN (SELECT id FROM pdf_pages WHERE pdf_source_id = :id)
            """), {"id": pid})
            deleted_problems += rp.rowcount
            # Страницы этого источника
            rp2 = db.execute(text("DELETE FROM pdf_pages WHERE pdf_source_id = :id"), {"id": pid})
            deleted_pages += rp2.rowcount
            # Сброс статуса
            db.execute(text("UPDATE pdf_sources SET status = 'pending', error_message = NULL WHERE id = :id"), {"id": pid})

        db.commit()
        print(f"\nУдалено записей: problems={deleted_problems}, pdf_pages={deleted_pages}")
        print("Статусы pdf_sources установлены в 'pending'.")

        if args.no_queue:
            print("Очередь не трогаем (--no-queue). Запустите воркер и постановку в очередь вручную.")
            return

        # Постановка в очередь (нужен Redis и apps.worker)
        try:
            from config import get_settings
            from redis import Redis
            from rq import Queue
            from ingestion import process_pdf_source
            settings = get_settings()
            redis_conn = Redis.from_url(settings.redis_url)
            queue = Queue("ingestion", connection=redis_conn)
        except Exception as e:
            print(f"Не удалось подключиться к Redis/очереди: {e}")
            print("Запустите с --no-queue и поставьте задачи в очередь отдельно.")
            return

        for row in sources:
            job = queue.enqueue(
                process_pdf_source,
                row.id,
                job_timeout="30m",
                result_ttl=3600,
            )
            print(f"  В очередь: pdf_source_id={row.id} -> job {job.id}")

        print(f"\nВ очередь добавлено {len(sources)} заданий. Запустите воркер (ingestion queue) для обработки.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
