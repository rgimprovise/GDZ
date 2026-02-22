#!/usr/bin/env python3
"""
Assign section (paragraph) numbers to problems based on page content.

Usage:
    python scripts/assign_sections.py --book-id 1
"""

import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "worker"))

from sqlalchemy import text
from database import SessionLocal


def get_page_sections(db, book_id: int) -> dict[int, str]:
    """
    Determine which section each page belongs to.
    Returns: {page_id: section_number}
    """
    result = db.execute(text("""
        SELECT pp.id, pp.page_num, pp.ocr_text
        FROM pdf_pages pp
        JOIN pdf_sources ps ON ps.id = pp.pdf_source_id
        WHERE ps.book_id = :book_id
        ORDER BY pp.page_num
    """), {"book_id": book_id})
    
    page_sections = {}
    current_section = None
    
    for row in result:
        page_id = row.id
        text_content = row.ocr_text or ""
        
        # Look for section header - OCR often confuses § with $ or S
        # Patterns: "§ 1." "$ 1." "§1." "$1." "§ 1 " "$ 8," etc.
        section_match = re.search(r'[§$S]\s*(\d{1,2})[.,\s]', text_content[:800])
        
        # Also check for "N класс" pattern which indicates section continuation
        if not section_match:
            # Look for header like "§ 11. Подобие фигур" anywhere in first 200 chars
            section_match = re.search(r'[§$]\s*(\d{1,2})\.\s*[А-Яа-я]', text_content[:200])
        
        if section_match:
            new_section = section_match.group(1)
            # Sanity check - section should be 1-25 for typical textbook
            if 1 <= int(new_section) <= 25:
                current_section = new_section
        
        if current_section:
            page_sections[page_id] = current_section
    
    return page_sections


def update_problem_sections(db, book_id: int, page_sections: dict, dry_run: bool = False) -> int:
    """Update problems with their section numbers."""
    
    # Get problems with their source pages
    result = db.execute(text("""
        SELECT p.id, p.number, p.source_page_id, p.section
        FROM problems p
        WHERE p.book_id = :book_id
          AND p.source_page_id IS NOT NULL
    """), {"book_id": book_id})
    
    updates = []
    for row in result:
        problem_id = row.id
        page_id = row.source_page_id
        current_section = row.section
        
        if page_id in page_sections:
            new_section = f"§{page_sections[page_id]}"
            if current_section != new_section:
                updates.append((problem_id, new_section))
    
    if not dry_run and updates:
        for problem_id, section in updates:
            db.execute(text("""
                UPDATE problems SET section = :section WHERE id = :id
            """), {"section": section, "id": problem_id})
    
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description="Assign sections to problems")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID")
    parser.add_argument("--dry-run", action="store_true", help="Don't update DB")
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        print(f"📚 Analyzing pages for book {args.book_id}...")
        page_sections = get_page_sections(db, args.book_id)
        
        unique_sections = sorted(set(page_sections.values()), key=int)
        print(f"✅ Found {len(unique_sections)} sections: §{', §'.join(unique_sections[:10])}...")
        
        print(f"\n🔍 {'Checking' if args.dry_run else 'Updating'} problems...")
        updated = update_problem_sections(db, args.book_id, page_sections, args.dry_run)
        
        if not args.dry_run:
            db.commit()
        
        print(f"✅ {'Would update' if args.dry_run else 'Updated'} {updated} problems with sections")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
