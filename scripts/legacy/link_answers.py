#!/usr/bin/env python3
"""
[LEGACY] Parse answers from OCR pages and link to problems.
Replaced by apps/worker/segmentation/answers.py (PR5, doc_map-driven). Kept for reference.

Usage:
    python scripts/legacy/link_answers.py --book-id 1
    python scripts/legacy/link_answers.py --book-id 1 --dry-run
"""

import re
import sys
import argparse
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "apps" / "worker"))

from sqlalchemy import text
from database import SessionLocal


def get_answer_pages(db, book_id: int) -> list[tuple[int, str]]:
    """Get OCR text from answer pages."""
    result = db.execute(text("""
        SELECT pp.page_num, pp.ocr_text
        FROM pdf_pages pp
        JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
        WHERE ps.book_id = :book_id
          AND pp.ocr_text ILIKE '%ответы%указан%задач%'
        ORDER BY pp.page_num
    """), {"book_id": book_id})
    
    return [(r.page_num, r.ocr_text) for r in result]


def parse_answers_from_ocr(pages: list[tuple[int, str]]) -> dict[str, dict[str, str]]:
    """
    Parse answers from OCR text.
    
    Returns: {paragraph: {problem_num: answer_text}}
    """
    all_text = "\n".join(text for _, text in pages)
    
    answers = {}
    current_paragraph = None
    
    lines = all_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Skip header lines
        if 'ОТВЕТЫ' in line.upper() and 'УКАЗАНИЯ' in line.upper():
            continue
        if line.startswith('Ответы') and 'указания' in line.lower():
            continue
        
        # Check for paragraph header: "§ 1." or "$ 1." (OCR confuses § with $)
        # Standalone: "§ 1." or "$ 2." at beginning
        para_match = re.match(r'^[§$S]\s*(\d{1,2})[.\s,]*$', line)
        if para_match:
            current_paragraph = para_match.group(1)
            if current_paragraph not in answers:
                answers[current_paragraph] = {}
            continue
        
        # Inline paragraph marker: "§ 8." or "$ 5." in the middle of text
        inline_para = re.search(r'[§$S]\s*(\d{1,2})[.\s,]', line)
        if inline_para:
            new_para = inline_para.group(1)
            if 1 <= int(new_para) <= 25:  # Valid section number
                current_paragraph = new_para
                if current_paragraph not in answers:
                    answers[current_paragraph] = {}
                # Continue parsing this line for answers
                line = line[inline_para.end():]
        
        if current_paragraph is None:
            continue
        
        # Parse answers: "4. text 7. text 10. text"
        # Split by problem numbers
        parts = re.split(r'(?<![0-9])(\d{1,3})\.\s*', line)
        
        # parts = ['prefix', '4', 'answer4', '7', 'answer7', ...]
        i = 1
        while i < len(parts) - 1:
            problem_num = parts[i]
            answer_text = parts[i + 1].strip().rstrip('.,;')
            
            if answer_text and len(answer_text) > 1 and int(problem_num) <= 200:
                # Accumulate answers
                if problem_num in answers[current_paragraph]:
                    answers[current_paragraph][problem_num] += ' ' + answer_text
                else:
                    answers[current_paragraph][problem_num] = answer_text
            i += 2
    
    return answers


def update_problems(db, book_id: int, answers: dict, dry_run: bool = False) -> tuple[int, int]:
    """Update problems with answers, matching by section, number, and type=exercise."""
    updated = 0
    not_found = 0
    
    for para, problem_answers in answers.items():
        section = f"§{para}"
        
        for problem_num, answer_text in problem_answers.items():
            if len(answer_text) < 2:
                continue
            
            # Match ONLY exercises (not questions) with section and number
            if dry_run:
                result = db.execute(text("""
                    SELECT id, number, section, problem_type, LEFT(problem_text, 50) as text
                    FROM problems 
                    WHERE book_id = :book_id 
                      AND number = :number
                      AND section = :section
                      AND problem_type = 'exercise'
                    LIMIT 3
                """), {"book_id": book_id, "number": problem_num, "section": section})
                rows = result.fetchall()
                if rows:
                    updated += len(rows)
                else:
                    not_found += 1
            else:
                result = db.execute(text("""
                    UPDATE problems 
                    SET answer_text = :answer
                    WHERE book_id = :book_id 
                      AND number = :number
                      AND section = :section
                      AND problem_type = 'exercise'
                      AND (answer_text IS NULL OR answer_text = '')
                    RETURNING id
                """), {
                    "answer": answer_text[:2000],
                    "book_id": book_id,
                    "number": problem_num,
                    "section": section
                })
                rows = result.fetchall()
                if rows:
                    updated += len(rows)
                else:
                    not_found += 1
    
    return updated, not_found


def main():
    parser = argparse.ArgumentParser(description="Link answers to problems from OCR (legacy)")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID")
    parser.add_argument("--dry-run", action="store_true", help="Don't update DB")
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        print(f"📚 Loading answer pages for book {args.book_id}...")
        pages = get_answer_pages(db, args.book_id)
        
        if not pages:
            print("❌ No answer pages found!")
            return
        
        print(f"✅ Found {len(pages)} pages with answers")
        
        print("🔍 Parsing answers...")
        answers = parse_answers_from_ocr(pages)
        
        total = sum(len(a) for a in answers.values())
        print(f"✅ Parsed {total} answers from {len(answers)} paragraphs")
        
        # Show sample
        for para in sorted(answers.keys(), key=lambda x: int(x) if x.isdigit() else 0)[:5]:
            items = list(answers[para].items())[:3]
            print(f"\n   § {para}:")
            for num, ans in items:
                print(f"      {num}. {ans[:60]}...")
        
        print(f"\n💾 {'Dry run - checking' if args.dry_run else 'Updating'} database...")
        updated, not_found = update_problems(db, args.book_id, answers, args.dry_run)
        
        if not args.dry_run:
            db.commit()
        
        print(f"✅ {'Would update' if args.dry_run else 'Updated'} {updated} problems")
        if not_found > 0:
            print(f"⚠️ {not_found} answers could not be matched")
            
    finally:
        db.close()


if __name__ == "__main__":
    main()
