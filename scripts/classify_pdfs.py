#!/usr/bin/env python3
"""
PDF Auto-Classification Script

Analyzes first pages of PDFs to extract metadata:
- Subject (math, physics, russian, etc.)
- Grade (5-11)
- Authors
- Title
- Publisher
- Part number

Then moves/renames files according to naming convention.

Usage:
    python scripts/classify_pdfs.py --input data/pdfs --dry-run
    python scripts/classify_pdfs.py --input data/pdfs --apply
"""

import os
import re
import json
import shutil
import argparse
import unicodedata
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


def normalize_unicode(text: str) -> str:
    """Normalize unicode to NFC form (important for macOS file names)."""
    return unicodedata.normalize('NFC', text)

# Try to import optional dependencies
try:
    import fitz  # pymupdf
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    print("⚠️  pymupdf not installed. Run: pip install pymupdf")

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


@dataclass
class BookMetadata:
    """Extracted book metadata."""
    subject: str = "other"
    grade: str = ""
    authors: str = ""
    title: str = ""
    publisher: str = ""
    part: str = ""
    year: str = ""
    is_gdz: bool = False
    confidence: float = 0.0
    raw_text: str = ""


# Subject mappings - ORDER MATTERS! More specific first
SUBJECT_KEYWORDS_ORDERED = [
    ("physics", ["физика", "физик"]),
    ("chemistry", ["химия", "хими"]),
    ("biology", ["биология", "биолог"]),
    ("russian", ["русский язык", "русск. яз", "русск"]),
    ("english", ["английский язык", "английск", "english", "англ яз", "spotlight", "starlight"]),
    ("history", ["история", "истори"]),
    ("geography", ["география", "географ"]),
    ("informatics", ["информатика", "информатик"]),
    ("math", ["математика", "алгебра", "геометрия", "матем", "алгебр", "геометри"]),
]

# Legacy dict for compatibility
SUBJECT_KEYWORDS = {k: v for k, v in SUBJECT_KEYWORDS_ORDERED}

# Publisher patterns
PUBLISHERS = [
    "просвещение", "дрофа", "вентана-граф", "мнемозина", 
    "русское слово", "бином", "экзамен", "легион",
    "национальное образование", "сферы", "баласс"
]

# Grade patterns
GRADE_PATTERNS = [
    r"(\d{1,2})\s*класс",
    r"(\d{1,2})-(\d{1,2})\s*класс",  # 7-9 класс
    r"класс\s*(\d{1,2})",
    r"(\d{1,2})\s*кл\.?",
]


def extract_text_from_pdf(pdf_path: str, max_pages: int = 3) -> str:
    """Extract text from first N pages of PDF."""
    if not HAS_PYMUPDF:
        return ""
    
    try:
        doc = fitz.open(pdf_path)
        text_parts = []
        
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text = page.get_text()
            text_parts.append(text)
        
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        print(f"  ⚠️  Error reading {pdf_path}: {e}")
        return ""


def classify_with_patterns(text: str, filename: str) -> BookMetadata:
    """Classify book using regex patterns."""
    # Normalize unicode (macOS uses NFD, we need NFC for matching)
    text_lower = normalize_unicode(text.lower())
    filename_lower = normalize_unicode(filename.lower())
    combined = f"{filename_lower} {text_lower}"
    
    metadata = BookMetadata()
    metadata.raw_text = text[:500]
    
    # Detect subject - use ordered list for priority
    for subject, keywords in SUBJECT_KEYWORDS_ORDERED:
        for kw in keywords:
            if kw in combined:
                metadata.subject = subject
                metadata.confidence += 0.3
                break
        if metadata.subject != "other":
            break
    
    # Detect grade - check for ranges first
    range_match = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s*класс", combined)
    if range_match:
        metadata.grade = f"{range_match.group(1)}-{range_match.group(2)}"
        metadata.confidence += 0.2
    else:
        for pattern in GRADE_PATTERNS:
            match = re.search(pattern, combined)
            if match:
                metadata.grade = match.group(1)
                metadata.confidence += 0.2
                break
    
    # Detect part
    part_match = re.search(r"часть\s*(\d+)|part\s*(\d+)|ч\.?\s*(\d+)", combined)
    if part_match:
        metadata.part = part_match.group(1) or part_match.group(2) or part_match.group(3)
        metadata.confidence += 0.1
    
    # Detect publisher
    for pub in PUBLISHERS:
        if pub in combined:
            metadata.publisher = pub.title()
            metadata.confidence += 0.1
            break
    
    # Detect if GDZ
    if any(kw in combined for kw in ["гдз", "решебник", "ответы", "готовые домашние"]):
        metadata.is_gdz = True
        metadata.confidence += 0.1
    
    # Try to extract authors from filename
    # Pattern: "Name1:Name2" or "Name1, Name2"
    author_match = re.search(r"класс\s+([А-ЯЁа-яё]+(?:[:/,]\s*[А-ЯЁа-яё]+)*)", filename)
    if author_match:
        metadata.authors = author_match.group(1).replace(":", ", ").replace("/", ", ")
        metadata.confidence += 0.1
    
    # Extract year if present
    year_match = re.search(r"(20\d{2}|19\d{2})", combined)
    if year_match:
        metadata.year = year_match.group(1)
    
    # Generate title from what we know
    if metadata.subject != "other" and metadata.grade:
        subj_names = {
            "math": "Математика",
            "physics": "Физика", 
            "chemistry": "Химия",
            "biology": "Биология",
            "russian": "Русский язык",
            "english": "Английский язык",
            "history": "История",
            "geography": "География",
            "informatics": "Информатика",
        }
        metadata.title = subj_names.get(metadata.subject, metadata.subject.title())
    
    return metadata


def classify_with_llm(text: str, filename: str) -> Optional[BookMetadata]:
    """Classify book using OpenAI LLM."""
    if not HAS_OPENAI:
        return None
    
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-your"):
        return None
    
    try:
        client = OpenAI(api_key=api_key)
        
        prompt = f"""Analyze this Russian textbook and extract metadata.

Filename: {filename}

Text from first pages:
{text[:2000]}

Return JSON with these fields:
- subject: one of [math, physics, chemistry, biology, russian, english, history, geography, informatics, other]
- grade: class number(s), e.g. "8" or "7-9"
- authors: author names in Russian
- title: book title in Russian
- publisher: publisher name
- part: part number if any, e.g. "1" or "2"
- year: publication year if found
- is_gdz: true if this is an answer book (ГДЗ/решебник)

JSON only, no explanation:"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
        )
        
        content = response.choices[0].message.content
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            metadata = BookMetadata(
                subject=data.get("subject", "other"),
                grade=str(data.get("grade", "")),
                authors=data.get("authors", ""),
                title=data.get("title", ""),
                publisher=data.get("publisher", ""),
                part=str(data.get("part", "")),
                year=str(data.get("year", "")),
                is_gdz=data.get("is_gdz", False),
                confidence=0.9,
                raw_text=text[:500],
            )
            return metadata
            
    except Exception as e:
        print(f"  ⚠️  LLM classification failed: {e}")
    
    return None


def generate_new_path(metadata: BookMetadata, base_dir: Path) -> tuple[Path, str]:
    """Generate new file path based on metadata."""
    # Determine target directory
    subject_dir = metadata.subject
    
    if metadata.grade:
        # Handle grade ranges like "7-9"
        if "-" in metadata.grade:
            grade_dir = f"{metadata.grade.split('-')[0]}class"
        else:
            grade_dir = f"{metadata.grade}class"
    else:
        grade_dir = "other"
    
    target_dir = base_dir / subject_dir / grade_dir
    
    # Generate filename
    parts = []
    
    if metadata.is_gdz:
        parts.append("gdz")
    
    parts.append(metadata.subject)
    
    if metadata.grade:
        parts.append(metadata.grade)
    
    if metadata.authors:
        # Simplify authors for filename
        author_short = metadata.authors.split(",")[0].split()[0].lower()
        author_short = re.sub(r'[^a-zа-яё]', '', author_short)
        if author_short:
            parts.append(author_short)
    
    if metadata.part:
        parts.append(f"part{metadata.part}")
    
    if metadata.year:
        parts.append(metadata.year)
    
    filename = "_".join(parts) + ".pdf"
    
    # Transliterate if needed
    filename = transliterate(filename)
    
    return target_dir, filename


def transliterate(text: str) -> str:
    """Simple transliteration for filenames."""
    mapping = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        ' ': '_', ':': '_', '/': '_', '\\': '_',
    }
    result = ""
    for char in text.lower():
        result += mapping.get(char, char)
    return re.sub(r'_+', '_', result)


def process_pdf(pdf_path: Path, base_dir: Path, use_llm: bool = True, dry_run: bool = True) -> dict:
    """Process single PDF file."""
    result = {
        "original_path": str(pdf_path),
        "status": "unknown",
        "metadata": None,
        "new_path": None,
    }
    
    print(f"\n📄 Processing: {pdf_path.name}")
    
    # Extract text
    text = extract_text_from_pdf(str(pdf_path))
    if not text:
        print("  ⚠️  Could not extract text")
        # Try classification from filename only
        text = ""
    
    # Classify
    metadata = None
    if use_llm:
        metadata = classify_with_llm(text, pdf_path.name)
        if metadata:
            print(f"  🤖 LLM classification: {metadata.subject}/{metadata.grade}")
    
    if not metadata:
        metadata = classify_with_patterns(text, pdf_path.name)
        print(f"  🔍 Pattern classification: {metadata.subject}/{metadata.grade}")
    
    result["metadata"] = asdict(metadata)
    
    # Generate new path
    target_dir, new_filename = generate_new_path(metadata, base_dir)
    new_path = target_dir / new_filename
    
    result["new_path"] = str(new_path)
    
    print(f"  📁 Subject: {metadata.subject}")
    print(f"  📚 Grade: {metadata.grade or 'unknown'}")
    print(f"  👤 Authors: {metadata.authors or 'unknown'}")
    print(f"  📖 Part: {metadata.part or '-'}")
    print(f"  🏢 Publisher: {metadata.publisher or 'unknown'}")
    print(f"  📊 Confidence: {metadata.confidence:.0%}")
    print(f"  ➡️  New path: {new_path}")
    
    if dry_run:
        print("  ⏸️  Dry run - not moving")
        result["status"] = "dry_run"
    else:
        try:
            # Create target directory
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # Move file
            if new_path.exists():
                print(f"  ⚠️  Target exists, adding suffix")
                stem = new_path.stem
                suffix = 1
                while new_path.exists():
                    new_path = target_dir / f"{stem}_{suffix}.pdf"
                    suffix += 1
            
            shutil.move(str(pdf_path), str(new_path))
            print(f"  ✅ Moved to: {new_path}")
            result["status"] = "moved"
            result["new_path"] = str(new_path)
        except Exception as e:
            print(f"  ❌ Error moving: {e}")
            result["status"] = "error"
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Auto-classify PDF textbooks")
    parser.add_argument("--input", "-i", default="data/pdfs", help="Input directory")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Don't move files")
    parser.add_argument("--apply", "-a", action="store_true", help="Actually move files")
    parser.add_argument("--no-llm", action="store_true", help="Don't use LLM classification")
    parser.add_argument("--output", "-o", help="Output JSON report path")
    
    args = parser.parse_args()
    
    if not args.apply:
        args.dry_run = True
    
    base_dir = Path(args.input)
    if not base_dir.exists():
        print(f"❌ Directory not found: {base_dir}")
        return
    
    print(f"📂 Scanning: {base_dir}")
    print(f"🔧 Mode: {'DRY RUN' if args.dry_run else 'APPLY CHANGES'}")
    print(f"🤖 LLM: {'disabled' if args.no_llm else 'enabled'}")
    print("=" * 50)
    
    # Find all PDFs
    pdf_files = list(base_dir.rglob("*.pdf")) + list(base_dir.rglob("*.PDF"))
    print(f"📚 Found {len(pdf_files)} PDF files")
    
    results = []
    for pdf_path in pdf_files:
        result = process_pdf(
            pdf_path, 
            base_dir, 
            use_llm=not args.no_llm,
            dry_run=args.dry_run
        )
        results.append(result)
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 SUMMARY")
    print("=" * 50)
    
    by_status = {}
    for r in results:
        status = r["status"]
        by_status[status] = by_status.get(status, 0) + 1
    
    for status, count in by_status.items():
        print(f"  {status}: {count}")
    
    # Save report
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n📝 Report saved to: {args.output}")
    
    if args.dry_run:
        print("\n💡 Run with --apply to actually move files")


if __name__ == "__main__":
    main()
