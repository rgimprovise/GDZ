# Legacy scripts (PR7+)

Scripts moved here for reference. Prefer the canonical pipeline:

- **Canonical entry point:** `pipeline.run.run_ingestion(pdf_source_id, mode=...)` or `scripts/dev/smoke_ingest.py`.

Moved scripts:

- **link_answers.py** — Replaced by `apps/worker/segmentation/answers.py` (PR5, doc_map-driven).
- **assign_sections.py** — Section assignment now from doc_map/ingestion (PR4).
- **link_theory.py** — Prefer runtime retrieval from `section_theory`; do not bake solutions offline.
- **process_all.py** — Runs classify (from scripts/) + assign_sections + link_answers + link_theory; use `run_ingestion` + smoke for canonical flow.
