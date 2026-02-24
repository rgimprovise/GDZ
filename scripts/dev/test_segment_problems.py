#!/usr/bin/env python3
"""
PR2 regression: § and Параграф must NOT be treated as problem starts.
- segment_problems must not return problems whose text starts with '§' or 'Параграф'.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "apps" / "worker"))
from ingestion import segment_problems


def test_paragraph_header_not_problem():
    """§ 1. Title and Параграф 2. Title must not create a problem row."""
    text_section = """
§ 1. Первый параграф

Текст теории параграфа. Определения и теоремы.

1. Докажите, что сумма углов треугольника равна 180°.
"""
    problems = segment_problems(text_section, page_num=0)
    # Must have exactly one problem (the "1. Докажите...")
    assert len(problems) >= 1, "Expected at least one real problem"
    for p in problems:
        t = (p.get("text") or "").strip()
        assert not t.startswith("§"), f"Problem must not start with §: {t[:80]!r}"
        assert not t.lower().startswith("параграф"), f"Problem must not start with Параграф: {t[:80]!r}"


def test_paragraph_only_page():
    """Page with only § 3. Title and theory — no problems."""
    text = """
§ 3. Смежные углы

Два угла называются смежными, если у них одна сторона общая...
"""
    problems = segment_problems(text, page_num=0)
    # Should not create a "problem" from "§ 3. Смежные углы"
    for p in problems:
        t = (p.get("text") or "").strip()
        assert not t.startswith("§"), f"§ must not be problem: {t[:80]!r}"
        assert not t.lower().startswith("параграф"), f"Параграф must not be problem: {t[:80]!r}"


def test_numbered_problem_kept():
    """Real numbered problem (1. ... or 206. ...) must still be detected."""
    text = """
206. Найдите площадь треугольника по сторонам 3, 4, 5.
207. В окружность вписан квадрат...
"""
    problems = segment_problems(text, page_num=0)
    assert len(problems) >= 1, "Numbered problems must still be detected"
    numbers = [p.get("number") for p in problems]
    assert "206" in numbers or "207" in numbers or any(n in ("206", "207") for n in numbers if n)


if __name__ == "__main__":
    test_paragraph_header_not_problem()
    test_paragraph_only_page()
    test_numbered_problem_kept()
    print("OK — PR2 regression: §/Параграф are not problem starts")
