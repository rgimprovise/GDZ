"""
PR5 — Parse answers from doc_map answers span; link to problems.
No hard limits (section 1..25, problem <=200). Multi-line continuations; multiple answers per line.
Link by (book_id, section, number) when possible; fallback (book_id, number).
"""
import re
from typing import Any, Optional

from sqlalchemy import or_

from document_map import get_answers_page_range


# § N or $ N (OCR) at line start or inline
RE_PARAGRAPH_HEADER = re.compile(r"^[§\$S]\s*(\d+(?:\.\d+)?)[.\s,]*$", re.IGNORECASE)
RE_INLINE_PARAGRAPH = re.compile(r"[§\$S]\s*(\d+(?:\.\d+)?)[.\s,]", re.IGNORECASE)
# Answer start: N. or N) at word boundary (not mid-number)
RE_ANSWER_NUM = re.compile(r"(?<![0-9])(\d+(?:\.\d+)?)\s*[.)]\s*", re.IGNORECASE)


def _skip_header_line(line: str) -> bool:
    """Skip 'Ответы и указания' etc."""
    s = line.strip()
    if not s:
        return True
    if "ОТВЕТЫ" in s.upper() and "УКАЗАНИЯ" in s.upper():
        return True
    if s.startswith("Ответы") and "указания" in s.lower():
        return True
    return False


def parse_answers_from_text(text: str) -> list[dict[str, Any]]:
    """
    Parse answers from full text. No section/problem number limits.
    Returns list of {number, answer_text, section} (section may be None).
    Continuation: line not starting with N. / N) appends to last answer.
    Multiple answers per line: split by N. / N) and attach to current section.
    """
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    result: list[dict[str, Any]] = []
    current_section: Optional[str] = None
    current_number: Optional[str] = None
    current_answer: list[str] = []

    def flush_answer():
        nonlocal current_number, current_answer
        if current_number is not None and current_answer:
            ans = " ".join(current_answer).strip().rstrip(".,;")
            if len(ans) > 0:
                result.append({
                    "number": current_number,
                    "answer_text": ans[:2000],
                    "section": current_section,
                })
        current_number = None
        current_answer = []

    for line in lines:
        stripped = line.strip()
        if _skip_header_line(line):
            continue
        if not stripped:
            if current_number is not None:
                current_answer.append("")
            continue

        # Paragraph header: "§ 1." or "$ 2."
        para_match = RE_PARAGRAPH_HEADER.match(stripped)
        if para_match:
            flush_answer()
            current_section = para_match.group(1)
            continue

        # Inline paragraph marker: "§ 8." in the middle
        inline = RE_INLINE_PARAGRAPH.search(stripped)
        if inline:
            new_para = inline.group(1)
            current_section = new_para
            stripped = stripped[inline.end() :].strip()
            if not stripped:
                continue

        # Split by answer numbers: "4. text 7. text" -> ['', '4', ' text ', '7', ' text']
        parts = RE_ANSWER_NUM.split(stripped)
        if len(parts) == 1:
            if current_number is not None:
                current_answer.append(stripped)
            continue

        # parts[0] = text before first number (continuation to previous)
        if current_number is not None and parts[0].strip():
            current_answer.append(parts[0].strip())
        flush_answer()

        i = 1
        last_num = None
        while i + 1 < len(parts):
            num = parts[i].strip()
            seg = parts[i + 1].strip().rstrip(".,;")
            if num:
                last_num = num
            if num and seg:
                result.append({
                    "number": num,
                    "answer_text": seg[:2000],
                    "section": current_section,
                })
            i += 2

        # Trailing text after last number: next line may continue this answer
        if i < len(parts) and parts[i].strip() and last_num:
            current_number = last_num
            current_answer = [parts[i].strip()]
        else:
            current_number = None
            current_answer = []

    flush_answer()
    return result


def extract_answers_from_pages(
    pages_data: list[tuple[int, str]],
    doc_map: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Get text from answers span only; parse and return list of {number, answer_text, section}.
    """
    if not doc_map:
        return []
    r = get_answers_page_range(doc_map)
    if not r:
        return []
    start_p, end_p = r
    pages_by_num = {p[0]: p[1] for p in pages_data}
    chunks = []
    for page_num in range(start_p, end_p + 1):
        t = pages_by_num.get(page_num)
        if t and (t or "").strip():
            chunks.append((t or "").strip())
    if not chunks:
        return []
    full_text = "\n\n".join(chunks)
    return parse_answers_from_text(full_text)


def link_answers_to_problems(
    db,
    book_id: int,
    answers: list[dict[str, Any]],
) -> tuple[int, int]:
    """
    Update problems with answer_text. Prefer (book_id, section, number); fallback (book_id, number).
    Only set when answer_text is null or empty.
    Returns (updated_count, not_found_count).
    """
    from models import Problem

    updated = 0
    not_found = 0
    for item in answers:
        number = (item.get("number") or "").strip()
        answer_text = (item.get("answer_text") or "").strip()
        section = (item.get("section") or "").strip() or None
        if not number or not answer_text:
            continue

        # Prefer: book_id + section + number
        q = db.query(Problem).filter(
            Problem.book_id == book_id,
            Problem.number == number,
            or_(Problem.answer_text == None, Problem.answer_text == ""),
        )
        if section:
            sec_val = f"§{section}" if not section.startswith("§") else section
            q = q.filter(Problem.section == sec_val)
        prob = q.first()
        if prob:
            prob.answer_text = answer_text[:2000]
            updated += 1
            continue

        # Fallback: book_id + number only
        prob = db.query(Problem).filter(
            Problem.book_id == book_id,
            Problem.number == number,
            or_(Problem.answer_text == None, Problem.answer_text == ""),
        ).first()
        if prob:
            prob.answer_text = answer_text[:2000]
            updated += 1
        else:
            not_found += 1

    if updated:
        db.commit()
    return updated, not_found
