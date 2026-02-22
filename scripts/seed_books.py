#!/usr/bin/env python3
"""
Seed books and pdf_sources from existing PDFs in data/pdfs/

Uses the classify_pdfs logic to extract metadata and create DB records.

Usage:
    cd infra && docker compose exec api python /app/scripts/seed_books.py
    
    # Or locally:
    cd apps/api && python ../../scripts/seed_books.py
"""

import os
import sys
import unicodedata
import re
from pathlib import Path
from datetime import datetime

# Add apps/api to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../apps/api')))

from database import SessionLocal, engine, Base
from models import Book, PdfSource

# Try to import pymupdf for text extraction
try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    print("⚠️  pymupdf not installed, will use filename-based classification only")


# Subject keywords for classification
SUBJECT_KEYWORDS = [
    ("physics", ["физика", "физик"]),
    ("chemistry", ["химия", "хими"]),
    ("biology", ["биология", "биолог"]),
    ("russian", ["русский язык", "русск. яз", "русск"]),
    ("english", ["английский язык", "английск", "english", "англ яз"]),
    ("history", ["история", "истори"]),
    ("geography", ["география", "географ"]),
    ("informatics", ["информатика", "информатик"]),
    ("geometry", ["геометрия", "геометри"]),  # до math, чтобы учебники геометрии не шли как "математика"
    ("math", ["математика", "алгебра", "матем", "алгебр"]),
]


def normalize(text: str) -> str:
    """Normalize unicode (macOS NFD → NFC)."""
    return unicodedata.normalize('NFC', text)


def extract_text_from_pdf(pdf_path: str, max_pages: int = 3) -> str:
    """Extract text from first N pages of PDF."""
    if not HAS_PYMUPDF:
        return ""
    try:
        doc = fitz.open(pdf_path)
        texts = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            texts.append(page.get_text())
        doc.close()
        return "\n".join(texts)
    except Exception as e:
        print(f"  ⚠️  Error reading PDF: {e}")
        return ""


def classify_pdf(pdf_path: Path) -> dict:
    """Classify PDF by filename and content."""
    filename = normalize(pdf_path.name.lower())
    text = normalize(extract_text_from_pdf(str(pdf_path)).lower())
    combined = f"{filename} {text}"
    
    result = {
        "subject": "other",
        "grade": None,
        "authors": None,
        "title": pdf_path.stem,
        "publisher": None,
        "part": None,
        "is_gdz": False,
    }
    
    # Detect subject
    for subject, keywords in SUBJECT_KEYWORDS:
        for kw in keywords:
            if kw in combined:
                result["subject"] = subject
                break
        if result["subject"] != "other":
            break
    
    # Detect grade range first (e.g., "7-11")
    range_match = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s*класс", combined)
    if range_match:
        result["grade"] = f"{range_match.group(1)}-{range_match.group(2)}"
    else:
        # Single grade
        grade_match = re.search(r"(\d{1,2})\s*класс", combined)
        if grade_match:
            result["grade"] = grade_match.group(1)
    
    # Detect part
    part_match = re.search(r"часть\s*(\d+)", combined)
    if part_match:
        result["part"] = part_match.group(1)
    
    # Detect authors from filename pattern "класс Автор1:Автор2"
    author_match = re.search(r"класс\s+([А-ЯЁа-яё]+(?:[:/,]\s*[А-ЯЁа-яё]+)*)", normalize(pdf_path.name))
    if author_match:
        result["authors"] = author_match.group(1).replace(":", ", ").replace("/", ", ")
    
    # Detect if GDZ
    if any(kw in combined for kw in ["гдз", "решебник", "ответы"]):
        result["is_gdz"] = True
    
    # Generate title
    subject_names = {
        "math": "Математика", "geometry": "Геометрия", "physics": "Физика", "chemistry": "Химия",
        "biology": "Биология", "russian": "Русский язык", "english": "Английский язык",
        "history": "История", "geography": "География", "informatics": "Информатика",
    }
    if result["subject"] in subject_names:
        title_parts = [subject_names[result["subject"]]]
        if result["grade"]:
            title_parts.append(f"{result['grade']} класс")
        if result["authors"]:
            title_parts.append(result["authors"])
        if result["part"]:
            title_parts.append(f"часть {result['part']}")
        result["title"] = " ".join(title_parts)
    
    return result


def seed_books(pdfs_dir: str = "data/pdfs"):
    """Seed books from PDFs directory."""
    print("📚 Seeding books from PDFs...")
    
    base_dir = Path(pdfs_dir)
    if not base_dir.exists():
        print(f"❌ Directory not found: {base_dir}")
        return
    
    # Find all PDFs
    pdf_files = list(base_dir.rglob("*.pdf")) + list(base_dir.rglob("*.PDF"))
    print(f"📄 Found {len(pdf_files)} PDF files")
    
    db = SessionLocal()
    created_books = 0
    created_pdfs = 0
    
    try:
        for pdf_path in pdf_files:
            print(f"\n📄 Processing: {pdf_path.name}")
            
            # Classify
            metadata = classify_pdf(pdf_path)
            print(f"   Subject: {metadata['subject']}, Grade: {metadata['grade']}")
            print(f"   Authors: {metadata['authors']}, Part: {metadata['part']}")
            
            # Check if book already exists
            existing_book = db.query(Book).filter(
                Book.subject == metadata["subject"],
                Book.grade == metadata["grade"],
                Book.authors == metadata["authors"],
                Book.part == metadata["part"],
            ).first()
            
            if existing_book:
                book = existing_book
                print(f"   📖 Using existing book: {book.title} (ID: {book.id})")
            else:
                # Create new book
                book = Book(
                    subject=metadata["subject"],
                    grade=metadata["grade"],
                    title=metadata["title"],
                    authors=metadata["authors"],
                    publisher=metadata["publisher"],
                    part=metadata["part"],
                    is_gdz=metadata["is_gdz"],
                )
                db.add(book)
                db.commit()
                db.refresh(book)
                created_books += 1
                print(f"   📖 Created book: {book.title} (ID: {book.id})")
            
            # Create PDF source (use relative path from data/ as minio_key)
            relative_path = pdf_path.relative_to(base_dir.parent)
            minio_key = str(relative_path)
            
            existing_pdf = db.query(PdfSource).filter(
                PdfSource.minio_key == minio_key
            ).first()
            
            if existing_pdf:
                print(f"   📁 PDF source already exists: {minio_key}")
            else:
                # Get page count
                page_count = None
                if HAS_PYMUPDF:
                    try:
                        doc = fitz.open(str(pdf_path))
                        page_count = len(doc)
                        doc.close()
                    except:
                        pass
                
                pdf_source = PdfSource(
                    book_id=book.id,
                    minio_key=minio_key,
                    original_filename=pdf_path.name,
                    file_size_bytes=pdf_path.stat().st_size,
                    page_count=page_count,
                    status="pending",
                )
                db.add(pdf_source)
                db.commit()
                created_pdfs += 1
                print(f"   📁 Created PDF source: {minio_key} ({page_count} pages)")
        
        print(f"\n✅ Done! Created {created_books} books, {created_pdfs} PDF sources")
        
        # Summary
        total_books = db.query(Book).count()
        total_pdfs = db.query(PdfSource).count()
        print(f"📊 Total: {total_books} books, {total_pdfs} PDF sources in database")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_books()
