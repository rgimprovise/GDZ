#!/usr/bin/env python3
"""
Извлечение встроенного текста из PDF (файл с «ocr» в имени) без БД и без Tesseract.
Пишет data/ocr_raw/{book_id}/{source_id}_embedded.md и data/ocr_normalized/{book_id}/{source_id}.md.
Дальше можно запустить «LLM нормализация» и «Распределение в БД» из интерфейса (когда БД доступна).

Использование (из корня репозитория):
  python scripts/run_embedded_pdf_extract.py --pdf "data/pdfs/...-ocr.pdf" --book-id 1 --source-id 1
  python scripts/run_embedded_pdf_extract.py   # ищет *ocr*.pdf в data/pdfs, book_id=1, source_id=1
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "worker"))

def main():
    ap = argparse.ArgumentParser(description="Extract embedded text from PDF (no OCR, no DB)")
    ap.add_argument("--pdf", type=str, help="Path to PDF with embedded text (e.g. *-ocr.pdf)")
    ap.add_argument("--book-id", type=int, default=1)
    ap.add_argument("--source-id", type=int, default=1)
    ap.add_argument("--data-dir", type=str, default=None, help="Data dir (default: ROOT/data)")
    args = ap.parse_args()

    data_dir = Path(args.data_dir or ROOT / "data")
    pdf_path = args.pdf
    if not pdf_path:
        pdfs_dir = data_dir / "pdfs"
        candidates = list(pdfs_dir.glob("*ocr*.pdf")) if pdfs_dir.exists() else []
        if not candidates:
            print("Не найден PDF с «ocr» в имени. Укажите --pdf путь.")
            sys.exit(1)
        pdf_path = str(candidates[0])
        print(f"Используется: {pdf_path}")

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"Файл не найден: {pdf_path}")
        sys.exit(1)

    try:
        import fitz
    except ImportError:
        print("Установите pymupdf: pip install pymupdf")
        sys.exit(1)

    doc = fitz.open(str(pdf_path))
    page_count = len(doc)
    print(f"📄 Страниц: {page_count}")
    raw_texts = []
    for i in range(page_count):
        raw_texts.append(doc[i].get_text(sort=True) or "")
        if (i + 1) % 50 == 0 or i == page_count - 1:
            print(f"   Извлечение текста: {i + 1}/{page_count}")
    doc.close()

    base = data_dir
    book_id, source_id = args.book_id, args.source_id
    raw_dir = base / "ocr_raw" / str(book_id)
    norm_dir = base / "ocr_normalized" / str(book_id)
    raw_dir.mkdir(parents=True, exist_ok=True)
    norm_dir.mkdir(parents=True, exist_ok=True)

    lines_raw = [f"# Книга {book_id}, источник {source_id}, модель embedded", ""]
    lines_norm = [f"# Книга {book_id}, источник {source_id}, модель normalized", ""]
    for page_num, text in enumerate(raw_texts, start=1):
        lines_raw.append(f"## Страница {page_num}")
        lines_raw.append("")
        lines_raw.append((text or "").strip())
        lines_raw.append("")
        lines_norm.append(f"## Страница {page_num}")
        lines_norm.append("")
        lines_norm.append((text or "").strip())
        lines_norm.append("")

    raw_path = raw_dir / f"{source_id}_embedded.md"
    norm_path = norm_dir / f"{source_id}.md"
    raw_path.write_text("\n".join(lines_raw).rstrip(), encoding="utf-8")
    norm_path.write_text("\n".join(lines_norm).rstrip(), encoding="utf-8")
    print(f"📁 Сырой текст: {raw_path}")
    print(f"📁 Нормализованный (для LLM/распределения): {norm_path}")
    print("Дальше: «LLM нормализация» и «Распределение в БД» из интерфейса (при доступной БД) или подгрузка .md на VPS (docs/UPLOAD_NORMALIZED_TO_VPS.md).")


if __name__ == "__main__":
    main()
