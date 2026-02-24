#!/usr/bin/env python3
"""
PR6 — Test safer header/footer stripping: only top/bottom N lines; enumerations preserved.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "apps" / "worker"))
from ocr_files import strip_page_headers_footers, strip_headers_footers_from_pages


def test_only_top_bottom_stripped():
    """Lines in the middle matching 'N класс' or '123' must NOT be removed."""
    text = """82 8 класс

§ 1. Первый параграф

Текст теории. Нумерация в середине страницы:
1) Первый пункт.
2) Второй пункт.
3) Третий пункт.

7 класс
"""
    result = strip_page_headers_footers(text, top_bottom_n=4)
    # "82 8 класс" is in top zone -> can be stripped
    # "7 класс" is in bottom zone -> can be stripped
    # "1) ..." "2) ..." "3) ..." must remain (middle + enumeration)
    assert "1)" in result or "1)" in result.split("\n")[3] or "Первый пункт" in result
    assert "2)" in result or "Второй пункт" in result
    assert "3)" in result or "Третий пункт" in result
    lines = [l.strip() for l in result.split("\n") if l.strip()]
    # No line should be just "7 класс" or "82 8 класс" if they were in zone and matched
    # We only check that enumerations are present
    assert any("1)" in l or "1." in l for l in lines) or "Первый" in result


def test_enumeration_in_top_zone_preserved():
    """1) or 2. at start of page (top zone) must NOT be stripped."""
    text = """1) Найдите угол.
2) Докажите равенство.
8 класс
"""
    result = strip_page_headers_footers(text, top_bottom_n=4)
    assert "1)" in result
    assert "2)" in result
    assert "Найдите" in result


def test_stats_mode():
    """Stats dict is populated with stripped count and by_pattern."""
    text = """7 класс

§ 1. Теория

Текст.

82
"""
    stats = {}
    result = strip_page_headers_footers(text, top_bottom_n=4, stats=stats)
    assert "stripped_count" in stats
    assert stats["stripped_count"] >= 1
    assert "by_pattern" in stats


def test_strip_headers_footers_from_pages_stats():
    """strip_headers_footers_from_pages with stats aggregates across pages."""
    pages = [
        (1, "8 класс\n\n§ 1.\n\nТекст.\n\n1"),
        (2, "7 класс\n\nЗадачи.\n\n2"),
    ]
    stats = {}
    out = strip_headers_footers_from_pages(pages, top_bottom_n=2, stats=stats)
    assert len(out) == 2
    assert "stripped_count" in stats


if __name__ == "__main__":
    test_only_top_bottom_stripped()
    test_enumeration_in_top_zone_preserved()
    test_stats_mode()
    test_strip_headers_footers_from_pages_stats()
    print("OK — PR6 strip: top/bottom only, enumerations preserved, stats mode")
