#!/usr/bin/env python3
"""
Master script to process all data for a book:
1. Classify problems (question vs exercise)
2. Assign sections (§N) to problems
3. Link answers for exercises
4. Link theory for questions

Usage:
    python scripts/process_all.py --book-id 1
    python scripts/process_all.py --book-id 1 --dry-run
    python scripts/process_all.py --book-id 1 --step classify  # Run single step
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "worker"))

from sqlalchemy import text
from database import SessionLocal


def run_step(step_name: str, func, *args, **kwargs):
    """Run a processing step with logging."""
    print(f"\n{'='*60}")
    print(f"📌 Step: {step_name}")
    print(f"{'='*60}")
    
    try:
        result = func(*args, **kwargs)
        print(f"\n✅ {step_name} - DONE")
        return result
    except Exception as e:
        print(f"\n❌ {step_name} - FAILED: {e}")
        raise


def step_classify_problems(db, book_id: int, dry_run: bool = False):
    """Step 1: Classify problems as question/exercise."""
    # Import from scripts folder
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "classify_problems", 
        Path(__file__).parent / "classify_problems.py"
    )
    classify_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(classify_module)
    
    stats, updates = classify_module.classify_all_problems(db, book_id, dry_run=dry_run)
    
    print(f"   📝 Questions: {stats['question']}")
    print(f"   🔢 Exercises: {stats['exercise']}")
    print(f"   ❓ Unknown: {stats['unknown']}")
    
    if not dry_run:
        db.commit()
        print(f"   💾 Committed {len(updates)} updates")
    
    return stats


def step_assign_sections(db, book_id: int, dry_run: bool = False):
    """Step 2: Assign section numbers to problems."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "assign_sections", 
        Path(__file__).parent / "assign_sections.py"
    )
    assign_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assign_module)
    
    page_sections = assign_module.get_page_sections(db, book_id)
    unique_sections = sorted(set(page_sections.values()), key=int) if page_sections else []
    
    print(f"   Found {len(unique_sections)} sections: {', '.join(f'§{s}' for s in unique_sections[:10])}...")
    
    updated = assign_module.update_problem_sections(db, book_id, page_sections, dry_run=dry_run)
    
    if not dry_run:
        db.commit()
    
    print(f"   {'Would update' if dry_run else 'Updated'} {updated} problems")
    return updated


def step_link_answers(db, book_id: int, dry_run: bool = False):
    """Step 3: Link numerical answers to exercises."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "link_answers", 
        Path(__file__).parent / "link_answers.py"
    )
    link_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(link_module)
    
    # Get answer pages
    pages = link_module.get_answer_pages(db, book_id)
    
    if not pages:
        print("   ⚠️ No 'Ответы' section found in book")
        return 0
    
    print(f"   Found {len(pages)} pages with answers")
    
    # Parse answers from OCR text
    answers = link_module.parse_answers_from_ocr(pages)
    
    if not answers:
        print("   ⚠️ No answers parsed from section")
        return 0
    
    total = sum(len(a) for a in answers.values())
    print(f"   Parsed {total} answers from {len(answers)} paragraphs")
    
    # Link to problems
    updated, not_found = link_module.update_problems(db, book_id, answers, dry_run=dry_run)
    
    if not dry_run:
        db.commit()
    
    print(f"   {'Would update' if dry_run else 'Updated'} {updated} problems")
    if not_found > 0:
        print(f"   ⚠️ {not_found} answers could not be matched")
    
    return updated


def step_link_theory(db, book_id: int, dry_run: bool = False):
    """Step 4: Link theoretical content to control questions."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "link_theory", 
        Path(__file__).parent / "link_theory.py"
    )
    theory_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(theory_module)
    
    # Get count of questions without solutions
    result = db.execute(text("""
        SELECT COUNT(*) FROM problems 
        WHERE book_id = :book_id 
          AND (problem_type = 'question' OR problem_type IS NULL)
          AND solution_text IS NULL
    """), {"book_id": book_id})
    
    count = result.scalar()
    print(f"   Questions needing theory: {count}")
    
    if count == 0:
        print("   ✅ All questions already have solutions")
        return 0
    
    theory_module.link_theory_to_questions(db, book_id, dry_run=dry_run)
    
    if not dry_run:
        db.commit()
    
    # Check how many were linked
    result = db.execute(text("""
        SELECT COUNT(*) FROM problems 
        WHERE book_id = :book_id 
          AND problem_type = 'question'
          AND solution_text IS NOT NULL
    """), {"book_id": book_id})
    
    linked = result.scalar()
    print(f"   Total questions with theory: {linked}")
    
    return linked


def get_book_stats(db, book_id: int) -> dict:
    """Get current statistics for a book."""
    stats = {}
    
    # Total problems
    result = db.execute(text("""
        SELECT COUNT(*) FROM problems WHERE book_id = :book_id
    """), {"book_id": book_id})
    stats['total'] = result.scalar()
    
    # By type
    result = db.execute(text("""
        SELECT problem_type, COUNT(*) 
        FROM problems 
        WHERE book_id = :book_id 
        GROUP BY problem_type
    """), {"book_id": book_id})
    stats['by_type'] = {row[0] or 'NULL': row[1] for row in result}
    
    # With answers
    result = db.execute(text("""
        SELECT COUNT(*) FROM problems 
        WHERE book_id = :book_id AND answer_text IS NOT NULL
    """), {"book_id": book_id})
    stats['with_answer'] = result.scalar()
    
    # With solutions
    result = db.execute(text("""
        SELECT COUNT(*) FROM problems 
        WHERE book_id = :book_id AND solution_text IS NOT NULL
    """), {"book_id": book_id})
    stats['with_solution'] = result.scalar()
    
    # With sections
    result = db.execute(text("""
        SELECT COUNT(*) FROM problems 
        WHERE book_id = :book_id AND section IS NOT NULL
    """), {"book_id": book_id})
    stats['with_section'] = result.scalar()
    
    return stats


def print_stats(stats: dict):
    """Print statistics in a formatted way."""
    print(f"\n📊 Current Book Statistics:")
    print(f"   Total problems: {stats['total']}")
    print(f"   By type: {stats['by_type']}")
    print(f"   With answer: {stats['with_answer']}")
    print(f"   With solution: {stats['with_solution']}")
    print(f"   With section: {stats['with_section']}")


def main():
    parser = argparse.ArgumentParser(description="Process all data for a book")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID")
    parser.add_argument("--dry-run", action="store_true", help="Don't update DB")
    parser.add_argument("--step", type=str, choices=['classify', 'sections', 'answers', 'theory', 'stats'],
                        help="Run only specific step")
    args = parser.parse_args()
    
    db = SessionLocal()
    
    try:
        # Get book info
        result = db.execute(text("""
            SELECT title, subject, grade FROM books WHERE id = :book_id
        """), {"book_id": args.book_id})
        book = result.fetchone()
        
        if not book:
            print(f"❌ Book {args.book_id} not found")
            return
        
        print(f"\n📚 Processing: {book.title}")
        print(f"   Subject: {book.subject}, Grade: {book.grade}")
        
        if args.dry_run:
            print("   ⚠️ DRY RUN MODE - no changes will be saved")
        
        # Show initial stats
        initial_stats = get_book_stats(db, args.book_id)
        print_stats(initial_stats)
        
        # Run steps
        if args.step == 'stats':
            # Just show stats
            pass
        elif args.step == 'classify':
            run_step("1. Classify Problems", step_classify_problems, db, args.book_id, args.dry_run)
        elif args.step == 'sections':
            run_step("2. Assign Sections", step_assign_sections, db, args.book_id, args.dry_run)
        elif args.step == 'answers':
            run_step("3. Link Answers", step_link_answers, db, args.book_id, args.dry_run)
        elif args.step == 'theory':
            run_step("4. Link Theory", step_link_theory, db, args.book_id, args.dry_run)
        else:
            # Run all steps
            run_step("1. Classify Problems", step_classify_problems, db, args.book_id, args.dry_run)
            run_step("2. Assign Sections", step_assign_sections, db, args.book_id, args.dry_run)
            run_step("3. Link Answers", step_link_answers, db, args.book_id, args.dry_run)
            run_step("4. Link Theory", step_link_theory, db, args.book_id, args.dry_run)
        
        # Show final stats
        final_stats = get_book_stats(db, args.book_id)
        print_stats(final_stats)
        
        print(f"\n{'🔍 DRY RUN completed' if args.dry_run else '✅ Processing completed!'}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
