#!/usr/bin/env python3
"""
[LEGACY] Parse theoretical content and link to control questions.
Prefer runtime retrieval from section_theory (ingestion). Kept for reference.

Usage:
    python scripts/legacy/link_theory.py --book-id 1
"""

import re
import sys
import argparse
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "apps" / "worker"))

from sqlalchemy import text
from database import SessionLocal


DEFINITION_PATTERNS = [
    r'Определение[.\s]+([^.]+(?:\.[^.]+){0,3}\.)',
    r'называется?\s+([^.]+\.)',
    r'называют\s+([^.]+\.)',
    r'—\s*это\s+([^.]+\.)',
]

THEOREM_PATTERNS = [
    r'Теорема[\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,5}\.)',
    r'ТЕОРЕМА[\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,5}\.)',
    r'Следствие[\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,3}\.)',
    r'Лемма[\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,3}\.)',
]

PROOF_START_PATTERNS = [
    r'Доказательство[.\s:]',
    r'Докажем[,.\s]',
    r'ДОКАЗАТЕЛЬСТВО[.\s:]',
]

PROPERTY_PATTERNS = [
    r'Свойств[оа][\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,3}\.)',
    r'(?:Основные\s+)?свойства?\s+([^:]+):\s*([^.]+(?:\.[^.]+){0,5}\.)',
]


class TheoryBlock:
    def __init__(self, block_type: str, content: str, keywords: list):
        self.type = block_type
        self.content = content
        self.keywords = keywords

    def __repr__(self):
        return f"<{self.type}: {self.content[:50]}... kw={self.keywords}>"


def extract_keywords(text: str) -> list:
    patterns = [
        r'угл[аоеу|ыі]+', r'смежн\w*', r'вертикальн\w*', r'параллельн\w*', r'перпендикулярн\w*',
        r'треугольник\w*', r'четырёхугольник\w*', r'окружност\w*', r'прям\w+', r'точк\w*',
        r'отрезок\w*', r'луч\w*', r'биссектрис\w*', r'медиан\w*', r'высот\w*', r'градус\w*',
        r'равн\w+', r'сумм\w*', r'разност\w*', r'теорем\w*', r'доказ\w+', r'свойств\w*',
        r'признак\w*', r'подоб\w+', r'симметри\w*',
    ]
    keywords = []
    text_lower = text.lower()
    for pattern in patterns:
        keywords.extend(re.findall(pattern, text_lower))
    seen = set()
    unique = [kw for kw in keywords if kw not in seen and not seen.add(kw)]
    return unique[:10]


def extract_theory_blocks(ocr_text: str) -> list:
    blocks = []
    for pattern in DEFINITION_PATTERNS:
        for match in re.finditer(pattern, ocr_text, re.IGNORECASE):
            content = match.group(0).strip()
            if len(content) > 20:
                blocks.append(TheoryBlock('definition', content, extract_keywords(content)))
    for pattern in THEOREM_PATTERNS:
        for match in re.finditer(pattern, ocr_text, re.IGNORECASE):
            content = match.group(0).strip()
            if len(content) > 20:
                blocks.append(TheoryBlock('theorem', content, extract_keywords(content)))
    for pattern in PROOF_START_PATTERNS:
        match = re.search(pattern, ocr_text, re.IGNORECASE)
        if match:
            start_pos = match.start()
            end_match = re.search(
                r'(?:\n\s*\n|Задачи|Упражнения|[§$]\s*\d+|Вопросы)',
                ocr_text[start_pos + 50:], re.IGNORECASE
            )
            end_pos = start_pos + 50 + (end_match.start() if end_match else 1500)
            end_pos = min(end_pos, len(ocr_text))
            content = ocr_text[start_pos:end_pos].strip()
            if len(content) > 50:
                blocks.append(TheoryBlock('proof', content, extract_keywords(content)))
    for pattern in PROPERTY_PATTERNS:
        for match in re.finditer(pattern, ocr_text, re.IGNORECASE):
            content = match.group(0).strip()
            if len(content) > 20:
                blocks.append(TheoryBlock('property', content, extract_keywords(content)))
    return blocks


def match_question_to_theory(question_text: str, theory_blocks: list) -> Optional[TheoryBlock]:
    question_lower = question_text.lower()
    question_keywords = extract_keywords(question_text)
    if not question_keywords:
        return None
    best_match = None
    best_score = 0
    for block in theory_blocks:
        common = set(question_keywords) & set(block.keywords)
        score = len(common)
        if 'что такое' in question_lower and block.type == 'definition':
            score += 2
        if 'докажите' in question_lower and block.type in ('proof', 'theorem'):
            score += 2
        if 'свойств' in question_lower and block.type == 'property':
            score += 2
        if 'теорем' in question_lower and block.type == 'theorem':
            score += 2
        for kw in question_keywords:
            if kw in block.content.lower():
                score += 0.5
        if score > best_score:
            best_score = score
            best_match = block
    return best_match if best_score >= 2 else None


def get_section_theory(db, book_id: int, section: str) -> list:
    result = db.execute(text("""
        SELECT pp.ocr_text FROM pdf_pages pp
        JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
        WHERE ps.book_id = :book_id ORDER BY pp.page_num
    """), {"book_id": book_id})
    all_blocks = []
    section_num = section.replace('§', '').strip() if section else None
    current_section = None
    for row in result:
        ocr_text = row.ocr_text or ""
        section_match = re.search(r'[§$S]\s*(\d{1,2})[.,\s]', ocr_text[:800])
        if section_match:
            try:
                if 1 <= int(section_match.group(1)) <= 25:
                    current_section = section_match.group(1)
            except ValueError:
                pass
        if section_num and current_section == section_num:
            all_blocks.extend(extract_theory_blocks(ocr_text))
    return all_blocks


def link_theory_to_questions(db, book_id: int, question_id: Optional[int] = None, dry_run: bool = False):
    query_params = {"book_id": book_id}
    base_query = """
        SELECT id, number, section, problem_text, solution_text
        FROM problems
        WHERE book_id = :book_id
          AND (problem_type = 'question' OR problem_type IS NULL OR problem_type = 'unknown')
          AND solution_text IS NULL
    """
    if question_id:
        base_query += " AND id = :question_id"
        query_params["question_id"] = question_id
    result = db.execute(text(base_query), query_params)
    questions = list(result)
    print(f"📚 Found {len(questions)} questions without solutions")
    section_cache = {}
    updates = []
    matched = 0
    for q in questions:
        section = q.section
        if section and section not in section_cache:
            section_cache[section] = get_section_theory(db, book_id, section)
        theory_blocks = section_cache.get(section, [])
        if not theory_blocks:
            continue
        match = match_question_to_theory(q.problem_text, theory_blocks)
        if match:
            matched += 1
            solution = f"[{match.type.upper()}]\n{match.content}"
            if not dry_run:
                updates.append((q.id, solution))
    if not dry_run and updates:
        for problem_id, solution in updates:
            db.execute(text("UPDATE problems SET solution_text = :solution, updated_at = NOW() WHERE id = :id"),
                       {"solution": solution, "id": problem_id})
        db.commit()
    print(f"   Matched: {matched}, {'Would update' if dry_run else 'Updated'}: {len(updates)}")


def main():
    parser = argparse.ArgumentParser(description="Link theory to control questions (legacy)")
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--question-id", type=int, help="Test single question")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        link_theory_to_questions(db, args.book_id, question_id=args.question_id, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
