#!/usr/bin/env python3
"""
Parse answers section from textbook PDF and link to problems.

Usage:
    python scripts/parse_answers.py /path/to/textbook.pdf --book-id 1
    
The script:
1. Finds "Ответы и указания к задачам" section
2. Extracts answers with problem numbers
3. Updates problems in database with answer_text
"""

import re
import sys
import argparse
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "worker"))

import fitz  # PyMuPDF
from sqlalchemy import text

from database import SessionLocal


def find_answers_section(doc: fitz.Document) -> tuple[int, int]:
    """
    Find start and end page of "Ответы и указания" section.
    Returns (start_page, end_page) - 0-indexed.
    """
    start_page = None
    end_page = len(doc) - 1
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        
        # Look for answers section header
        if re.search(r'ответы\s+(и\s+)?указания\s+к\s+задачам', text, re.IGNORECASE):
            if start_page is None:
                start_page = page_num
                print(f"📖 Found answers section at page {page_num + 1}")
        
        # Look for end markers (index, bibliography, etc.)
        if start_page is not None:
            if re.search(r'предметный\s+указатель|оглавление|содержание', text, re.IGNORECASE):
                end_page = page_num - 1
                print(f"📖 Answers section ends at page {end_page + 1}")
                break
    
    if start_page is None:
        # Try alternative patterns
        for page_num in range(len(doc) - 50, len(doc)):  # Last 50 pages
            if page_num < 0:
                continue
            page = doc[page_num]
            text = page.get_text()
            if re.search(r'§\s*1[.\s]', text) and '1)' in text and 'см' in text.lower():
                start_page = page_num
                print(f"📖 Found answers section (heuristic) at page {page_num + 1}")
                break
    
    return start_page, end_page


def parse_paragraph_answers(text: str) -> dict[str, list[tuple[str, str]]]:
    """
    Parse answers organized by paragraph (§).
    
    Returns: {paragraph_num: [(problem_num, answer_text), ...]}
    """
    answers = {}
    current_paragraph = None
    
    # Split by paragraphs: § 1., § 2., etc.
    para_pattern = r'§\s*(\d+)[.\s]'
    
    parts = re.split(para_pattern, text)
    
    # parts = ['...before §1...', '1', '...§1 content...', '2', '...§2 content...', ...]
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            para_num = parts[i]
            para_content = parts[i + 1]
            
            # Parse individual answers within paragraph
            # Format: "1. answer" or "1) answer" or "1. 1) sub-answer; 2) sub-answer"
            problem_answers = parse_problem_answers(para_content)
            if problem_answers:
                answers[para_num] = problem_answers
    
    return answers


def parse_problem_answers(content: str) -> list[tuple[str, str]]:
    """
    Parse problem answers from content.
    
    Format examples:
    - "4. Через две точки можно провести только одну прямую. 7.1) 6 см; 2) 7,7 дм"
    - "1. 150°, 135°, 120°, 90°. 2. 1), 2). Не могут"
    """
    results = []
    
    # Pattern: number followed by "." or ")" then answer text
    # Match: "4." or "4)" at start or after space/newline
    pattern = r'(?:^|\s)(\d+)[.)]?\s*([^§]+?)(?=(?:\s+\d+[.)]\s)|$)'
    
    # Simpler approach: split by problem numbers
    # "4. answer 7. answer 10. answer" -> ["4. answer", "7. answer", "10. answer"]
    
    # Find all problem number positions
    positions = []
    for m in re.finditer(r'(?:^|\s)(\d+)\.\s', content):
        positions.append((m.start(), m.group(1)))
    
    for i, (pos, num) in enumerate(positions):
        # Get text until next problem number or end
        end_pos = positions[i + 1][0] if i + 1 < len(positions) else len(content)
        answer_text = content[pos:end_pos].strip()
        
        # Clean up: remove leading number
        answer_text = re.sub(r'^\d+\.\s*', '', answer_text)
        answer_text = answer_text.strip()
        
        if answer_text:
            results.append((num, answer_text))
    
    return results


def update_problems_with_answers(db, book_id: int, paragraph_answers: dict):
    """
    Update problems in database with parsed answers.
    """
    updated = 0
    not_found = 0
    
    for para_num, answers in paragraph_answers.items():
        for problem_num, answer_text in answers:
            # Find matching problem
            # Problem number might be "1" or match with section
            result = db.execute(text("""
                UPDATE problems 
                SET answer_text = :answer
                WHERE book_id = :book_id 
                  AND number = :number
                  AND (section IS NULL OR section = :section OR section = '')
                RETURNING id
            """), {
                "answer": answer_text[:2000],  # Limit length
                "book_id": book_id,
                "number": problem_num,
                "section": f"§{para_num}"
            })
            
            rows = result.fetchall()
            if rows:
                updated += len(rows)
            else:
                not_found += 1
    
    return updated, not_found


def main():
    parser = argparse.ArgumentParser(description="Parse answers from textbook PDF")
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID in database")
    parser.add_argument("--dry-run", action="store_true", help="Don't update database")
    args = parser.parse_args()
    
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"❌ PDF not found: {pdf_path}")
        sys.exit(1)
    
    print(f"📚 Opening: {pdf_path.name}")
    doc = fitz.open(pdf_path)
    print(f"   Total pages: {len(doc)}")
    
    # Find answers section
    start_page, end_page = find_answers_section(doc)
    
    if start_page is None:
        print("❌ Could not find 'Ответы и указания к задачам' section")
        print("   Trying to parse last 30 pages...")
        start_page = max(0, len(doc) - 30)
        end_page = len(doc) - 1
    
    print(f"📖 Parsing pages {start_page + 1} to {end_page + 1}")
    
    # Extract text from answers section
    answers_text = ""
    for page_num in range(start_page, end_page + 1):
        page = doc[page_num]
        answers_text += page.get_text() + "\n"
    
    # Parse answers
    paragraph_answers = parse_paragraph_answers(answers_text)
    
    total_answers = sum(len(a) for a in paragraph_answers.values())
    print(f"✅ Parsed {total_answers} answers from {len(paragraph_answers)} paragraphs")
    
    # Show sample
    for para, answers in list(paragraph_answers.items())[:3]:
        print(f"\n   §{para}:")
        for num, ans in answers[:3]:
            print(f"      {num}. {ans[:60]}...")
    
    if args.dry_run:
        print("\n🔍 Dry run - not updating database")
        return
    
    # Update database
    print(f"\n💾 Updating database (book_id={args.book_id})...")
    db = SessionLocal()
    try:
        updated, not_found = update_problems_with_answers(db, args.book_id, paragraph_answers)
        db.commit()
        print(f"✅ Updated {updated} problems")
        if not_found > 0:
            print(f"⚠️ {not_found} answers could not be matched to problems")
    finally:
        db.close()


if __name__ == "__main__":
    main()
