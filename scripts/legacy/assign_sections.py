#!/usr/bin/env python3
"""
[LEGACY] Assign section (paragraph) numbers to problems based on page content.
Prefer doc_map-driven section assignment from ingestion (PR4). Kept for reference.

Usage:
    python scripts/legacy/assign_sections.py --book-id 1
"""

import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "apps" / "worker"))

from sqlalchemy import text
from database import SessionLocal


def get_page_sections(db, book_id: int) -> dict:
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
        
        section_match = re.search(r'[§$S]\s*(\d{1,2})[.,\s]', text_content[:800])
        if not section_match:
            section_match = re.search(r'[§$]\s*(\d{1,2})\.\s*[А-Яа-я]', text_content[:200])
        
        if section_match:
            new_section = section_match.group(1)
            try:
                if 1 <= int(new_section) <= 25:
                    current_section = new_section
            except ValueError:
                pass
        
        if current_section:
            page_sections[page_id] = current_section
    
    return page_sections


def update_problem_sections(db, book_id: int, page_sections: dict, dry_run: bool = False) -> int:
    """Update problems with their section numbers."""
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
    parser = argparse.ArgumentParser(description="Assign sections to problems (legacy)")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID")
    parser.add_argument("--dry-run", action="store_true", help="Don't update DB")
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        print(f"📚 Analyzing pages for book {args.book_id}...")
        page_sections = get_page_sections(db, args.book_id)
        
        unique_sections = sorted(set(page_sections.values()), key=lambda x: int(x) if str(x).isdigit() else 0)
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
