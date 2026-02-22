"""
Problem Retrieval Module

Hybrid search: Full-Text Search (FTS) + optional vector search.

Usage:
    from retrieval import search_problems
    
    results = search_problems("решите уравнение 2x + 5 = 13")
    for r in results:
        print(f"#{r.number}: {r.problem_text[:100]}... (score: {r.score})")
"""

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text, func
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Problem, Book


@dataclass
class SearchResult:
    """Search result with score."""
    problem_id: int
    book_id: int
    number: Optional[str]
    problem_text: str
    solution_text: Optional[str]
    answer_text: Optional[str]
    page_ref: Optional[str]
    book_title: str
    book_subject: str
    book_grade: Optional[str]
    problem_type: str  # 'question', 'exercise', 'unknown'
    section: Optional[str]  # Section/paragraph number (e.g., '§7')
    has_parts: bool = False  # Does this problem have sub-parts?
    requested_part: Optional[str] = None  # Which part was requested ("1", "2", etc.)
    part_answer: Optional[str] = None  # Answer for the specific part
    score: float = 0.0


def extract_part_number(query: str) -> Optional[str]:
    """
    Extract requested part/variant number from query.
    
    Examples:
        "смежные углы если один на 80 градусов больше" → "1"
        "найди 2 вариант" → "2"
        "решение 3)" → "3"
    """
    # Explicit part references
    patterns = [
        r'\b(\d)\s*(?:вариант|пункт|часть|подпункт)',
        r'(?:вариант|пункт|часть)\s*(\d)\b',
        r'\b(\d)\s*\)',  # "1)"
        r'(?:номер|№)\s*\d+[.,]?\s*(\d)',  # "№4.1" → part 1
    ]
    
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # Implicit detection based on problem text
    # "один на 80 градусов больше" → likely part 1
    # "разность равна" → likely part 2
    # "в 3 раза меньше" → likely part 3
    # "равны" → likely part 4
    
    implicit_markers = [
        (r'на\s+\d+\s*(?:°|градус(?:ов|а)?)', '1'),  # "на 80 градусов больше"
        (r'разность\s+равна', '2'),         # "разность равна"
        (r'в\s+\d+\s*раз', '3'),             # "в 3 раза"
        (r'\bравны\b', '4'),                 # "равны"
    ]
    
    for pattern, part_num in implicit_markers:
        if re.search(pattern, query, re.IGNORECASE):
            return part_num
    
    return None


def get_problem_part_answer(db, problem_id: int, part_number: str) -> Optional[str]:
    """
    Get the answer for a specific part of a multi-part problem.
    """
    result = db.execute(text("""
        SELECT part_text, answer_text, solution_text
        FROM problem_parts
        WHERE problem_id = :problem_id AND part_number = :part_number
    """), {"problem_id": problem_id, "part_number": part_number}).first()
    
    if result:
        return result.answer_text
    return None


def get_all_problem_parts(db, problem_id: int) -> list[dict]:
    """
    Get all parts for a problem.
    """
    result = db.execute(text("""
        SELECT part_number, part_text, answer_text, solution_text
        FROM problem_parts
        WHERE problem_id = :problem_id
        ORDER BY part_number
    """), {"problem_id": problem_id})
    
    return [
        {
            "part_number": row.part_number,
            "part_text": row.part_text,
            "answer_text": row.answer_text,
            "solution_text": row.solution_text,
        }
        for row in result
    ]
    

def preprocess_query(query: str) -> str:
    """
    Preprocess search query for better FTS matching.
    - Normalize degree symbols and units
    - Remove special characters
    - Normalize whitespace
    """
    # Normalize degree symbols: "градусов" -> "°", "°" -> ""
    query = re.sub(r'градусов|градуса|градус', '°', query, flags=re.IGNORECASE)
    query = re.sub(r'°', ' ', query)  # Remove ° for FTS (it's not indexed anyway)
    
    # Remove special characters except Russian letters, digits, spaces
    query = re.sub(r'[^\w\s\dа-яА-ЯёЁ]', ' ', query)
    # Normalize whitespace
    query = ' '.join(query.split())
    return query.lower()  # Lowercase for consistency


def search_problems_fts(
    query: str,
    db: Session,
    limit: int = 20,
    subject: Optional[str] = None,
    grade: Optional[str] = None,
) -> list[SearchResult]:
    """
    Search problems using PostgreSQL Full-Text Search.
    
    Args:
        query: Search query text
        db: Database session
        limit: Max results to return
        subject: Filter by subject (math, physics, etc.)
        grade: Filter by grade (8, 9, 7-11, etc.)
        
    Returns:
        List of SearchResult ordered by relevance
    """
    processed_query = preprocess_query(query)
    
    if not processed_query:
        return []
    
    # Convert query to tsquery format
    # Split into words and join with &
    words = processed_query.split()
    if not words:
        return []
    
    tsquery_str = ' & '.join(words)
    
    # Build the SQL query using plainto_tsquery (more forgiving than websearch_to_tsquery)
    # Also add ILIKE fallback for partial matches
    # Search in both raw and cleaned text
    # ВАЖНО: Добавляем буст для задач с ответами (+1.0) и с подчастями (+0.5)
    sql = """
        SELECT 
            p.id,
            p.book_id,
            p.number,
            COALESCE(p.problem_text_clean, p.problem_text) as problem_text,
            p.solution_text,
            p.answer_text,
            p.page_ref,
            p.problem_type,
            p.section,
            COALESCE(p.has_parts, false) as has_parts,
            b.title as book_title,
            b.subject as book_subject,
            b.grade as book_grade,
            COALESCE(
                ts_rank(
                    to_tsvector('russian', COALESCE(p.problem_text_clean, p.problem_text)),
                    plainto_tsquery('russian', :query)
                ),
                0
            ) + 
            CASE WHEN LOWER(COALESCE(p.problem_text_clean, p.problem_text)) LIKE :like_query THEN 0.5 ELSE 0 END +
            CASE WHEN p.answer_text IS NOT NULL AND LENGTH(p.answer_text) > 3 THEN 1.0 ELSE 0 END +
            CASE WHEN p.solution_text IS NOT NULL AND LENGTH(p.solution_text) > 10 THEN 0.5 ELSE 0 END +
            CASE WHEN p.has_parts = true THEN 0.5 ELSE 0 END
            as score
        FROM problems p
        JOIN books b ON b.id = p.book_id
        WHERE 
            to_tsvector('russian', COALESCE(p.problem_text_clean, p.problem_text)) @@ plainto_tsquery('russian', :query)
            OR LOWER(COALESCE(p.problem_text_clean, p.problem_text)) LIKE :like_query
    """
    
    # Create LIKE pattern from key words
    like_pattern = '%' + '%'.join(processed_query.split()[:4]) + '%'
    params = {"query": processed_query, "like_query": like_pattern}

    # Add filters
    if subject:
        sql += " AND b.subject = :subject"
        params["subject"] = subject
    
    if grade:
        sql += " AND (b.grade = :grade OR b.grade LIKE :grade_pattern)"
        params["grade"] = grade
        params["grade_pattern"] = f"%{grade}%"
    
    sql += " ORDER BY score DESC LIMIT :limit"
    params["limit"] = limit
    
    result = db.execute(text(sql), params)
    
    results = []
    for row in result:
        results.append(SearchResult(
            problem_id=row.id,
            book_id=row.book_id,
            number=row.number,
            problem_text=row.problem_text,
            solution_text=row.solution_text,
            answer_text=row.answer_text,
            page_ref=row.page_ref,
            book_title=row.book_title,
            book_subject=row.book_subject,
            book_grade=row.book_grade,
            problem_type=row.problem_type or 'unknown',
            section=row.section,
            has_parts=row.has_parts or False,
            score=float(row.score) if row.score else 0.0,
        ))
    
    return results


def search_problems(
    query: str,
    limit: int = 10,
    subject: Optional[str] = None,
    grade: Optional[str] = None,
) -> list[SearchResult]:
    """
    Main search function - hybrid search.
    
    Handles:
    - FTS search with cleaned OCR text
    - Part number extraction from query
    - Specific part answer lookup for multi-part problems
    """
    db = SessionLocal()
    try:
        # Extract requested part number from query
        requested_part = extract_part_number(query)
        
        # FTS search
        fts_results = search_problems_fts(query, db, limit=limit * 2, subject=subject, grade=grade)

        # For multi-part problems, look up specific part answer
        for result in fts_results:
            if result.has_parts:
                result.requested_part = requested_part
                
                if requested_part:
                    # Get specific part answer
                    part_answer = get_problem_part_answer(db, result.problem_id, requested_part)
                    if part_answer:
                        result.part_answer = part_answer
                else:
                    # Get all parts for display
                    all_parts = get_all_problem_parts(db, result.problem_id)
                    if all_parts:
                        # Format all answers for display
                        all_answers = []
                        for p in all_parts:
                            if p['answer_text']:
                                all_answers.append(f"{p['part_number']}) {p['answer_text']}")
                        if all_answers:
                            result.part_answer = "; ".join(all_answers)
        
        # TODO: Add vector search and merge results
        # vector_results = search_problems_vector(query, db, limit=limit)
        # results = merge_and_rerank(fts_results, vector_results)
        
        return fts_results[:limit]
    finally:
        db.close()


def get_problem_by_id(problem_id: int) -> Optional[SearchResult]:
    """Get a single problem by ID."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT 
                p.id,
                p.book_id,
                p.number,
                p.problem_text,
                p.solution_text,
                p.answer_text,
                p.page_ref,
                p.problem_type,
                p.section,
                b.title as book_title,
                b.subject as book_subject,
                b.grade as book_grade
            FROM problems p
            JOIN books b ON b.id = p.book_id
            WHERE p.id = :problem_id
        """), {"problem_id": problem_id}).first()
        
        if not result:
            return None
        
        return SearchResult(
            problem_id=result.id,
            book_id=result.book_id,
            number=result.number,
            problem_text=result.problem_text,
            solution_text=result.solution_text,
            answer_text=result.answer_text,
            page_ref=result.page_ref,
            book_title=result.book_title,
            book_subject=result.book_subject,
            book_grade=result.book_grade,
            problem_type=result.problem_type or 'unknown',
            section=result.section,
            score=1.0,
        )
    finally:
        db.close()


# ===========================================
# CLI for testing
# ===========================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python retrieval.py <search query>")
        print("Example: python retrieval.py 'решите уравнение'")
        sys.exit(1)
    
    query = " ".join(sys.argv[1:])
    print(f"🔍 Searching for: {query}\n")
    
    results = search_problems(query, limit=5)
    
    if not results:
        print("No results found.")
    else:
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r.book_subject}/{r.book_grade}] #{r.number or 'N/A'}")
            print(f"   Book: {r.book_title}")
            print(f"   Text: {r.problem_text[:150]}...")
            print(f"   Score: {r.score:.4f}")
            print()
