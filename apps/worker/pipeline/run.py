"""
PR7 — Canonical ingestion entry point.

run_ingestion(pdf_source_id, mode=...) dispatches to the appropriate pipeline step.
Produces the same artifacts as smoke harness (doc_map, metrics when run via import/reanalyze).
"""
from typing import Any, Optional


def run_ingestion(
    pdf_source_id: int,
    mode: str = "full",
    local_pdf_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Single entry point for ingestion pipeline.

    Modes:
      full             — OCR (or embedded text) → normalize → LLM correct → import (process_pdf_source)
      from_normalized  — Import from existing normalized .md only (no OCR)
      reanalyze        — Re-segment from current pdf_pages.ocr_text (no file read)
      llm_correct_only — Re-run LLM normalization on existing normalized file, then re-import

    Returns the same dict shape as the underlying ingestion function (status, pages_*, problems_*, etc.).
    """
    from ingestion import (
        process_pdf_source,
        import_from_normalized_file,
        import_from_normalized_file_llm,
        reanalyze_pdf_source,
        run_llm_normalize_only,
    )

    mode = (mode or "full").strip().lower()
    if mode == "full":
        return process_pdf_source(pdf_source_id, local_pdf_path=local_pdf_path)
    if mode == "from_normalized":
        return import_from_normalized_file(pdf_source_id)
    if mode == "reanalyze":
        return reanalyze_pdf_source(pdf_source_id)
    if mode == "llm_correct_only":
        return run_llm_normalize_only(pdf_source_id)
    if mode == "from_normalized_llm":
        return import_from_normalized_file_llm(pdf_source_id)
    return {
        "status": "error",
        "message": f"Unknown mode: {mode}. Use full, from_normalized, reanalyze, llm_correct_only, or from_normalized_llm.",
    }
