#!/usr/bin/env python3
"""
[LEGACY] Master script: classify → assign sections → link answers → link theory.
Canonical pipeline: use pipeline.run.run_ingestion() and scripts/dev/smoke_ingest.py.
Kept for reference. Classify still lives in scripts/; assign/answers/theory in legacy/.

Usage:
    python scripts/legacy/process_all.py --book-id 1
    python scripts/legacy/process_all.py --book-id 1 --dry-run
    python scripts/legacy/process_all.py --book-id 1 --step classify
"""

import sys
import argparse
from pathlib import Path

_here = Path(__file__).resolve().parent
_root = _here.parent.parent
sys.path.insert(0, str(_root / "apps" / "worker"))

from sqlalchemy import text
from database import SessionLocal


def run_step(step_name: str, func, *args, **kwargs):
    print(f"\n{'='*60}\n📌 Step: {step_name}\n{'='*60}")
    try:
        result = func(*args, **kwargs)
        print(f"\n✅ {step_name} - DONE")
        return result
    except Exception as e:
        print(f"\n❌ {step_name} - FAILED: {e}")
        raise


def step_classify_problems(db, book_id: int, dry_run: bool = False):
    """Step 1: Classify problems (loads from scripts/, not legacy)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "classify_problems",
        _here.parent / "classify_problems.py",
    )
    classify_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(classify_module)
    stats, updates = classify_module.classify_all_problems(db, book_id, dry_run=dry_run)
    print(f"   📝 Questions: {stats['question']}, Exercises: {stats['exercise']}, Unknown: {stats['unknown']}")
    if not dry_run:
        db.commit()
    return stats


def step_assign_sections(db, book_id: int, dry_run: bool = False):
    import importlib.util
    spec = importlib.util.spec_from_file_location("assign_sections", _here / "assign_sections.py")
    assign_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assign_module)
    page_sections = assign_module.get_page_sections(db, book_id)
    unique_sections = sorted(set(page_sections.values()), key=lambda x: int(x) if str(x).isdigit() else 0) if page_sections else []
    print(f"   Found {len(unique_sections)} sections: {', '.join(f'§{s}' for s in unique_sections[:10])}...")
    updated = assign_module.update_problem_sections(db, book_id, page_sections, dry_run=dry_run)
    if not dry_run:
        db.commit()
    print(f"   {'Would update' if dry_run else 'Updated'} {updated} problems")
    return updated


def step_link_answers(db, book_id: int, dry_run: bool = False):
    import importlib.util
    spec = importlib.util.spec_from_file_location("link_answers", _here / "link_answers.py")
    link_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(link_module)
    pages = link_module.get_answer_pages(db, book_id)
    if not pages:
        print("   ⚠️ No 'Ответы' section found")
        return 0
    answers = link_module.parse_answers_from_ocr(pages)
    total = sum(len(a) for a in answers.values())
    print(f"   Parsed {total} answers from {len(answers)} paragraphs")
    updated, not_found = link_module.update_problems(db, book_id, answers, dry_run=dry_run)
    if not dry_run:
        db.commit()
    print(f"   {'Would update' if dry_run else 'Updated'} {updated} problems")
    if not_found > 0:
        print(f"   ⚠️ {not_found} answers could not be matched")
    return updated


def step_link_theory(db, book_id: int, dry_run: bool = False):
    import importlib.util
    spec = importlib.util.spec_from_file_location("link_theory", _here / "link_theory.py")
    theory_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(theory_module)
    result = db.execute(text("""
        SELECT COUNT(*) FROM problems
        WHERE book_id = :book_id AND (problem_type = 'question' OR problem_type IS NULL) AND solution_text IS NULL
    """), {"book_id": book_id})
    count = result.scalar()
    print(f"   Questions needing theory: {count}")
    if count == 0:
        print("   ✅ All questions already have solutions")
        return 0
    theory_module.link_theory_to_questions(db, book_id, dry_run=dry_run)
    if not dry_run:
        db.commit()
    return count


def get_book_stats(db, book_id: int) -> dict:
    stats = {}
    for name, q in [
        ("total", "SELECT COUNT(*) FROM problems WHERE book_id = :book_id"),
        ("with_answer", "SELECT COUNT(*) FROM problems WHERE book_id = :book_id AND answer_text IS NOT NULL"),
        ("with_solution", "SELECT COUNT(*) FROM problems WHERE book_id = :book_id AND solution_text IS NOT NULL"),
        ("with_section", "SELECT COUNT(*) FROM problems WHERE book_id = :book_id AND section IS NOT NULL"),
    ]:
        stats[name] = db.execute(text(q), {"book_id": book_id}).scalar()
    result = db.execute(text("SELECT problem_type, COUNT(*) FROM problems WHERE book_id = :book_id GROUP BY problem_type"), {"book_id": book_id})
    stats["by_type"] = {row[0] or "NULL": row[1] for row in result}
    return stats


def main():
    parser = argparse.ArgumentParser(description="Process all data for a book (legacy)")
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--step", type=str, choices=["classify", "sections", "answers", "theory", "stats"])
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT title, subject, grade FROM books WHERE id = :book_id"), {"book_id": args.book_id})
        book = result.fetchone()
        if not book:
            print(f"❌ Book {args.book_id} not found")
            return
        print(f"\n📚 Processing: {book.title}")
        initial_stats = get_book_stats(db, args.book_id)
        print(f"   Total problems: {initial_stats['total']}, with answer: {initial_stats['with_answer']}, with section: {initial_stats['with_section']}")
        if args.step == "stats":
            pass
        elif args.step == "classify":
            run_step("1. Classify Problems", step_classify_problems, db, args.book_id, args.dry_run)
        elif args.step == "sections":
            run_step("2. Assign Sections", step_assign_sections, db, args.book_id, args.dry_run)
        elif args.step == "answers":
            run_step("3. Link Answers", step_link_answers, db, args.book_id, args.dry_run)
        elif args.step == "theory":
            run_step("4. Link Theory", step_link_theory, db, args.book_id, args.dry_run)
        else:
            run_step("1. Classify Problems", step_classify_problems, db, args.book_id, args.dry_run)
            run_step("2. Assign Sections", step_assign_sections, db, args.book_id, args.dry_run)
            run_step("3. Link Answers", step_link_answers, db, args.book_id, args.dry_run)
            run_step("4. Link Theory", step_link_theory, db, args.book_id, args.dry_run)
        final_stats = get_book_stats(db, args.book_id)
        print(f"\n   Final: total={final_stats['total']}, with_answer={final_stats['with_answer']}, with_section={final_stats['with_section']}")
        print(f"\n{'🔍 DRY RUN completed' if args.dry_run else '✅ Processing completed!'}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
