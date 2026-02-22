"""
PDF Ingestion Pipeline

Пайплайн: OCR → сырой текст в файлы → нормализация → LLM-коррекция формул/OCR → нормализованный файл → импорт в БД.
1. OCR (Tesseract) по всем страницам → запись в data/ocr_raw/{book_id}/{source_id}_{model}.md
2. Нормализация (ocr_cleaner) по страницам.
3. LLM-коррекция (OpenAI): исправление ошибок OCR и приведение формул к формату для БД/чата (без шаблонных замен).
4. Запись в data/ocr_normalized/{book_id}/{source_id}.md и импорт в БД (pdf_pages, сегментация задач и теории).

Usage:
    process_pdf_source(pdf_source_id=1)   # полный цикл OCR → файлы → БД
    import_from_normalized_file(pdf_source_id=1)  # переимпорт из нормализованного файла без OCR
"""

import io
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# PDF processing
try:
    import fitz  # pymupdf
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    print("⚠️  pymupdf not installed")

# OCR: Tesseract only
try:
    import pytesseract
    from PIL import Image
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    print("⚠️  pytesseract/Pillow not installed")

from config import get_settings
from database import SessionLocal

settings = get_settings()

# Нормализация текста (опционально: если модуль недоступен, работаем с сырым текстом)
try:
    from ocr_cleaner import clean_ocr_text
    HAS_OCR_CLEANER = True
except ImportError:
    HAS_OCR_CLEANER = False

    def clean_ocr_text(text: str, **kwargs) -> str:
        return text

# Файлы OCR: сырой и нормализованный .md по страницам
try:
    from ocr_files import write_raw_md, write_normalized_md, read_normalized_pages, get_ocr_normalized_path, get_llm_checkpoint_path
    HAS_OCR_FILES = True
except ImportError:
    HAS_OCR_FILES = False


# ===========================================
# Ingestion Job
# ===========================================

def process_pdf_source(pdf_source_id: int, local_pdf_path: Optional[str] = None) -> dict:
    """
    Process a PDF source: render pages, OCR, segment problems.
    
    Args:
        pdf_source_id: ID of PdfSource in database
        local_pdf_path: Optional path to local PDF file (if not using MinIO)
        
    Returns:
        dict with processing results
    """
    # Import models here to avoid circular imports
    from models import PdfSource, PdfPage, Problem, Book
    
    start_time = time.time()
    db = SessionLocal()
    
    try:
        # Get PDF source
        pdf_source = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        if not pdf_source:
            return {"status": "error", "message": f"PdfSource {pdf_source_id} not found"}
        
        print(f"📄 Processing PDF source {pdf_source_id}: {pdf_source.original_filename}")
        
        # Update status
        pdf_source.status = "rendering"
        db.commit()
        
        # Get PDF data
        if local_pdf_path:
            pdf_path = local_pdf_path
        else:
            # TODO: Download from MinIO
            # For now, try to find locally based on minio_key
            base_path = Path(os.environ.get("DATA_DIR", "data"))
            pdf_path = base_path / pdf_source.minio_key
            
            if not pdf_path.exists():
                # Try alternate paths
                alt_paths = [
                    Path("data") / pdf_source.minio_key,
                    Path("..") / "data" / pdf_source.minio_key,
                ]
                for alt in alt_paths:
                    if alt.exists():
                        pdf_path = alt
                        break
        
        if not Path(pdf_path).exists():
            pdf_source.status = "failed"
            pdf_source.error_message = f"PDF file not found: {pdf_path}"
            db.commit()
            return {"status": "error", "message": f"PDF not found: {pdf_path}"}
        
        print(f"   📂 Loading from: {pdf_path}")
        
        # Process PDF
        if not HAS_PYMUPDF:
            return {"status": "error", "message": "pymupdf not installed"}
        
        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        pdf_source.page_count = page_count
        
        print(f"   📃 Found {page_count} pages")
        
        # Check if already being processed by another worker
        if pdf_source.status == "ocr":
            print(f"   ⚠️  Already being processed, skipping")
            doc.close()
            return {"status": "skipped", "message": "Already being processed"}
        
        pdf_source.status = "ocr"
        db.commit()
        book_id = pdf_source.book_id
        
        # —— 1. OCR по всем страницам (Tesseract), сырой текст в память и в файл ——
        raw_texts = []
        ocr_confidences = []
        model_used = "tesseract"
        raw_path = norm_path = None
        if HAS_TESSERACT:
            print(f"   📷 OCR: Tesseract (rus+eng)")
        
        for page_num in range(page_count):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            text = ""
            conf = 70
            if HAS_TESSERACT:
                try:
                    text = pytesseract.image_to_string(img, lang="rus+eng")
                except Exception as e:
                    if page_num == 0:
                        print(f"   ⚠️  OCR failed for page {page_num}: {e}")
            raw_texts.append(text or "")
            ocr_confidences.append(conf)
            # Прогресс OCR каждые 25 страниц
            if (page_num + 1) % 25 == 0 or page_num == page_count - 1:
                print(f"   📃 OCR: {page_num + 1}/{page_count} pages")
        
        doc.close()
        
        # Запись сырого OCR в файл
        if HAS_OCR_FILES and raw_texts:
            raw_path = write_raw_md(book_id, pdf_source_id, model_used, raw_texts)
            print(f"   📁 Raw OCR: {raw_path}")
        
        # —— 2. Нормализация по страницам (ocr_cleaner) ——
        normalized_texts = []
        for i, t in enumerate(raw_texts):
            if HAS_OCR_CLEANER and (t or "").strip():
                try:
                    normalized_texts.append(clean_ocr_text(t, use_dictionary=False))
                except Exception as e:
                    if i == 0:
                        print(f"   ⚠️ OCR clean skip for page 0: {e}")
                    normalized_texts.append(t or "")
            else:
                normalized_texts.append(t or "")

        # —— 2b. LLM-коррекция формул и ошибок OCR (OpenAI) ——
        try:
            from llm_ocr_correct import correct_normalized_pages
            book = db.query(Book).filter(Book.id == book_id).first()
            subject = (book.subject if book else "geometry") or "geometry"
            print(f"   🤖 LLM-коррекция формул/OCR (предмет: {subject})...")
            normalized_texts = correct_normalized_pages(normalized_texts, subject=subject)
        except Exception as e:
            print(f"   ⚠️ LLM-коррекция пропущена: {e}")

        # —— 2c. Запись нормализованного файла ——
        if HAS_OCR_FILES and normalized_texts:
            norm_path = write_normalized_md(book_id, pdf_source_id, normalized_texts)
            print(f"   📁 Normalized: {norm_path}")
        
        # —— 3. Импорт в БД: только нормализованный текст, затем сегментация ——
        # Удаляем старые страницы и их задачи для этого источника
        existing_pages = db.query(PdfPage).filter(PdfPage.pdf_source_id == pdf_source_id).all()
        for p in existing_pages:
            db.query(Problem).filter(Problem.source_page_id == p.id).delete()
        db.query(PdfPage).filter(PdfPage.pdf_source_id == pdf_source_id).delete()
        db.flush()
        
        pages_processed = 0
        problems_found = 0
        for page_num in range(page_count):
            text = normalized_texts[page_num] if page_num < len(normalized_texts) else ""
            conf = ocr_confidences[page_num] if page_num < len(ocr_confidences) else 70
            pdf_page = PdfPage(
                pdf_source_id=pdf_source_id,
                page_num=page_num,
                ocr_text=text,
                ocr_confidence=conf,
            )
            db.add(pdf_page)
            db.flush()
            problems = segment_problems(text, page_num)
            for prob in problems:
                problem = Problem(
                    book_id=book_id,
                    source_page_id=pdf_page.id,
                    number=prob.get("number"),
                    section=prob.get("section"),
                    problem_text=prob["text"],
                    solution_text=prob.get("solution_text"),
                    page_ref=f"стр. {page_num + 1}",
                    confidence=prob.get("confidence", 50),
                )
                db.add(problem)
                problems_found += 1
            pages_processed += 1
            if pages_processed % 10 == 0:
                db.commit()
                print(f"   📃 Imported {pages_processed}/{page_count} pages, {problems_found} problems")
        
        theory_count = extract_and_save_section_theory(db, book_id, pdf_source_id)
        if theory_count is not None:
            print(f"   📖 Section theory: {theory_count} paragraphs saved")
        
        pdf_source.status = "done"
        db.commit()
        elapsed = time.time() - start_time
        print(f"   ✅ Done in {elapsed:.1f}s: {pages_processed} pages, {problems_found} problems")
        
        return {
            "status": "success",
            "pdf_source_id": pdf_source_id,
            "pages_processed": pages_processed,
            "problems_found": problems_found,
            "elapsed_seconds": elapsed,
            "raw_file": str(raw_path) if raw_path else None,
            "normalized_file": str(norm_path) if norm_path else None,
        }
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        
        if pdf_source:
            pdf_source.status = "failed"
            pdf_source.error_message = str(e)
            db.commit()
        
        return {"status": "error", "message": str(e)}
    
    finally:
        db.close()


# Начало блока решения/ответа (с возможными пробелами между буквами после OCR)
RE_SOLUTION_START = re.compile(
    r"^\s*Р\s*е\s*ш\s*е\s*н\s*и\s*е\s*\.|^\s*Решение\s*\."
    r"|^\s*О\s*т\s*в\s*е\s*т\s*\.|^\s*Ответ\s*\.",
    re.IGNORECASE
)


def segment_problems(text: str, page_num: int) -> list[dict]:
    """
    Сегментация страницы на задачи по нормализованному тексту.
    
    Поддерживаются разные типы разметки внутри одного учебника:
    задача, упражнение, задание, контрольное/практическое задание, вопрос, параграф, §, N. / N) и т.д.
    Граница условия и решения: строка «Решение.» — условие до неё, решение после неё до следующей задачи.
    
    Returns list of dicts: number, text (условие), solution_text (если есть), confidence
    """
    if not text or len(text.strip()) < 10:
        return []
    
    problems = []
    # Более специфичные паттерны — раньше. Номер всегда в группе 1.
    patterns = [
        r"Контрольное задание\s*(?:№\s*)?(?:\(\s*)?(\d+)(?:\))?",
        r"Контрольные задания\s*(?:№\s*)?(?:\(\s*)?(\d+)(?:\))?",
        r"Практическое задание\s*(?:№\s*)?(?:\(\s*)?(\d+)(?:\))?",
        r"Задача\s*\(\s*(\d+)\s*\)\s*\.?",   # Задача (22).
        r"Задача\s+(\d+)",
        r"Упражнение\s+(\d+)",
        r"Упражнение\s*\(\s*(\d+)\s*\)",
        r"Вопрос\s*(?:№\s*)?(?:\(\s*)?(\d+)(?:\))?",
        r"Вопросы?\s+(?:к?\s*)?(?:№\s*)?(\d+)",
        r"Задание\s*\(\s*(\d+)\s*\)",
        r"Задание\s+(\d+)",
        r"Задание\s*(?:№\s*)?(\d+)",
        r"§\s*(\d+(?:\.\d+)?)",
        r"Параграф\s*(\d+)",
        r"Exercise\s+(\d+)",   # английские учебники
        r"№\s*(\d+(?:\.\d+)?)",
        r"^(\d+)\.\s+",        # 1. Текст
        r"^(\d+)\)\s+",       # 1) Текст
    ]
    
    lines = text.split("\n")
    current_problem = None
    current_number = None
    solution_lines = None  # собираем строки решения после «Решение.»

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_problem and solution_lines is None:
                current_problem += "\n" + line.rstrip()
            elif solution_lines is not None:
                solution_lines.append(line.rstrip())
            continue

        # Проверка на начало блока «Решение.»
        if RE_SOLUTION_START.search(stripped):
            if current_problem and len(current_problem) > 20:
                problems.append({
                    "number": current_number,
                    "text": current_problem.strip(),
                    "solution_text": None,
                    "confidence": 60,
                })
            current_problem = None
            current_number = None
            solution_lines = [stripped]
            continue

        # Проверка на начало новой задачи
        is_problem_start = False
        number = None
        for pattern in patterns:
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                is_problem_start = True
                number = match.group(1)
                break

        if is_problem_start:
            # Прикрепить накопленное решение к предыдущей задаче
            if solution_lines is not None and problems:
                sol = "\n".join(s for s in solution_lines if s).strip()
                if sol:
                    problems[-1]["solution_text"] = sol
            solution_lines = None

            if current_problem and len(current_problem) > 20:
                problems.append({
                    "number": current_number,
                    "text": current_problem.strip(),
                    "solution_text": None,
                    "confidence": 60,
                })
            current_problem = stripped
            current_number = number
        elif solution_lines is not None:
            solution_lines.append(stripped)
        elif current_problem is not None:
            current_problem += "\n" + stripped

    if solution_lines is not None and problems:
        sol = "\n".join(s for s in solution_lines if s).strip()
        if sol:
            problems[-1]["solution_text"] = sol

    if current_problem and len(current_problem) > 20:
        problems.append({
            "number": current_number,
            "text": current_problem.strip(),
            "solution_text": None,
            "confidence": 60,
        })

    return problems


# Границы параграфа: после теории идёт блок заданий
RE_SECTION_HEADER = re.compile(r"^\s*[§\$]\s*(\d+)[.,\s]|^\s*Параграф\s*(\d+)[.,\s]", re.IGNORECASE)
RE_TASK_BLOCK_START = re.compile(
    r"^\s*(?:Задачи|Упражнения|Вопросы\s+к\s+параграфу|Контрольные\s+задания|Практические\s+задания)\s*[.:]?",
    re.IGNORECASE
)


def extract_and_save_section_theory(db, book_id: int, pdf_source_id: int) -> Optional[int]:
    """
    Извлекает теоретический материал по параграфам (§ N) из ocr_text страниц
    и сохраняет в section_theory. Нужно для ответов на контрольные вопросы
    и обоснования решений через LLM.
    """
    from models import PdfPage, SectionTheory

    pages = (
        db.query(PdfPage)
        .filter(PdfPage.pdf_source_id == pdf_source_id)
        .filter(PdfPage.ocr_text != None)
        .filter(PdfPage.ocr_text != "")
        .order_by(PdfPage.page_num)
        .all()
    )
    if not pages:
        return None

    sections = []  # list of (section_label, text, start_page, end_page)
    current_section = None
    current_text = []
    current_start_page = None
    current_end_page = None

    def flush_section():
        nonlocal current_section, current_text, current_start_page, current_end_page
        if current_section is not None and current_text:
            text = "\n".join(current_text).strip()
            if len(text) > 50:
                end = current_end_page if current_end_page is not None else current_start_page
                sections.append((current_section, text, current_start_page, end))
        current_section = None
        current_text = []
        current_start_page = None
        current_end_page = None

    for i, page in enumerate(pages):
        lines = (page.ocr_text or "").split("\n")

        for line in lines:
            stripped = line.strip()
            # Начало нового параграфа
            sec_match = RE_SECTION_HEADER.search(stripped)
            if sec_match:
                num = sec_match.group(1) or sec_match.group(2)
                flush_section()
                current_section = f"§{num}"
                current_start_page = page.page_num
                current_end_page = page.page_num
                current_text = [stripped]
                continue

            # Начало блока заданий — граница теории
            if RE_TASK_BLOCK_START.search(stripped):
                flush_section()
                continue

            if current_section is not None:
                current_text.append(stripped if stripped else line.rstrip())

        if current_section is not None:
            current_end_page = page.page_num

    flush_section()

    # Объединяем блоки с одним и тем же § (один параграф может всплывать на нескольких страницах)
    merged = {}
    for section_label, theory_text, start_page, end_page in sections:
        if section_label not in merged:
            merged[section_label] = {"texts": [], "start": start_page, "end": end_page}
        merged[section_label]["texts"].append(theory_text)
        merged[section_label]["start"] = min(merged[section_label]["start"], start_page)
        merged[section_label]["end"] = max(merged[section_label]["end"], end_page)

    saved = 0
    for section_label, data in merged.items():
        theory_text = "\n\n".join(data["texts"]).strip()
        if len(theory_text) < 50:
            continue
        start_page = data["start"]
        end_page = data["end"]
        page_ref = f"стр. {start_page + 1}" if start_page == end_page else f"стр. {start_page + 1}–{end_page + 1}"
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
    return saved if merged else None


def run_llm_normalize_only(pdf_source_id: int) -> dict:
    """
    Только LLM-нормализация: прочитать существующий нормализованный файл,
    прогнать через OpenAI (исправление формул/OCR), перезаписать файл и переимпортировать в БД.
    Не запускает OCR — используется когда нормализованный файл уже есть (например после полного пайплайна).
    """
    from models import PdfSource, Book

    db = SessionLocal()
    try:
        pdf_source = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        if not pdf_source:
            return {"status": "error", "message": f"PdfSource {pdf_source_id} not found"}
        book_id = pdf_source.book_id
        book = db.query(Book).filter(Book.id == book_id).first()
        subject = (book.subject if book else "geometry") or "geometry"
    finally:
        db.close()

    if not HAS_OCR_FILES:
        return {"status": "error", "message": "ocr_files module not available"}

    pages_data = read_normalized_pages(book_id, pdf_source_id)
    if not pages_data:
        return {"status": "error", "message": "Нормализованный файл не найден. Сначала выполните OCR (Начать OCR)."}

    page_texts = [t for _, t in sorted(pages_data, key=lambda x: x[0])]
    total = len(page_texts)
    print(f"   📄 LLM-нормализация источника {pdf_source_id}: {total} страниц (без перезапуска OCR)")

    checkpoint_path = get_llm_checkpoint_path(book_id, pdf_source_id)
    redis_conn = None
    try:
        from redis import Redis
        redis_conn = Redis.from_url(settings.redis_url)
    except Exception:
        pass
    progress_key = f"llm_norm_progress:{pdf_source_id}"

    def progress_callback(current: int, total_pages: int) -> None:
        if redis_conn:
            try:
                redis_conn.setex(progress_key, 3600, f"{current}/{total_pages}")
            except Exception:
                pass

    cancel_key = f"cancel_llm:{pdf_source_id}"

    def cancel_check() -> bool:
        if not redis_conn:
            return False
        try:
            if redis_conn.get(cancel_key):
                redis_conn.delete(cancel_key)
                return True
        except Exception:
            pass
        return False

    try:
        from llm_ocr_correct import correct_normalized_pages, LLMCancelRequested
        if redis_conn:
            try:
                redis_conn.setex(progress_key, 3600, f"0/{total}")
            except Exception:
                pass
        corrected = correct_normalized_pages(
            page_texts,
            subject=subject,
            checkpoint_path=checkpoint_path,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
    except LLMCancelRequested:
        if redis_conn:
            try:
                redis_conn.delete(progress_key)
            except Exception:
                pass
        return {"status": "cancelled", "message": "Остановлено пользователем. Можно продолжить повторным нажатием «LLM нормализация»."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

    write_normalized_md(book_id, pdf_source_id, corrected)
    print(f"   📁 Файл обновлён, переимпорт в БД...")
    out = import_from_normalized_file(pdf_source_id)
    if redis_conn:
        try:
            redis_conn.delete(progress_key)
        except Exception:
            pass
    return out


def import_from_normalized_file(pdf_source_id: int) -> dict:
    """
    Импорт в БД только из нормализованного файла (без OCR).
    Читает data/ocr_normalized/{book_id}/{pdf_source_id}.md, по страницам заполняет
    pdf_pages.ocr_text, запускает сегментацию задач и извлечение теории.
    """
    from models import PdfSource, PdfPage, Problem

    if not HAS_OCR_FILES:
        return {"status": "error", "message": "ocr_files module not available"}

    db = SessionLocal()
    try:
        pdf_source = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        if not pdf_source:
            return {"status": "error", "message": f"PdfSource {pdf_source_id} not found"}

        path = get_ocr_normalized_path(pdf_source.book_id, pdf_source_id)
        if not path.exists():
            return {"status": "error", "message": f"Normalized file not found: {path}"}

        pages_data = read_normalized_pages(pdf_source.book_id, pdf_source_id)
        if not pages_data:
            return {"status": "error", "message": "No pages in normalized file or parse error"}

        # Удаляем старые страницы и задачи этого источника
        existing_pages = db.query(PdfPage).filter(PdfPage.pdf_source_id == pdf_source_id).all()
        for p in existing_pages:
            db.query(Problem).filter(Problem.source_page_id == p.id).delete()
        db.query(PdfPage).filter(PdfPage.pdf_source_id == pdf_source_id).delete()
        db.flush()

        book_id = pdf_source.book_id
        problems_found = 0
        for page_num_1based, text in pages_data:
            page_num = page_num_1based - 1  # в БД page_num 0-based
            pdf_page = PdfPage(
                pdf_source_id=pdf_source_id,
                page_num=page_num,
                ocr_text=text,
                ocr_confidence=70,
            )
            db.add(pdf_page)
            db.flush()
            problems = segment_problems(text, page_num)
            for prob in problems:
                problem = Problem(
                    book_id=book_id,
                    source_page_id=pdf_page.id,
                    number=prob.get("number"),
                    section=prob.get("section"),
                    problem_text=prob["text"],
                    solution_text=prob.get("solution_text"),
                    page_ref=f"стр. {page_num + 1}",
                    confidence=prob.get("confidence", 50),
                )
                db.add(problem)
                problems_found += 1

        theory_count = extract_and_save_section_theory(db, book_id, pdf_source_id)
        pdf_source.status = "done"
        db.commit()
        print(f"   ✅ Import from normalized file: {len(pages_data)} pages, {problems_found} problems")
        return {
            "status": "success",
            "pdf_source_id": pdf_source_id,
            "pages_imported": len(pages_data),
            "problems_found": problems_found,
            "section_theory_saved": theory_count,
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


def import_from_normalized_file_llm(pdf_source_id: int) -> dict:
    """
    Распределение по БД на основе решений LLM (см. docs/LLM_DISTRIBUTION_DESIGN.md).
    Читает нормализованный .md → препроцессинг блоков → LLM батчами → полная перезапись
    данных по этому источнику: pdf_pages, problems, section_theory (по книге).
    """
    from models import PdfSource, PdfPage, Problem, ProblemPart, SectionTheory

    if not HAS_OCR_FILES:
        return {"status": "error", "message": "ocr_files module not available"}

    db = SessionLocal()
    try:
        pdf_source = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        if not pdf_source:
            return {"status": "error", "message": f"PdfSource {pdf_source_id} not found"}
        book_id = pdf_source.book_id
        from models import Book
        book = db.query(Book).filter(Book.id == book_id).first()
        subject = (book.subject if book else "geometry") or "geometry"

        path = get_ocr_normalized_path(book_id, pdf_source_id)
        if not path.exists():
            return {"status": "error", "message": f"Normalized file not found: {path}"}

        pages_data = read_normalized_pages(book_id, pdf_source_id)
        if not pages_data:
            return {"status": "error", "message": "No pages in normalized file or parse error"}

        def progress(batch_idx: int, total: int) -> None:
            print(f"   📦 Распределение LLM: батч {batch_idx}/{total}")

        redis_conn = None
        try:
            from redis import Redis
            redis_conn = Redis.from_url(settings.redis_url)
        except Exception:
            pass
        cancel_key = f"cancel_import_db:{pdf_source_id}"

        def cancel_check() -> bool:
            if not redis_conn:
                return False
            try:
                if redis_conn.get(cancel_key):
                    redis_conn.delete(cancel_key)
                    return True
            except Exception:
                pass
            return False

        from llm_distribute import distribute_batches, ImportDBCancelRequested
        try:
            parsed = distribute_batches(pages_data, subject, progress_callback=progress, cancel_check=cancel_check)
        except ImportDBCancelRequested:
            return {"status": "cancelled", "message": "Распределение по БД остановлено пользователем."}
        if not parsed:
            return {"status": "error", "message": "LLM не вернул блоки (проверь OPENAI_API_KEY и формат ответа)"}

        # Полная перезапись: удаляем старые данные по источнику и теорию по книге
        existing_pages = db.query(PdfPage).filter(PdfPage.pdf_source_id == pdf_source_id).all()
        for p in existing_pages:
            db.query(Problem).filter(Problem.source_page_id == p.id).delete()
        db.query(PdfPage).filter(PdfPage.pdf_source_id == pdf_source_id).delete()
        db.query(SectionTheory).filter(SectionTheory.book_id == book_id).delete()
        db.flush()

        # Восстанавливаем pdf_pages из файла (ocr_text по страницам)
        page_num_to_id: dict[int, int] = {}
        for page_num_1based, text in pages_data:
            page_num = page_num_1based - 1
            pdf_page = PdfPage(
                pdf_source_id=pdf_source_id,
                page_num=page_num,
                ocr_text=text,
                ocr_confidence=70,
            )
            db.add(pdf_page)
            db.flush()
            page_num_to_id[page_num_1based] = pdf_page.id

        # Теория: объединяем блоки по section
        theory_by_section: dict[str, list[str]] = {}
        for b in parsed:
            t = (b.get("type") or "").lower()
            if t not in ("section_theory", "theory"):
                continue
            sec = (b.get("section") or "").strip() or None
            if not sec:
                continue
            theory_text = (b.get("theory_text") or "").strip()
            if not theory_text:
                continue
            if not sec.startswith("§"):
                sec = f"§{sec.lstrip()}"
            if sec not in theory_by_section:
                theory_by_section[sec] = []
            theory_by_section[sec].append(theory_text)

        for section_label, texts in theory_by_section.items():
            theory_text = "\n\n".join(texts).strip()
            if len(theory_text) < 30:
                continue
            db.add(SectionTheory(book_id=book_id, section=section_label, theory_text=theory_text, page_ref=None))

        # Задачи из блоков type=problem; type=solution_only прикрепляется к последней задаче
        problems_found = 0
        last_added_problem = None
        for b in parsed:
            t = (b.get("type") or "").lower()
            if t == "solution_only":
                sol = (b.get("solution_text") or "").strip()
                ans = (b.get("answer_text") or "").strip()
                if last_added_problem and (sol or ans):
                    if sol:
                        last_added_problem.solution_text = sol if not last_added_problem.solution_text else (last_added_problem.solution_text + "\n\n" + sol)
                    if ans and not last_added_problem.answer_text:
                        last_added_problem.answer_text = ans
                continue
            if t != "problem":
                continue
            problem_text = (b.get("problem_text") or "").strip()
            if not problem_text:
                continue
            page_num_1 = b.get("_page_num") or 1
            source_page_id = page_num_to_id.get(page_num_1)
            if not source_page_id:
                source_page_id = next(iter(page_num_to_id.values()), None)
            sec = (b.get("section") or "").strip() or None
            if sec and not sec.startswith("§"):
                sec = f"§{sec.lstrip()}"
            parts_raw = b.get("parts")
            has_parts = isinstance(parts_raw, list) and len(parts_raw) > 0
            problem = Problem(
                book_id=book_id,
                source_page_id=source_page_id,
                number=b.get("number"),
                section=sec,
                problem_text=problem_text,
                solution_text=(b.get("solution_text") or "").strip() or None,
                answer_text=(b.get("answer_text") or "").strip() or None,
                page_ref=f"стр. {page_num_1}" if page_num_1 else None,
                confidence=70,
                has_parts=has_parts,
            )
            db.add(problem)
            db.flush()
            last_added_problem = problem
            if has_parts:
                for part in parts_raw:
                    if not isinstance(part, dict):
                        continue
                    part_number = (part.get("part_number") or "").strip() or None
                    part_text = (part.get("part_text") or "").strip() or None
                    if part_number is None and part_text is None:
                        continue
                    db.add(ProblemPart(
                        problem_id=problem.id,
                        part_number=part_number or "?",
                        part_text=part_text,
                        answer_text=(part.get("answer_text") or "").strip() or None,
                        solution_text=(part.get("solution_text") or "").strip() or None,
                    ))
            problems_found += 1

        # Блок ответов в конце книги: сопоставляем по номеру задачи и пишем answer_text в БД
        for b in parsed:
            if (b.get("type") or "").lower() != "answers_block":
                continue
            answers_list = b.get("answers")
            if not isinstance(answers_list, list):
                continue
            for item in answers_list:
                if not isinstance(item, dict):
                    continue
                num = (item.get("number") or "").strip() or None
                ans = (item.get("answer_text") or "").strip() or None
                if not num or not ans:
                    continue
                prob = db.query(Problem).filter(Problem.book_id == book_id, Problem.number == num).first()
                if prob and not prob.answer_text:
                    prob.answer_text = ans

        pdf_source.status = "done"
        db.commit()
        theory_count = len(theory_by_section)
        print(f"   ✅ Распределение LLM: {len(pages_data)} страниц, {problems_found} задач, {theory_count} параграфов теории")
        return {
            "status": "success",
            "pdf_source_id": pdf_source_id,
            "pages_imported": len(pages_data),
            "problems_found": problems_found,
            "section_theory_saved": theory_count,
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


def reanalyze_pdf_source(pdf_source_id: int) -> dict:
    """
    Повторный анализ уже нормализованных текстов: по ocr_text из pdf_pages
    заново запускается segment_problems и перезаписываются problems.
    PDF не читается, ocr_text не меняется.
    """
    from models import PdfSource, PdfPage, Problem

    db = SessionLocal()
    try:
        pdf_source = db.query(PdfSource).filter(PdfSource.id == pdf_source_id).first()
        if not pdf_source:
            return {"status": "error", "message": f"PdfSource {pdf_source_id} not found"}

        pages = (
            db.query(PdfPage)
            .filter(PdfPage.pdf_source_id == pdf_source_id, PdfPage.ocr_text != None)
            .filter(PdfPage.ocr_text != "")
            .order_by(PdfPage.page_num)
            .all()
        )
        if not pages:
            return {"status": "skipped", "message": "No pages with ocr_text", "problems_found": 0}

        total_problems = 0
        for i, page in enumerate(pages):
            # Удалить старые задачи этой страницы
            db.query(Problem).filter(Problem.source_page_id == page.id).delete()
            # Заново сегментировать по нормализованному тексту
            problems = segment_problems(page.ocr_text or "", page.page_num)
            for prob in problems:
                problem = Problem(
                    book_id=pdf_source.book_id,
                    source_page_id=page.id,
                    number=prob.get("number"),
                    section=prob.get("section"),
                    problem_text=prob["text"],
                    solution_text=prob.get("solution_text"),
                    page_ref=f"стр. {page.page_num + 1}",
                    confidence=prob.get("confidence", 50),
                )
                db.add(problem)
                total_problems += 1
            if (i + 1) % 50 == 0:
                db.commit()
                print(f"   📃 Reanalyzed {i + 1}/{len(pages)} pages, {total_problems} problems")

        # Обновить теоретический материал по параграфам
        theory_count = extract_and_save_section_theory(db, pdf_source.book_id, pdf_source_id)
        if theory_count is not None:
            print(f"   📖 Section theory: {theory_count} paragraphs updated")

        db.commit()
        print(f"   ✅ Reanalyze done: {len(pages)} pages, {total_problems} problems")
        return {
            "status": "success",
            "pdf_source_id": pdf_source_id,
            "pages_reanalyzed": len(pages),
            "problems_found": total_problems,
            "section_theory_saved": theory_count,
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


# ===========================================
# Queue Integration
# ===========================================

def enqueue_ingestion(pdf_source_id: int) -> str:
    """Enqueue PDF ingestion job."""
    from redis import Redis
    from rq import Queue

    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue("ingestion", connection=redis_conn)

    job = queue.enqueue(
        process_pdf_source,
        pdf_source_id,
        job_timeout="30m",  # PDF processing can be slow
        result_ttl=3600,
    )

    return job.id


def enqueue_reanalyze(pdf_source_id: int) -> str:
    """Поставить в очередь повторный анализ нормализованных текстов (без перечитывания PDF)."""
    from redis import Redis
    from rq import Queue

    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue("ingestion", connection=redis_conn)

    job = queue.enqueue(
        reanalyze_pdf_source,
        pdf_source_id,
        job_timeout="15m",
        result_ttl=3600,
    )
    return job.id


def enqueue_import_from_normalized_file(pdf_source_id: int) -> str:
    """Поставить в очередь импорт из нормализованного файла (без OCR)."""
    from redis import Redis
    from rq import Queue

    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue("ingestion", connection=redis_conn)
    job = queue.enqueue(
        import_from_normalized_file,
        pdf_source_id,
        job_timeout="15m",
        result_ttl=3600,
    )
    return job.id


def process_all_pending() -> list[dict]:
    """Process all pending PDF sources."""
    from models import PdfSource
    
    db = SessionLocal()
    try:
        pending = db.query(PdfSource).filter(PdfSource.status == "pending").all()
        print(f"📚 Found {len(pending)} pending PDF sources")
        
        results = []
        for pdf_source in pending:
            result = process_pdf_source(pdf_source.id)
            results.append(result)
        
        return results
    finally:
        db.close()


# ===========================================
# CLI
# ===========================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        pdf_source_id = int(sys.argv[1])
        result = process_pdf_source(pdf_source_id)
    else:
        results = process_all_pending()
        print(f"\n📊 Processed {len(results)} PDF sources")
