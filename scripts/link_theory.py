#!/usr/bin/env python3
"""
Parse theoretical content (definitions, theorems, proofs) from paragraph text
and link them to control questions.

Control questions typically ask:
- "Что такое X?" -> needs definition of X
- "Докажите, что X" -> needs theorem/proof about X
- "Какие свойства имеет X?" -> needs properties of X
- "Сформулируйте теорему о X" -> needs theorem formulation

Usage:
    python scripts/link_theory.py --book-id 1
    python scripts/link_theory.py --book-id 1 --dry-run
    python scripts/link_theory.py --book-id 1 --question-id 123  # Test single question
"""

import re
import sys
import argparse
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "worker"))

from sqlalchemy import text
from database import SessionLocal


# Patterns for identifying theoretical blocks
DEFINITION_PATTERNS = [
    r'Определение[.\s]+([^.]+(?:\.[^.]+){0,3}\.)',  # "Определение. ..."
    r'называется?\s+([^.]+\.)',                      # "...называется X."
    r'называют\s+([^.]+\.)',                         # "...называют X."
    r'—\s*это\s+([^.]+\.)',                          # "X — это Y."
]

THEOREM_PATTERNS = [
    r'Теорема[\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,5}\.)',  # "Теорема 1. ..."
    r'ТЕОРЕМА[\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,5}\.)',  # "ТЕОРЕМА 1. ..."
    r'Следствие[\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,3}\.)',  # "Следствие. ..."
    r'Лемма[\s\d.]*[.:]?\s*([^.]+(?:\.[^.]+){0,3}\.)',     # "Лемма. ..."
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
    """A block of theoretical content (definition, theorem, proof, etc.)"""
    def __init__(self, block_type: str, content: str, keywords: list[str]):
        self.type = block_type  # 'definition', 'theorem', 'proof', 'property'
        self.content = content
        self.keywords = keywords  # Main terms for matching
    
    def __repr__(self):
        return f"<{self.type}: {self.content[:50]}... kw={self.keywords}>"


def extract_keywords(text: str) -> list[str]:
    """Extract key mathematical/geometric terms from text."""
    # Common geometric terms
    patterns = [
        r'угл[аоеу|ыі]+',
        r'смежн\w*',
        r'вертикальн\w*',
        r'параллельн\w*',
        r'перпендикулярн\w*',
        r'треугольник\w*',
        r'четырёхугольник\w*',
        r'окружност\w*',
        r'прям\w+',
        r'точк\w*',
        r'отрезок\w*',
        r'луч\w*',
        r'биссектрис\w*',
        r'медиан\w*',
        r'высот\w*',
        r'градус\w*',
        r'равн\w+',
        r'сумм\w*',
        r'разност\w*',
        r'теорем\w*',
        r'доказ\w+',
        r'свойств\w*',
        r'признак\w*',
        r'подоб\w+',
        r'симметри\w*',
    ]
    
    keywords = []
    text_lower = text.lower()
    
    for pattern in patterns:
        matches = re.findall(pattern, text_lower)
        keywords.extend(matches)
    
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    
    return unique[:10]  # Limit to top 10 keywords


def extract_theory_blocks(ocr_text: str) -> list[TheoryBlock]:
    """Extract definitions, theorems, and proofs from OCR text."""
    blocks = []
    
    # Extract definitions
    for pattern in DEFINITION_PATTERNS:
        matches = re.finditer(pattern, ocr_text, re.IGNORECASE)
        for match in matches:
            content = match.group(0).strip()
            if len(content) > 20:  # Filter out noise
                keywords = extract_keywords(content)
                blocks.append(TheoryBlock('definition', content, keywords))
    
    # Extract theorems
    for pattern in THEOREM_PATTERNS:
        matches = re.finditer(pattern, ocr_text, re.IGNORECASE)
        for match in matches:
            content = match.group(0).strip()
            if len(content) > 20:
                keywords = extract_keywords(content)
                blocks.append(TheoryBlock('theorem', content, keywords))
    
    # Extract proofs (more complex - need to find start and end)
    for pattern in PROOF_START_PATTERNS:
        match = re.search(pattern, ocr_text, re.IGNORECASE)
        if match:
            # Get text from proof start to next section or paragraph break
            start_pos = match.start()
            # Find end (next major section or double newline or specific markers)
            end_match = re.search(
                r'(?:\n\s*\n|Задачи|Упражнения|[§$]\s*\d+|Вопросы)',
                ocr_text[start_pos + 50:],
                re.IGNORECASE
            )
            if end_match:
                end_pos = start_pos + 50 + end_match.start()
            else:
                end_pos = min(start_pos + 1500, len(ocr_text))  # Max 1500 chars
            
            content = ocr_text[start_pos:end_pos].strip()
            if len(content) > 50:
                keywords = extract_keywords(content)
                blocks.append(TheoryBlock('proof', content, keywords))
    
    # Extract properties
    for pattern in PROPERTY_PATTERNS:
        matches = re.finditer(pattern, ocr_text, re.IGNORECASE)
        for match in matches:
            content = match.group(0).strip()
            if len(content) > 20:
                keywords = extract_keywords(content)
                blocks.append(TheoryBlock('property', content, keywords))
    
    return blocks


def match_question_to_theory(question_text: str, theory_blocks: list[TheoryBlock]) -> Optional[TheoryBlock]:
    """
    Find the best matching theory block for a control question.
    Returns the best matching block or None.
    """
    question_lower = question_text.lower()
    question_keywords = extract_keywords(question_text)
    
    if not question_keywords:
        return None
    
    best_match = None
    best_score = 0
    
    for block in theory_blocks:
        # Calculate keyword overlap
        common_keywords = set(question_keywords) & set(block.keywords)
        score = len(common_keywords)
        
        # Boost score based on question type -> block type matching
        if 'что такое' in question_lower and block.type == 'definition':
            score += 2
        if 'докажите' in question_lower and block.type in ('proof', 'theorem'):
            score += 2
        if 'свойств' in question_lower and block.type == 'property':
            score += 2
        if 'теорем' in question_lower and block.type == 'theorem':
            score += 2
        if 'сформулируйте' in question_lower and block.type in ('theorem', 'definition'):
            score += 1
        
        # Check for direct content match
        for kw in question_keywords:
            if kw in block.content.lower():
                score += 0.5
        
        if score > best_score:
            best_score = score
            best_match = block
    
    # Require minimum score threshold
    if best_score >= 2:
        return best_match
    
    return None


def get_section_theory(db, book_id: int, section: str) -> list[TheoryBlock]:
    """Get all theory blocks from pages belonging to a section."""
    # Get all OCR text from pages in this section
    result = db.execute(text("""
        SELECT pp.ocr_text
        FROM pdf_pages pp
        JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
        WHERE ps.book_id = :book_id
        ORDER BY pp.page_num
    """), {"book_id": book_id})
    
    all_blocks = []
    section_num = section.replace('§', '').strip() if section else None
    
    current_section = None
    
    for row in result:
        ocr_text = row.ocr_text or ""
        
        # Detect section changes
        section_match = re.search(r'[§$S]\s*(\d{1,2})[.,\s]', ocr_text[:800])
        if section_match:
            new_sec = section_match.group(1)
            if 1 <= int(new_sec) <= 25:
                current_section = new_sec
        
        # Only process pages from the target section
        if section_num and current_section == section_num:
            blocks = extract_theory_blocks(ocr_text)
            all_blocks.extend(blocks)
    
    return all_blocks


def link_theory_to_questions(db, book_id: int, question_id: Optional[int] = None, dry_run: bool = False):
    """
    Link theoretical content to control questions.
    """
    # Get control questions (problem_type = 'question')
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
    
    # Cache theory blocks by section
    section_cache = {}
    updates = []
    matched = 0
    
    for q in questions:
        section = q.section
        
        if section and section not in section_cache:
            print(f"  📖 Loading theory for section {section}...")
            section_cache[section] = get_section_theory(db, book_id, section)
            print(f"     Found {len(section_cache[section])} theory blocks")
        
        theory_blocks = section_cache.get(section, [])
        
        if not theory_blocks:
            continue
        
        # Try to match question to theory
        match = match_question_to_theory(q.problem_text, theory_blocks)
        
        if match:
            matched += 1
            solution = f"[{match.type.upper()}]\n{match.content}"
            
            print(f"\n  ✅ Q{q.number}: {q.problem_text[:50]}...")
            print(f"     → Matched: {match.type} ({len(match.content)} chars)")
            
            if not dry_run:
                updates.append((q.id, solution))
    
    # Apply updates
    if not dry_run and updates:
        for problem_id, solution in updates:
            db.execute(text("""
                UPDATE problems 
                SET solution_text = :solution,
                    updated_at = NOW()
                WHERE id = :id
            """), {"solution": solution, "id": problem_id})
        db.commit()
    
    print(f"\n📊 Summary:")
    print(f"   Questions processed: {len(questions)}")
    print(f"   Matched to theory: {matched}")
    print(f"   {'Would update' if dry_run else 'Updated'}: {len(updates)}")


def analyze_section(db, book_id: int, section: str):
    """Analyze and display theory blocks from a section (for debugging)."""
    print(f"\n📖 Analyzing section {section} for book {book_id}...")
    
    blocks = get_section_theory(db, book_id, section)
    
    print(f"\n Found {len(blocks)} theory blocks:\n")
    
    for i, block in enumerate(blocks, 1):
        print(f"  {i}. [{block.type.upper()}]")
        print(f"     Keywords: {', '.join(block.keywords[:5])}")
        print(f"     Content: {block.content[:150]}...")
        print()


def main():
    parser = argparse.ArgumentParser(description="Link theory to control questions")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID")
    parser.add_argument("--question-id", type=int, help="Test single question")
    parser.add_argument("--analyze-section", type=str, help="Analyze theory in section (e.g. '§1')")
    parser.add_argument("--dry-run", action="store_true", help="Don't update DB")
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        if args.analyze_section:
            analyze_section(db, args.book_id, args.analyze_section)
        else:
            link_theory_to_questions(
                db, 
                args.book_id, 
                question_id=args.question_id,
                dry_run=args.dry_run
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
