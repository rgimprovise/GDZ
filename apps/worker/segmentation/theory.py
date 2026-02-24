"""
PR4 — Theory extraction from paragraph spans only (doc_map-driven).
Read only paragraph-span pages; stop at tasks block in content.
"""
from typing import Any, Optional

from document_map import get_paragraph_spans


def extract_and_save_section_theory_from_doc_map(
    db,
    book_id: int,
    pdf_source_id: int,
    pages_data: list[tuple[int, str]],
    doc_map: Optional[dict[str, Any]],
) -> Optional[int]:
    """
    Extract section theory from paragraph-span pages only. Saves to section_theory.
    Returns count of sections saved, or None if doc_map has no paragraph spans (caller may fall back to legacy).
    """
    from models import SectionTheory
    from datetime import datetime

    para_spans = get_paragraph_spans(doc_map) if doc_map else []
    if not para_spans:
        return None

    # pages by page_num_1based
    pages_by_num = {p[0]: p[1] for p in pages_data}

    # section -> list of text chunks (one per span occurrence; merge same section)
    section_texts: dict[str, list[str]] = {}
    for s in para_spans:
        section = s.get("section") or "§?"
        start_p = s.get("start_page")
        end_p = s.get("end_page")
        if start_p is None:
            continue
        if end_p is None:
            end_p = start_p
        chunks = []
        for page_num in range(start_p, end_p + 1):
            text = pages_by_num.get(page_num)
            if text and (text or "").strip():
                chunks.append((text or "").strip())
        if chunks:
            if section not in section_texts:
                section_texts[section] = []
            section_texts[section].append("\n\n".join(chunks))

    if not section_texts:
        return None

    saved = 0
    for section_label, chunks in section_texts.items():
        theory_text = "\n\n".join(chunks).strip()
        if len(theory_text) < 50:
            continue
        # page_ref from first/last page in first chunk span (we don't have per-section page range here; use first span)
        para = next((s for s in para_spans if (s.get("section") or "§?") == section_label), None)
        if para and para.get("start_page") is not None:
            start_page = para["start_page"]
            end_page = para.get("end_page") or start_page
            page_ref = f"стр. {start_page}" if start_page == end_page else f"стр. {start_page}–{end_page}"
        else:
            page_ref = None

        existing = db.query(SectionTheory).filter(
            SectionTheory.book_id == book_id,
            SectionTheory.section == section_label,
        ).first()
        if existing:
            existing.theory_text = theory_text
            existing.page_ref = page_ref
            existing.updated_at = datetime.utcnow()
        else:
            db.add(SectionTheory(
                book_id=book_id,
                section=section_label,
                theory_text=theory_text,
                page_ref=page_ref,
            ))
        saved += 1

    if saved:
        db.commit()
    return saved
