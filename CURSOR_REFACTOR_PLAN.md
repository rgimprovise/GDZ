# TutorBook Pipeline Refactor Plan (Cursor Execution Guide)

**Goal:** turn the current “OCR → normalize → LLM → DB” pipeline into a **deterministic, debuggable, universal** ingestion system for *any* textbook layout, while reducing LLM cost and preventing mixed entities (theory vs tasks vs answers).

This document is written as a **step-by-step implementation plan** for Cursor. Treat each milestone as a small PR. Do not attempt a “big bang” rewrite.

---

## 0) Guiding principles (hard rules)

### 0.1 Determinism first, LLM second
LLM must **not** be responsible for finding document structure boundaries. LLM is only allowed to:
- (a) correct OCR/formulas where heuristics are insufficient,
- (b) classify already well-formed blocks and extract fields.

### 0.2 Universal, layout-agnostic heuristics
No subject-specific or book-specific hardcoding (e.g., fixed section ranges like 1..25, max problem number 200). Use **document-derived constraints**.

### 0.3 Reproducibility and auditability
For any DB write, you must be able to reproduce:
- the exact input page text,
- the exact derived blocks,
- the exact LLM request/response (or a hash + stored raw response),
- the exact parser/validator version.

### 0.4 One entity per DB row
**One row in `problems` must represent one problem/question/exercise**, never “a page of problems”.

---

## 1) Current known failure points (fix targets)

1) **Problems segmentation treats paragraph headers as problems.**
2) **LLM distribution silently drops batches on JSON parse errors.**
3) **Answer linking selects only pages that contain the “Ответы и указания…” header.**
4) **Hard-coded limits break universality.**
5) **Header/footer stripping is risky.**
6) **Images are ignored.**
7) **The project has “script sprawl”.**

---

## 2) Target architecture (end state)

### 2.1 Canonical ingestion pipeline (single source of truth)
**Stage A — Extract pages**
- Prefer **embedded OCR PDF** when available (pdf with selectable text).
- Otherwise fallback to Tesseract.

**Stage B — Clean pages (deterministic)**
- Normalize OCR artifacts and symbols.
- Remove headers/footers safely (top/bottom-only strategy).

**Stage C — Build Document Map (deterministic)**
Create a `doc_map.json` describing spans:
- front_matter, toc, sections (paragraphs), tasks blocks, answers section, index.
- Each span: start_page, end_page, type, confidence, and optional anchors (matched headings).

**Stage D — Extract entities (deterministic-first, LLM as fallback)**
- Extract section theory using doc-map.
- Extract problems strictly from tasks spans.
- Parse “solution/answer” blocks when explicitly marked.

**Stage E — Link answers (doc-map-driven)**
- Parse the full answers span.
- Link by (book_id, section, number, type) using robust parsing.

**Stage F — Retrieval & serving**
- Retrieval stays mostly as-is (FTS + optional vector), but depends on ingestion correctness.

### 2.2 Suggested module layout
Introduce:
- `apps/worker/document_map.py`
- `apps/worker/segmentation/problems.py`
- `apps/worker/segmentation/answers.py`
- `apps/worker/segmentation/headers_footers.py`
- `apps/worker/llm/structured.py` (schema, validation, retries)
- `apps/worker/pipeline/run.py` (orchestrator)

Deprecate / move to `scripts/legacy/`:
- `process_all.py`, old `assign_sections.py`, old `link_theory.py`, old `link_answers.py`

---

## 3) Milestone plan (PR-by-PR)

### PR0 — Baseline tests + “golden” book harness
**Tasks**
- Add `scripts/dev/smoke_ingest.py` that runs the pipeline against a single `book_id` / `pdf_source_id`.
- Add metrics report:
  - pages imported
  - problems count
  - % problems whose text starts with '§' or 'Параграф'
  - answer coverage
  - section coverage
- Add artifact dump (doc_map + samples + LLM raw responses if used).

**Acceptance**
- Running smoke script produces a stable JSON report and artifacts folder.

---

### PR1 — Make LLM I/O non-breakable (structured outputs + retries)
**Tasks**
- Wrap LLM calls behind one interface: `llm_call(schema, messages) -> parsed_object`.
- Use strict JSON schema / structured output.
- Add retry:
  1) initial call
  2) “repair JSON only”
  3) fail with persisted raw response (no silent drops)

**Acceptance**
- No more `return []` on JSON parse errors.

---

### PR2 — Stop treating paragraph headers as problem starts (critical)
**Tasks**
- Remove `§...` and `Параграф...` from problem-start patterns in:
  - `ingestion.segment_problems`
  - `llm_distribute.RE_PROBLEM_START`
- Keep section detection separate from problem detection.
- Add regression test.

**Acceptance**
- “% problems starting with '§'” ≈ 0 on golden book.

---

### PR3 — Document Map (the heart of universality)
**Tasks**
- Implement `document_map.build(pages) -> doc_map`.
- Detect:
  - paragraph start (`§`, `Параграф`, `$` OCR-confusion, fallback numeric heading)
  - tasks block start (“Задачи/Упражнения/…/Контрольные/Практические”)
  - answers start (“Ответы”, fuzzy/robust)
  - toc/index (“Содержание/Оглавление/Предметный указатель”)
- Persist `doc_map.json`.

**Acceptance**
- doc_map marks answers span near end and many paragraph spans.

---

### PR4 — Rebuild problems extraction using doc_map spans
**Tasks**
- Move logic to `segmentation/problems.py`.
- Input: only tasks-span text.
- Ensure 1 DB problem row = 1 problem.
- Add splitter for multi-problem lines: `206. ... 207. ...`.

**Acceptance**
- No problems created from theory spans.
- Under-segmentation decreases.

---

### PR5 — Answers: replace `link_answers.py` with doc_map-driven linker
**Tasks**
- Parse answers using doc_map answers span.
- Remove hard limits (section 1..25, problem <=200).
- Handle multi-line continuations and multiple answers per line.
- Prefer PDF-based parsing when embedded text exists (optional, recommended).

**Acceptance**
- Answer coverage materially improves.

---

### PR6 — Safer header/footer stripping
**Tasks**
- Only strip candidates in top/bottom N lines of the page.
- (Optional) coordinate-based stripping in embedded PDF mode.

**Acceptance**
- No loss of meaningful enumerations and improved noise removal.

---

### PR7 — Unify ingestion entrypoints (reduce script sprawl)
**Tasks**
- Create orchestrator `run_ingestion(pdf_source_id, mode=...)`:
  - full / from_normalized / reanalyze / llm_correct_only
- Make `process_pdf_source` call orchestrator.
- Move legacy scripts to `scripts/legacy/`.

**Acceptance**
- One canonical pipeline path.

---

### PR8 — Cost controls (LLM gating) + formula pipeline
**Tasks**
- Quality scoring per page; only send flagged pages to LLM OCR-correction.
- Run deterministic formula fixes first; LLM only on low-confidence.

**Acceptance**
- Tokens/book decrease with stable quality.

---

### PR9 — Image capture (minimum viable)
**Tasks**
- Save page images and fill `PdfPage.image_minio_key` (or local path initially).
- Expose in debug tools.

**Acceptance**
- You can retrieve the page image for a problem.

---

## 4) Project-wide success metrics
- Pages imported == PDF pages.
- Garbage problems (header-like) near zero.
- Answer coverage high for books with answers section.
- Section coverage near 100% for tasks.
- Manual retrieval hit-rate improves.

---

## 5) Cursor workflow
- Branch per PR.
- Each PR: run smoke ingest, compare metrics JSON.
- Merge only if metrics stable/improving.

---


## Appendix A — File-level refactor checklist

### A1. “Must touch” files (current)
- `apps/worker/ingestion.py`
  - `process_pdf_source()`, `import_from_normalized_file()`, `import_from_normalized_file_llm()`, `reanalyze_pdf_source()`
  - `segment_problems()` (remove §/Параграф from problem-start)
  - `extract_and_save_section_theory()` (later: make it doc_map-driven, not global scan)
- `apps/worker/llm_distribute.py`
  - `call_llm_batch()` / `call_llm_paragraph()` (structured output, retries, audit)
  - `RE_PROBLEM_START` (remove §/Параграф)
  - `split_by_paragraphs()` (reuse for doc_map paragraph detection)
- `apps/worker/ocr_files.py`
  - `strip_page_headers_footers()` (rewrite to safer top/bottom-only strategy)
  - `parse_md_by_pages()` / `read_normalized_pages()` (used by pipeline)
- `scripts/link_answers.py`
  - Mark as legacy; replace with `apps/worker/segmentation/answers.py` driven by doc_map
- `scripts/link_theory.py`
  - Mark as legacy; do not bake “solutions” from theory offline. Prefer runtime retrieval.

### A2. “Nice to have” (after core)
- `apps/worker/formula_processor.py` (use as deterministic pass before LLM formula correction)
- `apps/worker/llm_ocr_correct.py` (add gating by quality score; keep checkpoint)
- `apps/worker/retrieval.py` (only minor tuning after ingestion improves)

---

## Appendix B — PR details (copy/paste into Cursor task list)

### PR0 — Baseline harness
**Files**
- `scripts/dev/smoke_ingest.py` (new)
- `scripts/dev/metrics_report.py` (new)
- `scripts/dev/artifacts_dump.py` (new)

**Implementation notes**
- Do not require external services except DB/Redis already used.
- Metrics report should read from DB tables (`pdf_pages`, `problems`, `problem_parts`, `section_theory`).

**Output artifacts**
- `artifacts/{book_id}/{pdf_source_id}/metrics.json`
- `artifacts/.../doc_map.json` (empty for PR0, filled later)
- `artifacts/.../samples/` (few pages + few problems as JSON)

---

### PR1 — Structured LLM output + audit
**Files**
- `apps/worker/llm_distribute.py` (refactor)
- `apps/worker/llm/structured.py` (new)
- `apps/worker/llm/prompts.py` (optional new, to isolate prompt text)

**Implementation notes**
- Centralize: model name, temperature, max tokens, response format.
- Store raw responses:
  - `data/llm_audit/{book_id}/{pdf_source_id}/{timestamp}_{mode}.json`
- Never silently swallow JSON errors. Raise with context, but keep a “non-destructive” dry-run mode.

---

### PR2 — Fix “§ becomes a problem” bug
**Files**
- `apps/worker/ingestion.py` (`segment_problems.patterns`)
- `apps/worker/llm_distribute.py` (`RE_PROBLEM_START`)
- `scripts/dev/test_segment_problems.py` (new minimal test)

**Implementation notes**
- “§ N” and “Параграф N” must only influence:
  - section labeling (doc_map / section detection),
  - theory extraction boundaries,
  - never creation of `problems` rows.

---

### PR3 — Document Map
**Files**
- `apps/worker/document_map.py` (new)
- `apps/worker/pipeline/artifacts.py` (optional new helper to save/load doc_map)
- `apps/worker/ingestion.py` (call doc_map builder in import modes)

**Doc map schema (suggested)**
```json
{
  "version": 1,
  "book_id": 1,
  "pdf_source_id": 1,
  "spans": [
    {"type":"front_matter","start_page":1,"end_page":4,"confidence":0.8},
    {"type":"paragraph","section":"§6","start_page":30,"end_page":36,"confidence":0.9},
    {"type":"answers","start_page":360,"end_page":385,"confidence":0.95},
    {"type":"toc","start_page":386,"end_page":387,"confidence":0.8},
    {"type":"index","start_page":388,"end_page":392,"confidence":0.8}
  ]
}
```

**Implementation notes**
- Prefer simple scoring over brittle exact matches:
  - if “Ответы” appears near top and page is near end => high confidence answers start
  - if many short “§ N. ...” lines => toc
  - if “Предметный указатель” => index
- Keep it language-agnostic where possible, but allow a small RU/EN phrase set.

---

### PR4 — Entity extraction uses doc_map spans
**Files**
- `apps/worker/segmentation/problems.py` (new)
- `apps/worker/segmentation/theory.py` (new)
- `apps/worker/ingestion.py` (replace direct calls with these modules)

**Implementation notes**
- Theory extraction should read only paragraph spans and stop at tasks block start marker.
- Problems extraction reads only tasks spans, and writes page_ref based on first page where the problem starts.

---

### PR5 — Answers parser/linker uses doc_map spans
**Files**
- `apps/worker/segmentation/answers.py` (new)
- `apps/worker/ingestion.py` (call after problems exist)
- `scripts/link_answers.py` → move to `scripts/legacy/link_answers.py` (keep for reference)

**Implementation notes**
- Remove any assumptions like section range 1..25 or problem <=200.
- Support continuation lines: if a line doesn’t start with a number but you are “inside” an answer, append.
- Prefer linking by (book_id, section, number, problem_type) when possible; fallback to (book_id, number) only if section missing and confidence low.

---

### PR6 — Header/footer stripping rewrite
**Files**
- `apps/worker/ocr_files.py` (rewrite strip function)
- `scripts/dev/test_strip_headers.py` (new)

**Implementation notes**
- Only consider first/last N lines (e.g., 4) for stripping candidates.
- Never remove inside-page enumerations like “1) … 2) …”.
- Add a “stats mode” that reports what got stripped and how often.

---

### PR7 — Orchestrator + legacy quarantine
**Files**
- `apps/worker/pipeline/run.py` (new)
- `apps/worker/ingestion.py` (thin wrappers call orchestrator)
- `scripts/legacy/*` (moved)

**Implementation notes**
- The orchestrator should produce the same artifacts and metrics as smoke harness.

---

### PR8 — LLM cost gating
**Files**
- `apps/worker/llm_ocr_correct.py` (gate pages)
- `apps/worker/ocr_cleaner.py` (expose quality scoring)
- `apps/worker/formula_processor.py` (run before LLM)

---

### PR9 — Page images
**Files**
- `apps/worker/ingestion.py` (capture pixmap bytes)
- `apps/worker/storage.py` (optional abstraction: minio/local)
- `apps/worker/models.py` (no schema change; just populate existing field)

---

## Appendix C — “Do not do” list (common traps)
- Don’t chunk text by fixed page counts for LLM.
- Don’t add new hard-coded ranges like “sections 1..25” or “problems <=200”.
- Don’t silently catch-and-drop LLM failures; always persist raw output.
- Don’t run `process_all.py` as part of the canonical pipeline after PR7.

