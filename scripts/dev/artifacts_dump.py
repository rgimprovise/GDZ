#!/usr/bin/env python3
"""
Dump artifacts for a single book/pdf_source (PR0 baseline).
- doc_map.json: empty spans for PR0 (filled in PR3).
- samples/: few pages + few problems as JSON.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "apps" / "worker"))
from database import SessionLocal
from models import PdfPage, Problem


def get_doc_map_placeholder(book_id: int, pdf_source_id: int) -> dict:
    """PR0: doc_map with no spans. Schema ready for PR3."""
    return {
        "version": 1,
        "book_id": book_id,
        "pdf_source_id": pdf_source_id,
        "spans": [],
    }


def dump_artifacts(book_id: int, pdf_source_id: int, artifacts_dir: Path, max_pages: int = 3, max_problems: int = 5) -> None:
    """
    Write doc_map.json and samples/ under artifacts_dir.
    """
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # doc_map.json: PR3 ingestion writes real doc_map; only write placeholder if missing or empty spans
    doc_map_path = artifacts_dir / "doc_map.json"
    write_doc_map = True
    if doc_map_path.exists():
        try:
            existing = json.loads(doc_map_path.read_text(encoding="utf-8"))
            if existing.get("spans"):
                write_doc_map = False
        except (json.JSONDecodeError, OSError):
            pass
    if write_doc_map:
        doc_map = get_doc_map_placeholder(book_id, pdf_source_id)
        doc_map_path.write_text(
            json.dumps(doc_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    samples_dir = artifacts_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        all_pages = (
            db.query(PdfPage)
            .filter(PdfPage.pdf_source_id == pdf_source_id)
            .order_by(PdfPage.page_num)
            .all()
        )
        page_ids = {p.id for p in all_pages}
        pages_sample = all_pages[:max_pages]
        for p in pages_sample:
            sample = {
                "id": p.id,
                "page_num": p.page_num,
                "ocr_text_preview": (p.ocr_text or "")[:500] + ("..." if len(p.ocr_text or "") > 500 else ""),
            }
            (samples_dir / f"page_{p.page_num + 1}.json").write_text(
                json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        problems = (
            db.query(Problem)
            .filter(Problem.book_id == book_id, Problem.source_page_id != None)
            .all()
        )
        problems = [p for p in problems if p.source_page_id in page_ids][:max_problems]
        for i, p in enumerate(problems):
            sample = {
                "id": p.id,
                "number": p.number,
                "section": p.section,
                "page_ref": p.page_ref,
                "problem_text_preview": (p.problem_text or "")[:300] + ("..." if len(p.problem_text or "") > 300 else ""),
                "has_answer": bool((p.answer_text or "").strip()),
            }
            (samples_dir / f"problem_{i + 1}.json").write_text(
                json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dump artifacts (doc_map + samples) for book/pdf_source")
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--pdf-source-id", type=int, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=None)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-problems", type=int, default=5)
    args = parser.parse_args()
    artifacts_dir = args.artifacts_dir or (
        Path(os.environ.get("ARTIFACTS_DIR", "artifacts"))
        / str(args.book_id)
        / str(args.pdf_source_id)
    )
    dump_artifacts(args.book_id, args.pdf_source_id, artifacts_dir, args.max_pages, args.max_problems)
    print(f"Artifacts written to {artifacts_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
