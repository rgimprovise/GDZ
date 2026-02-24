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


def get_page_images_dir(book_id: int, pdf_source_id: int) -> Path:
    """Каталог изображений страниц: data/page_images/{book_id}/{pdf_source_id}/."""
    base = get_data_base()
    return base / "page_images" / str(book_id) / str(pdf_source_id)


def save_page_image(book_id: int, pdf_source_id: int, page_num: int, png_bytes: bytes) -> Optional[str]:
    """
    Сохранить PNG страницы на диск; вернуть относительный ключ для PdfPage.image_minio_key.
    Ключ: page_images/{book_id}/{pdf_source_id}/page_{page_num}.png (для разрешения через DATA_DIR).
    """
    try:
        dir_path = get_page_images_dir(book_id, pdf_source_id)
        dir_path.mkdir(parents=True, exist_ok=True)
        path = dir_path / f"page_{page_num}.png"
        path.write_bytes(png_bytes)
        return f"page_images/{book_id}/{pdf_source_id}/page_{page_num}.png"
    except Exception:
        return None


def resolve_page_image_path(image_minio_key: Optional[str]) -> Optional[Path]:
    """
    Разрешить image_minio_key (относительный путь) в полный путь к файлу.
    Для использования в debug/API при отдаче изображения страницы.
    """
    if not image_minio_key or not image_minio_key.strip():
        return None
    base = get_data_base()
    path = base / image_minio_key.strip()
    if path.exists() and path.is_file():
        return path
    return None


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


# Паттерны колонтитулов (header/footer), попадающих в OCR с верстки учебника.
# Типично: "N класс", "82 8 класс", номер страницы, короткие артефакты.
RE_HEADER_CLASS = re.compile(r"^\s*[\d\s]*\d+\s*класс\s*$", re.IGNORECASE)
RE_PAGE_NUMBER_ONLY = re.compile(r"^\s*\d+\s*$")
RE_HEADER_ARTIFACT = re.compile(r"^\s*[\d\s]{1,15}\s*$")  # только цифры/пробелы, короткая строка

# PR6: не удалять нумерованные пункты (1) … 2) … или 1. … 2. …) даже в зоне колонтитулов
RE_ENUMERATION_START = re.compile(r"^\s*\d+\s*[.)]\s+", re.IGNORECASE)


def _is_header_footer_candidate(stripped: str) -> Optional[str]:
    """
    Return pattern name if line looks like header/footer, else None.
    Used only in top/bottom zone; enumerations are excluded separately.
    """
    if not stripped:
        return None
    if RE_HEADER_CLASS.match(stripped):
        return "class"
    if RE_PAGE_NUMBER_ONLY.match(stripped):
        return "page_number"
    if len(stripped) <= 15 and RE_HEADER_ARTIFACT.match(stripped):
        return "artifact"
    return None


def strip_page_headers_footers(
    text: str,
    top_bottom_n: int = 4,
    stats: Optional[dict] = None,
) -> str:
    """
    PR6 — Удалять колонтитулы только в первых и последних N строках страницы.
    Строки в середине страницы не трогаем (нет потери нумераций 1) 2) и т.д.).
    Передайте stats={} для отчёта: что и сколько удалено.
    """
    if not (text or "").strip():
        return text or ""
    lines = (text or "").split("\n")
    n = max(0, top_bottom_n)
    top_indices = set(range(min(n, len(lines))))
    bottom_indices = set(range(max(0, len(lines) - n), len(lines))) if len(lines) > 2 * n else set()

    result = []
    stripped_count = 0
    by_pattern = {}

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue
        # Только в зоне колонтитулов проверяем удаление
        in_zone = i in top_indices or i in bottom_indices
        if not in_zone:
            result.append(line)
            continue
        # Не удалять нумерованные пункты (1) … 2. …)
        if RE_ENUMERATION_START.match(stripped):
            result.append(line)
            continue
        pattern = _is_header_footer_candidate(stripped)
        if pattern:
            stripped_count += 1
            by_pattern[pattern] = by_pattern.get(pattern, 0) + 1
            continue
        result.append(line)

    if stats is not None:
        stats["stripped_count"] = stats.get("stripped_count", 0) + stripped_count
        for p, c in by_pattern.items():
            stats["by_pattern"] = stats.get("by_pattern") or {}
            stats["by_pattern"][p] = stats["by_pattern"].get(p, 0) + c

    return "\n".join(result).strip()


def strip_headers_footers_from_pages(
    pages_data: list[tuple[int, str]],
    top_bottom_n: int = 4,
    stats: Optional[dict] = None,
) -> list[tuple[int, str]]:
    """Применить strip_page_headers_footers к тексту каждой страницы. PR6: top/bottom only; optional stats."""
    out = []
    for page_num, text in pages_data:
        cleaned = strip_page_headers_footers(text, top_bottom_n=top_bottom_n, stats=stats)
        out.append((page_num, cleaned))
    return out


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
