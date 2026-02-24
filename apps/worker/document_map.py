"""
PR3 — Document Map: deterministic spans (paragraph, tasks, answers, toc, index).

build(pages_data, book_id, pdf_source_id) -> doc_map dict.
Pages: list of (page_num_1based, text). Output: start_page/end_page 1-based.
"""
import re
from typing import Any, Optional

# Paragraph: § N, Параграф N, $ N (OCR confusion), fallback: numeric heading
RE_PARAGRAPH = re.compile(
    r"^\s*[§\$]\s*(\d+(?:\.\d+)?)[.,\s]|^\s*Параграф\s*(\d+)[.,\s]",
    re.IGNORECASE,
)
RE_FALLBACK_PARAGRAPH = re.compile(
    r"^\s*(\d+)\s*[\.\)]\s+[А-ЯA-Z].{3,120}$",
)

# Tasks block start
RE_TASKS_BLOCK = re.compile(
    r"^\s*(?:Задачи|Упражнения|Вопросы\s+к\s+параграфу|"
    r"Контрольные\s+задания|Практические\s+задания)\s*[.:]?",
    re.IGNORECASE,
)

# Answers: fuzzy (Ответы, Ответы и указания, etc.)
RE_ANSWERS = re.compile(
    r"^\s*(?:Ответы|Ответы\s+и\s+указания|Ответы\s+и\s+решения?)\s*[.:]?\s*$",
    re.IGNORECASE,
)

# TOC
RE_TOC = re.compile(
    r"^\s*(?:Содержание|Оглавление)\s*$",
    re.IGNORECASE,
)

# Index
RE_INDEX = re.compile(
    r"^\s*(?:Предметный\s+указатель|Указатель)\s*$",
    re.IGNORECASE,
)


def _page_text(lines: list[str]) -> str:
    return " ".join(l.strip() for l in lines if l.strip())


def _score_answers_page(page_num_1based: int, total_pages: int, text: str) -> float:
    """Higher if 'Ответы' near top and page is near end of book."""
    if not text or total_pages < 10:
        return 0.0
    lines = text.split("\n")[:8]
    head = "\n".join(lines).lower()
    if "ответ" not in head:
        return 0.0
    # Page near end
    ratio = page_num_1based / max(total_pages, 1)
    if ratio < 0.5:
        return 0.3
    if ratio >= 0.85:
        return 0.95
    return 0.5 + 0.45 * (ratio - 0.5) / 0.35


def _score_toc_page(text: str) -> float:
    """Many short lines like '§ N. Title' or 'N. Title' => toc."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 5:
        return 0.0
    short = sum(1 for l in lines if len(l) < 80)
    numbered = sum(1 for l in lines if re.match(r"^\s*[§\$]?\s*\d+[\.\)]\s+", l))
    if short >= len(lines) * 0.6 and numbered >= 3:
        return 0.85
    return 0.0


def build(
    pages_data: list[tuple[int, str]],
    book_id: int,
    pdf_source_id: int,
) -> dict[str, Any]:
    """
    Build document map from pages_data (list of (page_num_1based, text)).
    Returns doc_map: { version, book_id, pdf_source_id, spans: [...] }.
    Page numbers in spans are 1-based.
    """
    if not pages_data:
        return {
            "version": 1,
            "book_id": book_id,
            "pdf_source_id": pdf_source_id,
            "spans": [],
        }

    # Ensure page order (page_num 1-based)
    pages_data = sorted(pages_data, key=lambda x: x[0])
    total_pages = pages_data[-1][0] if pages_data else 0
    spans: list[dict[str, Any]] = []

    # 1) Paragraph spans (§ N, Параграф N)
    current_paragraph: Optional[tuple[str, int, int]] = None  # (section, start_page_1, end_page_1)
    prev_blank = True

    for page_num_1based, text in pages_data:
        lines = (text or "").split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped:
                prev_blank = True
                continue
            m = RE_PARAGRAPH.match(stripped)
            if m:
                num = (m.group(1) or m.group(2) or "").strip()
                section = f"§{num}" if num else "§?"
                if current_paragraph:
                    sec, start, end = current_paragraph
                    spans.append({
                        "type": "paragraph",
                        "section": sec,
                        "start_page": start,
                        "end_page": end,
                        "confidence": 0.9,
                    })
                current_paragraph = (section, page_num_1based, page_num_1based)
                prev_blank = False
                continue
            fm = RE_FALLBACK_PARAGRAPH.match(stripped)
            if fm and prev_blank and current_paragraph is None:
                current_paragraph = (f"§{fm.group(1)}", page_num_1based, page_num_1based)
            if current_paragraph is not None:
                sec, start, _ = current_paragraph
                current_paragraph = (sec, start, page_num_1based)
            prev_blank = False
        prev_blank = True

    if current_paragraph:
        sec, start, end = current_paragraph
        spans.append({
            "type": "paragraph",
            "section": sec,
            "start_page": start,
            "end_page": end,
            "confidence": 0.8,
        })

    # 2) Tasks block spans (first occurrence per "block" of theory)
    for page_num_1based, text in pages_data:
        for line in (text or "").split("\n"):
            if RE_TASKS_BLOCK.search(line.strip()):
                spans.append({
                    "type": "tasks_block",
                    "start_page": page_num_1based,
                    "end_page": page_num_1based,
                    "confidence": 0.85,
                })
                break

    # 3) Answers span (page with "Ответы" near top, near end of book)
    best_answers_page: Optional[int] = None
    best_score = 0.0
    for page_num_1based, text in pages_data:
        score = _score_answers_page(page_num_1based, total_pages, text or "")
        if score > best_score:
            best_score = score
            best_answers_page = page_num_1based
    if best_answers_page is not None and best_score >= 0.5:
        spans.append({
            "type": "answers",
            "start_page": best_answers_page,
            "end_page": total_pages,
            "confidence": round(best_score, 2),
        })

    # 4) TOC (first pages with many short numbered lines)
    for page_num_1based, text in pages_data:
        if page_num_1based > 20:
            break
        if _score_toc_page(text or "") >= 0.8:
            spans.append({
                "type": "toc",
                "start_page": page_num_1based,
                "end_page": page_num_1based,
                "confidence": 0.8,
            })
            break
    # Also explicit "Содержание" / "Оглавление"
    for page_num_1based, text in pages_data:
        for line in (text or "").split("\n")[:5]:
            if RE_TOC.search(line.strip()):
                if not any(s.get("type") == "toc" for s in spans):
                    spans.append({
                        "type": "toc",
                        "start_page": page_num_1based,
                        "end_page": page_num_1based,
                        "confidence": 0.9,
                    })
                break

    # 5) Index (Предметный указатель, usually near end)
    for page_num_1based, text in pages_data:
        if page_num_1based < total_pages - 20:
            continue
        for line in (text or "").split("\n")[:5]:
            if RE_INDEX.search(line.strip()):
                spans.append({
                    "type": "index",
                    "start_page": page_num_1based,
                    "end_page": total_pages,
                    "confidence": 0.8,
                })
                break
        else:
            continue
        break

    # 6) Front matter (first few pages before first paragraph or toc)
    first_content = total_pages + 1
    for s in spans:
        if s.get("type") in ("paragraph", "toc"):
            first_content = min(first_content, s["start_page"])
    if first_content > 1:
        spans.insert(0, {
            "type": "front_matter",
            "start_page": 1,
            "end_page": first_content - 1,
            "confidence": 0.8,
        })

    return {
        "version": 1,
        "book_id": book_id,
        "pdf_source_id": pdf_source_id,
        "spans": spans,
    }


def get_tasks_page_ranges(doc_map: dict[str, Any]) -> Optional[list[tuple[int, int]]]:
    """
    PR4: Return list of (start_page_1based, end_page_1based) for tasks content.
    From first tasks_block to (answers start - 1) or end of doc. Returns None if no tasks_block (fallback to full scan).
    """
    spans = doc_map.get("spans") or []
    tasks_start: Optional[int] = None
    answers_start: Optional[int] = None
    max_page = 0
    for s in spans:
        t = s.get("type")
        start = s.get("start_page")
        end = s.get("end_page")
        if start is not None:
            max_page = max(max_page, start, end if end is not None else start)
        if t == "tasks_block":
            if tasks_start is None and start is not None:
                tasks_start = start
        elif t == "answers" and start is not None:
            answers_start = start
    if tasks_start is None:
        return None
    end_page = (answers_start - 1) if answers_start is not None and answers_start > tasks_start else max_page
    if end_page < tasks_start:
        return None
    return [(tasks_start, end_page)]


def get_paragraph_spans(doc_map: dict[str, Any]) -> list[dict[str, Any]]:
    """PR4: Return spans with type=paragraph (section theory)."""
    return [s for s in (doc_map.get("spans") or []) if s.get("type") == "paragraph"]


def get_answers_page_range(doc_map: dict[str, Any]) -> Optional[tuple[int, int]]:
    """
    PR5: Return (start_page_1based, end_page_1based) for answers span, or None.
    """
    for s in (doc_map.get("spans") or []):
        if s.get("type") == "answers":
            start = s.get("start_page")
            end = s.get("end_page")
            if start is not None:
                return (start, end if end is not None else start)
    return None
