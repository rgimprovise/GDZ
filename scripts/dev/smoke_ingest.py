#!/usr/bin/env python3
"""
PR0 — Baseline smoke ingest: run pipeline for a single book/pdf_source, then metrics + artifacts.

Usage:
  python scripts/dev/smoke_ingest.py --pdf-source-id 1
  python scripts/dev/smoke_ingest.py --pdf-source-id 1 --mode from_normalized
  python scripts/dev/smoke_ingest.py --pdf-source-id 1 --skip-ingest   # metrics + artifacts only (no ingestion)

Modes:
  from_normalized — import from data/ocr_normalized/{book_id}/{pdf_source_id}.md (default)
  reanalyze       — re-segment from existing pdf_pages.ocr_text (no file needed)

Output:
  artifacts/{book_id}/{pdf_source_id}/metrics.json
  artifacts/{book_id}/{pdf_source_id}/doc_map.json  (empty for PR0)
  artifacts/{book_id}/{pdf_source_id}/samples/
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Worker path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "apps" / "worker"))
# Scripts/dev for metrics_report and artifacts_dump
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import SessionLocal
from models import PdfSource


def get_book_id_for_source(pdf_source_id: int) -> Optional[int]:
    db = SessionLocal()
    try:
        src = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        return src.book_id if src else None
    finally:
        db.close()


def run_smoke_ingest(
    pdf_source_id: int,
    mode: str = "from_normalized",
    skip_ingest: bool = False,
    artifacts_base: Optional[Path] = None,
) -> dict:
    """
    Run ingestion (optional), then metrics report and artifacts dump.
    Returns dict with status, metrics, and paths.
    """
    book_id = get_book_id_for_source(pdf_source_id)
    if book_id is None:
        return {"status": "error", "message": f"PdfSource {pdf_source_id} not found"}

    artifacts_dir = artifacts_base or Path(os.environ.get("ARTIFACTS_DIR", "artifacts"))
    run_dir = artifacts_dir / str(book_id) / str(pdf_source_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    ingest_result = None
    if not skip_ingest:
        from ingestion import import_from_normalized_file, reanalyze_pdf_source
        from ocr_files import get_ocr_normalized_path, read_normalized_pages

        if mode == "from_normalized":
            path = get_ocr_normalized_path(book_id, pdf_source_id)
            if not path.exists():
                return {
                    "status": "error",
                    "message": f"Normalized file not found: {path}. Run full pipeline or use --skip-ingest to report on existing DB state.",
                }
            ingest_result = import_from_normalized_file(pdf_source_id)
        elif mode == "reanalyze":
            ingest_result = reanalyze_pdf_source(pdf_source_id)
        else:
            return {"status": "error", "message": f"Unknown mode: {mode}"}

        if ingest_result.get("status") not in ("success",):
            return {
                "status": "error",
                "message": ingest_result.get("message", str(ingest_result)),
                "ingest_result": ingest_result,
            }

    # Metrics (from DB)
    from metrics_report import compute_metrics, write_metrics_json
    metrics = compute_metrics(book_id, pdf_source_id)
    write_metrics_json(metrics, run_dir)

    # Artifacts (doc_map placeholder + samples)
    from artifacts_dump import dump_artifacts
    dump_artifacts(book_id, pdf_source_id, run_dir, max_pages=3, max_problems=5)

    return {
        "status": "success",
        "book_id": book_id,
        "pdf_source_id": pdf_source_id,
        "metrics": metrics,
        "artifacts_dir": str(run_dir),
        "ingest_result": ingest_result,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PR0 smoke ingest: pipeline + metrics + artifacts")
    parser.add_argument("--pdf-source-id", type=int, required=True)
    parser.add_argument("--mode", choices=("from_normalized", "reanalyze"), default="from_normalized")
    parser.add_argument("--skip-ingest", action="store_true", help="Only compute metrics and dump artifacts from current DB")
    parser.add_argument("--artifacts-dir", type=Path, default=None)
    args = parser.parse_args()

    result = run_smoke_ingest(
        args.pdf_source_id,
        mode=args.mode,
        skip_ingest=args.skip_ingest,
        artifacts_base=args.artifacts_dir,
    )

    if result.get("status") != "success":
        print(result.get("message", result), file=sys.stderr)
        return 1

    metrics = result["metrics"]
    print("\n--- Metrics (before/after baseline) ---")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"\nArtifacts: {result['artifacts_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
