"""
Файловый слой OCR: сырой и нормализованный текст по страницам в .md.

- raw: data/ocr_raw/{book_id}/{pdf_source_id}_{model}.md
- normalized: data/ocr_normalized/{book_id}/{pdf_source_id}.md

Структура внутри файла: заголовки ## Страница N, затем текст страницы.
Удобно для сравнения OCR-движков, ручной проверки и постраничной подачи в ИИ.
"""

import os
import re
from pathlib import Path
from typing import Optional


def get_data_base() -> Path:
    """Базовый каталог данных (DATA_DIR или data)."""
    return Path(os.environ.get("DATA_DIR", "data"))


def get_ocr_raw_path(book_id: int, pdf_source_id: int, model: str) -> Path:
    """Путь к файлу сырого OCR: ocr_raw/{book_id}/{pdf_source_id}_{model}.md"""
    base = get_data_base()
    return base / "ocr_raw" / str(book_id) / f"{pdf_source_id}_{model}.md"


def get_ocr_normalized_path(book_id: int, pdf_source_id: int) -> Path:
    """Путь к файлу нормализованного текста: ocr_normalized/{book_id}/{pdf_source_id}.md"""
    base = get_data_base()
    return base / "ocr_normalized" / str(book_id) / f"{pdf_source_id}.md"


def get_llm_checkpoint_path(book_id: int, pdf_source_id: int) -> Path:
    """Путь к чекпоинту LLM-нормализации (для продолжения после сбоя)."""
    base = get_data_base()
    return base / "ocr_normalized" / str(book_id) / f"{pdf_source_id}.llm_checkpoint.json"


PAGE_HEADER = re.compile(r"^##\s+Страница\s+(\d+)\s*$", re.IGNORECASE)


def build_md_by_pages(book_id: int, pdf_source_id: int, model: str, page_texts: list[str]) -> str:
    """Собрать содержимое .md: заголовок книги и для каждой страницы ## Страница N + текст."""
    lines = [
        f"# Книга {book_id}, источник {pdf_source_id}, модель {model}",
        "",
    ]
    for page_num, text in enumerate(page_texts, start=1):
        lines.append(f"## Страница {page_num}")
        lines.append("")
        lines.append((text or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip()


def write_raw_md(book_id: int, pdf_source_id: int, model: str, page_texts: list[str]) -> Path:
    """Записать сырой OCR в файл; создать каталоги при необходимости."""
    path = get_ocr_raw_path(book_id, pdf_source_id, model)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = build_md_by_pages(book_id, pdf_source_id, model, page_texts)
    path.write_text(content, encoding="utf-8")
    return path


def write_normalized_md(book_id: int, pdf_source_id: int, page_texts: list[str]) -> Path:
    """Записать нормализованный текст в файл (та же структура по страницам)."""
    path = get_ocr_normalized_path(book_id, pdf_source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = build_md_by_pages(book_id, pdf_source_id, "normalized", page_texts)
    path.write_text(content, encoding="utf-8")
    return path


def parse_md_by_pages(content: str) -> list[tuple[int, str]]:
    """
    Разобрать .md по блокам ## Страница N.
    Возвращает список (page_num_1based, text).
    Страницы без заголовка не учитываются; нумерация страниц — с 1.
    """
    result = []
    current_page = None
    current_lines = []

    for line in content.split("\n"):
        match = PAGE_HEADER.match(line.strip())
        if match:
            if current_page is not None:
                result.append((current_page, "\n".join(current_lines).strip()))
            current_page = int(match.group(1))
            current_lines = []
            continue
        if current_page is not None:
            current_lines.append(line)

    if current_page is not None:
        result.append((current_page, "\n".join(current_lines).strip()))
    return result


def read_normalized_pages(book_id: int, pdf_source_id: int) -> Optional[list[tuple[int, str]]]:
    """
    Прочитать нормализованный файл и вернуть список (page_num_1based, text).
    page_num_1based от 1. Если файла нет — None.
    """
    path = get_ocr_normalized_path(book_id, pdf_source_id)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    return parse_md_by_pages(content)
