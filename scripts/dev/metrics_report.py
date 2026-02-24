#!/usr/bin/env python3
"""
Metrics report for a single book/pdf_source (PR0 baseline).
Reads from DB: pdf_pages, problems, problem_parts, section_theory.
Writes artifacts/{book_id}/{pdf_source_id}/metrics.json.
"""
import json
import os
import sys
from pathlib import Path

# Worker imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "apps" / "worker"))
from database import SessionLocal
from models import PdfPage, Problem, ProblemPart, SectionTheory


def compute_metrics(book_id: int, pdf_source_id: int) -> dict:
    """
    Compute metrics from DB for the given book and pdf_source.
    Returns dict suitable for metrics.json.
    """
    db = SessionLocal()
    try:
        # Pages for this source
        pages = (
            db.query(PdfPage)
            .filter(PdfPage.pdf_source_id == pdf_source_id)
            .order_by(PdfPage.page_num)
            .all()
        )
        pages_count = len(pages)
        page_ids = {p.id for p in pages}

        # Problems that belong to this source (via source_page_id in our pages)
        all_problems = (
            db.query(Problem)
            .filter(Problem.book_id == book_id, Problem.source_page_id != None)
            .all()
        )
        problems = [p for p in all_problems if p.source_page_id in page_ids]
        problems_count = len(problems)

        # % problems whose problem_text starts with '§' or 'Параграф'
        starts_with_paragraph = sum(
            1 for p in problems
            if ((p.problem_text or "").strip().startswith("§")
                or (p.problem_text or "").strip().lower().startswith("параграф"))
        )
        pct_starts_with_paragraph = (
            (100.0 * starts_with_paragraph / problems_count) if problems_count else 0.0
        )

        # Answer coverage: % of problems with non-empty answer_text
        with_answer = sum(1 for p in problems if (p.answer_text or "").strip())
        answer_coverage_pct = (
            (100.0 * with_answer / problems_count) if problems_count else 0.0
        )

        # Section coverage: % of problems with non-empty section
        with_section = sum(1 for p in problems if (p.section or "").strip())
        section_coverage_pct = (
            (100.0 * with_section / problems_count) if problems_count else 0.0
        )

        # Section theory count for this book
        theory_count = (
            db.query(SectionTheory).filter(SectionTheory.book_id == book_id).count()
        )

        # Problem parts count (for this book, problems that belong to this source)
        problem_ids = {p.id for p in problems}
        parts_count = (
            db.query(ProblemPart).filter(ProblemPart.problem_id.in_(problem_ids)).count()
            if problem_ids else 0
        )

        return {
            "book_id": book_id,
            "pdf_source_id": pdf_source_id,
            "pages_imported": pages_count,
            "problems_count": problems_count,
            "problem_parts_count": parts_count,
            "section_theory_count": theory_count,
            "pct_problems_start_with_paragraph": round(pct_starts_with_paragraph, 2),
            "problems_start_with_paragraph_count": starts_with_paragraph,
            "answer_coverage_pct": round(answer_coverage_pct, 2),
            "problems_with_answer_count": with_answer,
            "section_coverage_pct": round(section_coverage_pct, 2),
            "problems_with_section_count": with_section,
        }
    finally:
        db.close()


def write_metrics_json(metrics: dict, artifacts_dir: Path) -> Path:
    """Write metrics.json to artifacts_dir. Creates parent dirs. Returns path."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / "metrics.json"
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Compute and optionally write metrics for book/pdf_source")
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--pdf-source-id", type=int, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=None,
                        help="Default: artifacts/{book_id}/{pdf_source_id}")
    args = parser.parse_args()
    artifacts_dir = args.artifacts_dir or (
        Path(os.environ.get("ARTIFACTS_DIR", "artifacts"))
        / str(args.book_id)
        / str(args.pdf_source_id)
    )
    metrics = compute_metrics(args.book_id, args.pdf_source_id)
    out_path = write_metrics_json(metrics, artifacts_dir)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
