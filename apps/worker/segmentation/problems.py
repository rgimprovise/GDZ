"""
PR4 — Problems extraction from tasks-span text only (doc_map-driven).
1 DB row = 1 problem. Multi-problem line splitter: 206. ... 207. ...
"""
import re
from typing import Any, Optional

from document_map import get_tasks_page_ranges

# Начало блока решения/ответа
RE_SOLUTION_START = re.compile(
    r"^\s*Р\s*е\s*ш\s*е\s*н\s*и\s*е\s*\.|^\s*Решение\s*\."
    r"|^\s*О\s*т\s*в\s*е\s*т\s*\.|^\s*Ответ\s*\.",
    re.IGNORECASE,
)

PROBLEM_START_PATTERNS = [
    r"Контрольное задание\s*(?:№\s*)?(?:\(\s*)?(\d+)(?:\))?",
    r"Контрольные задания\s*(?:№\s*)?(?:\(\s*)?(\d+)(?:\))?",
    r"Практическое задание\s*(?:№\s*)?(?:\(\s*)?(\d+)(?:\))?",
    r"Задача\s*\(\s*(\d+)\s*\)\s*\.?",
    r"Задача\s+(\d+)",
    r"Упражнение\s+(\d+)",
    r"Упражнение\s*\(\s*(\d+)\s*\)",
    r"Вопрос\s*(?:№\s*)?(?:\(\s*)?(\d+)(?:\))?",
    r"Вопросы?\s+(?:к?\s*)?(?:№\s*)?(\d+)",
    r"Задание\s*\(\s*(\d+)\s*\)",
    r"Задание\s+(\d+)",
    r"Задание\s*(?:№\s*)?(\d+)",
    r"Exercise\s+(\d+)",
    r"№\s*(\d+(?:\.\d+)?)",
    r"^(\d+)\.\s+",
    r"^(\d+)\)\s+",
]


def segment_problems(text: str, page_num: int) -> list[dict[str, Any]]:
    """
    Segment page text into problems. Same logic as ingestion.segment_problems.
    Returns list of dicts: number, text, solution_text, confidence.
    """
    if not text or len(text.strip()) < 10:
        return []

    problems = []
    lines = text.split("\n")
    current_problem = None
    current_number = None
    solution_lines = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_problem and solution_lines is None:
                current_problem += "\n" + line.rstrip()
            elif solution_lines is not None:
                solution_lines.append(line.rstrip())
            continue

        if RE_SOLUTION_START.search(stripped):
            if current_problem and len(current_problem) > 20:
                problems.append({
                    "number": current_number,
                    "text": current_problem.strip(),
                    "solution_text": None,
                    "confidence": 60,
                })
            current_problem = None
            current_number = None
            solution_lines = [stripped]
            continue

        is_problem_start = False
        number = None
        for pattern in PROBLEM_START_PATTERNS:
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                is_problem_start = True
                number = match.group(1)
                break

        if is_problem_start:
            if solution_lines is not None and problems:
                sol = "\n".join(s for s in solution_lines if s).strip()
                if sol:
                    problems[-1]["solution_text"] = sol
            solution_lines = None

            if current_problem and len(current_problem) > 20:
                problems.append({
                    "number": current_number,
                    "text": current_problem.strip(),
                    "solution_text": None,
                    "confidence": 60,
                })
            current_problem = stripped
            current_number = number
        elif solution_lines is not None:
            solution_lines.append(stripped)
        elif current_problem is not None:
            current_problem += "\n" + stripped

    if solution_lines is not None and problems:
        sol = "\n".join(s for s in solution_lines if s).strip()
        if sol:
            problems[-1]["solution_text"] = sol

    if current_problem and len(current_problem) > 20:
        problems.append({
            "number": current_number,
            "text": current_problem.strip(),
            "solution_text": None,
            "confidence": 60,
        })

    return problems


# Multi-problem on one line: "206. Текст. 207. Текст."
RE_NUM_DOT = re.compile(r"(\d+)\.\s+")


def split_multi_problem_line(text: str) -> list[tuple[str, str]]:
    """
    If text contains multiple "N. " starts on one line, split into (number, problem_text).
    E.g. "206. Найдите x. 207. Докажите." -> [("206", "206. Найдите x."), ("207", "207. Докажите.")]
    Returns list of (number, text); if no split, returns single item or empty.
    """
    if not text or len(text.strip()) < 10:
        return []
    stripped = text.strip()
    matches = list(RE_NUM_DOT.finditer(stripped))
    if len(matches) <= 1:
        first = RE_NUM_DOT.match(stripped)
        if first:
            return [(first.group(1), stripped)]
        return []
    result = []
    for i, m in enumerate(matches):
        num = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped)
        segment = stripped[start:end].strip()
        if len(segment) > 15:
            result.append((num, segment))
    return result


def _apply_multi_problem_split(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run split_multi_problem_line on each problem text; expand into more problems if split."""
    out = []
    for p in problems:
        parts = split_multi_problem_line(p.get("text") or "")
        if len(parts) <= 1:
            out.append(p)
            continue
        for num, seg_text in parts:
            out.append({
                "number": num,
                "text": seg_text,
                "solution_text": p.get("solution_text"),
                "confidence": p.get("confidence", 60),
            })
    return out


def extract_problems_from_pages(
    pages_data: list[tuple[int, str]],
    doc_map: Optional[dict[str, Any]],
    book_id: int,
) -> list[dict[str, Any]]:
    """
    Extract problems from tasks-span pages only. When doc_map has tasks ranges, filter pages to that range.
    Returns list of dicts: number, text, solution_text, confidence, page_num_1based (for source_page_id lookup).
    Applies multi-problem line splitter. 1 row = 1 problem.
    """
    pages_data = sorted(pages_data, key=lambda x: x[0])
    if not pages_data:
        return []

    tasks_ranges = get_tasks_page_ranges(doc_map) if doc_map else None
    if tasks_ranges:
        page_set = set()
        for start, end in tasks_ranges:
            for p in range(start, end + 1):
                page_set.add(p)
        pages_data = [(p, t) for p, t in pages_data if p in page_set]
    if not pages_data:
        return []

    all_problems = []
    for page_num_1based, text in pages_data:
        page_num_0 = page_num_1based - 1
        problems = segment_problems(text, page_num_0)
        problems = _apply_multi_problem_split(problems)
        for p in problems:
            p["page_num_1based"] = page_num_1based
            p["page_ref"] = f"стр. {page_num_1based}"
        all_problems.extend(problems)

    return all_problems
